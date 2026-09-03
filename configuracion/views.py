"""Panel de configuración: administración de catálogos por parte del admin.

Página propia (no el admin de Django) para crear/editar/activar los catálogos
organizativos: Departamentos, Áreas, Zonas, Tiendas y Tipos de documento.
"""

import os
import sqlite3
import tempfile
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.db import IntegrityError, connection, transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from cuentas.models import Area, Cargo, Departamento, RecuperacionClave, Sede, Zona
from expedientes.auditoria import registrar
from expedientes.models import (
    ConceptoPago, Moneda, MotivoContratacion, RegistroAuditoria, TipoDocumento,
    Trabajador,
)
from expedientes.purga import barrer, pendientes

from .forms import (
    AreaForm, CargoForm, ConceptoPagoForm, DepartamentoForm, MonedaForm,
    MotivoContratacionForm, PreferenciasForm,
    SedeForm, TipoDocumentoForm, ZonaForm,
)
from .models import Preferencias

Usuario = get_user_model()


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
    "motivos-contratacion": {
        "model": MotivoContratacion, "form": MotivoContratacionForm,
        "singular": "motivo de contratación", "plural": "Motivos de contratación",
        "icono": "📅", "activo": "activo",
        "columnas": [("Nombre", lambda o: o.nombre),
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
def usuarios(request):
    """Listado de usuarios con búsqueda, cambio de clave y links de recuperación.

    El buscador cubre usuario, nombre, apellido, correo y cédula: cuando alguien
    llama diciendo «no puedo entrar», lo único que se tiene a mano es cualquiera
    de esos datos.
    """
    q = (request.GET.get("q") or "").strip()
    lista = Usuario.objects.all().order_by("username")
    if q:
        lista = lista.filter(
            Q(username__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
            | Q(cedula__icontains=q)
        )
    return render(request, "configuracion/usuarios.html", {"q": q, "usuarios": lista})


@admin_requerido
@require_POST
def usuario_cambiar_clave(request, pk):
    """El Administrador le fija una clave nueva a un usuario, al momento."""
    usuario = get_object_or_404(Usuario, pk=pk)
    form = SetPasswordForm(usuario, request.POST)
    if form.is_valid():
        form.save()
        registrar(request, RegistroAuditoria.Accion.EDITAR, entidad="Usuario",
                  objeto_id=usuario.pk,
                  descripcion=f"Cambió la clave de '{usuario.username}'")
        messages.success(request, f"Clave de {usuario.username} actualizada.")
    else:
        primer_error = next(iter(form.errors.values()))[0]
        messages.error(
            request, f"No se cambió la clave de {usuario.username}: {primer_error}")
    return redirect("configuracion:usuarios")


@admin_requerido
@require_POST
def usuario_recuperacion(request, pk):
    """Genera el link de 48 horas para que la persona recupere su clave sola.

    Un solo link vigente por usuario: generar uno nuevo anula el anterior, así
    no quedan varias puertas abiertas a la misma cuenta.
    """
    usuario = get_object_or_404(Usuario, pk=pk)
    if not usuario.is_active:
        messages.error(
            request, f"{usuario.username} está desactivado: no se le puede dar un link.")
        return redirect("configuracion:usuarios")
    RecuperacionClave.objects.filter(usuario=usuario, activa=True).update(activa=False)
    rec = RecuperacionClave.objects.create(usuario=usuario, creada_por=request.user)
    registrar(request, RegistroAuditoria.Accion.CREAR,
              entidad="Recuperación de clave", objeto_id=rec.pk,
              descripcion=f"Generó link de recuperación para '{usuario.username}'")
    messages.success(
        request,
        f"Link de recuperación para {usuario.username} (vale 48 h): "
        f"{rec.get_link_absoluto()}")
    return redirect("configuracion:usuarios")


@admin_requerido
def duplicados(request):
    """Expedientes que podrían ser la misma persona cargada dos veces.

    Con las cargas masivas de varios archivos pasó: misma persona con la
    cédula escrita distinto («V-123» y «123»), o dos veces en archivos
    distintos con datos levemente diferentes. La cédula es única en la base,
    así que el duplicado siempre entra disfrazado de otra cosa.

    No se borra ni se fusiona nada acá: se muestran los grupos sospechosos,
    del más evidente al menos, y la decisión la toma una persona en cada
    expediente (dar de baja al que sobre).
    """
    import re
    import unicodedata
    from collections import defaultdict

    def norm(t):
        t = unicodedata.normalize("NFD", t or "")
        t = "".join(c for c in t if unicodedata.category(c) != "Mn")
        return re.sub(r"\s+", " ", t).strip().upper()

    trabajadores = list(
        Trabajador.objects.select_related("sede", "puesto", "tipo_documento")
        .annotate(cant_docs=Count("documentos", filter=Q(documentos__activo=True)))
        .order_by("apellidos", "nombres"))

    def nombre_de(t):
        return norm(f"{t.apellidos} {t.nombres}")

    criterios = [
        ("Misma cédula escrita de dos formas",
         lambda t: re.sub(r"\D", "", t.documento_identidad) or None),
        ("Mismo RIF",
         lambda t: re.sub(r"[^0-9A-Za-z]", "", t.rif).upper() or None),
    ]
    grupos = []
    for titulo, clave_de in criterios:
        por_clave = defaultdict(list)
        for t in trabajadores:
            clave = clave_de(t)
            if clave:
                por_clave[clave].append(t)
        for miembros in por_clave.values():
            if len(miembros) > 1:
                grupos.append({"criterio": titulo, "miembros": miembros})

    # Mismo nombre: si además coincide la fecha de nacimiento es duplicado
    # casi seguro; si no, puede ser homónimo y se marca para mirar con calma.
    por_nombre = defaultdict(list)
    for t in trabajadores:
        clave = nombre_de(t)
        if clave:
            por_nombre[clave].append(t)
    for miembros in por_nombre.values():
        if len(miembros) < 2:
            continue
        fechas = {t.fecha_nacimiento for t in miembros}
        if len(fechas) == 1 and None not in fechas:
            grupos.append({"criterio": "Mismo nombre y misma fecha de nacimiento",
                           "miembros": miembros})
        else:
            grupos.append({"criterio": "Mismo nombre (posible homónimo: revisar)",
                           "miembros": miembros})

    return render(request, "configuracion/duplicados.html", {"grupos": grupos})


@admin_requerido
def respaldo_descargar(request):
    """Descarga una copia de la base de datos: solo los datos, no los archivos.

    Los documentos de los expedientes (media/) no van: se respaldan aparte.

    La copia se hace con la API de respaldo de SQLite sobre la conexión de
    Django, y no copiando el archivo a lo bruto: si alguien está guardando
    algo en ese instante, el respaldo sale consistente igual. Además, así
    funciona igual en las pruebas, cuya base vive en memoria.
    """
    connection.ensure_connection()
    temporal = tempfile.NamedTemporaryFile(
        prefix="gde-respaldo-", suffix=".sqlite3", delete=False)
    temporal.close()
    try:
        destino = sqlite3.connect(temporal.name)
        try:
            connection.connection.backup(destino)
        finally:
            destino.close()
        with open(temporal.name, "rb") as f:
            datos = f.read()
    finally:
        os.unlink(temporal.name)

    marca = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    registrar(request, RegistroAuditoria.Accion.DESCARGAR, entidad="BaseDeDatos",
              descripcion="Descargó un respaldo de la base de datos")
    respuesta = HttpResponse(datos, content_type="application/vnd.sqlite3")
    respuesta["Content-Disposition"] = (
        f'attachment; filename="gde-respaldo-{marca}.sqlite3"')
    return respuesta


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
