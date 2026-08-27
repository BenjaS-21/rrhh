"""El motivo de contratación se elige de un desplegable.

Las opciones salen del catálogo (Configuración → Motivos de contratación),
sembrado con las temporadas del Excel de ingresos. El campo sigue guardando
texto: los motivos viejos cargados a mano se ofrecen igual, para que editar
la ficha no los borre.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Sede, Zona
from expedientes.models import DatosContratacion, MotivoContratacion, Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class _ConExpediente(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="V-1", nombres="Ana", apellidos="Alvarez",
            sede=cls.sede)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def editar(self):
        self.client.force_login(self.admin)
        return self.client.get(
            reverse("expedientes:trabajador_update", args=[self.trabajador.pk])
        ).content.decode()


class ElDesplegable(_ConExpediente):

    def test_el_catalogo_trae_las_temporadas_del_excel(self):
        self.assertEqual(MotivoContratacion.objects.filter(activo=True).count(), 12)
        self.assertTrue(MotivoContratacion.objects.filter(
            nombre="Temporada Decembrina").exists())

    def test_es_un_select_con_las_temporadas(self):
        cuerpo = self.editar()
        self.assertIn('<select name="contrato-motivo_contratacion"', cuerpo)
        self.assertIn("Temporada Decembrina", cuerpo)
        self.assertIn("Temporada de Carnaval", cuerpo)

    def test_el_motivo_viejo_se_ofrece_aunque_no_sea_del_catalogo(self):
        DatosContratacion.objects.create(
            trabajador=self.trabajador,
            motivo_contratacion="Temporada que ya no existe")
        self.assertIn("Temporada que ya no existe", self.editar())

    def test_se_guarda_lo_elegido(self):
        DatosContratacion.objects.create(trabajador=self.trabajador)
        self.client.force_login(self.admin)
        self.client.post(
            reverse("expedientes:trabajador_update", args=[self.trabajador.pk]),
            {"documento_identidad": "V-1", "nombres": "Ana",
             "apellidos": "Alvarez", "sede": self.sede.pk, "estado": "ACTIVO",
             "contrato-motivo_contratacion": "Temporada Decembrina"})
        datos = DatosContratacion.objects.get(trabajador=self.trabajador)
        self.assertEqual(datos.motivo_contratacion, "Temporada Decembrina")

    def test_el_catalogo_se_administra_desde_configuracion(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("configuracion:index")).content.decode()
        self.assertIn("Motivos de contratación", cuerpo)
        self.assertIn(
            reverse("configuracion:lista", args=["motivos-contratacion"]), cuerpo)
