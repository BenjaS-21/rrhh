"""Rutas principales del proyecto."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = f"{settings.NOMBRE_SISTEMA} — Administración"
admin.site.site_title = settings.NOMBRE_SISTEMA
admin.site.index_title = "Panel de administración"

urlpatterns = [
    path("gestion-django/", admin.site.urls),
    path("cuentas/", include("cuentas.urls")),
    path("configuracion/", include("configuracion.urls")),
    path("", include("expedientes.urls")),
]
