"""El nombre del sistema sale de un solo lugar y llega a todas las pantallas.

Cuando el nombre está escrito a mano en cada plantilla, un cambio deja mitad de
las pestañas con el nombre viejo y nadie se entera hasta que un usuario lo ve.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Sede, Zona

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class NombreDelSistema(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.zona = Zona.objects.create(nombre="MIRANDA")
        Sede.objects.create(nombre="CCCT", zona=cls.zona)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def test_esta_definido_en_settings(self):
        self.assertEqual(settings.NOMBRE_SISTEMA, "GDE")
        self.assertEqual(settings.NOMBRE_SISTEMA_LARGO,
                         "Gestión Digital de Expedientes")

    def test_aparece_en_la_pestana_de_cada_pantalla(self):
        self.client.force_login(self.admin)
        pantallas = [
            reverse("expedientes:panel"),
            reverse("expedientes:trabajador_list"),
            reverse("expedientes:trabajador_create"),
            reverse("expedientes:nomina"),
            reverse("expedientes:auditoria_list"),
            reverse("configuracion:index"),
            reverse("cuentas:invitaciones"),
            reverse("configuracion:preferencias"),
            reverse("configuracion:lista", args=["tiendas"]),
            reverse("configuracion:crear", args=["tiendas"]),
        ]
        for url in pantallas:
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200)
                titulo = r.content.decode().split("<title>")[1].split("</title>")[0]
                self.assertIn("GDE", titulo)

    def test_el_login_lo_muestra_completo(self):
        cuerpo = self.client.get(reverse("cuentas:login")).content.decode()
        self.assertIn("GDE", cuerpo)
        self.assertIn("Gestión Digital de Expedientes", cuerpo)

    def test_el_pie_lo_muestra(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("expedientes:panel")).content.decode()
        self.assertIn("Gestión Digital de Expedientes", cuerpo)

    def test_el_admin_de_django_tambien(self):
        self.admin.is_staff = self.admin.is_superuser = True
        self.admin.save()
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("admin:index")).content.decode()
        self.assertIn("GDE", cuerpo)

    def test_no_quedo_ninguna_pantalla_con_el_nombre_viejo(self):
        self.client.force_login(self.admin)
        for url in (reverse("expedientes:panel"), reverse("cuentas:login"),
                    reverse("configuracion:index")):
            with self.subTest(url=url):
                cuerpo = self.client.get(url).content.decode()
                self.assertNotIn("Expedientes RRHH", cuerpo)
                self.assertNotIn("Sistema de Expedientes", cuerpo)

    def test_cambiarlo_en_settings_alcanza(self):
        """La prueba de que no está escrito a mano en las plantillas."""
        with self.settings(NOMBRE_SISTEMA="XYZ"):
            self.client.force_login(self.admin)
            cuerpo = self.client.get(reverse("expedientes:panel")).content.decode()
            titulo = cuerpo.split("<title>")[1].split("</title>")[0]
            self.assertIn("XYZ", titulo)
            self.assertNotIn("GDE", titulo)
