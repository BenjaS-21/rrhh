"""El Excel trae exactamente lo que está filtrado en pantalla.

Lo que se ve es lo que se baja. El riesgo real no es el filtro del servidor
—que ya andaba— sino el botón: vive fuera de lo que HTMX reemplaza, así que su
enlace se quedaba con los filtros del momento en que se abrió la pantalla y
bajaba la nómina entera sin avisar.
"""

import re
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from cuentas.models import Departamento, Sede, Zona
from expedientes.models import Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class ExportaLoFiltrado(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.miranda = Zona.objects.create(nombre="MIRANDA")
        cls.zulia = Zona.objects.create(nombre="ZULIA")
        cls.ccct = Sede.objects.create(nombre="CCCT", zona=cls.miranda)
        cls.trinidad = Sede.objects.create(nombre="TRINIDAD", zona=cls.miranda)
        cls.maracaibo = Sede.objects.create(nombre="MARACAIBO", zona=cls.zulia)

        cls.ventas = Departamento.objects.create(nombre="VENTAS")
        cls.deposito = Departamento.objects.create(nombre="DEPOSITO")

        cls.ana = cls._trabajador("V-1", "Ana", "Alvarez", cls.ccct, cls.ventas)
        cls.beto = cls._trabajador("V-2", "Beto", "Blanco", cls.trinidad, cls.deposito)
        cls.caro = cls._trabajador("V-3", "Caro", "Castro", cls.maracaibo, cls.ventas)
        cls.dario = cls._trabajador("V-4", "Dario", "Diaz", cls.maracaibo,
                                    cls.deposito, estado="BAJA")

        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    @classmethod
    def _trabajador(cls, ci, nombres, apellidos, sede, depto, estado="ACTIVO"):
        return Trabajador.objects.create(
            documento_identidad=ci, nombres=nombres, apellidos=apellidos,
            sede=sede, departamento=depto, estado=estado)

    def exportar(self, **filtros):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("expedientes:nomina_export"), filtros)
        self.assertEqual(r.status_code, 200)
        hoja = load_workbook(BytesIO(r.content)).active
        return [f[0] for f in list(hoja.values)[1:]]

    # --- Cada filtro ----------------------------------------------------------
    def test_sin_filtros_trae_a_todos(self):
        self.assertEqual(set(self.exportar()), {"V-1", "V-2", "V-3", "V-4"})

    def test_filtrando_por_una_tienda(self):
        self.assertEqual(self.exportar(sedes=self.maracaibo.pk), ["V-3", "V-4"])

    def test_filtrando_por_varias_tiendas(self):
        traidos = self.exportar(sedes=[self.ccct.pk, self.maracaibo.pk])
        self.assertEqual(set(traidos), {"V-1", "V-3", "V-4"})

    def test_filtrando_por_departamento(self):
        self.assertEqual(set(self.exportar(departamento=self.ventas.pk)),
                         {"V-1", "V-3"})

    def test_filtrando_por_estado(self):
        self.assertEqual(self.exportar(estado="BAJA"), ["V-4"])

    def test_buscando_por_nombre(self):
        self.assertEqual(self.exportar(q="Beto"), ["V-2"])

    def test_buscando_por_documento(self):
        self.assertEqual(self.exportar(q="V-3"), ["V-3"])

    def test_varios_filtros_a_la_vez(self):
        traidos = self.exportar(sedes=self.maracaibo.pk,
                                departamento=self.deposito.pk, estado="BAJA")
        self.assertEqual(traidos, ["V-4"])

    def test_un_valor_invalido_no_borra_los_demas_filtros(self):
        """Antes, un dato raro en la URL devolvía la nómina completa.

        Pasa con una tienda que se borró, un link viejo, o cualquiera que toque
        la URL a mano: el filtro que sí vale tiene que seguir valiendo.
        """
        traidos = self.exportar(sedes=self.maracaibo.pk, estado="INVENTADO")
        self.assertEqual(set(traidos), {"V-3", "V-4"})

    def test_un_filtro_que_no_da_nada_trae_un_archivo_vacio(self):
        """Con encabezados pero sin filas: no puede traer la nómina entera."""
        self.assertEqual(self.exportar(q="NO EXISTE NADIE"), [])

    # --- La paginación no recorta el archivo ----------------------------------
    def test_exporta_todas_las_paginas_no_solo_la_que_se_ve(self):
        for i in range(30):
            self._trabajador(f"V-9{i:02}", "Extra", f"Numero{i:02}", self.ccct,
                             self.ventas)
        traidos = self.exportar(sedes=self.ccct.pk, page=2)
        self.assertEqual(len(traidos), 31)   # los 30 nuevos + Ana

    # --- El botón de la pantalla ---------------------------------------------
    def test_el_boton_arranca_con_los_filtros_de_la_url(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("expedientes:nomina"),
                                 {"sedes": self.ccct.pk}).content.decode()
        enlace = re.search(r'id="exportar-nomina"[^>]*href="([^"]+)"', cuerpo)
        self.assertIsNotNone(enlace, "no está el botón de exportar")
        self.assertIn(f"sedes={self.ccct.pk}", enlace.group(1).replace("&amp;", "&"))

    def test_el_boton_se_rearma_solo_al_filtrar_sin_recargar(self):
        """La parte que fallaba: HTMX cambia la tabla y el botón queda viejo."""
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("expedientes:nomina")).content.decode()
        self.assertIn('id="filtros-nomina"', cuerpo)
        self.assertIn('id="exportar-nomina"', cuerpo)
        self.assertIn("htmx:afterSwap", cuerpo)

    # --- El conteo del encabezado --------------------------------------------
    def test_el_encabezado_dice_cuantos_se_van_a_exportar(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("expedientes:nomina"),
                                 {"sedes": self.maracaibo.pk}).content.decode()
        resumen = re.search(r'id="resumen-nomina"[^>]*>(.*?)</div>', cuerpo, re.S)
        self.assertIn("2 trabajadores", resumen.group(1))
        self.assertIn("MARACAIBO", resumen.group(1))

    def test_al_filtrar_sin_recargar_el_conteo_viaja_con_la_tabla(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("expedientes:nomina"),
                            {"sedes": self.ccct.pk}, headers={"hx-request": "true"})
        cuerpo = r.content.decode()
        self.assertIn('hx-swap-oob="true"', cuerpo)
        self.assertIn('id="resumen-nomina"', cuerpo)
        self.assertIn("1 trabajador", cuerpo)

    def test_al_cargar_la_pantalla_entera_el_conteo_no_sale_duplicado(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("expedientes:nomina")).content.decode()
        self.assertEqual(cuerpo.count('id="resumen-nomina"'), 1)
        self.assertNotIn("hx-swap-oob", cuerpo)
