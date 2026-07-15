"""Rutas principales del proyecto."""

from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Expedientes RRHH — Administración"
admin.site.site_title = "Expedientes RRHH"
admin.site.index_title = "Panel de administración"

urlpatterns = [
    path("gestion-django/", admin.site.urls),
    path("cuentas/", include("cuentas.urls")),
    path("configuracion/", include("configuracion.urls")),
    path("", include("expedientes.urls")),
]
