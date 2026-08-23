"""Panel de configuración: administración de catálogos por parte del admin.

Página propia (no el admin de Django) para crear/editar/activar los catálogos
organizativos: Departamentos, Áreas, Zonas, Tiendas y Tipos de documento.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from cuentas.models import Area, Cargo, Departamento, Sede, Zona
from expedientes.auditoria import registrar
from expedientes.models import ConceptoPago, Moneda, RegistroAuditoria, TipoDocumento
from expedientes.purga import barrer, pendientes

from .forms import (
    AreaForm, CargoForm, ConceptoPagoForm, DepartamentoForm, MonedaForm,
    PreferenciasForm,
    SedeForm, TipoDocumentoForm, ZonaForm,
)
from .models import Preferencias


def _si_no(v):
    return "Sí" if v else "No"


def _datos(request):
    """Datos del POST, o None si es un GET.

    No sirve `request.POST or None`: un POST cuyo único campo es una casilla
    sin marcar llega vacío, y el formulario quedaría sin ligar justo cuando se
    quiere apagar una opción.
    """
    return request.POST if request.method == "POST" else None


# Registro de catálogos administrables. Cada entrada define su modelo, formulario,
# etiquetas, el nombre del campo "activo" y las columnas de la tabla.
CATALOGOS = {
    "departamentos": {
        "model": Departamento, "form": DepartamentoForm,
        "singular": "departamento", "plural": "Departamentos",
        "icono": "🏢", "activo": "activo",
        "columnas": [("Nombre", lambda o: o.nombre),
                     ("Descripción", lambda o: o.descripcion or "—")],
    },
    "areas": {
        "model": Area, "form": AreaForm,
        "singular": "área", "plural": "Áreas",
        "icono": "🗂️", "activo": "activo", "select_related": ["departamento"],
        "columnas": [("Nombre", lambda o: o.nombre),
                     ("Departamento", lambda o: str(o.departamento)),
                     ("Descripción", lambda o: o.descripcion or "—")],
    },
    "cargos": {
        "model": Cargo, "form": CargoForm,
        "singular": "cargo", "plural": "Cargos",
        "icono": "🧰", "activo": "activo", "select_related": ["departamento"],
        # Son cientos: sin buscador la página no se puede usar.
        "buscar": ["nombre__icontains", "departamento__nombre__icontains"],
        "columnas": [("Nombre", lambda o: o.nombre),
                     ("Unidad organizativa", lambda o: str(o.departamento))],
    },
    "zonas": {
        "model": Zona, "form": ZonaForm,
        "singular": "zona", "plural": "Zonas",
        "icono": "🗺️", "activo": "activa",
        "columnas": [("Nombre", lambda o: o.nombre),
                     ("Descripción", lambda o: o.descripcion or "—")],
    },
    "tiendas": {
        "model": Sede, "form": SedeForm,
        "singular": "tienda", "plural": "Tiendas",
        "icono": "🏬", "activo": "activa", "select_related": ["zona"],
        "columnas": [("Nombre", lambda o: o.nombre),
                     ("Zona", lambda o: str(o.zona)),
                     # Se muestra `lugar` y no `ciudad`: asi se ve de una cual
                     # va a salir impresa en los documentos, este cargada o no.
                     ("Ciudad", lambda o: o.lugar),
                     ("Central", lambda o: _si_no(o.es_central))],
    },
    "tipos-documento": {
        "model": TipoDocumento, "form": TipoDocumentoForm,
        "singular": "tipo de documento", "plural": "Tipos de documento",
        "icono": "📄", "activo": "activo",
        "columnas": [("Nombre", lambda o: o.nombre),
                     ("Obligatorio", lambda o: _si_no(o.obligatorio)),
                     ("Vence", lambda o: _si_no(o.requiere_vencimiento)),
                     ("Orden", lambda o: o.orden)],
    },
    "monedas": {
        "model": Moneda, "form": MonedaForm,
        "singular": "moneda", "plural": "Monedas",
        "icono": "💱", "activo": "activa",
        "columnas": [("Código", lambda o: o.codigo),
                     ("Nombre", lambda o: o.nombre),
                     ("Símbolo", lambda o: o.simbolo),
                     ("Nacional", lambda o: _si_no(o.es_nacional))],
    },
    "conceptos-pago": {
        "model": ConceptoPago, "form": ConceptoPagoForm,
        "singular": "concepto de pago", "plural": "Conceptos de pago",
        "icono": "💰", "activo": "activo", "select_related": ["moneda"],
        "columnas": [("Nombre", lambda o: o.nombre),
                     ("Clase", lambda o: o.get_clase_display()),
                     ("Moneda", lambda o: f"{o.moneda.simbolo} ({o.moneda.codigo})"),
                     ("Descripción", lambda o: o.descripcion or "—"),
                     ("Orden", lambda o: o.orden)],
    },
}


def admin_requerido(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.es_admin:
            messages.error(request, "Solo el administrador puede acceder a la configuración.")
            return redirect("expedientes:panel")
        return view(request, *args, **kwargs)
    return wrapper


def _cat(slug):
    cat = CATALOGOS.get(slug)
    if cat is None:
        raise Http404("Catálogo no encontrado.")
    return cat


@admin_requerido
def index(request):
    tarjetas = []
    for slug, cat in CATALOGOS.items():
        activos = cat["model"].objects.filter(**{cat["activo"]: True}).count()
        total = cat["model"].objects.count()
        tarjetas.append({
            "slug": slug, "plural": cat["plural"], "singular": cat["singular"],
            "icono": cat["icono"], "activos": activos, "total": total,
        })
    return render(request, "configuracion/index.html", {
        "tarjetas": tarjetas,
        "preferencias": Preferencias.obtener(),
        # Con el número a la vista no hace falta entrar a la pantalla para
        # enterarse de que alguien está esperando una respuesta.
        "cuantos_pendientes": pendientes().count(),
    })


@admin_requerido
def pendientes_de_eliminar(request):
    """Los documentos que alguien marcó para eliminar, esperando decisión.

    Barre primero: si el Administrador puso un plazo, los que ya lo cumplieron
    tienen que estar en la papelera antes de dibujar la lista. Si no, quedan
    a la vista como pendientes cuando en realidad su plazo ya pasó, y el
    número de arriba miente.
    """
    barridos = barrer()
    if barridos:
        messages.info(
            request,
            f"{barridos} documento/s con el plazo cumplido pasaron a la papelera.")

    prefs = Preferencias.obtener()
    dias = prefs.dias_para_eliminar_marcados
    documentos = [
        {"doc": d, "se_borra_el": d.se_borra_el(dias)}
        for d in pendientes()
    ]
    return render(request, "configuracion/pendientes.html", {
        "documentos": documentos,
        "dias": dias,
        "preferencias": prefs,
    })


@admin_requerido
def preferencias(request):
    """Opciones que valen para todo el sistema, no un catálogo."""
    obj = Preferencias.obtener()
    anterior = obj.restringir_por_zona
    form = PreferenciasForm(_datos(request), instance=obj)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.actualizado_por = request.user
        obj.save()
        if obj.restringir_por_zona != anterior:
            estado = "Activó" if obj.restringir_por_zona else "Desactivó"
            registrar(request, RegistroAuditoria.Accion.EDITAR,
                      entidad="Opciones del sistema", objeto_id=obj.pk,
                      descripcion=f"{estado} «restringir cada usuario a su zona»")
        messages.success(request, "Opciones guardadas.")
        return redirect("configuracion:preferencias")
    return render(request, "configuracion/preferencias.html", {"form": form})


@admin_requerido
def lista(request, slug):
    cat = _cat(slug)
    campo_activo = cat["activo"]
    qs = cat["model"].objects.all()
    if cat.get("select_related"):
        qs = qs.select_related(*cat["select_related"])

    # Buscador, solo donde el catálogo lo pide. Los cargos son 800 y pico: sin
    # esto la página es una lista imposible de recorrer.
    busqueda = (request.GET.get("q") or "").strip()
    if busqueda and cat.get("buscar"):
        condicion = Q()
        for campo in cat["buscar"]:
            condicion |= Q(**{campo: busqueda})
        qs = qs.filter(condicion)

    filas = []
    for o in qs:
        filas.append({
            "pk": o.pk,
            "activo": getattr(o, campo_activo),
            "celdas": [getter(o) for _, getter in cat["columnas"]],
        })
    contexto = {
        "slug": slug, "cat": cat,
        "headers": [h for h, _ in cat["columnas"]],
        "filas": filas,
        "busqueda": busqueda,
        "total": cat["model"].objects.count(),
        # El botón de pasar a mayúsculas solo tiene sentido si hay algo que
        # pasar. Se cuenta sobre TODO el catálogo, no sobre lo que dejó ver el
        # buscador: el botón tampoco se limita a lo que está en pantalla.
        "sin_mayusculas": _cuantos_sin_mayusculas(cat),
    }
    return render(request, "configuracion/lista.html", contexto)


def _sin_mayusculas(cat):
    """Los objetos del catálogo cuyo nombre no está todo en mayúsculas."""
    return [o for o in cat["model"].objects.all() if o.nombre != o.nombre.upper()]


def _cuantos_sin_mayusculas(cat):
    return sum(1 for n in cat["model"].objects.values_list("nombre", flat=True)
               if n != n.upper())


@admin_requerido
@require_POST
def mayusculas(request, slug):
    """Pasa a MAYÚSCULAS los nombres del catálogo que no lo estén.

    El catálogo real de la empresa está todo en mayúsculas. Lo que se carga a
    mano entra como se escribió, y entonces conviven "Sistemas" y "GERENCIA DE
    SISTEMAS" como si fueran dos cosas distintas: la lista se desordena y en
    los desplegables parecen unidades duplicadas.

    Se cambia uno por uno y no con un UPDATE masivo a propósito: así, si al
    pasarlo a mayúscula choca con otro que ya existía, se saltea ese y sigue
    con el resto, en vez de fallar entero sin explicar cuál fue.
    """
    cat = _cat(slug)
    cambiados, chocaron = [], []
    for objeto in _sin_mayusculas(cat):
        anterior = objeto.nombre
        objeto.nombre = anterior.upper()
        try:
            with transaction.atomic():
                objeto.save(update_fields=["nombre"])
        except IntegrityError:
            objeto.nombre = anterior
            chocaron.append(anterior)
        else:
            cambiados.append(anterior)

    if cambiados:
        muestra = ", ".join(cambiados[:5])
        if len(cambiados) > 5:
            muestra += f" y {len(cambiados) - 5} más"
        registrar(request, RegistroAuditoria.Accion.EDITAR, entidad=cat["plural"],
                  descripcion=f"Pasó {len(cambiados)} nombre"
                              f"{'s' if len(cambiados) != 1 else ''} a mayúsculas "
                              f"en {cat['plural']}: {muestra}")
        messages.success(
            request,
            f"{len(cambiados)} nombre{'s' if len(cambiados) != 1 else ''} "
            f"pasado{'s' if len(cambiados) != 1 else ''} a mayúsculas.")
    elif not chocaron:
        messages.info(request, f"Los nombres de {cat['plural'].lower()} ya estaban "
                               "todos en mayúsculas.")

    if chocaron:
        # No se toca lo que ya existe: quien decide cuál se queda es una persona.
        messages.warning(
            request,
            f"No se cambiaron {len(chocaron)}: ya hay otro con ese mismo nombre "
            f"en mayúsculas ({', '.join(chocaron[:5])}). "
            "Revisalos y unificalos a mano.")

    return redirect("configuracion:lista", slug=slug)


@admin_requerido
def crear(request, slug):
    cat = _cat(slug)
    form = cat["form"](_datos(request))
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        registrar(request, RegistroAuditoria.Accion.CREAR, entidad=cat["plural"],
                  objeto_id=obj.pk, descripcion=f"Creó {cat['singular']}: {obj}")
        messages.success(request, f"{cat['singular'].capitalize()} creado: {obj}")
        return redirect("configuracion:lista", slug=slug)
    return render(request, "configuracion/form.html", {
        "slug": slug, "cat": cat, "form": form,
        "titulo": f"Nuevo: {cat['singular']}",
    })


@admin_requerido
def editar(request, slug, pk):
    cat = _cat(slug)
    obj = get_object_or_404(cat["model"], pk=pk)
    form = cat["form"](_datos(request), instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        registrar(request, RegistroAuditoria.Accion.EDITAR, entidad=cat["plural"],
                  objeto_id=obj.pk, descripcion=f"Editó {cat['singular']}: {obj}")
        messages.success(request, f"{cat['singular'].capitalize()} actualizado: {obj}")
        return redirect("configuracion:lista", slug=slug)
    return render(request, "configuracion/form.html", {
        "slug": slug, "cat": cat, "form": form,
        "titulo": f"Editar: {obj}",
    })


@admin_requerido
@require_POST
def toggle(request, slug, pk):
    cat = _cat(slug)
    obj = get_object_or_404(cat["model"], pk=pk)
    campo = cat["activo"]
    nuevo = not getattr(obj, campo)
    setattr(obj, campo, nuevo)
    obj.save(update_fields=[campo])
    accion = "Activó" if nuevo else "Desactivó"
    registrar(request, RegistroAuditoria.Accion.EDITAR, entidad=cat["plural"],
              objeto_id=obj.pk, descripcion=f"{accion} {cat['singular']}: {obj}")
    messages.info(request, f"{accion} {cat['singular']}: {obj}")
    return redirect("configuracion:lista", slug=slug)
