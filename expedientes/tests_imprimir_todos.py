"""Dos pedidos de quien usa el sistema, llegados el mismo día.

**«En el número de cédula del jefe falta la V-».** La del trabajador sale del
expediente y ya viene con la letra; la del representante legal está escrita en
la plantilla y venía pelada. En el bloque de firmas quedaban las dos una al
lado de la otra: «V-26045681» y «17158865».

Tiene una trampa: en el mismo párrafo del cuerpo está el RIF de la empresa,
«V-17158865-7», que ya tiene su letra y su dígito verificador. Un reemplazo a
lo bruto lo dejaría en «V-V-17158865-7», y eso sí que invalida un contrato.

**«¿Podrás poner un botón donde se pueda imprimir todos los documentos
corporativos?».** Eran siete botones de Imprimir, uno por uno, y siete
diálogos de impresión por cada persona que entra. Con una tanda de ingresos
son cientos de clics.

Sale un PDF único y no un ZIP: un ZIP hay que descargar, descomprimir y abrir
siete archivos, o sea que no se puede imprimir de una.
"""

import unittest
import zipfile
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Cargo, Departamento, Sede, TipoDocumentoIdentidad, Zona
from expedientes import documentos as generador
from expedientes import pdf as conversor
from expedientes.models import (AsignacionPago, ConceptoPago, DatosContratacion,
                                Moneda, RegistroAuditoria, Trabajador)
from expedientes.tests_documentos import falta_plantillas, texto_generado

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"

CEDULA_JEFE = "17158865"
CON_CEDULA_DEL_JEFE = ("contrato", "corporativo", "beneficios", "confidencialidad")


class _ConExpediente(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        sede = Sede.objects.create(nombre="TIENDA GUATIRE", zona=zona,
                                   ciudad="GUATIRE")
        unidad = Departamento.objects.create(nombre="ADMINISTRACION")
        puesto = Cargo.objects.create(nombre="LIDER EXPERIENCIA INTERNA",
                                      departamento=unidad)
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="26045681",
            tipo_documento=TipoDocumentoIdentidad.objects.get(codigo="V"),
            nombres="HENMARY ALEJANDRA", apellidos="GOMEZ RAMOS", sede=sede,
            departamento=unidad, puesto=puesto,
            fecha_nacimiento=date(1995, 4, 12), fecha_ingreso=date(2026, 8, 24))
        DatosContratacion.objects.create(
            trabajador=cls.trabajador, estado_civil="SOLTERO",
            direccion="URB LOS NARANJOS", ciudad_nacimiento="GUATIRE",
            horario="8:00AM a 5:00PM", motivo_contratacion="Temporada",
            fecha_culminacion=date(2026, 11, 22))
        AsignacionPago.objects.create(
            trabajador=cls.trabajador, concepto=ConceptoPago.objects.first(),
            monto=Decimal("130.00"), moneda=Moneda.objects.get(codigo="VES"))

        cls.admin = Usuario.objects.create_user(
            username="jefa", password=CLAVE, rol=Usuario.Rol.ADMIN)
        cls.mirona = Usuario.objects.create_user(
            username="mirona", password=CLAVE, rol=Usuario.Rol.SOLO_LECTURA,
            acceso_nacional=True)

    def cuerpo(self, clave):
        datos, nombre, _ = generador.generar(clave, self.trabajador)
        return texto_generado(datos, nombre)


@falta_plantillas
class LaCedulaDelJefeLlevaSuLetra(_ConExpediente):

    def test_sale_con_la_v_adelante(self):
        for clave in CON_CEDULA_DEL_JEFE:
            with self.subTest(documento=clave):
                self.assertIn("V-17", self.cuerpo(clave).replace(".", ""))

    def test_no_queda_ninguna_pelada(self):
        """El caso del reporte: «17158865» suelto, sin letra."""
        import re

        for clave in CON_CEDULA_DEL_JEFE:
            texto = self.cuerpo(clave).replace(".", "")
            with self.subTest(documento=clave):
                self.assertIsNone(
                    re.search(r"(?<!V-)(?<!\d)" + CEDULA_JEFE, texto),
                    "quedó una cédula del empleador sin la V-")

    def test_el_rif_de_la_empresa_no_se_duplico(self):
        """La trampa: el RIF ya traía la letra y está en el mismo párrafo."""
        for clave in CON_CEDULA_DEL_JEFE:
            texto = self.cuerpo(clave)
            with self.subTest(documento=clave):
                self.assertNotIn("V-V-", texto)
                self.assertIn("V-17158865-7", texto.replace(".", ""))

    def test_las_dos_cedulas_de_las_firmas_se_leen_igual(self):
        """Era lo que se veía: una con letra y la otra sin, lado a lado."""
        for clave in ("contrato", "corporativo"):
            texto = self.cuerpo(clave)
            with self.subTest(documento=clave):
                self.assertIn("V-17158865", texto)
                self.assertIn("V-26045681", texto)

    def test_ya_no_dice_nro_pegado_al_numero(self):
        """Venía «Nro.17158865», sin el espacio; con la letra se leía peor."""
        for clave in ("contrato", "corporativo", "beneficios"):
            with self.subTest(documento=clave):
                self.assertNotIn("Nro.V-", self.cuerpo(clave))

    def test_y_el_nro_sigue_estando(self):
        """Testigo, y no de más: al agregar el espacio, la primera versión
        borraba el «Nro.» entero. La prueba de arriba pasaba igual, porque
        «Nro.V-» tampoco aparecía. Un texto legal al que le falta una palabra
        es peor que uno mal espaciado."""
        for clave in ("contrato", "corporativo", "beneficios"):
            with self.subTest(documento=clave):
                self.assertIn("identidad Nro. V-17158865", self.cuerpo(clave))

    def test_la_del_trabajador_sigue_saliendo_del_expediente(self):
        """Testigo: no se tocó la que ya andaba."""
        self.trabajador.documento_identidad = "30111222"
        self.trabajador.save()
        self.assertIn("V-30111222", self.cuerpo("contrato"))

    def test_correr_de_nuevo_la_preparacion_no_agrega_otra_v(self):
        """Idempotente: `preparar_plantillas` se corre en cada arranque."""
        from expedientes.management.commands.preparar_plantillas import Command

        ruta = generador.ruta_plantilla("contrato")
        salida = BytesIO()
        partes, root = Command._abrir_docx(ruta)
        # Segunda pasada sobre una plantilla YA preparada: no debe cambiar nada.
        self.assertEqual(Command._cedula_del_empleador(root), 0)
        del partes, salida


@falta_plantillas
@unittest.skipUnless(conversor.hay_conversor(),
                     "Esta máquina no tiene Word: no se pueden juntar en PDF.")
class ElBotonDeImprimirTodos(_ConExpediente):
    """Un solo PDF con todo, en el orden en que se firman."""

    def url(self):
        return reverse("expedientes:documentos_todos", args=[self.trabajador.pk])

    def setUp(self):
        self.client.force_login(self.admin)

    def pdf(self):
        import pymupdf

        resp = self.client.get(self.url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        return resp, pymupdf.open(stream=resp.content, filetype="pdf")

    def test_devuelve_un_solo_pdf(self):
        resp, documento = self.pdf()
        with documento:
            self.assertTrue(resp.content.startswith(b"%PDF-"))
            self.assertGreater(len(documento), 1)

    def test_se_abre_en_el_navegador_para_imprimir(self):
        """Y no como descarga: el visor ya trae el botón de imprimir."""
        resp = self.client.get(self.url())
        self.assertIn("inline", resp["Content-Disposition"])

    def test_estan_todos_los_documentos(self):
        import re

        _, documento = self.pdf()
        with documento:
            crudo = "\n".join(p.get_text() for p in documento)
        # El texto del PDF viene cortado por renglones: el título sale como
        # «CONTRATO INDIVIDUAL DE / TRABAJO A TIEMPO / DETERMINADO».
        texto = re.sub(r"\s+", " ", crudo)
        # Una frase propia de cada documento, para no confiar en el título.
        for frase in ("CONTRATO INDIVIDUAL DE TRABAJO",
                      "confidencialidad",
                      "beneficios",
                      "GERENTE DE TIENDA",
                      "LISTA DE VERIFICACIÓN"):
            with self.subTest(frase=frase):
                self.assertIn(frase.lower(), texto.lower())

    def test_tiene_al_menos_tantas_paginas_como_la_suma(self):
        """Testigo de que junta y no reemplaza: si pegara uno solo, no llega."""
        _, juntos = self.pdf()
        with juntos:
            total_juntos = len(juntos)
        self.assertGreaterEqual(total_juntos, 8)

    def test_el_nombre_del_archivo_lleva_a_la_persona(self):
        resp = self.client.get(self.url())
        self.assertIn("GOMEZ", resp["Content-Disposition"])

    def test_queda_asentado_en_la_auditoria(self):
        self.client.get(self.url())
        ultimo = RegistroAuditoria.objects.latest("id")
        self.assertIn("imprimir los", ultimo.descripcion)
        self.assertIn("GOMEZ", ultimo.descripcion)

    def test_solo_lectura_no_lo_puede_pedir(self):
        """Mismo permiso que los documentos de a uno: traen sueldos."""
        self.client.force_login(self.mirona)
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_el_boton_esta_en_la_ficha(self):
        cuerpo = self.client.get(
            reverse("expedientes:trabajador_detail",
                    args=[self.trabajador.pk])).content.decode()
        self.assertIn(self.url(), cuerpo)
        self.assertIn("Imprimir todos", cuerpo)


@falta_plantillas
class UnoQueFalleNoDejaSinImprimirALosOtros(_ConExpediente):
    """La persona está esperando para armar la carpeta.

    Si una plantilla falta o Word se traba con una, el PDF sale con las demás y
    se avisa cuáles quedaron afuera. Negarse a entregar nada sería peor: no hay
    nada que la analista pueda hacer al respecto en ese momento.
    """

    def test_sin_word_se_avisa_y_no_se_rompe(self):
        from unittest.mock import patch

        self.client.force_login(self.admin)
        with patch("expedientes.pdf.hay_conversor", return_value=False):
            resp = self.client.get(
                reverse("expedientes:documentos_todos",
                        args=[self.trabajador.pk]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "hace falta Word")

    def test_sin_word_el_boton_no_se_muestra(self):
        """Un botón que no puede funcionar es un botón que hay que probar."""
        from unittest.mock import patch

        self.client.force_login(self.admin)
        with patch("expedientes.pdf.hay_conversor", return_value=False):
            cuerpo = self.client.get(
                reverse("expedientes:trabajador_detail",
                        args=[self.trabajador.pk])).content.decode()
        self.assertNotIn("Imprimir todos", cuerpo)
