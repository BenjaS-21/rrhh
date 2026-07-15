"""Panel de configuración: administración de catálogos por parte del admin.

Página propia (no el admin de Django) para crear/editar/activar los catálogos
organizativos: Departamentos, Áreas, Zonas, Tiendas y Tipos de documento.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from cuentas.models import Area, Departamento, Sede, Zona
from expedientes.auditoria import registrar
from expedientes.models import RegistroAuditoria, TipoDocumento

from .forms import (
    AreaForm, DepartamentoForm, SedeForm, TipoDocumentoForm, ZonaForm,
)


def _si_no(v):
    return "Sí" if v else "No"


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
        "icono": "🗂️", "activo": "activo",
        "columnas": [("Nombre", lambda o: o.nombre),
                     ("Departamento", lambda o: str(o.departamento)),
                     ("Descripción", lambda o: o.descripcion or "—")],
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
        "icono": "🏬", "activo": "activa",
        "columnas": [("Nombre", lambda o: o.nombre),
                     ("Zona", lambda o: str(o.zona)),
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
            "slug": slug, "plural": cat["plural"], "icono": cat["icono"],
            "activos": activos, "total": total,
        })
    return render(request, "configuracion/index.html", {"tarjetas": tarjetas})


@admin_requerido
def lista(request, slug):
    cat = _cat(slug)
    campo_activo = cat["activo"]
    filas = []
    for o in cat["model"].objects.all():
        filas.append({
            "pk": o.pk,
            "activo": getattr(o, campo_activo),
            "celdas": [getter(o) for _, getter in cat["columnas"]],
        })
    contexto = {
        "slug": slug, "cat": cat,
        "headers": [h for h, _ in cat["columnas"]],
        "filas": filas,
    }
    return render(request, "configuracion/lista.html", contexto)


@admin_requerido
def crear(request, slug):
    cat = _cat(slug)
    form = cat["form"](request.POST or None)
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
    form = cat["form"](request.POST or None, instance=obj)
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
