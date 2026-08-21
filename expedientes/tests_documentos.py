"""Tests de la generación automática de los documentos corporativos.

Verifican de punta a punta: que los datos del expediente entren en las
plantillas Word reales, que no quede ningún rastro de la persona de ejemplo
que traían, y que solo pueda generarlos quien tiene permiso.
"""

import re
import unittest
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Cargo, Departamento, Sede, Zona
from expedientes import documentos as generador
from expedientes.models import (
    AsignacionPago, ConceptoPago, DatosContratacion, Moneda, Trabajador,
)

Usuario = get_user_model()
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Datos de la persona de ejemplo que venían en las plantillas originales.
RASTROS = ["PENA TEIJIDO", "9239429", "DIRECTOR DE POST VENTA", "MANAURE",
           "ALCALA RIVAS", "32687769", "MERGEFIELD", "{{", "«"]

PLANTILLAS_LISTAS = all(
    (Path(settings.PLANTILLAS_DIR) / m["archivo"]).exists()
    for m in generador.PLANTILLAS.values()
)
falta_plantillas = unittest.skipUnless(
    PLANTILLAS_LISTAS, "Faltan las plantillas: python manage.py preparar_plantillas"
)


def texto_docx(datos: bytes) -> str:
    z = zipfile.ZipFile(BytesIO(datos))
    partes = [n for n in z.namelist()
              if n.startswith("word/") and n.endswith(".xml")]
    salida = []
    for parte in partes:
        root = ET.fromstring(z.read(parte))
        for p in root.iter(W + "p"):
            salida.append("".join(t.text or "" for t in p.iter(W + "t")))
    return "\n".join(salida)


class MontoEnLetras(TestCase):
    """La cláusula de salario del contrato se escribe en letras."""

    def test_ejemplos(self):
        casos = [
            (130, "CIENTO TREINTA BOLÍVARES CON 00/100 CÉNTIMOS (Bs.130,00)"),
            (1, "UN BOLÍVAR CON 00/100 CÉNTIMOS (Bs.1,00)"),
            (100, "CIEN BOLÍVARES CON 00/100 CÉNTIMOS (Bs.100,00)"),
            (1000, "MIL BOLÍVARES CON 00/100 CÉNTIMOS (Bs.1.000,00)"),
        ]
        for numero, esperado in casos:
            with self.subTest(numero=numero):
                self.assertEqual(generador.monto_en_letras(numero), esperado)

    def test_decimales(self):
        self.assertEqual(
            generador.monto_en_letras(Decimal("180.50")),
            "CIENTO OCHENTA BOLÍVARES CON 50/100 CÉNTIMOS (Bs.180,50)",
        )

    def test_veintiuno_se_apocopa(self):
        self.assertIn("VEINTIÚN BOLÍVARES", generador.monto_en_letras(21))

    def test_otras_monedas(self):
        self.assertIn("DÓLARES", generador.monto_en_letras(400, "USD"))
        self.assertIn("EUROS", generador.monto_en_letras(50, "EUR"))

    def test_numeros_sueltos(self):
        self.assertEqual(generador.numero_a_letras(0), "CERO")
        self.assertEqual(generador.numero_a_letras(16), "DIECISÉIS")
        self.assertEqual(generador.numero_a_letras(999), "NOVECIENTOS NOVENTA Y NUEVE")
        self.assertEqual(generador.numero_a_letras(1_000_000), "UN MILLÓN")


class BaseDocumentos(TestCase):
    """Con la restricción por zona prendida: acá se prueban los permisos por zona."""

    @classmethod
    def setUpTestData(cls):
        from configuracion.models import Preferencias

        Preferencias.objects.update_or_create(
            pk=1, defaults={"restringir_por_zona": True})
        cls.norte = Zona.objects.create(nombre="Norte")
        cls.sur = Zona.objects.create(nombre="Sur")
        cls.sede = Sede.objects.create(
            nombre="SAMBIL CARACAS", zona=cls.norte,
            direccion="CC SAMBIL, NIVEL 2, LOCAL 210, CARACAS",
        )
        cls.unidad = Departamento.objects.create(nombre="TIENDA DAMASCO SAMBIL")
        cls.cargo = Cargo.objects.create(nombre="VENDEDOR DE PISO",
                                         departamento=cls.unidad)
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="12345678", nombres="JUAN CARLOS",
            apellidos="PEREZ GOMEZ", sede=cls.sede, puesto=cls.cargo,
            fecha_nacimiento=date(1990, 3, 5), fecha_ingreso=date(2026, 8, 1),
        )
        DatosContratacion.objects.create(
            trabajador=cls.trabajador,
            estado_civil=DatosContratacion.EstadoCivil.CASADO,
            direccion="AV SIEMPRE VIVA 742, URB EL PARAISO, CARACAS",
            ciudad_nacimiento="MARACAY, ARAGUA",
            horario="8:00AM a 5:00PM de lunes a sábado",
            motivo_contratacion="Temporada Navidad",
            fecha_culminacion=date(2026, 10, 31),
            ciudad_firma="CARACAS",
        )

        bs = Moneda.objects.get(codigo="VES")
        sueldo = ConceptoPago.objects.get(nombre="Sueldo base")
        AsignacionPago.objects.create(
            trabajador=cls.trabajador, concepto=sueldo,
            monto=Decimal("180.00"), moneda=bs,
        )

        cls.admin = cls._usuario("admin_doc", Usuario.Rol.ADMIN, None)
        cls.rrhh_norte = cls._usuario("rrhh_n", Usuario.Rol.RRHH_INTERIOR, cls.norte)
        cls.rrhh_sur = cls._usuario("rrhh_s", Usuario.Rol.RRHH_INTERIOR, cls.sur)
        cls.lectura = cls._usuario("lectura_doc", Usuario.Rol.SOLO_LECTURA, cls.norte)

    @classmethod
    def _usuario(cls, username, rol, zona):
        u = Usuario.objects.create_user(username=username, password="Clave-Prueba-123")
        u.rol, u.zona = rol, zona
        u.save()
        return u

    def url(self, clave):
        return reverse("expedientes:documento_generar",
                       args=[self.trabajador.pk, clave])


class Contexto(BaseDocumentos):
    """Los campos de las plantillas se arman con los datos del expediente."""

    def test_arma_los_campos_de_la_plantilla(self):
        c = {generador.normalizar_campo(k): v
             for k, v in generador.contexto_documentos(self.trabajador).items()}

        self.assertEqual(c["apellido_y_nombre"], "PEREZ GOMEZ JUAN CARLOS")
        self.assertEqual(c["cedula"], "12345678")
        self.assertEqual(c["cargo"], "VENDEDOR DE PISO")
        self.assertEqual(c["estado_civil"], "CASADO(A)")
        self.assertEqual(c["tienda"], "SAMBIL CARACAS")
        self.assertEqual(c["direccion_de_tienda"], "CC SAMBIL, NIVEL 2, LOCAL 210, CARACAS")

    def test_descompone_las_fechas(self):
        c = {generador.normalizar_campo(k): v
             for k, v in generador.contexto_documentos(self.trabajador).items()}
        self.assertEqual((c["dia_de_ingreso"], c["mes_de_ingreso"], c["ano_de_ingreso"]),
                         ("1", "agosto", "2026"))
        self.assertEqual((c["dia_de_nacimiento"], c["mes_de_nacimiento"]), ("5", "marzo"))
        self.assertEqual((c["dia_de_culminacion"], c["mes_de_culminacion"]),
                         ("31", "octubre"))

    def test_los_alias_de_la_plantilla_apuntan_al_mismo_dato(self):
        """Confidencialidad usa Columna1/Columna2 para cédula y nombre."""
        c = {generador.normalizar_campo(k): v
             for k, v in generador.contexto_documentos(self.trabajador).items()}
        self.assertEqual(c["columna2"], c["apellido_y_nombre"])
        self.assertEqual(c["columna1"], c["cedula"])
        self.assertEqual(c["nombres_y_apellidos"], c["apellido_y_nombre"])

    def test_el_salario_sale_de_la_remuneracion(self):
        c = {generador.normalizar_campo(k): v
             for k, v in generador.contexto_documentos(self.trabajador).items()}
        self.assertEqual(
            c["salario_texto"],
            "CIENTO OCHENTA BOLÍVARES CON 00/100 CÉNTIMOS (Bs.180,00)",
        )

    def test_sin_sueldo_cargado_el_salario_queda_vacio(self):
        AsignacionPago.objects.all().delete()
        self.assertEqual(generador.salario_en_letras(self.trabajador), "")

    def test_avisa_que_campos_van_a_salir_en_blanco(self):
        DatosContratacion.objects.filter(trabajador=self.trabajador).delete()
        sin_datos = Trabajador.objects.get(pk=self.trabajador.pk)
        faltan = generador.campos_incompletos(sin_datos)
        self.assertIn("Estado civil (datos de contratación)", faltan)
        self.assertIn("Dirección de habitación (datos de contratación)", faltan)

    def test_con_todo_cargado_no_falta_nada(self):
        self.assertEqual(generador.campos_incompletos(self.trabajador), [])


@falta_plantillas
class GeneracionReal(BaseDocumentos):
    """Se generan los 5 Word de verdad, con las plantillas del proyecto."""

    def setUp(self):
        self.client.force_login(self.admin)

    def test_los_cinco_documentos_se_descargan(self):
        for clave, meta in generador.PLANTILLAS.items():
            with self.subTest(documento=clave):
                resp = self.client.get(self.url(clave))
                self.assertEqual(resp.status_code, 200)
                self.assertGreater(len(resp.content), 5000)
                self.assertIn("attachment", resp["Content-Disposition"])
                self.assertIn(meta["titulo"], resp["Content-Disposition"])

    def test_el_docx_generado_es_valido(self):
        for clave in ["contrato", "confidencialidad", "beneficios", "carta"]:
            with self.subTest(documento=clave):
                resp = self.client.get(self.url(clave))
                z = zipfile.ZipFile(BytesIO(resp.content))
                self.assertIsNone(z.testzip())
                self.assertIn("word/document.xml", z.namelist())

    def test_el_contrato_lleva_los_datos_del_trabajador(self):
        cuerpo = texto_docx(self.client.get(self.url("contrato")).content)
        for esperado in ["PEREZ GOMEZ JUAN CARLOS", "12345678", "VENDEDOR DE PISO",
                         "CASADO(A)", "AV SIEMPRE VIVA 742", "MARACAY, ARAGUA",
                         "CARACAS"]:
            self.assertIn(esperado, cuerpo)

    def test_el_contrato_lleva_el_salario_de_la_remuneracion(self):
        cuerpo = texto_docx(self.client.get(self.url("contrato")).content)
        self.assertIn("CIENTO OCHENTA BOLÍVARES CON 00/100 CÉNTIMOS (Bs.180,00)", cuerpo)
        self.assertNotIn("CIENTO TREINTA", cuerpo)  # el monto viejo de la plantilla

    def test_el_contrato_lleva_las_fechas_desarmadas(self):
        cuerpo = texto_docx(self.client.get(self.url("contrato")).content)
        self.assertIn("agosto", cuerpo)
        self.assertIn("octubre", cuerpo)      # culminación
        self.assertIn("Temporada Navidad", cuerpo)

    def test_la_carta_lleva_la_tienda_y_el_cargo(self):
        cuerpo = texto_docx(self.client.get(self.url("carta")).content)
        self.assertIn("PEREZ GOMEZ JUAN CARLOS", cuerpo)
        self.assertIn("SAMBIL CARACAS", cuerpo)
        self.assertIn("VENDEDOR DE PISO", cuerpo)

    def test_el_acta_de_beneficios_se_completa(self):
        """Esta plantilla no tenía campos: se le insertaron marcadores."""
        cuerpo = texto_docx(self.client.get(self.url("beneficios")).content)
        self.assertIn("PEREZ GOMEZ JUAN CARLOS", cuerpo)
        self.assertIn("12345678", cuerpo)
        self.assertIn("VENDEDOR DE PISO", cuerpo)
        self.assertNotIn("____", cuerpo)

    def test_el_acta_de_recibos_se_completa(self):
        crudo = self.client.get(self.url("recibo")).content.decode("latin-1")
        self.assertIn("PEREZ GOMEZ JUAN CARLOS", crudo)
        self.assertIn("12345678", crudo)

    def test_no_queda_ningun_rastro_de_la_plantilla(self):
        """Ni datos de la persona de ejemplo ni campos sin resolver."""
        for clave in generador.PLANTILLAS:
            resp = self.client.get(self.url(clave))
            if clave == "recibo":
                crudo = resp.content.decode("latin-1")
            else:
                crudo = "".join(
                    zipfile.ZipFile(BytesIO(resp.content)).read(n).decode("utf-8", "replace")
                    for n in zipfile.ZipFile(BytesIO(resp.content)).namelist()
                    if n.endswith(".xml")
                )
            for rastro in RASTROS:
                with self.subTest(documento=clave, rastro=rastro):
                    self.assertNotIn(rastro, crudo)

    def test_el_xml_generado_sigue_siendo_valido(self):
        """Todas las partes del .docx tienen que parsear.

        Al reescribir el XML se pierden los xmlns que ningún elemento usa, y
        eso deja sin declarar los prefijos de `mc:Ignorable`. Word entonces
        abre el archivo avisando que tiene "contenido ilegible".
        """
        for clave in ["contrato", "confidencialidad", "beneficios", "carta"]:
            resp = self.client.get(self.url(clave))
            z = zipfile.ZipFile(BytesIO(resp.content))
            for parte in z.namelist():
                if not parte.endswith((".xml", ".rels")):
                    continue
                with self.subTest(documento=clave, parte=parte):
                    ET.fromstring(z.read(parte))  # ParseError si quedó roto

    def test_se_conservan_los_namespaces_de_la_plantilla(self):
        for clave in ["contrato", "confidencialidad", "beneficios", "carta"]:
            resp = self.client.get(self.url(clave))
            z = zipfile.ZipFile(BytesIO(resp.content))
            for parte in z.namelist():
                if not parte.endswith(".xml"):
                    continue
                cabecera = z.read(parte)[:6000].decode("utf-8", "replace")
                ignorable = re.search(r'mc:Ignorable="([^"]*)"', cabecera)
                if not ignorable:
                    continue
                declarados = set(re.findall(r"xmlns:([A-Za-z0-9_]+)=", cabecera))
                with self.subTest(documento=clave, parte=parte):
                    self.assertLessEqual(set(ignorable.group(1).split()), declarados)

    def test_documento_desconocido_da_404(self):
        resp = self.client.get(
            reverse("expedientes:documento_generar", args=[self.trabajador.pk, "inventado"])
        )
        self.assertEqual(resp.status_code, 404)


@falta_plantillas
class PermisosDocumentos(BaseDocumentos):
    """Los documentos llevan sueldo y datos personales: mismo permiso que Remuneración."""

    def test_admin_puede(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url("contrato")).status_code, 200)

    def test_rrhh_de_su_zona_puede(self):
        self.client.force_login(self.rrhh_norte)
        self.assertEqual(self.client.get(self.url("contrato")).status_code, 200)

    def test_rrhh_de_otra_zona_no_puede(self):
        self.client.force_login(self.rrhh_sur)
        self.assertEqual(self.client.get(self.url("contrato")).status_code, 403)

    def test_solo_lectura_no_puede(self):
        self.client.force_login(self.lectura)
        self.assertEqual(self.client.get(self.url("contrato")).status_code, 403)

    def test_solo_lectura_no_ve_la_seccion(self):
        self.client.force_login(self.lectura)
        resp = self.client.get(
            reverse("expedientes:trabajador_detail", args=[self.trabajador.pk])
        )
        self.assertNotContains(resp, "Documentos corporativos")

    def test_anonimo_va_al_login(self):
        resp = self.client.get(self.url("contrato"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("ingresar", resp["Location"])

    def test_solo_lectura_no_edita_el_expediente(self):
        """Los datos de contratacion se cargan en el alta/edicion del expediente."""
        self.client.force_login(self.lectura)
        resp = self.client.get(
            reverse("expedientes:trabajador_update", args=[self.trabajador.pk])
        )
        self.assertEqual(resp.status_code, 403)
