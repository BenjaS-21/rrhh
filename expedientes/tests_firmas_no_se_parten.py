"""El bloque de firmas no se corta entre el nombre y la cédula.

Reporte de la gente que usa el sistema, con el PDF abierto en la página 4 de 4:
esa última hoja tenía **solo los dos números de cédula**, sueltos en blanco. Los
nombres y las rayas para firmar habían quedado en la página anterior.

La tabla de firmas son tres filas —las etiquetas «EL EMPLEADOR» / «EL
TRABAJADOR», los nombres, y las cédulas— y ninguna estaba marcada como
indivisible. Word corta una tabla entre dos filas sin preguntar, así que cuando
el texto de las cláusulas llegaba justo al pie de la página, el corte caía
entre los nombres y las cédulas.

No es cosmético. Un contrato firmado es una hoja donde la cédula identifica a
quien firma justo arriba. Separadas, la hoja firmada parece incompleta y la
última parece un anexo de otro documento.

Se revisa en dos niveles, porque se pueden romper por separado:

* **la plantilla**, que corre en cualquier máquina: las filas quedaron
  marcadas para no partirse;
* **el PDF de verdad**, solo donde hay Word: se generan los contratos con
  varios largos de texto —lo que mueve el corte de página— y se comprueba que
  el nombre y la cédula caigan siempre en la misma hoja.

Sin la marca, tres de esos casos se partían.
"""

import unittest
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.test import TestCase

from cuentas.models import Cargo, Departamento, Sede, TipoDocumentoIdentidad, Zona
from expedientes import documentos as generador
from expedientes import pdf as conversor
from expedientes.models import (AsignacionPago, ConceptoPago, DatosContratacion,
                                Moneda, Trabajador)
from expedientes.tests_documentos import falta_plantillas

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Los dos documentos que llevan bloque de firmas.
CON_FIRMAS = ("contrato", "corporativo")

# El representante legal de la empresa: va escrito en la plantilla, no es un
# campo. Aparece también en el cuerpo de la primera página, así que siempre se
# busca la ÚLTIMA hoja donde sale — la del bloque de firmas.
NOMBRE_EMPLEADOR = "JONATHAN ANTONIO JBARAH SALIM"
CEDULA_EMPLEADOR = "17158865"

# Largos de dirección que mueven el corte de página. Los tres primeros son los
# que se partían antes del arreglo (dos en el corporativo, uno en el contrato);
# el corto es el control.
LARGOS = (10, 120, 260, 560)


def _tabla_de_firmas(clave):
    ruta = generador.ruta_plantilla(clave)
    with zipfile.ZipFile(ruta) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    for tabla in root.iter(W + "tbl"):
        if "EMPLEADOR" in "".join(t.text or "" for t in tabla.iter(W + "t")):
            return tabla
    return None


@falta_plantillas
class LaPlantillaTraeLasFilasPegadas(TestCase):
    """Nivel plantilla: corre en cualquier máquina, con o sin Word."""

    def test_los_dos_contratos_tienen_bloque_de_firmas(self):
        """Testigo del testigo: si no lo encontrara, lo de abajo pasaría solo."""
        for clave in CON_FIRMAS:
            with self.subTest(documento=clave):
                self.assertIsNotNone(_tabla_de_firmas(clave))

    def test_ninguna_fila_se_puede_partir(self):
        for clave in CON_FIRMAS:
            filas = _tabla_de_firmas(clave).findall(W + "tr")
            self.assertEqual(len(filas), 3, f"{clave}: la tabla ya no son 3 filas")
            for numero, fila in enumerate(filas):
                with self.subTest(documento=clave, fila=numero):
                    trpr = fila.find(W + "trPr")
                    self.assertIsNotNone(trpr, "la fila no tiene propiedades")
                    self.assertIsNotNone(
                        trpr.find(W + "cantSplit"),
                        "la fila se puede partir a la mitad entre dos páginas")

    def test_las_filas_de_arriba_arrastran_a_la_de_abajo(self):
        """Lo que mantiene juntas las TRES filas, no solo cada una entera."""
        for clave in CON_FIRMAS:
            filas = _tabla_de_firmas(clave).findall(W + "tr")
            for numero, fila in enumerate(filas[:-1]):
                for parrafo in fila.iter(W + "p"):
                    with self.subTest(documento=clave, fila=numero):
                        ppr = parrafo.find(W + "pPr")
                        self.assertIsNotNone(ppr)
                        self.assertIsNotNone(
                            ppr.find(W + "keepNext"),
                            "esta fila puede quedar en otra página que la siguiente")

    def test_la_ultima_fila_no_arrastra_a_nada(self):
        """Testigo: `keepNext` en la última pegaría las firmas al pie siguiente."""
        for clave in CON_FIRMAS:
            ultima = _tabla_de_firmas(clave).findall(W + "tr")[-1]
            for parrafo in ultima.iter(W + "p"):
                with self.subTest(documento=clave):
                    ppr = parrafo.find(W + "pPr")
                    if ppr is not None:
                        self.assertIsNone(ppr.find(W + "keepNext"))

    def test_el_xml_sigue_siendo_valido(self):
        """Las propiedades van en un orden fijo; mal puestas, Word se queja."""
        for clave in CON_FIRMAS:
            with zipfile.ZipFile(generador.ruta_plantilla(clave)) as z:
                for nombre in z.namelist():
                    if nombre.endswith(".xml"):
                        with self.subTest(documento=clave, parte=nombre):
                            ET.fromstring(z.read(nombre))


class _ConContrato(TestCase):

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
        cls.datos = DatosContratacion.objects.create(
            trabajador=cls.trabajador, estado_civil="SOLTERO",
            direccion="CALLE 1", ciudad_nacimiento="GUATIRE",
            horario="8:00AM a 5:00PM", motivo_contratacion="Temporada",
            fecha_culminacion=date(2026, 11, 22))
        AsignacionPago.objects.create(
            trabajador=cls.trabajador, concepto=ConceptoPago.objects.first(),
            monto=Decimal("130.00"), moneda=Moneda.objects.get(codigo="VES"))


@falta_plantillas
@unittest.skipUnless(conversor.hay_conversor(),
                     "Esta máquina no tiene Word: no se puede paginar de verdad.")
class EnElPdfDeVerdadCaenEnLaMismaHoja(_ConContrato):
    """Nivel PDF. Es lo que vio quien reportó: la página 4 con dos números.

    Solo corre donde hay Word, porque el corte de página lo decide Word y no
    hay forma honesta de simularlo. Las pruebas de plantilla de arriba cubren
    el resto de las máquinas.
    """

    def _hojas(self, clave):
        """(hoja del nombre, hoja de la cédula, total), del bloque de firmas."""
        import pymupdf

        crudo, nombre, _ = generador.generar(clave, self.trabajador)
        salida = conversor.convertir_a_pdf(crudo, nombre)
        with pymupdf.open(stream=salida, filetype="pdf") as documento:
            ultima = {}
            for numero, pagina in enumerate(documento, start=1):
                texto = pagina.get_text()
                for buscado in (NOMBRE_EMPLEADOR, CEDULA_EMPLEADOR):
                    if buscado in texto:
                        ultima[buscado] = numero
            return (ultima.get(NOMBRE_EMPLEADOR), ultima.get(CEDULA_EMPLEADOR),
                    len(documento))

    def test_la_cedula_va_en_la_misma_hoja_que_el_nombre(self):
        for largo in LARGOS:
            self.datos.direccion = "AV PRINCIPAL " + ("X" * largo)
            self.datos.save()
            for clave in CON_FIRMAS:
                hoja_nombre, hoja_cedula, total = self._hojas(clave)
                with self.subTest(documento=clave, direccion=largo):
                    self.assertIsNotNone(hoja_nombre, "no salió el firmante")
                    self.assertEqual(
                        hoja_nombre, hoja_cedula,
                        f"{clave}: el nombre quedó en la hoja {hoja_nombre} y la "
                        f"cédula en la {hoja_cedula} (de {total}); el bloque de "
                        "firmas se partió")

    def test_y_el_bloque_sale_completo(self):
        """Testigo: coincidirían igual si no se imprimiera ninguno de los dos."""
        hoja_nombre, hoja_cedula, _ = self._hojas("contrato")
        self.assertIsNotNone(hoja_nombre)
        self.assertIsNotNone(hoja_cedula)
