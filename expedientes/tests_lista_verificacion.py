"""La lista de verificación del expediente (COR-FRM-GEH-005).

Es el único formato que no vino en Word: es un PDF plano y se rellena
escribiendo encima (ver `expedientes/formulario_pdf.py`).

Y es el único que se rellena a medias **a propósito**. Las 29 casillas
☐ SI ☐ NO ☐ N/A quedan vacías: la hoja se imprime y se va tildando a mano
mientras se arma la carpeta, documento por documento. Lo que sí se completa es
el recuadro «SOLO PARA USO DE GESTIÓN HUMANA» del pie —fecha de ingreso,
sueldo, bonos, nombre, cédula, cargo y dependencia—, que son datos que el
sistema ya tiene y que hoy alguien copia a mano de la ficha.

Las dos mitades tienen prueba propia, porque las dos se pueden romper en
sentidos opuestos: que deje de escribir los datos, o que empiece a marcar
casillas que nadie revisó.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import (Cargo, Departamento, Sede, TipoDocumentoIdentidad,
                            Zona)
from expedientes import documentos as generador
from expedientes.formulario_pdf import CAMPOS, FormularioCambio, rellenar_pdf
from expedientes.models import (AsignacionPago, ConceptoPago, Moneda,
                                Trabajador)
from expedientes.tests_documentos import falta_plantillas, texto_pdf

Usuario = get_user_model()
CLAVE = "checklist"
CLAVE_USUARIO = "Clave-De-Prueba-123"

# La casilla de verificación del formulario, tal como está dibujada.
CASILLA = "☐"
CUANTAS_CASILLAS = 29 * 3   # 29 renglones × SI / NO / N/A


class _ConExpediente(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="CENTRO DE DISTRIBUCION GUATIRE I",
                                       zona=zona, ciudad="GUATIRE")
        cls.unidad = Departamento.objects.create(nombre="CENTRO DE DISTRIBUCION")
        cargo = Cargo.objects.create(nombre="AUXILIAR DE ALMACEN",
                                     departamento=cls.unidad)
        cls.ves = Moneda.objects.get(codigo="VES")
        cls.usd = Moneda.objects.get(codigo="USD")
        cls.sueldo = ConceptoPago.objects.get(nombre="Sueldo base")
        cls.bono = ConceptoPago.objects.create(
            nombre="Bono de Alimentación", clase="BONO", moneda=cls.usd, orden=20)
        cls.complemento = ConceptoPago.objects.create(
            nombre="Complemento Alimentación", clase="BONO", moneda=cls.usd,
            orden=30)

        cls.trabajador = Trabajador.objects.create(
            documento_identidad="21104480",
            tipo_documento=TipoDocumentoIdentidad.objects.get(codigo="V"),
            nombres="LEONARDO ALEJANDRO", apellidos="MAVARE",
            sede=cls.sede, departamento=cls.unidad, puesto=cargo,
            fecha_nacimiento=date(1990, 1, 2), fecha_ingreso=date(2026, 8, 24))
        for concepto, monto, moneda in (
                (cls.sueldo, "13068.75", cls.ves),
                (cls.bono, "120.00", cls.usd),
                (cls.complemento, "45.50", cls.usd)):
            AsignacionPago.objects.create(
                trabajador=cls.trabajador, concepto=concepto,
                monto=Decimal(monto), moneda=moneda)

    def hoja(self, trabajador=None):
        datos, _, _ = generador.generar(CLAVE, trabajador or self.trabajador)
        return texto_pdf(datos)


@falta_plantillas
class ElRecuadroDeGestionHumanaSaleCompleto(_ConExpediente):
    """Lo que el sistema ya sabe no se vuelve a copiar a mano."""

    def test_la_fecha_de_ingreso_en_numeros(self):
        self.assertIn("24/08/2026", self.hoja())

    def test_el_nombre_como_lo_pide_el_formulario(self):
        """«Apellidos y Nombre(s)»: primero el apellido."""
        self.assertIn("MAVARE LEONARDO ALEJANDRO", self.hoja())

    def test_la_cedula_con_su_letra(self):
        self.assertIn("V-21104480", self.hoja())

    def test_el_cargo(self):
        self.assertIn("AUXILIAR DE ALMACEN", self.hoja())

    def test_la_dependencia(self):
        self.assertIn("CENTRO DE DISTRIBUCION", self.hoja())

    def test_el_sueldo_en_cifras(self):
        self.assertIn("13.068,75 Bs", self.hoja())

    def test_el_bono_de_alimentacion(self):
        self.assertIn("120,00 $", self.hoja())

    def test_el_complemento_por_separado(self):
        """Son dos conceptos distintos y dos casillas distintas del formulario."""
        self.assertIn("45,50 $", self.hoja())

    def test_no_queda_ningun_campo_sin_completar(self):
        _, _, faltantes = generador.generar(CLAVE, self.trabajador)
        self.assertEqual(faltantes, set())


@falta_plantillas
class LasCasillasSeTildanAMano(_ConExpediente):
    """La mitad que NO se rellena, y que es igual de importante.

    Una lista que viniera con casillas marcadas sería peor que inútil: diría
    que se verificó algo que nadie miró.
    """

    def test_las_29_casillas_siguen_vacias(self):
        self.assertEqual(self.hoja().count(CASILLA), CUANTAS_CASILLAS)

    def test_no_aparece_ninguna_marca(self):
        for marca in ("☑", "☒", "✓", "✔", "X SI"):
            with self.subTest(marca=marca):
                self.assertNotIn(marca, self.hoja())

    def test_las_firmas_quedan_en_blanco(self):
        """Se firman a mano: el sistema no pone nombres donde va una firma.

        Se mira el RECUADRO y no el texto: lo que se escribe encima queda al
        final del PDF, así que buscar «MAVARE después de la palabra Firma» da
        siempre positivo aunque el nombre esté impreso arriba de todo.
        """
        import pymupdf

        datos, _, _ = generador.generar(CLAVE, self.trabajador)
        with pymupdf.open(stream=datos, filetype="pdf") as documento:
            pagina = documento[0]
            etiqueta = pagina.search_for("Firma Analista Responsable:")[0]
            # Hasta el pie de página, que no es parte del recuadro.
            pie = pagina.search_for("USO INTERNO")[0]
            debajo = pymupdf.Rect(etiqueta.x0 - 5, etiqueta.y1 + 1,
                                  pagina.rect.x1, pie.y0 - 2)
            escrito = pagina.get_text("text", clip=debajo).strip()
        self.assertEqual(escrito, "", "hay algo escrito donde van las firmas")

    def test_los_29_renglones_del_formulario_siguen_ahi(self):
        """Testigo: escribir encima no puede tapar ni correr el formato."""
        hoja = self.hoja()
        for renglon in ("Oferta de Servicios", "Síntesis Curricular",
                        "Acuerdo de Confidencialidad", "Foto Carnet",
                        "Documentación Asociada a la Relación de Trabajo"):
            with self.subTest(renglon=renglon):
                self.assertIn(renglon, hoja)

    def test_el_pie_de_uso_interno_sigue_impreso(self):
        self.assertIn("USO INTERNO", self.hoja())


@falta_plantillas
class CadaHojaEsLaDeSuTrabajador(_ConExpediente):
    """Testigo del testigo: que los datos sean del expediente y no del papel.

    Misma disciplina que `tests_fechas_de_los_documentos`: dos personas
    distintas tienen que dar dos hojas distintas. Si algo coincidiera, sería
    porque quedó escrito en la plantilla.
    """

    def otro(self):
        cargo = Cargo.objects.create(nombre="CAJERA", departamento=self.unidad)
        trabajador = Trabajador.objects.create(
            documento_identidad="30111222",
            tipo_documento=TipoDocumentoIdentidad.objects.get(codigo="V"),
            nombres="ANA MARÍA", apellidos="PÉREZ", sede=self.sede,
            departamento=self.unidad, puesto=cargo,
            fecha_nacimiento=date(1995, 5, 5), fecha_ingreso=date(2026, 1, 5))
        AsignacionPago.objects.create(
            trabajador=trabajador, concepto=self.sueldo,
            monto=Decimal("9000.00"), moneda=self.ves)
        return trabajador

    def test_los_datos_cambian_de_una_hoja_a_la_otra(self):
        una, otra = self.hoja(), self.hoja(self.otro())
        for dato in ("24/08/2026", "MAVARE", "21104480", "AUXILIAR DE ALMACEN",
                     "13.068,75 Bs"):
            with self.subTest(dato=dato):
                self.assertIn(dato, una)
                self.assertNotIn(dato, otra)

    def test_y_la_otra_trae_los_suyos(self):
        otra = self.hoja(self.otro())
        for dato in ("05/01/2026", "PÉREZ ANA MARÍA", "V-30111222", "CAJERA",
                     "9.000,00 Bs"):
            with self.subTest(dato=dato):
                self.assertIn(dato, otra)


@falta_plantillas
class LoQueNoEstaCargadoSaleEnBlanco(_ConExpediente):
    """Un expediente a medias imprime igual: los huecos se llenan a mano.

    Es una lista para completar mientras se arma la carpeta, no un contrato:
    negarse a emitirla porque falta el bono dejaría a la analista sin la hoja
    con la que trabaja.
    """

    def setUp(self):
        self.trabajador.pagos.all().delete()
        self.trabajador.departamento = None
        self.trabajador.fecha_ingreso = None
        self.trabajador.save()

    def test_se_genera_igual(self):
        self.assertIn("Oferta de Servicios", self.hoja())

    def test_y_avisa_cuales_quedaron_vacios(self):
        _, _, faltantes = generador.generar(CLAVE, self.trabajador)
        self.assertEqual(
            faltantes,
            {"Fecha_de_ingreso", "Sueldo", "Bono_de_alimentacion",
             "Complemento_alimentacion", "Dependencia"})

    def test_lo_que_si_hay_se_escribe(self):
        """Testigo: que no salga todo en blanco por un campo faltante."""
        self.assertIn("MAVARE LEONARDO ALEJANDRO", self.hoja())


@falta_plantillas
class ElSueldoDiceLoMismoQueElContrato(_ConExpediente):
    """En letras en el contrato, en cifras acá: tiene que ser el mismo número.

    Los dos salen de `_sueldo_vigente`, a propósito. Si cada uno eligiera los
    conceptos por su cuenta, un expediente con sueldo en dos monedas podría
    tener un contrato y una carátula que no coinciden.
    """

    def test_el_mismo_monto_en_los_dos_formatos(self):
        self.assertIn("13.068,75 Bs", self.hoja())
        self.assertIn("TRECE MIL SESENTA Y OCHO",
                      generador.salario_en_letras(self.trabajador))

    def test_con_sueldo_en_divisa_tambien_coinciden(self):
        """Sin bolívares, los dos tienen que caer en la misma moneda."""
        self.trabajador.pagos.filter(concepto=self.sueldo).update(moneda=self.usd)
        self.assertIn("13.068,75 $", self.hoja())
        self.assertIn("DÓLARES", generador.salario_en_letras(self.trabajador))


@falta_plantillas
class SeBuscaPorEtiquetaYNoPorCoordenadas(_ConExpediente):
    """Por qué el relleno no tiene ningún (x, y) escrito en el código.

    El formato lo revisa Gestión Humana —este ya dice «Versión: 01»—. Con
    coordenadas fijas, la próxima versión imprimiría el sueldo encima de otra
    cosa y nadie se enteraría hasta ver una hoja impresa.
    """

    def test_todas_las_etiquetas_se_encuentran_en_el_formulario(self):
        """Si una deja de estar, esta prueba lo dice antes que una impresión."""
        hoja = texto_pdf(generador.ruta_plantilla(CLAVE).read_bytes())
        for etiqueta, _campo in CAMPOS:
            with self.subTest(etiqueta=etiqueta):
                self.assertIn(etiqueta, hoja)

    def test_ninguna_etiqueta_aparece_dos_veces_en_la_hoja(self):
        """Varias son cortas: «Complemento», «C.I.», «Cargo:».

        Arriba hay 29 renglones de texto libre que Gestión Humana reescribe
        cuando revisa el formato. El día que uno de esos renglones repita una
        de estas palabras, el dato se escribiría en la lista de casillas. Esta
        prueba avisa ese día, y no cuando alguien vea la hoja impresa.
        """
        import pymupdf

        with pymupdf.open(generador.ruta_plantilla(CLAVE)) as documento:
            pagina = documento[0]
            for etiqueta, _campo in CAMPOS:
                with self.subTest(etiqueta=etiqueta):
                    self.assertEqual(
                        len(pagina.search_for(etiqueta)), 1,
                        f"«{etiqueta}» dejó de ser única: hay que darle un "
                        "anclaje más largo en formulario_pdf.CAMPOS")

    def test_sin_el_recuadro_se_avisa_en_vez_de_escribir_a_ciegas(self):
        """Testigo: un PDF cualquiera no se rellena «por las dudas»."""
        import tempfile

        import pymupdf

        with tempfile.TemporaryDirectory() as carpeta:
            ruta = f"{carpeta}/otra-cosa.pdf"
            documento = pymupdf.open()
            documento.new_page()
            documento.save(ruta)
            documento.close()
            with self.assertRaises(FormularioCambio):
                rellenar_pdf(ruta, {})


@falta_plantillas
class SeDescargaYSeImprime(_ConExpediente):
    """La hoja se usa impresa: ese camino tiene que funcionar."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = Usuario.objects.create_user(
            username="admin", password=CLAVE_USUARIO, rol=Usuario.Rol.ADMIN)
        cls.mirona = Usuario.objects.create_user(
            username="mirona", password=CLAVE_USUARIO,
            rol=Usuario.Rol.SOLO_LECTURA, acceso_nacional=True)

    def url(self, formato="word"):
        return (reverse("expedientes:documento_generar",
                        args=[self.trabajador.pk, CLAVE]) + f"?formato={formato}")

    def test_aparece_entre_los_documentos_del_expediente(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(
            reverse("expedientes:trabajador_detail",
                    args=[self.trabajador.pk])).content.decode()
        self.assertIn("Lista de verificación del expediente", cuerpo)

    def test_se_descarga_como_pdf(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self.url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF-"))
        self.assertIn("attachment", resp["Content-Disposition"])

    def test_imprimir_la_abre_en_el_navegador(self):
        """Sin bajar nada: el visor del navegador ya trae el botón de imprimir."""
        self.client.force_login(self.admin)
        resp = self.client.get(self.url("imprimir"))
        self.assertIn("inline", resp["Content-Disposition"])
        self.assertEqual(resp["Content-Type"], "application/pdf")

    def test_no_se_convierte_con_word(self):
        """Ya es un PDF: mandarlo a convertir sería pedirle a Word que abra
        un PDF, y en un servidor sin Word el documento no saldría."""
        from unittest.mock import patch

        self.client.force_login(self.admin)
        with patch("expedientes.pdf.convertir_a_pdf") as conversor:
            resp = self.client.get(self.url("pdf"))
        conversor.assert_not_called()
        self.assertTrue(resp.content.startswith(b"%PDF-"))

    def test_solo_lectura_no_la_genera(self):
        """Mismo permiso que los demás documentos: trae sueldos."""
        self.client.force_login(self.mirona)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
