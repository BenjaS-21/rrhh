"""El PDF de «Imprimir todos» lleva UN contrato, no los dos.

Reporte de quien usa el sistema: «el contrato se me descargan juntos, necesito
un tilde para escoger el contrato corporativo o el general».

El catálogo tiene los dos —contrato de trabajo y contrato corporativo— porque
son para figuras distintas, y el PDF junto los metía a los dos. O sea que la
carpeta salía con un contrato de más, y no es uno cualquiera: es un contrato de
trabajo que no corresponde, impreso y listo para que alguien lo firme.

Cuál va no se puede deducir: no hay ningún dato del expediente que diga con qué
figura entra la persona. Lo sabe quien arma la carpeta, así que se tilda en la
pantalla.

Los dos se siguen pudiendo bajar de a uno, cada uno con su botón: acá se decide
qué va en el juego que se imprime de una.
"""

import unittest
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Cargo, Departamento, Sede, TipoDocumentoIdentidad, Zona
from expedientes import documentos as generador
from expedientes import pdf as conversor
from expedientes.models import (AsignacionPago, ConceptoPago, DatosContratacion,
                                Moneda, RegistroAuditoria, Trabajador)
from expedientes.tests_documentos import falta_plantillas

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"

# Una frase propia de cada contrato. No sirve el título —los dos se llaman
# «CONTRATO INDIVIDUAL DE TRABAJO A TIEMPO DETERMINADO»— ni «EL TRABAJADOR»,
# que también aparece en el acuerdo de confidencialidad. Estas dos se
# comprobaron contra los cinco Word y el RTF: cada una está en un solo
# documento, y en texto fijo, no en un campo que se reemplaza.
DEL_DE_TRABAJO = "descanso semanal rotativo"
DEL_CORPORATIVO = "trabajadora de direcci"


class ElCatalogoSabeQueSonExcluyentes(TestCase):
    """Sin tocar la base ni Word: es la regla, y se lee sola."""

    def test_son_los_dos_contratos(self):
        self.assertEqual(set(generador.CONTRATOS_EXCLUYENTES),
                         {"contrato", "corporativo"})

    def test_el_juego_junto_lleva_uno_solo(self):
        for elegido in generador.CONTRATOS_EXCLUYENTES:
            claves = [c for c, _ in generador.para_imprimir_juntos(elegido)]
            with self.subTest(contrato=elegido):
                self.assertIn(elegido, claves)
                otro = [c for c in generador.CONTRATOS_EXCLUYENTES
                        if c != elegido][0]
                self.assertNotIn(otro, claves)

    def test_y_no_se_pierde_ningun_otro_documento(self):
        """Testigo: elegir un contrato no puede sacar del juego a los demás."""
        for elegido in generador.CONTRATOS_EXCLUYENTES:
            claves = set(c for c, _ in generador.para_imprimir_juntos(elegido))
            faltan = (set(generador.PLANTILLAS)
                      - claves
                      - set(generador.CONTRATOS_EXCLUYENTES))
            with self.subTest(contrato=elegido):
                self.assertEqual(faltan, set())
                self.assertEqual(len(claves), len(generador.PLANTILLAS) - 1)

    def test_el_orden_de_firma_se_conserva(self):
        del_catalogo = [c for c in generador.PLANTILLAS if c != "corporativo"]
        self.assertEqual([c for c, _ in generador.para_imprimir_juntos("contrato")],
                         del_catalogo)

    def test_un_valor_raro_no_deja_la_carpeta_sin_contrato(self):
        """Un `?contrato=` inventado, o vacío, cae en el de siempre."""
        for basura in (None, "", "otro", "CORPORATIVO ", "1"):
            with self.subTest(valor=repr(basura)):
                self.assertEqual(generador.contrato_elegido(basura),
                                 generador.CONTRATO_POR_DEFECTO)

    def test_el_de_siempre_es_uno_de_los_dos(self):
        self.assertIn(generador.CONTRATO_POR_DEFECTO,
                      generador.CONTRATOS_EXCLUYENTES)


class _ConExpediente(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        sede = Sede.objects.create(nombre="TIENDA GUATIRE", zona=zona,
                                   ciudad="GUATIRE")
        unidad = Departamento.objects.create(nombre="ADMINISTRACION")
        puesto = Cargo.objects.create(nombre="ALMACENISTA", departamento=unidad)
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="26045681",
            tipo_documento=TipoDocumentoIdentidad.objects.get(codigo="V"),
            nombres="HENMARY ALEJANDRA", apellidos="GOMEZ RAMOS", sede=sede,
            departamento=unidad, puesto=puesto,
            fecha_nacimiento=date(1995, 4, 12), fecha_ingreso=date(2026, 8, 3))
        DatosContratacion.objects.create(
            trabajador=cls.trabajador, estado_civil="SOLTERO(A)",
            direccion="URB LOS NARANJOS", ciudad_nacimiento="GUATIRE",
            horario="8:00AM a 5:00PM", motivo_contratacion="Temporada",
            ciudad_firma="GUATIRE", fecha_culminacion=date(2026, 11, 22))
        AsignacionPago.objects.create(
            trabajador=cls.trabajador, concepto=ConceptoPago.objects.first(),
            monto=Decimal("130.00"), moneda=Moneda.objects.get(codigo="VES"))
        cls.admin = Usuario.objects.create_user(
            username="diana", password=CLAVE, rol=Usuario.Rol.ADMIN)

    def setUp(self):
        self.client.force_login(self.admin)

    def url(self, contrato=None):
        base = reverse("expedientes:documentos_todos", args=[self.trabajador.pk])
        return f"{base}?contrato={contrato}" if contrato else base


@falta_plantillas
class ElTildeEstaEnLaPantalla(_ConExpediente):

    def cuerpo(self):
        return self.client.get(
            reverse("expedientes:trabajador_detail",
                    args=[self.trabajador.pk])).content.decode()

    @unittest.skipUnless(conversor.hay_conversor(), "sin Word no hay botón")
    def test_hay_una_opcion_por_contrato(self):
        cuerpo = self.cuerpo()
        for valor in generador.CONTRATOS_EXCLUYENTES:
            with self.subTest(contrato=valor):
                self.assertIn(f'name="contrato" value="{valor}"', cuerpo)

    @unittest.skipUnless(conversor.hay_conversor(), "sin Word no hay botón")
    def test_viajan_con_el_boton_de_imprimir_todos(self):
        """Si el tilde quedara fuera del formulario, elegir no haría nada."""
        cuerpo = self.cuerpo()
        formulario = cuerpo.split(self.url())[1].split("</form>")[0]
        self.assertIn('name="contrato"', formulario)
        self.assertIn("Imprimir todos", formulario)

    @unittest.skipUnless(conversor.hay_conversor(), "sin Word no hay botón")
    def test_viene_uno_tildado(self):
        """Un tilde sin nada marcado deja imprimir sin contrato ninguno."""
        self.assertIn("checked", self.cuerpo())

    @unittest.skipUnless(conversor.hay_conversor(), "sin Word no hay botón")
    def test_los_dos_se_siguen_bajando_de_a_uno(self):
        """Testigo: elegir para el juego junto no puede esconder ninguno de
        los botones de a uno."""
        cuerpo = self.cuerpo()
        for clave in generador.CONTRATOS_EXCLUYENTES:
            with self.subTest(documento=clave):
                self.assertIn(f"documentos/{clave}/", cuerpo)


@falta_plantillas
@unittest.skipUnless(conversor.hay_conversor(),
                     "Esta máquina no tiene Word: no se pueden juntar en PDF.")
class EnElPdfVaSoloElElegido(_ConExpediente):

    def texto(self, contrato=None):
        import pymupdf
        import re

        resp = self.client.get(self.url(contrato))
        self.assertEqual(resp.status_code, 200)
        with pymupdf.open(stream=resp.content, filetype="pdf") as doc:
            crudo = "\n".join(p.get_text() for p in doc)
        return re.sub(r"\s+", " ", crudo)

    def test_tildando_el_corporativo_no_va_el_de_trabajo(self):
        texto = self.texto("corporativo")
        self.assertIn(DEL_CORPORATIVO, texto)
        self.assertNotIn(DEL_DE_TRABAJO, texto)

    def test_tildando_el_de_trabajo_no_va_el_corporativo(self):
        texto = self.texto("contrato")
        self.assertIn(DEL_DE_TRABAJO, texto)
        self.assertNotIn(DEL_CORPORATIVO, texto)

    def test_los_demas_documentos_van_igual(self):
        """Testigo: sacar un contrato no puede vaciar la carpeta."""
        for contrato in generador.CONTRATOS_EXCLUYENTES:
            texto = self.texto(contrato)
            with self.subTest(contrato=contrato):
                for frase in ("confidencialidad", "beneficios",
                              "LISTA DE VERIFICACIÓN"):
                    self.assertIn(frase.lower(), texto.lower())

    def test_sale_mas_corto_que_con_los_dos(self):
        """Medida indirecta y directa a la vez: si siguiera metiendo los dos,
        el PDF tendría las páginas de los dos contratos."""
        import pymupdf

        def paginas(contrato):
            resp = self.client.get(self.url(contrato))
            with pymupdf.open(stream=resp.content, filetype="pdf") as doc:
                return len(doc)

        uno = paginas("contrato")
        otro = paginas("corporativo")
        juntos_de_antes = uno + otro
        self.assertLess(uno, juntos_de_antes)
        self.assertLess(otro, juntos_de_antes)

    def test_el_nombre_del_archivo_dice_cual_lleva(self):
        """Se imprimen los dos juegos en una tanda mixta: dos PDF con el mismo
        nombre en Descargas no se distinguen."""
        for contrato, esperado in (("contrato", "contrato de trabajo"),
                                   ("corporativo", "corporativo")):
            resp = self.client.get(self.url(contrato))
            with self.subTest(contrato=contrato):
                self.assertIn(esperado, resp["Content-Disposition"])

    def test_la_auditoria_guarda_con_cual_salio(self):
        """Es un contrato de trabajo: qué se imprimió tiene que quedar."""
        self.client.get(self.url("corporativo"))
        ultimo = RegistroAuditoria.objects.latest("id")
        self.assertIn("corporativo", ultimo.descripcion)

    def test_sin_elegir_sale_el_de_siempre(self):
        """El botón tiene que seguir andando de un clic."""
        texto = self.texto()
        self.assertIn(DEL_DE_TRABAJO, texto)
        self.assertNotIn(DEL_CORPORATIVO, texto)
