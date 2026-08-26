"""El botón «Comprimir aquí y subir» de la pantalla de carga.

Los escaneos que manda una tienda a veces pasan los 20 MB: hasta acá la única
salida era volver a escanear con menos calidad. Ahora el cartel ofrece
comprimirlo ahí mismo: las imágenes se achican en el navegador y los PDF
viajan una sola vez al servidor, que los redibuja página por página.

Acá se prueba la mitad servidor de ese arreglo:
  - que un PDF pesado quede por debajo del tope y siga siendo un PDF legible,
    con las mismas páginas;
  - que una imagen pesada quede como JPEG;
  - que la ruta de compresión sea la ÚNICA que admite un cuerpo más grande
    (el resto del sistema sigue cortando temprano);
  - que los permisos sean los mismos que para subir.
"""

import os
import random
from io import BytesIO

import pymupdf
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from configuracion.models import Preferencias
from cuentas.models import Sede, Zona
from expedientes.models import (
    Documento, RegistroAuditoria, TipoDocumento, Trabajador,
)

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"

TOPE = 1_000_000  # DOCUMENTOS_MAX_BYTES de mentira, para que las pruebas vuelen.


def _imagen_ruido(ancho, alto, formato="JPEG", calidad=95):
    """Una imagen que pesa: el ruido no se deja comprimir, como un escaneo."""
    azar = random.Random(42)
    pixeles = bytes(azar.randrange(256) for _ in range(ancho * alto * 3))
    imagen = Image.frombytes("RGB", (ancho, alto), pixeles)
    salida = BytesIO()
    imagen.save(salida, format=formato, quality=calidad)
    return salida.getvalue()


def _pdf_pesado(paginas=3):
    """Un PDF de escaneos grandes, armado como los que manda una tienda."""
    doc = pymupdf.open()
    for _ in range(paginas):
        pagina = doc.new_page(width=595, height=842)  # A4 en puntos
        pagina.insert_image(pagina.rect, stream=_imagen_ruido(1600, 2200))
    salida = BytesIO()
    doc.save(salida)
    doc.close()
    return salida.getvalue()


@override_settings(DOCUMENTOS_MAX_BYTES=TOPE)
class _ConExpediente(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.zona = Zona.objects.create(nombre="MIRANDA")
        sede = Sede.objects.create(nombre="TRINIDAD", zona=cls.zona)
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="V-30719983", nombres="Benjamin",
            apellidos="Velazco", sede=sede)
        cls.tipo = TipoDocumento.objects.create(nombre="Cédula", orden=1)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def comprimir(self, contenido, nombre):
        self.client.force_login(self.admin)
        return self.client.post(
            reverse("expedientes:documento_comprimir", args=[self.trabajador.pk]),
            {"tipo": self.tipo.pk,
             "archivo": SimpleUploadedFile(nombre, contenido)},
            headers={"x-requested-with": "XMLHttpRequest"})


class UnPdfPesadoQuedaLiviano(_ConExpediente):

    def test_se_guarda_por_debajo_del_tope(self):
        pesado = _pdf_pesado()
        self.assertGreater(len(pesado), TOPE)  # testigo: era pesado de verdad
        r = self.comprimir(pesado, "escaneo.pdf")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["ok"])
        doc = Documento.objects.get()
        self.assertLessEqual(doc.tamano_bytes, TOPE)

    def test_el_resultado_es_un_pdf_legible_con_las_mismas_paginas(self):
        self.comprimir(_pdf_pesado(paginas=3), "escaneo.pdf")
        doc = Documento.objects.get()
        datos = doc.archivo.storage.leer_descifrado(doc.archivo.name)
        self.assertTrue(datos.startswith(b"%PDF-"))
        with pymupdf.open(stream=datos, filetype="pdf") as rearmado:
            self.assertEqual(rearmado.page_count, 3)

    def test_queda_en_la_auditoria_con_los_pesos(self):
        self.comprimir(_pdf_pesado(), "escaneo.pdf")
        asiento = RegistroAuditoria.objects.filter(
            accion=RegistroAuditoria.Accion.SUBIR).get()
        self.assertIn("comprimido", asiento.descripcion)
        self.assertIn("MB", asiento.descripcion)

    def test_versiona_como_cualquier_subida(self):
        self.comprimir(_pdf_pesado(), "a.pdf")
        self.comprimir(_pdf_pesado(), "b.pdf")
        self.assertEqual(
            sorted(Documento.objects.values_list("version", flat=True)), [1, 2])


class UnaImagenPesadaQuedaComoJpeg(_ConExpediente):

    def test_se_guarda_por_debajo_del_tope_y_cambia_la_extension(self):
        pesada = _imagen_ruido(3000, 2000, formato="PNG")
        self.assertGreater(len(pesada), TOPE)
        r = self.comprimir(pesada, "foto.png")
        self.assertTrue(r.json()["ok"], r.content)
        doc = Documento.objects.get()
        self.assertLessEqual(doc.tamano_bytes, TOPE)
        self.assertTrue(doc.nombre_original.endswith(".jpg"))
        datos = doc.archivo.storage.leer_descifrado(doc.archivo.name)
        self.assertTrue(datos.startswith(b"\xff\xd8\xff"))  # JPEG de verdad


class LoQueNoSePuedeSeRechaza(_ConExpediente):

    def test_un_tipo_de_archivo_sin_compresion(self):
        r = self.comprimir(b"contenido", "carta.docx")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])
        self.assertEqual(Documento.objects.count(), 0)

    def test_un_pdf_que_no_es_pdf(self):
        r = self.comprimir(b"esto no es un pdf", "tramposo.pdf")
        self.assertEqual(r.status_code, 400)
        self.assertIn("PDF", r.json()["error"])
        self.assertEqual(Documento.objects.count(), 0)

    def test_sin_archivo(self):
        self.client.force_login(self.admin)
        r = self.client.post(
            reverse("expedientes:documento_comprimir", args=[self.trabajador.pk]),
            {"tipo": self.tipo.pk},
            headers={"x-requested-with": "XMLHttpRequest"})
        self.assertEqual(r.status_code, 400)


class LosPermisosSonLosDeSiempre(_ConExpediente):

    def test_solo_lectura_no_puede(self):
        lectura = Usuario.objects.create_user(username="lec", password=CLAVE)
        lectura.rol = Usuario.Rol.SOLO_LECTURA
        lectura.save()
        self.client.force_login(lectura)
        r = self.client.post(
            reverse("expedientes:documento_comprimir", args=[self.trabajador.pk]),
            {"tipo": self.tipo.pk,
             "archivo": SimpleUploadedFile("a.pdf", _pdf_pesado())})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Documento.objects.count(), 0)

    def test_otra_zona_no_puede(self):
        Preferencias.obtener()
        Preferencias.objects.filter(pk=1).update(restringir_por_zona=True)
        otra_zona = Zona.objects.create(nombre="LARA")
        de_otra_zona = Usuario.objects.create_user(username="lar", password=CLAVE)
        de_otra_zona.rol = Usuario.Rol.RRHH_INTERIOR
        de_otra_zona.zona = otra_zona
        de_otra_zona.save()
        self.client.force_login(de_otra_zona)
        r = self.client.post(
            reverse("expedientes:documento_comprimir", args=[self.trabajador.pk]),
            {"tipo": self.tipo.pk,
             "archivo": SimpleUploadedFile("a.pdf", _pdf_pesado())})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Documento.objects.count(), 0)


class LaRutaDeComprimirEsLaUnicaExcepcion(_ConExpediente):
    """Para comprimir hay que recibir el archivo; para todo lo demás, no."""

    @override_settings(SUBIDA_MAX_BYTES=2_000,
                       COMPRESION_MAX_BYTES=50_000_000)
    def test_a_comprimir_si_la_deja_pasar(self):
        r = self.comprimir(_pdf_pesado(), "escaneo.pdf")
        self.assertTrue(r.json()["ok"], r.content)
        self.assertEqual(Documento.objects.count(), 1)

    @override_settings(SUBIDA_MAX_BYTES=2_000,
                       COMPRESION_MAX_BYTES=50_000_000)
    def test_a_subir_la_sigue_cortando(self):
        """Testigo: la excepción no abrió la puerta para las demás rutas."""
        self.client.force_login(self.admin)
        r = self.client.post(
            reverse("expedientes:documento_subir", args=[self.trabajador.pk]),
            {"tipo": self.tipo.pk,
             "archivo": SimpleUploadedFile("a.pdf", os.urandom(50_000))},
            headers={"x-requested-with": "XMLHttpRequest"})
        self.assertEqual(r.status_code, 413)
        self.assertEqual(Documento.objects.count(), 0)


class LaPantallaOfreceLaOpcion(_ConExpediente):

    def test_el_formulario_sabe_a_donde_mandar_lo_pesado(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(
            reverse("expedientes:trabajador_detail",
                    args=[self.trabajador.pk])).content.decode()
        self.assertIn("data-comprimir-url=", cuerpo)
        self.assertIn(
            reverse("expedientes:documento_comprimir", args=[self.trabajador.pk]),
            cuerpo)
