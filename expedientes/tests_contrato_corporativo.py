"""El sexto documento: el contrato corporativo.

Se agrega al conjunto que ya generaba el sistema. Lo particular de este Word es
que llegó con los datos de una persona real escritos a mano en el recuadro de
encabezado —nombre completo, cédula y cargo de quien sirvió de ejemplo— en vez
de campos de combinación como el resto del documento.

Sin tocar eso, cada contrato saldría con esa persona arriba y con la que
corresponde abajo: el dato personal de alguien ajeno, repetido en el contrato
de todo el personal, y un documento que se contradice a sí mismo. `preparar_
plantillas` lo cambia por marcadores.

La prueba principal de acá abajo es esa: que no quede rastro. Está escrita
buscando los datos de la persona real, así que se cae si alguien vuelve a
copiar el Word original encima sin prepararlo.
"""

import unittest
from io import BytesIO
from zipfile import ZipFile

from django.urls import reverse

from expedientes import documentos as generador
from expedientes.tests_documentos import (
    BaseDocumentos, falta_plantillas, texto_docx,
)

CLAVE = "corporativo"

# Los datos que traía el Word original. No se leen de la plantilla a propósito:
# si se leyeran de ahí, prepararla mal y borrar la prueba darían igual.
DE_LA_PERSONA_DE_EJEMPLO = [
    "RAMON ALFREDO CASTILLO SANCHEZ",
    "19.692.045",
    "CHIEF OF TECHNOLOGY (CTO)",
]


class EstaRegistrado(unittest.TestCase):

    def test_figura_entre_las_plantillas(self):
        self.assertIn(CLAVE, generador.PLANTILLAS)

    def test_con_un_titulo_que_se_entiende_en_pantalla(self):
        self.assertEqual(generador.PLANTILLAS[CLAVE]["titulo"], "Contrato corporativo")

    def test_no_pisa_el_archivo_del_otro_contrato(self):
        """Dos entradas apuntando al mismo archivo dejarían uno de los dos roto."""
        archivos = [m["archivo"] for m in generador.PLANTILLAS.values()]
        self.assertEqual(len(archivos), len(set(archivos)))


@falta_plantillas
class SeGeneraYSeDescarga(BaseDocumentos):

    def setUp(self):
        self.client.force_login(self.admin)

    def pedir(self):
        return self.client.get(
            reverse("expedientes:documento_generar",
                    args=[self.trabajador.pk, CLAVE]))

    def test_se_descarga(self):
        r = self.pedir()
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertIn("Contrato corporativo", r["Content-Disposition"])

    def test_el_archivo_es_un_word_valido(self):
        z = ZipFile(BytesIO(self.pedir().content))
        self.assertIsNone(z.testzip())
        self.assertIn("word/document.xml", z.namelist())

    def test_aparece_en_la_ficha_del_trabajador(self):
        cuerpo = self.client.get(
            reverse("expedientes:trabajador_detail",
                    args=[self.trabajador.pk])).content.decode()
        self.assertIn("Contrato corporativo", cuerpo)


@falta_plantillas
class NoSeCuelaElDatoDeOtraPersona(BaseDocumentos):
    """La razón por la que este documento necesitó preparación aparte."""

    def setUp(self):
        self.client.force_login(self.admin)
        self.cuerpo = texto_docx(self.client.get(
            reverse("expedientes:documento_generar",
                    args=[self.trabajador.pk, CLAVE])).content)

    def test_no_queda_rastro_de_la_persona_de_ejemplo(self):
        for dato in DE_LA_PERSONA_DE_EJEMPLO:
            with self.subTest(dato=dato):
                self.assertNotIn(
                    dato, self.cuerpo,
                    f"el contrato salió con '{dato}', que es de otra persona")

    def test_el_recuadro_de_arriba_trae_al_trabajador_de_la_ficha(self):
        """Testigo: borrar los datos viejos y dejar el recuadro vacío no sirve."""
        for esperado in ["PEREZ GOMEZ JUAN CARLOS", "12345678", "VENDEDOR DE PISO"]:
            with self.subTest(dato=esperado):
                self.assertIn(esperado, self.cuerpo)

    def test_la_cedula_no_sale_con_la_letra_repetida(self):
        """El "V-" del Word era un pedazo aparte y la cédula ya la trae."""
        self.assertNotIn("V-V-", self.cuerpo)

    def test_no_queda_ningun_marcador_a_la_vista(self):
        """Un `{{CARGO}}` impreso en un contrato firmado es papelón asegurado."""
        self.assertNotIn("{{", self.cuerpo)

    def test_los_datos_de_la_empresa_siguen_estando(self):
        """Testigo: limpiar de más borraría al empleador, que sí va fijo."""
        self.assertIn("IMPORTACIONES JBARAH", self.cuerpo)

    def test_el_resto_de_los_datos_del_expediente_tambien_entran(self):
        for esperado in ["CASADO(A)", "CARACAS", "2026"]:
            with self.subTest(dato=esperado):
                self.assertIn(esperado, self.cuerpo)


@falta_plantillas
class LaPreparacionEsIdempotente(unittest.TestCase):
    """Correr `preparar_plantillas` de nuevo no puede empeorar el resultado.

    Se corre seguido —cada vez que cambia un Word original—, y la segunda
    pasada trabaja sobre el original otra vez, no sobre lo ya preparado.
    """

    def test_la_plantilla_preparada_no_tiene_los_datos_viejos(self):
        ruta = generador.ruta_plantilla(CLAVE)
        with ZipFile(ruta) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        for dato in DE_LA_PERSONA_DE_EJEMPLO:
            with self.subTest(dato=dato):
                self.assertNotIn(dato, xml)

    def test_y_si_tiene_los_marcadores_puestos(self):
        ruta = generador.ruta_plantilla(CLAVE)
        with ZipFile(ruta) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        for marcador in ["{{NOMBRES_Y_APELLIDOS}}", "{{CEDULA}}", "{{CARGO}}"]:
            with self.subTest(marcador=marcador):
                self.assertIn(marcador, xml)
