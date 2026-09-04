"""La cláusula Cuarta: cuándo entra en vigencia el contrato y cuándo concluye.

Reporte de quien usa el sistema, con el contrato a la vista: «observo esto de
la doble de, no está tomando la fecha de final». Decía:

    entrará en vigencia el 3 de agosto de 2026 y concluirá el  de  de 2026

Ese renglón mezcla dos cosas distintas, y la segunda es peor que la que se vio.

**Lo que se veía.** Esa persona no tiene cargada la fecha de culminación en
Datos de contratación, así que el día y el mes salen vacíos. Hasta ahí es
correcto —el sistema ya lo avisa en la ficha, entre los campos incompletos—,
pero el año seguía imprimiéndose, y un «de  de 2026» no se lee como un dato
que falta: se lee como un contrato mal armado.

**Lo que no se veía.** El año del final apuntaba al campo del INGRESO. Con una
fecha de culminación cargada de verdad, un contrato que empieza el 3 de agosto
de 2026 y termina el 15 de enero de 2027 salía impreso así:

    entrará en vigencia el 3 de agosto de 2026 y concluirá el 15 de enero de 2026

Concluye cinco meses antes de empezar. Un contrato vencido el día que se firma
no obliga a nada, y el error no se nota leyendo: los dos años dicen 2026 y el
ojo lo da por bueno.

Esto ya se había arreglado en el contrato corporativo —tiene su comentario en
`_fechas_del_corporativo`— pero se arregló solo ahí, porque ahí el día y el mes
también estaban rotos y eran lo que se estaba mirando. En el contrato de
trabajo el día y el mes ya eran campos, así que nadie volvió a pasar por esa
cláusula y el año quedó mal.
"""

import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from decimal import Decimal

from django.test import TestCase

from cuentas.models import Cargo, Departamento, Sede, TipoDocumentoIdentidad, Zona
from expedientes import documentos as generador
from expedientes.models import (AsignacionPago, ConceptoPago, DatosContratacion,
                                Moneda, Trabajador)
from expedientes.tests_documentos import falta_plantillas, texto_generado

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Los dos Word que llevan la cláusula Cuarta.
CON_CLAUSULA = ("contrato", "corporativo")


def _clausula_de_la_plantilla(clave):
    """El párrafo de la cláusula Cuarta, tal como quedó en la plantilla."""
    with zipfile.ZipFile(generador.ruta_plantilla(clave)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    for parrafo in root.iter(W + "p"):
        if "entrará en vigencia el" in "".join(
                t.text or "" for t in parrafo.iter(W + "t")):
            return parrafo
    return None


def _campos(parrafo):
    return [i.text or "" for i in parrafo.iter(W + "instrText")]


@falta_plantillas
class LaPlantillaApuntaAlAnioCorrecto(TestCase):
    """Nivel plantilla: se ve sin generar nada y corre en cualquier máquina."""

    def test_las_dos_traen_la_clausula(self):
        """Testigo del testigo: si no la encontrara, lo de abajo pasaría solo."""
        for clave in CON_CLAUSULA:
            with self.subTest(documento=clave):
                self.assertIsNotNone(_clausula_de_la_plantilla(clave))

    def test_el_anio_del_ingreso_aparece_una_sola_vez(self):
        """Estaba dos veces: la segunda era, en realidad, el año del final."""
        for clave in CON_CLAUSULA:
            campos = _campos(_clausula_de_la_plantilla(clave))
            cuantos = sum(1 for c in campos if "o_de_ingreso" in c)
            with self.subTest(documento=clave):
                self.assertEqual(cuantos, 1, f"{clave}: {campos}")

    def test_y_el_de_la_culminacion_esta(self):
        for clave in CON_CLAUSULA:
            campos = _campos(_clausula_de_la_plantilla(clave))
            with self.subTest(documento=clave):
                self.assertTrue(
                    any("o_de_culminaci" in c for c in campos),
                    f"{clave}: no quedó el año de culminación — {campos}")

    def test_preparar_de_nuevo_no_cambia_nada(self):
        """`preparar_plantillas` corre en cada arranque: tiene que ser
        idempotente. La segunda pasada ya no encuentra dos años de ingreso."""
        from expedientes.management.commands.preparar_plantillas import Command

        for clave in CON_CLAUSULA:
            parrafo = _clausula_de_la_plantilla(clave)
            with self.subTest(documento=clave):
                self.assertEqual(Command._anio_del_cierre(parrafo), 0)


class _ConContrato(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        sede = Sede.objects.create(nombre="TIENDA GUATIRE", zona=zona,
                                   ciudad="GUATIRE")
        unidad = Departamento.objects.create(nombre="ADMINISTRACION")
        puesto = Cargo.objects.create(nombre="ASESOR DE VENTAS",
                                      departamento=unidad)
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="26045681",
            tipo_documento=TipoDocumentoIdentidad.objects.get(codigo="V"),
            nombres="HENMARY ALEJANDRA", apellidos="GOMEZ RAMOS", sede=sede,
            departamento=unidad, puesto=puesto,
            fecha_nacimiento=date(1995, 4, 12), fecha_ingreso=date(2026, 8, 3))
        cls.datos = DatosContratacion.objects.create(
            trabajador=cls.trabajador, estado_civil="SOLTERO",
            direccion="URB LOS NARANJOS", ciudad_nacimiento="GUATIRE",
            horario="8:00AM a 5:00PM", motivo_contratacion="Temporada",
            fecha_culminacion=date(2026, 11, 22))
        AsignacionPago.objects.create(
            trabajador=cls.trabajador, concepto=ConceptoPago.objects.first(),
            monto=Decimal("130.00"), moneda=Moneda.objects.get(codigo="VES"))

    def clausula(self, clave, fin):
        """(lo que dice del comienzo, lo que dice del final)."""
        self.datos.fecha_culminacion = fin
        self.datos.save()
        datos, nombre, _ = generador.generar(clave, self.trabajador)
        texto = re.sub(r"\s+", " ", texto_generado(datos, nombre))
        encontrado = re.search(
            r"entrará en vigencia el(?P<inicio>.*?)y concluirá el(?P<fin>.*?),",
            texto)
        self.assertIsNotNone(encontrado, f"{clave}: no salió la cláusula Cuarta")
        return encontrado.group("inicio"), encontrado.group("fin")


@falta_plantillas
class ElContratoDiceCuandoTermina(_ConContrato):

    def test_la_fecha_de_fin_sale_completa(self):
        for clave in CON_CLAUSULA:
            inicio, fin = self.clausula(clave, date(2026, 11, 22))
            with self.subTest(documento=clave):
                self.assertIn("3 de agosto de 2026", inicio)
                self.assertIn("22 de noviembre de 2026", fin)

    def test_si_termina_el_anio_siguiente_dice_el_anio_siguiente(self):
        """El caso que rompía: los dos años salían del ingreso, así que el
        contrato concluía cinco meses ANTES de empezar."""
        for clave in CON_CLAUSULA:
            _, fin = self.clausula(clave, date(2027, 1, 15))
            with self.subTest(documento=clave):
                self.assertIn("15 de enero de 2027", fin)
                self.assertNotIn("2026", fin)

    def test_el_comienzo_sigue_saliendo_del_ingreso(self):
        """Testigo: mover el año del final no puede llevarse el del comienzo."""
        for clave in CON_CLAUSULA:
            inicio, _ = self.clausula(clave, date(2027, 1, 15))
            with self.subTest(documento=clave):
                self.assertIn("2026", inicio)


@falta_plantillas
class SinFechaDeFinNoSeInventaNada(_ConContrato):
    """Lo que se vio en el reporte: «concluirá el  de  de 2026».

    Que salga vacío es correcto —la fecha no está cargada y la ficha lo avisa
    entre los campos incompletos—, pero el año no puede quedar impreso solo. Un
    hueco se ve y se completa a mano; un «de  de 2026» parece un dato bueno.
    """

    def test_no_queda_ningun_numero_suelto(self):
        for clave in CON_CLAUSULA:
            _, fin = self.clausula(clave, None)
            with self.subTest(documento=clave):
                self.assertFalse(re.search(r"\d", fin),
                                 f"{clave}: quedó un número en «{fin.strip()}»")

    def test_el_comienzo_se_sigue_imprimiendo(self):
        """Testigo: la fecha de ingreso no depende de la de culminación."""
        for clave in CON_CLAUSULA:
            inicio, _ = self.clausula(clave, None)
            with self.subTest(documento=clave):
                self.assertIn("3 de agosto de 2026", inicio)

    def test_la_ficha_avisa_que_falta(self):
        """Es lo que evita que salga en blanco por descuido."""
        self.datos.fecha_culminacion = None
        self.datos.save()
        faltan = generador.campos_incompletos(self.trabajador)
        self.assertIn("Fecha de culminación (datos de contratación)", faltan)
