"""Ninguna fecha de los documentos puede quedar escrita a mano en el Word.

Este archivo nació de encontrar el mismo defecto tres veces seguidas, cada vez
por un reporte distinto:

* el contrato corporativo cerraba siempre «a los 11»;
* el acta de recibos no imprimía la fecha y decía «En ROTATIVO»;
* el acuerdo de confidencialidad decía «ha suscrito en fecha 16 de…».

Siempre lo mismo: en el Word, parte de la fecha era un campo de combinación y
parte había quedado escrita a mano, con la fecha de la persona que sirvió de
ejemplo. Y como el mes o el año sí cambiaban, el documento se veía correcto de
lejos: hay que conocer la fecha real para darse cuenta.

Buscarlos de a uno no termina nunca. Así que en vez de una prueba por caso, acá
se genera CADA documento para DOS trabajadores con fechas distintas y se
comparan: lo que debería cambiar y no cambia, está escrito fijo. Una fecha que
alguien deje a mano mañana, en cualquier plantilla nueva, se cae acá sola.

Lo único que sí es fijo son las fechas de registro de la empresa, que no
dependen de ningún trabajador.
"""

import re
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from cuentas.models import Cargo, Departamento, Sede, Zona
from expedientes import documentos as generador
from expedientes.models import (AsignacionPago, ConceptoPago, DatosContratacion,
                                Moneda, Trabajador)
from expedientes.tests_documentos import falta_plantillas, texto_generado

# "5 de enero de 2026"
FECHA = re.compile(r"(\d{1,2}) de ([a-zA-ZñáéíóúÑÁÉÍÓÚ]+) de (\d{4})")

# Constitución de la empresa y acta de refundición. Van en el cuerpo legal de
# los contratos y no cambian con nadie.
DE_LA_EMPRESA = {("09", "septiembre", "2008"), ("12", "noviembre", "2024")}


@falta_plantillas
class NingunaFechaQuedaEscritaAMano(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="CENDIS GUATIRE I", zona=zona,
                                       ciudad="GUATIRE")
        cls.unidad = Departamento.objects.create(nombre="CENDIS")
        cls.moneda = Moneda.objects.get(codigo="VES")
        cls.concepto = ConceptoPago.objects.first()

        # Dos personas sin un solo dato de fecha en común: ni el día, ni el mes,
        # ni el año. Si algo coincide, es porque está escrito en la plantilla.
        cls.uno = cls._crear("11111111", "ANA", "PRIMERA", "CAJERA",
                             date(1985, 3, 7), date(2026, 1, 5))
        cls.dos = cls._crear("22222222", "BETO", "SEGUNDO", "ALMACENISTA",
                             date(1995, 11, 23), date(2026, 9, 28))

    @classmethod
    def _crear(cls, ci, nombres, apellidos, cargo, nace, entra):
        puesto = Cargo.objects.create(nombre=cargo, departamento=cls.unidad)
        t = Trabajador.objects.create(
            documento_identidad=ci, nombres=nombres, apellidos=apellidos,
            sede=cls.sede, departamento=cls.unidad, puesto=puesto,
            fecha_nacimiento=nace, fecha_ingreso=entra)
        DatosContratacion.objects.create(
            trabajador=t, estado_civil="SOLTERO", direccion="CALLE 1",
            ciudad_nacimiento="GUATIRE", horario="ROTATIVO",
            motivo_contratacion="Temporada",
            fecha_culminacion=entra + timedelta(days=90))
        AsignacionPago.objects.create(trabajador=t, concepto=cls.concepto,
                                      monto=Decimal("180.00"), moneda=cls.moneda)
        return t

    def _texto(self, clave, trabajador):
        datos, nombre, _ = generador.generar(clave, trabajador)
        return re.sub(r"\s+", " ", texto_generado(datos, nombre))

    def _fechas(self, clave, trabajador):
        return FECHA.findall(self._texto(clave, trabajador))

    def test_toda_fecha_impresa_cambia_de_un_trabajador_a_otro(self):
        for clave in generador.PLANTILLAS:
            de_uno = self._fechas(clave, self.uno)
            de_dos = self._fechas(clave, self.dos)
            with self.subTest(documento=clave):
                self.assertEqual(
                    len(de_uno), len(de_dos),
                    f"{clave} imprime distinta cantidad de fechas para cada uno")
                for k, (a, b) in enumerate(zip(de_uno, de_dos)):
                    if a in DE_LA_EMPRESA:
                        continue
                    # Se comparan el día y el mes por separado, no la fecha
                    # entera. Comparar la fecha completa deja pasar justo el
                    # caso más traicionero: el acuerdo decía «16 de enero» y
                    # «16 de septiembre», o sea que el mes cambiaba y el día
                    # estaba escrito a mano. Visto de lejos parecía andar.
                    # El AÑO no entra: los dos entran el mismo año a propósito,
                    # y exigir que cambie daría falsos positivos.
                    for pos, parte in ((0, "el día"), (1, "el mes")):
                        self.assertNotEqual(
                            a[pos], b[pos],
                            f"{clave}: en la fecha {k + 1} ('{' de '.join(a)}') "
                            f"{parte} no cambia de un trabajador al otro; "
                            "está escrito a mano en la plantilla")

    def test_las_fechas_de_la_empresa_si_se_quedan_quietas(self):
        """Testigo: si todo cambiara, se estaría reescribiendo el cuerpo legal."""
        vistas = set()
        for clave in generador.PLANTILLAS:
            vistas.update(f for f in self._fechas(clave, self.uno)
                          if f in DE_LA_EMPRESA)
        self.assertEqual(vistas, DE_LA_EMPRESA,
                         "desaparecieron las fechas de registro de la empresa")

    def test_los_documentos_imprimen_alguna_fecha(self):
        """Testigo del testigo: una plantilla vacía pasaría todo lo de arriba."""
        con_fecha = [c for c in generador.PLANTILLAS if self._fechas(c, self.uno)]
        self.assertGreaterEqual(len(con_fecha), 4)


@falta_plantillas
class LosTresCasosQueLoDestaparon(NingunaFechaQuedaEscritaAMano):
    """Cada reporte, con nombre y apellido, para que no se pierda el porqué."""

    def test_el_acuerdo_toma_el_dia_de_ingreso(self):
        """«ha suscrito en fecha 16 de agosto» — el 16 no se movía nunca."""
        texto = self._texto("confidencialidad", self.dos)
        self.assertIn("ha suscrito en fecha 28 de septiembre de 2026", texto)

    def test_el_corporativo_toma_la_fecha_de_vigencia(self):
        """Decía «entrará en vigencia el 11 de agosto» para todo el mundo."""
        texto = self._texto("corporativo", self.dos)
        self.assertIn("vigencia el 28 de septiembre de 2026", texto)

    def test_y_la_de_culminacion(self):
        """El día y el mes eran fijos; el año miraba al de ingreso."""
        texto = self._texto("corporativo", self.dos)
        self.assertIn("concluirá el 27 de diciembre de 2026", texto)

    def test_el_corporativo_cierra_el_dia_que_corresponde(self):
        """Firmaba siempre «a los 11»."""
        self.assertIn("a los 28 de septiembre de 2026",
                      self._texto("corporativo", self.dos))

    def test_el_acta_de_recibos_imprime_la_fecha(self):
        self.assertIn("28", self._texto("recibo", self.dos))
        self.assertIn("septiembre", self._texto("recibo", self.dos))

    def test_el_contrato_de_trabajo_nunca_estuvo_roto(self):
        """Testigo: ese ya andaba y ninguno de los arreglos podía romperlo."""
        texto = self._texto("contrato", self.dos)
        self.assertIn("vigencia el 28 de septiembre de 2026", texto)
        self.assertIn("concluirá el 27 de diciembre de 2026", texto)
