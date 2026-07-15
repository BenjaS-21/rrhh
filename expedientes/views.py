"""Vistas del sistema de expedientes."""

import mimetypes
import os
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .auditoria import registrar
from .forms import DocumentoForm, FiltroTrabajadorForm, TrabajadorForm
from .models import Documento, RegistroAuditoria, Trabajador
from .permisos import (
    exigir_borrar,
    exigir_editar_trabajador,
    exigir_ver_trabajador,
    trabajadores_visibles,
)


@login_required
def panel(request):
    """Tablero con métricas según el alcance del usuario."""
    trabajadores = trabajadores_visibles(request.user)
    docs = Documento.objects.filter(activo=True, trabajador__in=trabajadores)
    hoy = timezone.localdate()
    limite = hoy + timezone.timedelta(days=30)

    por_vencer = docs.filter(
        fecha_vencimiento__isnull=False,
        fecha_vencimiento__gte=hoy,
        fecha_vencimiento__lte=limite,
    ).select_related("trabajador", "tipo").order_by("fecha_vencimiento")[:10]

    contexto = {
        "total_trabajadores": trabajadores.count(),
        "total_documentos": docs.count(),
        "por_vencer": por_vencer,
        "cantidad_por_vencer": docs.filter(
            fecha_vencimiento__isnull=False,
            fecha_vencimiento__gte=hoy,
            fecha_vencimiento__lte=limite,
        ).count(),
        "vencidos": docs.filter(fecha_vencimiento__lt=hoy).count(),
    }
    return render(request, "expedientes/panel.html", contexto)


@login_required
def trabajador_list(request):
    form = FiltroTrabajadorForm(request.GET or None, usuario=request.user)
    qs = trabajadores_visibles(request.user).annotate(
        cant_docs=Count("documentos", filter=Q(documentos__activo=True))
    ).order_by("apellidos", "nombres")

    if form.is_valid():
        q = form.cleaned_data.get("q")
        sede = form.cleaned_data.get("sede")
        estado = form.cleaned_data.get("estado")
        if q:
            qs = qs.filter(
                Q(nombres__icontains=q)
                | Q(apellidos__icontains=q)
                | Q(documento_identidad__icontains=q)
            )
        if sede:
            qs = qs.filter(sede=sede)
        if estado:
            qs = qs.filter(estado=estado)

    paginador = Paginator(qs, 15)
    pagina = paginador.get_page(request.GET.get("page"))

    contexto = {"form": form, "pagina": pagina}
    # Respuesta parcial para HTMX (búsqueda en vivo).
    if request.headers.get("HX-Request"):
        return render(request, "expedientes/_tabla_trabajadores.html", contexto)
    return render(request, "expedientes/trabajador_list.html", contexto)


@login_required
def trabajador_detail(request, pk):
    trabajador = get_object_or_404(
        Trabajador.objects.select_related("sede", "sede__zona"), pk=pk
    )
    exigir_ver_trabajador(request.user, trabajador)
    registrar(request, RegistroAuditoria.Accion.VER, entidad="Trabajador",
              objeto_id=trabajador.pk, descripcion=f"Consultó expediente de {trabajador}")

    documentos = (
        trabajador.documentos.filter(activo=True)
        .select_related("tipo", "subido_por")
        .order_by("tipo__orden", "-subido_en")
    )
    cargados, requeridos, faltantes = trabajador.estado_completitud()

    contexto = {
        "trabajador": trabajador,
        "documentos": documentos,
        "form_doc": DocumentoForm(),
        "cargados": cargados,
        "requeridos": requeridos,
        "faltantes": faltantes,
        "pct_completitud": int(cargados / requeridos * 100) if requeridos else 100,
    }
    return render(request, "expedientes/trabajador_detail.html", contexto)


@login_required
def trabajador_create(request):
    if not request.user.puede_editar:
        messages.error(request, "Tu rol no permite crear expedientes.")
        return redirect("expedientes:trabajador_list")

    form = TrabajadorForm(request.POST or None, usuario=request.user)
    if request.method == "POST" and form.is_valid():
        trabajador = form.save()
        registrar(request, RegistroAuditoria.Accion.CREAR, entidad="Trabajador",
                  objeto_id=trabajador.pk, descripcion=f"Creó expediente de {trabajador}")
        messages.success(request, "Expediente creado correctamente.")
        return redirect("expedientes:trabajador_detail", pk=trabajador.pk)

    return render(request, "expedientes/trabajador_form.html",
                  {"form": form, "titulo": "Nuevo expediente"})


@login_required
def trabajador_update(request, pk):
    trabajador = get_object_or_404(Trabajador, pk=pk)
    exigir_editar_trabajador(request.user, trabajador)

    form = TrabajadorForm(request.POST or None, instance=trabajador, usuario=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        registrar(request, RegistroAuditoria.Accion.EDITAR, entidad="Trabajador",
                  objeto_id=trabajador.pk, descripcion=f"Editó datos de {trabajador}")
        messages.success(request, "Datos actualizados.")
        return redirect("expedientes:trabajador_detail", pk=trabajador.pk)

    return render(request, "expedientes/trabajador_form.html",
                  {"form": form, "titulo": f"Editar: {trabajador.nombre_completo}"})


@login_required
@require_POST
def documento_subir(request, pk):
    trabajador = get_object_or_404(Trabajador, pk=pk)
    exigir_editar_trabajador(request.user, trabajador)

    form = DocumentoForm(request.POST, request.FILES)
    if form.is_valid():
        doc = form.save(commit=False)
        doc.trabajador = trabajador
        doc.subido_por = request.user
        doc.nombre_original = request.FILES["archivo"].name[:255]
        doc.tamano_bytes = request.FILES["archivo"].size
        # Versionado: cuenta documentos previos del mismo tipo (incluye papelera).
        doc.version = trabajador.documentos.filter(tipo=doc.tipo).count() + 1
        doc.save()
        registrar(request, RegistroAuditoria.Accion.SUBIR, entidad="Documento",
                  objeto_id=doc.pk,
                  descripcion=f"Subió '{doc.tipo}' (v{doc.version}) a {trabajador}")
        messages.success(request, f"Documento '{doc.tipo}' cargado (v{doc.version}).")
    else:
        errores = "; ".join(f"{c}: {', '.join(e)}" for c, e in form.errors.items())
        messages.error(request, f"No se pudo subir el documento. {errores}")
    return redirect("expedientes:trabajador_detail", pk=trabajador.pk)


@login_required
def documento_descargar(request, pk):
    doc = get_object_or_404(
        Documento.objects.select_related("trabajador", "trabajador__sede"), pk=pk
    )
    exigir_ver_trabajador(request.user, doc.trabajador)
    if not doc.activo and not request.user.es_admin:
        raise Http404()

    try:
        contenido = doc.archivo.storage.leer_descifrado(doc.archivo.name)
    except FileNotFoundError:
        raise Http404("El archivo no está disponible.")

    registrar(request, RegistroAuditoria.Accion.DESCARGAR, entidad="Documento",
              objeto_id=doc.pk,
              descripcion=f"Descargó '{doc.tipo}' de {doc.trabajador}")

    nombre = doc.nombre_original or os.path.basename(doc.archivo.name)
    tipo_mime = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
    inline = doc.extension in {".pdf", ".jpg", ".jpeg", ".png", ".webp"}

    respuesta = FileResponse(BytesIO(contenido), content_type=tipo_mime)
    disp = "inline" if inline else "attachment"
    respuesta["Content-Disposition"] = f'{disp}; filename="{nombre}"'
    return respuesta


@login_required
@require_POST
def documento_borrar(request, pk):
    doc = get_object_or_404(Documento.objects.select_related("trabajador"), pk=pk)
    exigir_ver_trabajador(request.user, doc.trabajador)
    exigir_borrar(request.user)

    doc.activo = False
    doc.save(update_fields=["activo"])
    registrar(request, RegistroAuditoria.Accion.BORRAR, entidad="Documento",
              objeto_id=doc.pk,
              descripcion=f"Envió a papelera '{doc.tipo}' de {doc.trabajador}")
    messages.warning(request, "Documento enviado a la papelera.")
    return redirect("expedientes:trabajador_detail", pk=doc.trabajador_id)


@login_required
@require_POST
def documento_restaurar(request, pk):
    doc = get_object_or_404(Documento.objects.select_related("trabajador"), pk=pk)
    exigir_ver_trabajador(request.user, doc.trabajador)
    exigir_borrar(request.user)

    doc.activo = True
    doc.save(update_fields=["activo"])
    registrar(request, RegistroAuditoria.Accion.RESTAURAR, entidad="Documento",
              objeto_id=doc.pk,
              descripcion=f"Restauró '{doc.tipo}' de {doc.trabajador}")
    messages.success(request, "Documento restaurado.")
    return redirect("expedientes:trabajador_detail", pk=doc.trabajador_id)


@login_required
def papelera(request, pk):
    """Documentos en papelera de un trabajador (solo admin)."""
    trabajador = get_object_or_404(Trabajador, pk=pk)
    exigir_ver_trabajador(request.user, trabajador)
    if not request.user.es_admin:
        messages.error(request, "Solo el Administrador puede ver la papelera.")
        return redirect("expedientes:trabajador_detail", pk=pk)

    documentos = trabajador.documentos.filter(activo=False).select_related("tipo")
    return render(request, "expedientes/papelera.html",
                  {"trabajador": trabajador, "documentos": documentos})


def _nomina_filtrada(request):
    """Queryset de trabajadores visibles + filtros de la nómina. Devuelve (form, qs)."""
    form = FiltroTrabajadorForm(request.GET or None, usuario=request.user)
    qs = (trabajadores_visibles(request.user)
          .select_related("sede", "sede__zona", "departamento")
          .order_by("apellidos", "nombres"))
    if form.is_valid():
        q = form.cleaned_data.get("q")
        sede = form.cleaned_data.get("sede")
        departamento = form.cleaned_data.get("departamento")
        estado = form.cleaned_data.get("estado")
        if q:
            qs = qs.filter(
                Q(nombres__icontains=q)
                | Q(apellidos__icontains=q)
                | Q(documento_identidad__icontains=q)
            )
        if sede:
            qs = qs.filter(sede=sede)
        if departamento:
            qs = qs.filter(departamento=departamento)
        if estado:
            qs = qs.filter(estado=estado)
    return form, qs


@login_required
def nomina(request):
    """Listado de trabajadores: C.I., apellidos, nombres, cargo, departamento, tienda."""
    form, qs = _nomina_filtrada(request)
    paginador = Paginator(qs, 25)
    pagina = paginador.get_page(request.GET.get("page"))
    contexto = {"form": form, "pagina": pagina, "total": qs.count(),
                "querystring": request.GET.urlencode()}
    if request.headers.get("HX-Request"):
        return render(request, "expedientes/_tabla_nomina.html", contexto)
    return render(request, "expedientes/nomina.html", contexto)


@login_required
def nomina_export(request):
    """Exporta la nómina filtrada a un archivo Excel (.xlsx)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    _, qs = _nomina_filtrada(request)

    wb = Workbook()
    ws = wb.active
    ws.title = "Nómina"

    encabezados = ["C.I.", "Apellidos", "Nombres", "Cargo", "Departamento", "Tienda"]
    ws.append(encabezados)

    # Estilo del encabezado (rojo Damasco, texto blanco).
    header_fill = PatternFill("solid", fgColor="E1052D")
    header_font = Font(bold=True, color="FFFFFF")
    for col, _titulo in enumerate(encabezados, start=1):
        celda = ws.cell(row=1, column=col)
        celda.fill = header_fill
        celda.font = header_font
        celda.alignment = Alignment(horizontal="left", vertical="center")

    for t in qs:
        ws.append([
            t.documento_identidad,
            t.apellidos,
            t.nombres,
            t.puesto or "",
            t.departamento.nombre if t.departamento else "",
            t.sede.nombre if t.sede else "",
        ])

    # Ancho de columnas automático (acotado).
    for col in range(1, len(encabezados) + 1):
        letra = get_column_letter(col)
        largo = max([len(str(encabezados[col - 1]))]
                    + [len(str(ws.cell(row=r, column=col).value or ""))
                       for r in range(2, ws.max_row + 1)] or [0])
        ws.column_dimensions[letra].width = min(max(largo + 2, 12), 40)
    ws.freeze_panes = "A2"

    registrar(request, RegistroAuditoria.Accion.DESCARGAR, entidad="Nómina",
              descripcion=f"Exportó la nómina a Excel ({qs.count()} trabajadores)")

    from io import BytesIO
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    fecha = timezone.localdate().strftime("%Y%m%d")
    resp = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="nomina_{fecha}.xlsx"'
    return resp


@login_required
def auditoria_list(request):
    """Bitácora de auditoría. Solo administradores."""
    if not request.user.es_admin:
        messages.error(request, "Solo el Administrador puede ver la auditoría.")
        return redirect("expedientes:trabajador_list")

    qs = RegistroAuditoria.objects.select_related("usuario")
    accion = request.GET.get("accion")
    if accion:
        qs = qs.filter(accion=accion)
    q = request.GET.get("q")
    if q:
        qs = qs.filter(Q(usuario_texto__icontains=q) | Q(descripcion__icontains=q))

    paginador = Paginator(qs, 30)
    pagina = paginador.get_page(request.GET.get("page"))
    return render(request, "expedientes/auditoria_list.html", {
        "pagina": pagina,
        "acciones": RegistroAuditoria.Accion.choices,
        "accion_sel": accion or "",
        "q": q or "",
    })
