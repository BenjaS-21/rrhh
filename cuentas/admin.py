from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.utils.html import format_html

from .models import Area, Departamento, InvitacionRegistro, Sede, Usuario, Zona


@admin.register(Zona)
class ZonaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "descripcion", "activa")
    list_filter = ("activa",)
    search_fields = ("nombre",)


@admin.register(Departamento)
class DepartamentoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "descripcion", "activo")
    list_filter = ("activo",)
    search_fields = ("nombre",)


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "departamento", "activo")
    list_filter = ("departamento", "activo")
    search_fields = ("nombre",)


@admin.register(Sede)
class SedeAdmin(admin.ModelAdmin):
    list_display = ("nombre", "zona", "es_central", "activa")
    list_filter = ("zona", "es_central", "activa")
    search_fields = ("nombre",)


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    add_form = UserCreationForm
    form = UserChangeForm
    list_display = ("username", "get_full_name", "rol", "zona", "departamento", "is_active")
    list_filter = ("rol", "zona", "departamento", "is_active")
    search_fields = ("username", "first_name", "last_name", "email")

    fieldsets = UserAdmin.fieldsets + (
        ("Rol, zona y departamento", {"fields": ("rol", "zona", "departamento", "telefono")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Rol, zona y departamento", {"fields": ("rol", "zona", "departamento")}),
    )


@admin.register(InvitacionRegistro)
class InvitacionRegistroAdmin(admin.ModelAdmin):
    """Links tokenizados de registro. El filtro lateral por Rol es el 'menú' de links."""

    list_display = ("descripcion_corta", "rol", "zona", "departamento", "estado_badge", "link_registro", "expira_en", "creada_en")
    list_filter = ("rol", "activa", "zona", "departamento")   # <- filtro por rol = menú lateral
    search_fields = ("email", "nota", "token", "usada_por__username")
    readonly_fields = ("token", "link_registro", "creada_por", "creada_en",
                       "usada_por", "usada_en", "estado_badge")
    fieldsets = (
        ("Configuración del link", {
            "fields": ("rol", "zona", "departamento", "email", "nota", "expira_en"),
            "description": "Elegí el rol (y la zona si es RRHH Interior o Solo lectura). "
                           "El departamento es opcional e informativo. "
                           "Al guardar se genera el link para copiar y enviar.",
        }),
        ("Link generado", {"fields": ("link_registro", "token", "estado_badge")}),
        ("Uso", {"fields": ("usada_por", "usada_en", "activa", "creada_por", "creada_en")}),
    )
    actions = ["anular_invitaciones"]

    @admin.display(description="Invitación")
    def descripcion_corta(self, obj):
        return obj.nota or (obj.email or f"#{obj.pk}")

    @admin.display(description="Estado")
    def estado_badge(self, obj):
        colores = {"Vigente": "#22C55E", "Usada": "#747474",
                   "Expirada": "#F59E0B", "Anulada": "#EF4444"}
        color = colores.get(obj.estado, "#747474")
        return format_html(
            '<b style="color:{}">{}</b>', color, obj.estado
        )

    @admin.display(description="Link de registro")
    def link_registro(self, obj):
        if not obj.pk:
            return "—"
        url = obj.get_link_absoluto()
        if obj.esta_vigente:
            return format_html('<a href="{}" target="_blank">{}</a>', url, url)
        return format_html('<span style="color:#747474;text-decoration:line-through">{}</span>', url)

    def save_model(self, request, obj, form, change):
        if not obj.pk and not obj.creada_por_id:
            obj.creada_por = request.user
        super().save_model(request, obj, form, change)
        if not change:
            messages.success(
                request,
                format_html("Link generado: <b>{}</b> — copialo y envialo a la persona.",
                            obj.get_link_absoluto()),
            )

    @admin.action(description="Anular invitaciones seleccionadas")
    def anular_invitaciones(self, request, queryset):
        n = queryset.update(activa=False)
        self.message_user(request, f"{n} invitación(es) anulada(s).")
