from django.contrib import admin

from .models import Documento, RegistroAuditoria, TipoDocumento, Trabajador


@admin.register(TipoDocumento)
class TipoDocumentoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "obligatorio", "requiere_vencimiento", "activo", "orden")
    list_filter = ("obligatorio", "requiere_vencimiento", "activo")
    search_fields = ("nombre",)
    list_editable = ("obligatorio", "requiere_vencimiento", "activo", "orden")


class DocumentoInline(admin.TabularInline):
    model = Documento
    extra = 0
    fields = ("tipo", "archivo", "version", "fecha_vencimiento", "activo", "subido_por", "subido_en")
    readonly_fields = ("version", "subido_por", "subido_en")


@admin.register(Trabajador)
class TrabajadorAdmin(admin.ModelAdmin):
    list_display = ("documento_identidad", "apellidos", "nombres", "puesto",
                    "departamento", "sede", "estado")
    list_filter = ("sede__zona", "sede", "departamento", "estado")
    search_fields = ("documento_identidad", "nombres", "apellidos")
    inlines = [DocumentoInline]


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ("trabajador", "tipo", "version", "fecha_vencimiento", "activo", "subido_por", "subido_en")
    list_filter = ("tipo", "activo", "trabajador__sede__zona")
    search_fields = ("trabajador__apellidos", "trabajador__documento_identidad")
    readonly_fields = ("subido_por", "subido_en", "tamano_bytes", "nombre_original")


@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(admin.ModelAdmin):
    list_display = ("creado_en", "usuario_texto", "accion", "entidad", "descripcion", "ip")
    list_filter = ("accion", "creado_en")
    search_fields = ("usuario_texto", "descripcion")
    readonly_fields = ("usuario", "usuario_texto", "accion", "entidad", "objeto_id",
                       "descripcion", "ip", "creado_en")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
