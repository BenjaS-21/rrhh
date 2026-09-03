from django.urls import path

from . import views

app_name = "configuracion"

urlpatterns = [
    path("", views.index, name="index"),
    # Antes de "<slug>/" para que no se la coma el patrón de catálogos.
    path("opciones/", views.preferencias, name="preferencias"),
    path("pendientes/", views.pendientes_de_eliminar, name="pendientes"),
    path("respaldo/", views.respaldo_descargar, name="respaldo"),
    path("usuarios/", views.usuarios, name="usuarios"),
    path("usuarios/<int:pk>/clave/", views.usuario_cambiar_clave, name="usuario_clave"),
    path("usuarios/<int:pk>/recuperacion/", views.usuario_recuperacion,
         name="usuario_recuperacion"),
    path("duplicados/", views.duplicados, name="duplicados"),
    path("<slug:slug>/", views.lista, name="lista"),
    path("<slug:slug>/nuevo/", views.crear, name="crear"),
    path("<slug:slug>/mayusculas/", views.mayusculas, name="mayusculas"),
    path("<slug:slug>/<int:pk>/editar/", views.editar, name="editar"),
    path("<slug:slug>/<int:pk>/estado/", views.toggle, name="toggle"),
]
