"""Vistas de autenticación con registro de auditoría."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from expedientes.auditoria import obtener_ip, registrar
from expedientes.models import RegistroAuditoria
from .forms import InvitacionForm, RegistroForm
from .models import InvitacionRegistro


def destino_seguro(request, propuesto):
    """A dónde mandar después de entrar, sin dejar que lo elija un desconocido.

    El `?next=` de la dirección lo escribe cualquiera. Se usaba tal cual, así
    que un link como `…/ingresar/?next=https://sitio-falso/` mostraba el login
    de verdad —dominio propio, candado y todo— y apenas la persona entraba con
    su usuario la depositaba en otro sitio. Ahí ya confió, y lo que le pidan
    después lo escribe.

    Solo se acepta un destino dentro de este mismo sistema.
    """
    if propuesto and url_has_allowed_host_and_scheme(
            url=propuesto,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure()):
        return propuesto
    return "expedientes:panel"


def _llave_de_intentos(request, usuario):
    """Se cuenta por usuario Y por origen.

    Solo por usuario, cualquiera deja afuera a una persona real probando mal su
    contraseña a propósito. Solo por origen, no frena a quien reparte los
    intentos entre muchas cuentas.
    """
    return f"login-fallidos:{(usuario or '').strip().lower()}:{obtener_ip(request) or 'sin-ip'}"


def esta_frenado(request, usuario):
    return cache.get(_llave_de_intentos(request, usuario), 0) >= settings.LOGIN_INTENTOS_MAX


@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return redirect("expedientes:panel")

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST":
        nombre = request.POST.get("username", "")
        llave = _llave_de_intentos(request, nombre)

        if esta_frenado(request, nombre):
            minutos = settings.LOGIN_BLOQUEO_SEGUNDOS // 60
            registrar(request, RegistroAuditoria.Accion.LOGIN_FALLIDO,
                      descripcion=f"Intento bloqueado por reintentos para '{nombre}'")
            messages.error(
                request,
                f"Demasiados intentos fallidos. Esperá {minutos} minutos "
                "o pedile al administrador que te cambie la contraseña.")
        elif form.is_valid():
            usuario = form.get_user()
            cache.delete(llave)
            login(request, usuario)
            registrar(request, RegistroAuditoria.Accion.LOGIN,
                      descripcion=f"Ingresó al sistema ({usuario.get_rol_display()})")
            messages.success(request, f"Bienvenido/a, {usuario.get_full_name() or usuario.username}.")
            return redirect(destino_seguro(
                request, request.POST.get("next") or request.GET.get("next")))
        else:
            # `add` no pisa el vencimiento si ya existe: la ventana se cuenta
            # desde el primer fallo y no se renueva sola con cada intento.
            cache.add(llave, 0, settings.LOGIN_BLOQUEO_SEGUNDOS)
            try:
                cache.incr(llave)
            except ValueError:      # vencio entre el `add` y el `incr`
                cache.set(llave, 1, settings.LOGIN_BLOQUEO_SEGUNDOS)
            registrar(request, RegistroAuditoria.Accion.LOGIN_FALLIDO,
                      descripcion=f"Intento de ingreso fallido para '{nombre}'")
            messages.error(request, "Usuario o contraseña incorrectos.")

    for campo in form.fields.values():
        campo.widget.attrs.setdefault("class", "input")
    return render(request, "cuentas/login.html", {
        "form": form,
        "next": request.GET.get("next", ""),
    })


@require_POST
def logout_view(request):
    """Solo por POST.

    Por GET alcanzaba con que alguien viera una imagen `<img src=".../salir/">`
    —en un correo, en cualquier página— para quedar afuera del sistema sin
    entender por qué. Molesto más que grave, pero además deja la bitácora
    llena de cierres de sesión que nadie hizo.
    """
    if request.user.is_authenticated:
        registrar(request, RegistroAuditoria.Accion.LOGOUT, descripcion="Cerró sesión")
    logout(request)
    messages.info(request, "Sesión cerrada.")
    return redirect("cuentas:login")


@login_required
def invitaciones(request):
    """Página propia para generar y gestionar links de registro. Solo admin."""
    if not request.user.es_admin:
        messages.error(request, "Solo el administrador puede generar invitaciones.")
        return redirect("expedientes:panel")

    form = InvitacionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        inv = form.save(commit=False)
        inv.creada_por = request.user
        inv.save()
        registrar(request, RegistroAuditoria.Accion.CREAR, entidad="Invitación",
                  objeto_id=inv.pk,
                  descripcion=f"Generó link de registro para {inv.get_rol_display()}"
                              f"{f' ({inv.zona})' if inv.zona else ''}")
        messages.success(request, "Link de registro generado. Copialo y envialo.")
        return redirect("cuentas:invitaciones")

    invs = (InvitacionRegistro.objects
            .select_related("zona", "departamento", "usada_por")
            .all())
    return render(request, "cuentas/invitaciones.html", {
        "form": form, "invitaciones": invs,
    })


@login_required
@require_POST
def invitacion_anular(request, pk):
    if not request.user.es_admin:
        messages.error(request, "Solo el administrador puede anular invitaciones.")
        return redirect("expedientes:panel")
    inv = get_object_or_404(InvitacionRegistro, pk=pk)
    inv.activa = False
    inv.save(update_fields=["activa"])
    registrar(request, RegistroAuditoria.Accion.EDITAR, entidad="Invitación",
              objeto_id=inv.pk, descripcion="Anuló un link de registro")
    messages.info(request, "Invitación anulada.")
    return redirect("cuentas:invitaciones")


@never_cache
def registro(request, token):
    """Registro público mediante link tokenizado. El rol/zona vienen de la invitación."""
    invitacion = get_object_or_404(InvitacionRegistro, token=token)

    if not invitacion.esta_vigente:
        return render(request, "cuentas/registro_invalido.html",
                      {"invitacion": invitacion}, status=410)

    form = RegistroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = form.save(commit=False)
        # El rol, la zona y el departamento los define la invitación, no el usuario.
        usuario.rol = invitacion.rol
        usuario.zona = invitacion.zona
        usuario.acceso_nacional = invitacion.acceso_nacional
        usuario.departamento = invitacion.departamento
        usuario.save()

        # Marcar la invitación como usada (un solo uso).
        invitacion.usada_por = usuario
        invitacion.usada_en = timezone.now()
        invitacion.activa = False
        invitacion.save(update_fields=["usada_por", "usada_en", "activa"])

        registrar(request, RegistroAuditoria.Accion.CREAR, entidad="Usuario",
                  objeto_id=usuario.pk,
                  descripcion=f"Registro por invitación: '{usuario.username}' "
                              f"como {usuario.get_rol_display()}"
                              f"{f' ({usuario.zona})' if usuario.zona else ''}")

        login(request, usuario)
        messages.success(request, f"¡Cuenta creada! Bienvenido/a, {usuario.get_full_name() or usuario.username}.")
        return redirect("expedientes:panel")

    return render(request, "cuentas/registro.html", {
        "form": form, "invitacion": invitacion,
    })
