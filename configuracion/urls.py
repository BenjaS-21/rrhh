from django.urls import path

from . import views

app_name = "configuracion"

urlpatterns = [
    path("", views.index, name="index"),
    path("<slug:slug>/", views.lista, name="lista"),
    path("<slug:slug>/nuevo/", views.crear, name="crear"),
    path("<slug:slug>/<int:pk>/editar/", views.editar, name="editar"),
    path("<slug:slug>/<int:pk>/estado/", views.toggle, name="toggle"),
]
