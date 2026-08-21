"""Vistas de autenticación con registro de auditoría."""

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from expedientes.auditoria import registrar
from expedientes.models import RegistroAuditoria
from .forms import InvitacionForm, RegistroForm
from .models import InvitacionRegistro


@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return redirect("expedientes:panel")

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            usuario = form.get_user()
            login(request, usuario)
            registrar(request, RegistroAuditoria.Accion.LOGIN,
                      descripcion=f"Ingresó al sistema ({usuario.get_rol_display()})")
            messages.success(request, f"Bienvenido/a, {usuario.get_full_name() or usuario.username}.")
            destino = request.GET.get("next") or "expedientes:panel"
            return redirect(destino)
        else:
            intento = request.POST.get("username", "")
            registrar(request, RegistroAuditoria.Accion.LOGIN_FALLIDO,
                      descripcion=f"Intento de ingreso fallido para '{intento}'")
            messages.error(request, "Usuario o contraseña incorrectos.")

    for campo in form.fields.values():
        campo.widget.attrs.setdefault("class", "input")
    return render(request, "cuentas/login.html", {"form": form})


def logout_view(request):
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
