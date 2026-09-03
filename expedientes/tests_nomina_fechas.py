"""Nómina: filtro por fechas y columnas Estatus/Observación en el Excel.

El filtro de fechas es el mismo del listado de expedientes (creación e
ingreso, desde/hasta) y como el botón de exportar se sincroniza con el
formulario, lo que se ve filtrado es lo que baja el Excel.

En el archivo exportado, la columna Estatus dice Activo o Baja, y Observación
trae el motivo de la baja solo cuando el trabajador no está activo.
"""

import datetime
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from cuentas.models import Sede, Zona
from expedientes.models import Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class _Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        cls.ana = Trabajador.objects.create(
            documento_identidad="V-1", nombres="Ana", apellidos="Alvarez",
            sede=cls.sede, fecha_ingreso=datetime.date(2026, 1, 10))
        cls.beto = Trabajador.objects.create(
            documento_identidad="V-2", nombres="Beto", apellidos="Blanco",
            sede=cls.sede, fecha_ingreso=datetime.date(2026, 8, 20),
            estado="BAJA", observaciones_baja="Renuncia voluntaria")
        Trabajador.objects.filter(pk=cls.ana.pk).update(
            creado_en=datetime.datetime(2026, 2, 1, 10, 0,
                                        tzinfo=datetime.timezone.utc))
        Trabajador.objects.filter(pk=cls.beto.pk).update(
            creado_en=datetime.datetime(2026, 8, 15, 10, 0,
                                        tzinfo=datetime.timezone.utc))
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def exportar(self, **filtros):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("expedientes:nomina_export"), filtros)
        self.assertEqual(r.status_code, 200)
        hoja = load_workbook(BytesIO(r.content)).active
        filas = list(hoja.values)
        return filas[0], filas[1:]


class ElFiltroDeFechas(_Base):

    def nomina(self, **params):
        self.client.force_login(self.admin)
        return self.client.get(reverse("expedientes:nomina"), params).content.decode()

    def test_los_campos_estan_en_la_pantalla(self):
        cuerpo = self.nomina()
        for campo in ("creado_desde", "creado_hasta",
                      "ingreso_desde", "ingreso_hasta"):
            self.assertIn(f'name="{campo}"', cuerpo)

    def test_por_ingreso(self):
        cuerpo = self.nomina(ingreso_desde="2026-08-01")
        self.assertIn("Blanco", cuerpo)
        self.assertNotIn("Alvarez", cuerpo)

    def test_por_creacion(self):
        cuerpo = self.nomina(creado_hasta="2026-03-01")
        self.assertIn("Alvarez", cuerpo)
        self.assertNotIn("Blanco", cuerpo)

    def test_el_export_tambien_filtra(self):
        _, filas = self.exportar(ingreso_desde="2026-08-01")
        self.assertEqual([f[0] for f in filas], ["V-2"])


class LasColumnasDelExcel(_Base):

    def test_estatus_dice_activo_o_baja(self):
        encabezado, filas = self.exportar()
        col = encabezado.index("Estatus")
        valores = {f[0]: f[col] for f in filas}
        self.assertEqual(valores, {"V-1": "Activo", "V-2": "Baja"})

    def test_observacion_solo_si_no_esta_activo(self):
        encabezado, filas = self.exportar()
        col = encabezado.index("Observación")
        valores = {f[0]: f[col] for f in filas}
        self.assertEqual(valores["V-2"], "Renuncia voluntaria")
        self.assertIn(valores["V-1"], ("", None))

    def test_va_despues_de_la_fecha_de_ingreso(self):
        encabezado, _ = self.exportar()
        self.assertLess(list(encabezado).index("Fecha de ingreso"),
                        list(encabezado).index("Estatus"))
        self.assertLess(list(encabezado).index("Estatus"),
                        list(encabezado).index("Observación"))
