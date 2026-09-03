"""Configuración → Validar duplicados.

Agrupa los expedientes que parecen la misma persona dos veces: la cédula es
única en la base, así que el duplicado siempre entra disfrazado (la cédula
escrita distinto, el mismo RIF en dos fichas, o el mismo nombre completo).
No borra ni fusiona: muestra los grupos y una persona decide.
"""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Sede, Zona
from expedientes.models import Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"
NACIMIENTO = datetime.date(1990, 5, 15)


class _Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()
        cls.rrhh = Usuario.objects.create_user(username="rrhh", password=CLAVE)
        cls.rrhh.rol = Usuario.Rol.RRHH_INTERIOR
        cls.rrhh.save()

    def _trabajador(self, cedula, nombres, apellidos, rif="", nacimiento=None):
        return Trabajador.objects.create(
            documento_identidad=cedula, nombres=nombres, apellidos=apellidos,
            sede=self.sede, rif=rif, fecha_nacimiento=nacimiento)

    def cuerpo(self):
        self.client.force_login(self.admin)
        return self.client.get(reverse("configuracion:duplicados")).content.decode()


class LosGrupos(_Base):

    def test_misma_cedula_escrita_distinto(self):
        self._trabajador("V-123456", "Ana", "Perez")
        self._trabajador("123456", "Ana", "Perez")
        cuerpo = self.cuerpo()
        self.assertIn("Misma cédula escrita de dos formas", cuerpo)
        self.assertIn("V-123456", cuerpo)

    def test_mismo_rif(self):
        self._trabajador("111", "Ana", "Perez", rif="V-11111111-1")
        self._trabajador("222", "Ana", "Perez", rif="V111111111")
        self.assertIn("Mismo RIF", self.cuerpo())

    def test_mismo_nombre_y_fecha(self):
        self._trabajador("111", "Ana", "Perez", nacimiento=NACIMIENTO)
        self._trabajador("222", "ana", "perez", nacimiento=NACIMIENTO)
        self.assertIn("Mismo nombre y misma fecha de nacimiento", self.cuerpo())

    def test_mismo_nombre_fecha_distinta_es_posible_homonimo(self):
        self._trabajador("111", "Ana", "Perez", nacimiento=NACIMIENTO)
        self._trabajador("222", "Ana", "Perez",
                         nacimiento=datetime.date(1995, 1, 1))
        self.assertIn("posible homónimo", self.cuerpo())

    def test_sin_duplicados_avisa_limpio(self):
        self._trabajador("111", "Ana", "Perez", nacimiento=NACIMIENTO)
        self._trabajador("222", "Beto", "Gomez")
        self.assertIn("No se encontraron duplicados", self.cuerpo())

    def test_los_miembros_enlazan_a_su_expediente(self):
        t1 = self._trabajador("V-123456", "Ana", "Perez")
        self._trabajador("123456", "Ana", "Perez")
        self.assertIn(
            reverse("expedientes:trabajador_detail", args=[t1.pk]), self.cuerpo())


class LosPermisos(_Base):

    def test_rrhh_no_entra(self):
        self.client.force_login(self.rrhh)
        r = self.client.get(reverse("configuracion:duplicados"))
        self.assertEqual(r.status_code, 302)

    def test_se_ofrece_en_el_indice(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("configuracion:index")).content.decode()
        self.assertIn("Validar duplicados", cuerpo)
        self.assertIn(reverse("configuracion:duplicados"), cuerpo)
