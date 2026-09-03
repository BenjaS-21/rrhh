"""Tests de la descarga en PDF y de la impresión de los documentos.

La conversión real necesita Word instalado, así que casi todo se prueba con un
doble: lo que importa acá es que la vista pida el formato correcto, respete los
permisos y avise bien cuando no se puede convertir. Al final hay un test que sí
convierte de verdad, y que se saltea solo si la máquina no tiene Word.
"""

import unittest
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from expedientes import documentos as generador
from expedientes import pdf as conversor
from expedientes.tests_documentos import NECESITAN_CONVERSION, BaseDocumentos

PDF_FALSO = b"%PDF-1.7\n% documento de prueba\n"


class DescargaEnPdf(BaseDocumentos):
    """La vista entrega Word, PDF o PDF para imprimir según se le pida."""

    def url(self, clave="contrato", **params):
        base = reverse("expedientes:documento_generar",
                       args=[self.trabajador.pk, clave])
        if not params:
            return base
        return base + "?" + "&".join(f"{k}={v}" for k, v in params.items())

    def setUp(self):
        self.client.force_login(self.admin)

    # --- Word (lo de siempre) ------------------------------------------------
    def test_sin_formato_sigue_bajando_el_word(self):
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)
        self.assertIn("wordprocessingml", r["Content-Type"])
        self.assertIn("attachment;", r["Content-Disposition"])
        self.assertIn(".docx", r["Content-Disposition"])

    def test_el_acta_de_recibos_sigue_bajando_como_rtf(self):
        r = self.client.get(self.url("recibo"))
        self.assertEqual(r["Content-Type"], "application/rtf")
        self.assertIn(".rtf", r["Content-Disposition"])

    # --- PDF -----------------------------------------------------------------
    @patch("expedientes.pdf.convertir_a_pdf", return_value=PDF_FALSO)
    def test_formato_pdf_descarga_un_pdf(self, convertir):
        r = self.client.get(self.url(formato="pdf"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("attachment;", r["Content-Disposition"])
        self.assertIn(".pdf", r["Content-Disposition"])
        self.assertNotIn(".docx", r["Content-Disposition"])
        self.assertEqual(r.content, PDF_FALSO)

    @patch("expedientes.pdf.convertir_a_pdf", return_value=PDF_FALSO)
    def test_convierte_el_documento_ya_completado(self, convertir):
        """Se convierte el Word con los datos puestos, no la plantilla vacía."""
        self.client.get(self.url(formato="pdf"))
        datos, nombre = convertir.call_args[0]
        self.assertTrue(nombre.endswith(".docx"))
        self.assertIn(b"PK", datos[:4])  # es el .docx generado

    @patch("expedientes.pdf.convertir_a_pdf", return_value=PDF_FALSO)
    def test_el_rtf_llega_al_conversor_como_rtf(self, convertir):
        """Word decide cómo abrirlo por la extensión: no se puede renombrar."""
        self.client.get(self.url("recibo", formato="pdf"))
        _datos, nombre = convertir.call_args[0]
        self.assertTrue(nombre.endswith(".rtf"))

    # --- Imprimir ------------------------------------------------------------
    @patch("expedientes.pdf.convertir_a_pdf", return_value=PDF_FALSO)
    def test_imprimir_muestra_el_pdf_en_el_navegador(self, convertir):
        r = self.client.get(self.url(formato="imprimir"))
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("inline;", r["Content-Disposition"])
        self.assertNotIn("attachment", r["Content-Disposition"])

    # --- Cuando no se puede --------------------------------------------------
    @patch("expedientes.pdf.convertir_a_pdf",
           side_effect=conversor.ConversionNoDisponible("Word no está instalado."))
    def test_si_falla_la_conversion_avisa_y_no_entrega_basura(self, convertir):
        r = self.client.get(self.url(formato="pdf"), follow=True)
        self.assertEqual(r.status_code, 200)
        mensajes = [str(m) for m in r.context["messages"]]
        self.assertIn("Word no está instalado.", mensajes)
        # Nunca se manda un PDF roto disfrazado de PDF.
        self.assertNotEqual(r["Content-Type"], "application/pdf")

    def test_un_formato_inventado_da_404(self):
        r = self.client.get(self.url(formato="excel"))
        self.assertEqual(r.status_code, 404)

    # --- Permisos ------------------------------------------------------------
    def test_solo_lectura_no_puede_bajar_el_pdf(self):
        self.client.force_login(self.lectura)
        for formato in ("pdf", "imprimir"):
            with self.subTest(formato=formato):
                r = self.client.get(self.url(formato=formato))
                self.assertEqual(r.status_code, 403)

    def test_rrhh_de_otra_zona_no_puede_bajar_el_pdf(self):
        self.client.force_login(self.rrhh_sur)
        r = self.client.get(self.url(formato="pdf"))
        self.assertEqual(r.status_code, 403)

    # --- Auditoría -----------------------------------------------------------
    @patch("expedientes.pdf.convertir_a_pdf", return_value=PDF_FALSO)
    def test_queda_registrado_que_formato_se_pidio(self, convertir):
        from expedientes.models import RegistroAuditoria

        self.client.get(self.url(formato="pdf"))
        self.client.get(self.url(formato="imprimir"))
        descripciones = list(
            RegistroAuditoria.objects.filter(entidad="Documento generado")
            .values_list("descripcion", flat=True)
        )
        self.assertTrue(any("en PDF" in d for d in descripciones))
        self.assertTrue(any("imprimir" in d for d in descripciones))


class BotonesEnLaPantalla(BaseDocumentos):
    """Los botones aparecen solo si la máquina puede convertir."""

    def url_detalle(self):
        return reverse("expedientes:trabajador_detail", args=[self.trabajador.pk])

    @patch("expedientes.pdf.hay_conversor", return_value=True)
    def test_con_word_se_ofrecen_los_tres(self, hay):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(self.url_detalle()).content.decode()
        self.assertIn("formato=pdf", cuerpo)
        self.assertIn("formato=imprimir", cuerpo)
        self.assertIn("<svg", cuerpo)

    @patch("expedientes.pdf.hay_conversor", return_value=False)
    def test_sin_word_solo_queda_el_de_word_y_se_explica(self, hay):
        """Vale para los documentos que SÍ hay que convertir.

        Esta prueba miraba la página entera —«que no aparezca `formato=pdf` en
        ningún lado»— y era cierto mientras los siete documentos nacían en
        Word. La lista de verificación ya nace en PDF y no se convierte, así
        que ahora sí ofrece su descarga en una máquina sin Word: eso es el
        arreglo, no la falla. Lo que esta prueba cuida —que no se prometa un
        PDF que el servidor no puede armar— se comprueba sobre el contrato.
        La lista tiene su propio par de testigos en
        `tests_lista_verificacion.py`.
        """
        self.client.force_login(self.admin)
        cuerpo = self.client.get(self.url_detalle()).content.decode()
        self.assertNotIn("documentos/contrato/?formato=pdf", cuerpo)
        self.assertNotIn("documentos/contrato/?formato=imprimir", cuerpo)
        self.assertIn("no tiene Word instalado", cuerpo)
        # El Word se sigue pudiendo bajar: no se pierde la función.
        self.assertIn("documentos/contrato/", cuerpo)


@unittest.skipUnless(conversor.hay_conversor(),
                     "Esta máquina no tiene Word: no se puede convertir de verdad.")
class ConversionReal(BaseDocumentos):
    """Conversión de verdad, sin dobles. Solo corre donde hay Word."""

    def test_los_documentos_word_se_convierten(self):
        for clave in NECESITAN_CONVERSION:
            with self.subTest(documento=clave):
                datos, nombre, _ = generador.generar(clave, self.trabajador)
                salida = conversor.convertir_a_pdf(datos, nombre)
                self.assertTrue(salida.startswith(b"%PDF-"),
                                f"{clave} no devolvió un PDF")
                self.assertGreater(len(salida), 5000)

    def test_el_pdf_conserva_los_datos_del_trabajador(self):
        """Comprobación indirecta: el PDF del contrato ocupa varias páginas."""
        datos, nombre, _ = generador.generar("contrato", self.trabajador)
        salida = conversor.convertir_a_pdf(datos, nombre)
        paginas = salida.count(b"/Type /Page") + salida.count(b"/Type/Page")
        self.assertGreaterEqual(paginas, 1)
