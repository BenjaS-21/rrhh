from django.urls import path

from . import views

app_name = "cuentas"

urlpatterns = [
    path("ingresar/", views.login_view, name="login"),
    path("salir/", views.logout_view, name="logout"),
    path("invitaciones/", views.invitaciones, name="invitaciones"),
    path("invitaciones/<int:pk>/anular/", views.invitacion_anular, name="invitacion_anular"),
    path("registro/<str:token>/", views.registro, name="registro"),
]
