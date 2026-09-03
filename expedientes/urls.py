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
    path("trabajadores/<int:pk>/estado/", views.trabajador_estado, name="trabajador_estado"),
    path("trabajadores/<int:pk>/papelera/", views.papelera, name="papelera"),
    path("renovaciones/", views.renovaciones, name="renovaciones"),
    path("renovaciones/<int:pk>/guardar/", views.renovacion_guardar,
         name="renovacion_guardar"),
    path("renovaciones/<int:pk>/renovar/", views.renovacion_renovar,
         name="renovacion_renovar"),
    path("trabajadores/<int:pk>/documentos/subir/", views.documento_subir, name="documento_subir"),
    path("trabajadores/<int:pk>/documentos/comprimir/", views.documento_comprimir,
         name="documento_comprimir"),
    path("trabajadores/<int:pk>/documentos/escanear/", views.documento_escanear,
         name="documento_escanear"),
    path("trabajadores/<int:pk>/remuneracion/", views.remuneracion_guardar,
         name="remuneracion_guardar"),
    path("trabajadores/<int:pk>/documentos/<slug:clave>/", views.documento_generar,
         name="documento_generar"),
    path("trabajadores/<int:pk>/pagos/agregar/", views.pago_agregar, name="pago_agregar"),
    path("trabajadores/<int:pk>/hijos/agregar/", views.hijo_agregar, name="hijo_agregar"),
    path("hijos/<int:pk>/borrar/", views.hijo_borrar, name="hijo_borrar"),
    path("pagos/<int:pk>/editar/", views.pago_editar, name="pago_editar"),
    path("pagos/<int:pk>/borrar/", views.pago_borrar, name="pago_borrar"),
    path("documentos/<int:pk>/descargar/", views.documento_descargar, name="documento_descargar"),
    path("documentos/<int:pk>/marcar/", views.documento_marcar, name="documento_marcar"),
    path("documentos/<int:pk>/desmarcar/", views.documento_desmarcar,
         name="documento_desmarcar"),
    path("documentos/<int:pk>/borrar/", views.documento_borrar, name="documento_borrar"),
    path("documentos/<int:pk>/restaurar/", views.documento_restaurar, name="documento_restaurar"),
    path("auditoria/", views.auditoria_list, name="auditoria_list"),
]
