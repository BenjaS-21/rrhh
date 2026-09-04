"""Los documentos no salen con el control de cambios de Word encima.

Reporte de quien usa el sistema, con el acuerdo de confidencialidad abierto:
al margen derecho, un globo que dice «Con formato: Fuente: Sin Negrita», con su
línea roja apuntando al párrafo y las barras de cambio en el margen izquierdo.

El Word original de Gestión Humana llegó con el **control de cambios puesto**:
28 inserciones, 6 borrados y 25 cambios de formato de quien redactó la versión
nueva. El sistema copiaba el archivo tal cual, así que el documento que se
imprime para firmar arrastraba todo eso.

Importa por tres razones, y ninguna es estética:

* es un papel que se firma, y va con marcas de corrección encima;
* el globo deja a la vista **quién** redactó cada frase y **qué decía la
  versión anterior** — el historial de la redacción viaja con cada copia que
  se entrega;
* cómo se ve depende de la máquina. Word decide si mostrar las marcas según la
  configuración de quien abre el archivo, así que el mismo documento sale de
  una forma en una computadora y de otra en la de al lado.

Aceptar los cambios **no cambia lo que dice el acuerdo**: Word ya mostraba el
texto aceptado y el sistema tampoco leía lo borrado. La prueba de abajo lo fija:
el texto tiene que salir carácter por carácter igual.

Se acepta al abrir el Word, en `_abrir_docx`, y no en el preparador de cada
plantilla. Esa decisión también viene de un error: el año del cierre del
contrato estuvo mal más de un mes por haberse arreglado en un Word y no en el
otro. Acá cualquier plantilla que llegue con marcas queda limpia sin que nadie
tenga que acordarse.
"""

import collections
import re
import xml.etree.ElementTree as ET
import zipfile

from django.test import TestCase

from expedientes import documentos as generador
from expedientes.management.commands.preparar_plantillas import Command
from expedientes.tests_documentos import falta_plantillas

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Todo lo que Word guarda cuando el control de cambios está puesto.
MARCAS = (r"<w:(ins|del|rPrChange|pPrChange|tblPrChange|trPrChange|tcPrChange|"
          r"sectPrChange|tblGridChange|moveFrom|moveTo)[ />]")

LOS_WORD = [c for c, m in generador.PLANTILLAS.items()
            if m["archivo"].lower().endswith(".docx")]

# El que llegó con las marcas. Los demás vinieron limpios, y por eso están:
# la limpieza tiene que valer para todos, no para el que se reportó.
EL_DEL_REPORTE = "confidencialidad"


def _marcas(datos):
    xml = zipfile.ZipFile(datos).read("word/document.xml").decode("utf-8", "replace")
    return collections.Counter(re.findall(MARCAS, xml))


def _texto(ruta):
    root = ET.fromstring(zipfile.ZipFile(ruta).read("word/document.xml"))
    return "".join((t.text or "") for t in root.iter(W + "t"))


@falta_plantillas
class NingunaPlantillaLlevaMarcasDeCorreccion(TestCase):

    def test_ninguna(self):
        for clave in LOS_WORD:
            with self.subTest(documento=clave):
                self.assertEqual(
                    dict(_marcas(generador.ruta_plantilla(clave))), {},
                    "sale con el control de cambios de Word encima")

    def test_el_original_del_reporte_si_las_tenia(self):
        """Testigo: si el original hubiera venido limpio, lo de arriba pasaría
        solo y no probaría nada. Este es el archivo que mandó Gestión Humana."""
        from django.conf import settings
        from pathlib import Path

        origen = Command._buscar(
            Path(settings.BASE_DIR),
            generador.PLANTILLAS[EL_DEL_REPORTE]["origen"])[0]
        if origen is None:
            self.skipTest("no está el Word original en la raíz del proyecto")
        self.assertGreater(sum(_marcas(origen).values()), 0,
                           "el original ya no trae marcas: revisar esta prueba")


@falta_plantillas
class AceptarNoCambiaLoQueDiceElDocumento(TestCase):
    """Lo que se va es el registro de cómo se llegó al texto, no el texto."""

    def test_el_texto_es_el_mismo_que_mostraba_word(self):
        """Sobre el Word original, aceptando en memoria.

        No se puede comparar el original contra la plantilla preparada: ahí el
        texto cambia a propósito —«Caracas» pasa a ser un marcador, la cédula
        del empleador estrena su «V-»—. Lo que se comprueba es la invariante
        sola: aceptar los cambios deja el texto visible tal cual estaba.
        """
        from pathlib import Path

        from django.conf import settings

        origen = Command._buscar(
            Path(settings.BASE_DIR),
            generador.PLANTILLAS[EL_DEL_REPORTE]["origen"])[0]
        if origen is None:
            self.skipTest("no está el Word original en la raíz del proyecto")

        root = ET.fromstring(zipfile.ZipFile(origen).read("word/document.xml"))
        antes = "".join((t.text or "") for t in root.iter(W + "t"))
        # Doble uso: además de aceptar, confirma que había algo que aceptar.
        # Sin esto la comparación de abajo pasaría con cualquier archivo.
        self.assertGreater(Command._aceptar_los_cambios(root), 0,
                           "el original ya venía limpio: revisar esta prueba")
        Command._unir_parrafos_con_marca_borrada(root)
        despues = "".join((t.text or "") for t in root.iter(W + "t"))
        self.assertEqual(antes, despues,
                         "aceptar el control de cambios movió el texto")

    def test_las_clausulas_de_la_version_nueva_estan(self):
        """Lo insertado se queda: son las cláusulas que agregó quien revisó.

        Si en vez de aceptar se rechazara, el acuerdo volvería a la redacción
        vieja sin que se note — y eso es lo que se firma.
        """
        texto = _texto(generador.ruta_plantilla(EL_DEL_REPORTE))
        for frase in ("Violación de la Confidencialidad",
                      "medidas de seguridad adecuadas",
                      "daños irreparables"):
            with self.subTest(frase=frase):
                self.assertIn(frase, texto)

    def test_lo_borrado_no_esta(self):
        """Y lo borrado se va de verdad, no solo de la vista."""
        crudo = zipfile.ZipFile(
            generador.ruta_plantilla(EL_DEL_REPORTE)).read("word/document.xml")
        self.assertNotIn(b"delText", crudo)


@falta_plantillas
class CorrerlaDeNuevoNoRompeNada(TestCase):
    """`preparar_plantillas` corre en cada arranque."""

    def test_sobre_una_plantilla_limpia_no_toca_nada(self):
        for clave in LOS_WORD:
            root = ET.fromstring(zipfile.ZipFile(
                generador.ruta_plantilla(clave)).read("word/document.xml"))
            with self.subTest(documento=clave):
                self.assertEqual(Command._aceptar_los_cambios(root), 0)
                self.assertEqual(Command._unir_parrafos_con_marca_borrada(root), 0)

    def test_el_acuerdo_conserva_sus_dos_lineas_de_firma(self):
        """La marca de párrafo borrada estaba en la línea de firma: aceptarla
        une ese párrafo con el siguiente. Que la unión no se coma una firma."""
        texto = _texto(generador.ruta_plantilla(EL_DEL_REPORTE))
        self.assertIn("El Trabajador", texto)
        self.assertIn("La Empresa", texto)
        self.assertGreaterEqual(texto.count("_____"), 2,
                                "faltó una de las dos rayas para firmar")
