from django.urls import path

from . import views

app_name = "expedientes"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("trabajadores/", views.trabajador_list, name="trabajador_list"),
    path("nomina/", views.nomina, name="nomina"),
    path("nomina/exportar/", views.nomina_export, name="nomina_export"),
    path("trabajadores/nuevo/", views.trabajador_create, name="trabajador_create"),
    path("trabajadores/<int:pk>/", views.trabajador_detail, name="trabajador_detail"),
    path("trabajadores/<int:pk>/editar/", views.trabajador_update, name="trabajador_update"),
    path("trabajadores/<int:pk>/papelera/", views.papelera, name="papelera"),
    path("trabajadores/<int:pk>/documentos/subir/", views.documento_subir, name="documento_subir"),
    path("documentos/<int:pk>/descargar/", views.documento_descargar, name="documento_descargar"),
    path("documentos/<int:pk>/borrar/", views.documento_borrar, name="documento_borrar"),
    path("documentos/<int:pk>/restaurar/", views.documento_restaurar, name="documento_restaurar"),
    path("auditoria/", views.auditoria_list, name="auditoria_list"),
]
