"""Filtro del listado por fecha de creación y por fecha de ingreso.

Cuatro campos opcionales: creación desde/hasta e ingreso desde/hasta. El de
creación mira `creado_en` (fecha-hora) por día, para que «hasta» incluya el
día entero.
"""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Sede, Zona
from expedientes.models import Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class _Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

        cls.viejo = Trabajador.objects.create(
            documento_identidad="V-1", nombres="Ana", apellidos="Antigua",
            sede=cls.sede, fecha_ingreso=datetime.date(2026, 1, 10))
        cls.nuevo = Trabajador.objects.create(
            documento_identidad="V-2", nombres="Beto", apellidos="Recien",
            sede=cls.sede, fecha_ingreso=datetime.date(2026, 8, 20))
        # `creado_en` se llena solo: se pisa a mano para fijar el escenario.
        Trabajador.objects.filter(pk=cls.viejo.pk).update(
            creado_en=datetime.datetime(2026, 2, 1, 10, 0,
                                        tzinfo=datetime.timezone.utc))
        Trabajador.objects.filter(pk=cls.nuevo.pk).update(
            creado_en=datetime.datetime(2026, 8, 15, 10, 0,
                                        tzinfo=datetime.timezone.utc))

    def listado(self, **params):
        self.client.force_login(self.admin)
        return self.client.get(
            reverse("expedientes:trabajador_list"), params).content.decode()


class PorIngreso(_Base):

    def test_desde(self):
        cuerpo = self.listado(ingreso_desde="2026-08-01")
        self.assertIn("Recien", cuerpo)
        self.assertNotIn("Antigua", cuerpo)

    def test_hasta(self):
        cuerpo = self.listado(ingreso_hasta="2026-02-01")
        self.assertIn("Antigua", cuerpo)
        self.assertNotIn("Recien", cuerpo)

    def test_rango_que_cubre_a_los_dos(self):
        cuerpo = self.listado(ingreso_desde="2026-01-01",
                              ingreso_hasta="2026-12-31")
        self.assertIn("Antigua", cuerpo)
        self.assertIn("Recien", cuerpo)


class PorCreacion(_Base):

    def test_desde(self):
        cuerpo = self.listado(creado_desde="2026-08-01")
        self.assertIn("Recien", cuerpo)
        self.assertNotIn("Antigua", cuerpo)

    def test_hasta_incluye_todo_el_dia(self):
        cuerpo = self.listado(creado_hasta="2026-02-01")
        self.assertIn("Antigua", cuerpo)
        self.assertNotIn("Recien", cuerpo)


class LaPantalla(_Base):

    def test_los_cuatro_campos_estan(self):
        cuerpo = self.listado()
        for campo in ("creado_desde", "creado_hasta",
                      "ingreso_desde", "ingreso_hasta"):
            self.assertIn(f'name="{campo}"', cuerpo)

    def test_convive_con_la_busqueda(self):
        cuerpo = self.listado(q="Ana", ingreso_desde="2026-08-01")
        self.assertNotIn("Antigua", cuerpo)  # la fecha la deja afuera
        self.assertNotIn("Recien", cuerpo)   # y Beto no es «Ana»


class LimpiarFiltros(_Base):

    def test_sin_filtros_no_se_ofrece(self):
        self.assertNotIn("Limpiar filtros", self.listado())

    def test_la_paginacion_sola_no_cuenta_como_filtro(self):
        self.assertNotIn("Limpiar filtros", self.listado(page="2"))

    def test_con_filtros_lleva_al_listado_pelado(self):
        cuerpo = self.listado(ingreso_desde="2026-08-01")
        self.assertIn("Limpiar filtros", cuerpo)
        self.assertIn(f'href="{reverse("expedientes:trabajador_list")}"', cuerpo)
