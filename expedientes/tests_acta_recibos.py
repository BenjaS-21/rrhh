"""El cierre del acta de emisión de recibos de pago.

Reporte: «a este formato no le toma la fecha de inicio». El renglón final decía

    En  ROTATIVO______________ a los _____ días del mes de ________ de _____.

Dos cosas mal, las dos heredadas del Word original.

**Donde va la ciudad hay un `MERGEFIELD Horario`.** No es un descuido
inofensivo: el acta salía firmada «En ROTATIVO», que es el turno del
trabajador. Alguien tenía que tacharlo a mano en cada acta.

**La fecha eran tres huecos en blanco.** Estaba decidido así —se completaban al
firmar—, pero el sistema conoce la fecha de ingreso y la imprime en todos los
demás documentos. Dejarla a mano solo acá obliga a buscarla y copiarla, que es
justo lo que el expediente viene a evitar.

Es un .rtf y no un .docx, así que se revisa sobre el texto crudo: en RTF el
texto visible queda partido en grupos, pero cada palabra suelta aparece entera.
"""

from datetime import date

from django.test import TestCase

from cuentas.models import Cargo, Departamento, Sede, Zona
from expedientes import documentos as generador
from expedientes.models import DatosContratacion, Trabajador
from expedientes.tests_documentos import falta_plantillas

CLAVE = "recibo"
HORARIO = "ROTATIVO"


class _ConActa(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(
            nombre="CENTRO DE DISTRIBUCION GUATIRE I", zona=zona,
            ciudad="GUATIRE")
        unidad = Departamento.objects.create(nombre="CENDIS")
        cargo = Cargo.objects.create(nombre="AUXILIAR DE ALMACEN",
                                     departamento=unidad)
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="21104480", nombres="LEONARDO ALEJANDRO",
            apellidos="MAVARE", sede=cls.sede, departamento=unidad, puesto=cargo,
            fecha_nacimiento=date(1990, 1, 2), fecha_ingreso=date(2026, 8, 24))
        DatosContratacion.objects.create(
            trabajador=cls.trabajador, horario=HORARIO)

    def acta(self):
        datos, _, _ = generador.generar(CLAVE, self.trabajador)
        return datos.decode("latin-1", "replace")


@falta_plantillas
class LaFechaDeIngresoSaleImpresa(_ConActa):
    """Lo que pidió el reporte."""

    def test_esta_el_dia(self):
        self.assertIn("24", self.acta())

    def test_esta_el_mes_con_nombre(self):
        self.assertIn("agosto", self.acta())

    def test_esta_el_anio(self):
        self.assertIn("2026", self.acta())

    def test_no_queda_ningun_hueco_para_llenar_a_mano(self):
        """Testigo: si quedara uno, el acta seguiría saliendo incompleta."""
        self.assertNotIn("___", self.acta())

    def test_ningun_campo_se_queda_sin_valor(self):
        _, _, faltantes = generador.generar(CLAVE, self.trabajador)
        self.assertEqual(faltantes, set())


@falta_plantillas
class YDondeIbaElHorarioVaLaCiudad(_ConActa):
    """El acta salía firmada «En ROTATIVO»."""

    def test_ya_no_sale_el_turno(self):
        self.assertNotIn(HORARIO, self.acta())

    def test_sale_la_ciudad_de_la_tienda(self):
        self.assertIn("GUATIRE", self.acta())

    def test_sin_ciudad_cargada_sale_el_estado(self):
        """Nunca en blanco, igual que en el resto de los documentos."""
        self.sede.ciudad = ""
        self.sede.save()
        self.assertIn("MIRANDA", self.acta())

    def test_es_la_misma_que_la_del_contrato(self):
        """Se firman juntos: dos ciudades distintas se leen como un error."""
        from expedientes.tests_documentos import texto_docx
        contrato, _, _ = generador.generar("contrato", self.trabajador)
        self.assertIn("ciudad de GUATIRE", texto_docx(contrato))
        self.assertIn("GUATIRE", self.acta())

    def test_la_plantilla_ya_no_tiene_el_campo_equivocado(self):
        """Testigo del arreglo, sobre la plantilla y no sobre el resultado."""
        ruta = generador.ruta_plantilla(CLAVE)
        crudo = ruta.read_text(encoding="latin-1", errors="replace")
        self.assertNotIn("MERGEFIELD Horario", crudo)
        self.assertIn("MERGEFIELD Ciudad_de_firma", crudo)


@falta_plantillas
class LoQueYaAndabaSigueAndando(_ConActa):
    """Testigos: el acta traía otras dos cosas resueltas y no se tocan."""

    def test_el_nombre_completo(self):
        self.assertIn("MAVARE LEONARDO ALEJANDRO", self.acta())

    def test_la_cedula(self):
        self.assertIn("21104480", self.acta())

    def test_sigue_siendo_un_rtf_que_abre(self):
        crudo = self.acta()
        self.assertTrue(crudo.startswith("{\\rtf"))
        self.assertEqual(crudo.count("{"), crudo.count("}"))
