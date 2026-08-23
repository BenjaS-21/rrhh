"""El lugar que sale impreso en los documentos.

Viene de un reporte con la autorización de ingreso en la mano: alguien que
entra al CENTRO DE DISTRIBUCION GUATIRE I recibía una carta encabezada
«Caracas, 24 de agosto de 2026». Y la carta va dirigida al gerente de esa misma
tienda, que lee una ciudad que no es la suya.

Eran dos cosas superpuestas:

1. En la carta, «Caracas, » estaba escrito fijo en el Word. La fecha sí era un
   campo; la ciudad no. Así que TODAS las autorizaciones decían Caracas.
2. `ciudad_firma` del expediente venía con `default="CARACAS"`, así que los
   contratos —que sí tenían el campo— también imprimían Caracas para todos.

Ahora el lugar sale de una cadena: lo que diga el expediente, si alguien lo
escribió porque se firmó en otro lado; si no, la ciudad de la tienda; y si esa
no está cargada, la zona, que es el estado. Nunca queda en blanco.

Lo que NO se toca, y tiene su propia prueba: las cláusulas de jurisdicción
—«domicilio especial a la ciudad de CARACAS, a la Jurisdicción de cuyos
Tribunales»—. Ahí Caracas no es un lugar, es a qué tribunal se someten las
partes. Cambiarlo sería cambiar el contrato.
"""

import unittest
from datetime import date

from django.test import TestCase

from cuentas.models import Cargo, Departamento, Sede, Zona
from expedientes import documentos as generador
from expedientes.models import DatosContratacion, Trabajador
from expedientes.tests_documentos import falta_plantillas, texto_docx


class LaTiendaSabeDondeEsta(TestCase):

    def setUp(self):
        self.zona = Zona.objects.create(nombre="MIRANDA")
        self.sede = Sede.objects.create(
            nombre="CENTRO DE DISTRIBUCION GUATIRE I", zona=self.zona)

    def test_sin_ciudad_cargada_vale_la_zona(self):
        """Nunca en blanco: «, 24 de agosto» se ve peor que el estado."""
        self.assertEqual(self.sede.lugar, "MIRANDA")

    def test_con_la_ciudad_cargada_vale_la_ciudad(self):
        self.sede.ciudad = "GUATIRE"
        self.assertEqual(self.sede.lugar, "GUATIRE")

    def test_los_espacios_sueltos_no_cuentan_como_ciudad(self):
        """Un campo con un espacio dejaría el documento encabezado con nada."""
        self.sede.ciudad = "   "
        self.assertEqual(self.sede.lugar, "MIRANDA")

    def test_se_carga_desde_configuracion(self):
        from configuracion.forms import SedeForm
        self.assertIn("ciudad", SedeForm.base_fields)

    def test_y_se_ve_en_el_listado_de_tiendas(self):
        """Se muestra el lugar y no el campo: así se ve cuál va a salir impresa."""
        from configuracion.views import CATALOGOS
        etiquetas = [c[0] for c in CATALOGOS["tiendas"]["columnas"]]
        self.assertIn("Ciudad", etiquetas)


class _ConTrabajador(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(
            nombre="CENTRO DE DISTRIBUCION GUATIRE I", zona=cls.zona)
        unidad = Departamento.objects.create(nombre="CENDIS")
        cargo = Cargo.objects.create(nombre="AUXILIAR DE ALMACEN",
                                     departamento=unidad)
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="21104480", nombres="LEONARDO ALEJANDRO",
            apellidos="MAVARE", sede=cls.sede, departamento=unidad, puesto=cargo,
            fecha_nacimiento=date(1990, 1, 2), fecha_ingreso=date(2026, 8, 24))

    def lugar(self):
        return generador.contexto_documentos(self.trabajador)["Ciudad_de_firma"]


class DeDondeSaleElLugar(_ConTrabajador):

    def test_sin_datos_de_contratacion_sale_el_de_la_tienda(self):
        self.sede.ciudad = "GUATIRE"
        self.sede.save()
        self.assertEqual(self.lugar(), "GUATIRE")

    def test_sin_ciudad_en_la_tienda_sale_el_estado(self):
        self.assertEqual(self.lugar(), "MIRANDA")

    def test_lo_escrito_en_el_expediente_manda(self):
        """Si de verdad se firmó en otra ciudad, se escribe y gana."""
        self.sede.ciudad = "GUATIRE"
        self.sede.save()
        DatosContratacion.objects.create(
            trabajador=self.trabajador, ciudad_firma="CARACAS")
        self.assertEqual(self.lugar(), "CARACAS")

    def test_pero_vacio_no_tapa_al_de_la_tienda(self):
        """Testigo: el expediente casi siempre lo tiene vacío."""
        self.sede.ciudad = "GUATIRE"
        self.sede.save()
        DatosContratacion.objects.create(
            trabajador=self.trabajador, ciudad_firma="")
        self.assertEqual(self.lugar(), "GUATIRE")

    def test_el_campo_del_expediente_ya_no_nace_diciendo_caracas(self):
        """La causa de fondo: venía con `default="CARACAS"` para todo el país."""
        datos = DatosContratacion.objects.create(trabajador=self.trabajador)
        self.assertEqual(datos.ciudad_firma, "")

    def test_nunca_queda_vacio(self):
        """Un documento encabezado «, 24 de agosto de 2026» no se puede firmar."""
        self.assertTrue(self.lugar().strip())


@falta_plantillas
class EnLosDocumentosDeVerdad(_ConTrabajador):

    def cuerpo(self, clave):
        datos, nombre, _ = generador.generar(clave, self.trabajador)
        return texto_docx(datos)

    def test_la_autorizacion_ya_no_dice_caracas(self):
        """El reporte, textual: la carta de Guatire encabezada en Caracas."""
        self.assertNotIn("Caracas", self.cuerpo("carta"))

    def test_dice_el_estado_cuando_no_hay_ciudad(self):
        self.assertIn("MIRANDA, 24 de agosto de 2026", self.cuerpo("carta"))

    def test_y_la_ciudad_cuando_esta_cargada(self):
        self.sede.ciudad = "GUATIRE"
        self.sede.save()
        self.assertIn("GUATIRE, 24 de agosto de 2026", self.cuerpo("carta"))

    def test_el_contrato_corporativo_cierra_en_el_mismo_lugar(self):
        self.sede.ciudad = "GUATIRE"
        self.sede.save()
        self.assertIn("ciudad de GUATIRE", self.cuerpo("corporativo"))

    def test_y_el_contrato_de_trabajo_tambien(self):
        self.sede.ciudad = "GUATIRE"
        self.sede.save()
        self.assertIn("ciudad de GUATIRE", self.cuerpo("contrato"))


@falta_plantillas
class LasClausulasLegalesNoSeTocan(_ConTrabajador):
    """Caracas aparece en los contratos por dos motivos distintos.

    Uno es un lugar —dónde se firma— y se cambia. El otro es una elección
    legal: a qué tribunales se someten las partes. Reemplazar el segundo por la
    ciudad de la tienda cambiaría la jurisdicción del contrato sin que nadie lo
    haya decidido.
    """

    def cuerpo(self, clave):
        self.sede.ciudad = "GUATIRE"
        self.sede.save()
        datos, _, _ = generador.generar(clave, self.trabajador)
        return texto_docx(datos)

    def test_el_domicilio_especial_sigue_siendo_caracas(self):
        self.assertIn("domicilio especial a la ciudad de CARACAS",
                      self.cuerpo("contrato"))

    def test_y_en_el_corporativo_tambien(self):
        self.assertIn("domicilio especial a la ciudad de CARACAS",
                      self.cuerpo("corporativo"))

    def test_pero_el_lugar_de_firma_del_mismo_documento_si_cambio(self):
        """Testigo del testigo: los dos conviven en la misma hoja."""
        cuerpo = self.cuerpo("contrato")
        self.assertIn("ciudad de GUATIRE a los", cuerpo)
        self.assertIn("Jurisdicción de cuyos Tribunales", cuerpo)


@falta_plantillas
class ElDiaDelCierreDelContratoCorporativo(_ConTrabajador):
    """El corporativo se firmaba siempre «a los 11».

    El cierre dice «en la ciudad de X a los N de MES de AÑO». El mes y el año
    eran campos; el día había quedado escrito a mano en el Word. El contrato de
    trabajo sí traía el campo, así que pasaba solo en el corporativo — y con el
    mes correcto al lado, que lo hace más difícil de notar.
    """

    def cuerpo(self):
        datos, _, _ = generador.generar("corporativo", self.trabajador)
        return texto_docx(datos)

    def test_sale_el_dia_de_ingreso(self):
        self.assertIn("a los 24 de agosto de 2026", self.cuerpo())

    def test_y_no_el_que_traia_la_plantilla(self):
        self.assertNotIn("a los 11 de agosto", self.cuerpo())

    def test_el_contrato_de_trabajo_sigue_bien(self):
        """Testigo: ese ya andaba, el arreglo no puede romperlo."""
        datos, _, _ = generador.generar("contrato", self.trabajador)
        self.assertIn("a los 24 de agosto de 2026", texto_docx(datos))


@falta_plantillas
class LosDocumentosQueSeFirmanJuntosDicenLoMismo(_ConTrabajador):
    """Dos papeles del mismo día con dos ciudades distintas se leen como error.

    El contrato, el acuerdo de confidencialidad y la carta se firman en la
    misma reunión. El acuerdo también traía «En Caracas,» escrito fijo.
    """

    def setUp(self):
        self.sede.ciudad = "GUATIRE"
        self.sede.save()

    def cuerpo(self, clave):
        datos, _, _ = generador.generar(clave, self.trabajador)
        return texto_docx(datos)

    def test_el_acuerdo_de_confidencialidad_tambien(self):
        self.assertIn("En GUATIRE, 24 de agosto de 2026",
                      self.cuerpo("confidencialidad"))

    def test_y_ya_no_dice_en_caracas(self):
        self.assertNotIn("En Caracas,", self.cuerpo("confidencialidad"))

    def test_pero_su_clausula_de_jurisdiccion_sigue_intacta(self):
        """Testigo: ahí Caracas también es la jurisdicción, no un lugar."""
        self.assertIn("a la ciudad de Caracas y a la Jurisdicción",
                      self.cuerpo("confidencialidad"))

    def test_los_tres_coinciden(self):
        lugares = set()
        for clave in ("carta", "contrato", "confidencialidad", "corporativo"):
            cuerpo = self.cuerpo(clave)
            self.assertIn("GUATIRE", cuerpo, f"{clave} no dice la ciudad")
            lugares.add("GUATIRE")
        self.assertEqual(lugares, {"GUATIRE"})
