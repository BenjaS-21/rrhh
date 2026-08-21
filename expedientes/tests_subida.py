"""Subir un documento sin voltear el servidor.

Viene de un reporte: «cuando quieren subir un archivo el sistema deja de
responder y se cae». No era el tamaño del disco ni la base: era la memoria.
Fernet cifra sobre bytes en memoria, así que cifrar un archivo entero de una
vez pedía casi siete veces su tamaño en RAM —100 MB de archivo, 670 MB de
pico—, y encima no había ningún límite de tamaño. Dos subidas grandes al mismo
tiempo y el proceso se quedaba sin aire.

Se probaron tres cosas, que son las tres mitades del arreglo:
  - que el archivo vuelva a salir igual que como entró, incluidos los que ya
    estaban guardados con el formato viejo;
  - que la memoria NO dependa del tamaño del archivo;
  - que un archivo demasiado grande se rechace, y se rechace temprano.
"""

import os
import shutil
import struct
import tempfile
import tracemalloc

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from cuentas.models import Sede, Zona
from expedientes.models import Documento, TipoDocumento, Trabajador
from expedientes.storage import CABECERA, AlmacenamientoCifrado, _get_fernet

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class _ConAlmacen(SimpleTestCase):
    """Un almacén cifrado sobre una carpeta de paso."""

    def setUp(self):
        self.carpeta = tempfile.mkdtemp(prefix="gde-storage-")
        self.addCleanup(shutil.rmtree, self.carpeta, ignore_errors=True)
        self.almacen = AlmacenamientoCifrado(location=self.carpeta)

    def crudo(self, nombre):
        """Los bytes tal cual quedaron en disco, sin descifrar."""
        with open(os.path.join(self.carpeta, nombre), "rb") as f:
            return f.read()


class ElArchivoVuelveIgual(_ConAlmacen):

    def test_uno_chico(self):
        nombre = self.almacen.save("chico.pdf", ContentFile(b"una cedula"))
        self.assertEqual(self.almacen.leer_descifrado(nombre), b"una cedula")

    def test_uno_de_varios_bloques(self):
        """El corte en bloques es donde se pierden bytes si está mal hecho."""
        datos = os.urandom(3 * 1024 * 1024 + 12345)   # ni redondo ni alineado
        nombre = self.almacen.save("grande.pdf", ContentFile(datos))
        self.assertEqual(self.almacen.leer_descifrado(nombre), datos)

    def test_uno_vacio(self):
        nombre = self.almacen.save("vacio.pdf", ContentFile(b""))
        self.assertEqual(self.almacen.leer_descifrado(nombre), b"")

    def test_leerlo_por_pedazos_da_lo_mismo_que_entero(self):
        datos = os.urandom(2 * 1024 * 1024 + 7)
        nombre = self.almacen.save("x.pdf", ContentFile(datos))
        self.assertEqual(b"".join(self.almacen.pedazos_descifrados(nombre)), datos)

    def test_en_disco_no_esta_el_contenido(self):
        """Testigo de todo lo anterior: sigue estando cifrado de verdad."""
        secreto = b"V-30719983 Benjamin Velazco" * 500
        nombre = self.almacen.save("s.pdf", ContentFile(secreto))
        en_disco = self.crudo(nombre)
        self.assertNotIn(b"Velazco", en_disco)
        self.assertNotIn(secreto[:40], en_disco)
        self.assertTrue(en_disco.startswith(CABECERA))


class LosDeAntesSeSiguenLeyendo(_ConAlmacen):
    """Lo que no se puede romper.

    Los documentos ya subidos son un único token Fernet, sin encabezado. Si el
    lector nuevo no los entendiera, todos los expedientes cargados hasta hoy
    quedarían ilegibles —y no hay vuelta atrás, porque el original no está—.
    """

    def _guardar_al_modo_viejo(self, nombre, datos):
        ruta = os.path.join(self.carpeta, nombre)
        with open(ruta, "wb") as f:
            f.write(_get_fernet().encrypt(datos))
        return nombre

    def test_un_documento_del_formato_viejo_se_abre(self):
        nombre = self._guardar_al_modo_viejo("viejo.pdf", b"contrato firmado")
        self.assertEqual(self.almacen.leer_descifrado(nombre), b"contrato firmado")

    def test_y_tambien_por_pedazos(self):
        datos = os.urandom(200_000)
        nombre = self._guardar_al_modo_viejo("viejo2.pdf", datos)
        self.assertEqual(b"".join(self.almacen.pedazos_descifrados(nombre)), datos)

    def test_los_dos_formatos_conviven(self):
        """Testigo: que el lector no esté adivinando siempre lo mismo."""
        viejo = self._guardar_al_modo_viejo("v.pdf", b"del formato viejo")
        nuevo = self.almacen.save("n.pdf", ContentFile(b"del formato nuevo"))
        self.assertFalse(self.crudo(viejo).startswith(CABECERA))
        self.assertTrue(self.crudo(nuevo).startswith(CABECERA))
        self.assertEqual(self.almacen.leer_descifrado(viejo), b"del formato viejo")
        self.assertEqual(self.almacen.leer_descifrado(nuevo), b"del formato nuevo")


class LaMemoriaNoDependeDelTamano(_ConAlmacen):
    """El test que corresponde al reporte.

    Antes, guardar pedía ~6,7 veces el tamaño del archivo. Acá se guarda uno
    chico y uno tres veces más grande y se compara el pico: si el arreglo se
    cayera, el segundo pediría el triple.
    """

    def _pico_al_guardar(self, mb, nombre):
        datos = os.urandom(mb * 1024 * 1024)
        tracemalloc.start()
        try:
            self.almacen.save(nombre, ContentFile(datos))
            _, pico = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        return pico

    def test_guardar_uno_grande_no_pide_mas_memoria_que_uno_chico(self):
        chico = self._pico_al_guardar(4, "chico.bin")
        grande = self._pico_al_guardar(12, "grande.bin")
        # 12 MB contra 4 MB: sin el arreglo, el pico sería 3 veces más alto.
        # Se deja aire para el ruido del intérprete, pero no tres veces.
        self.assertLess(
            grande, chico * 1.6,
            f"guardar 12 MB pidió {grande/1024/1024:.0f} MB y guardar 4 MB "
            f"pidió {chico/1024/1024:.0f} MB: el pico sigue atado al tamaño")

    def test_leer_por_pedazos_tampoco(self):
        nombre = self.almacen.save("g.bin", ContentFile(os.urandom(12 * 1024 * 1024)))
        tracemalloc.start()
        try:
            for _ in self.almacen.pedazos_descifrados(nombre):
                pass
            _, pico = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(pico, 12 * 1024 * 1024,
                        "leer un archivo de 12 MB se lo trae entero a memoria")


class UnArchivoDanadoNoTiraElServidor(_ConAlmacen):

    def test_uno_cortado_a_la_mitad_lo_dice(self):
        nombre = self.almacen.save("c.pdf", ContentFile(os.urandom(2_000_000)))
        ruta = os.path.join(self.carpeta, nombre)
        entero = self.crudo(nombre)
        with open(ruta, "wb") as f:
            f.write(entero[:len(entero) // 2])
        with self.assertRaises(ValueError) as e:
            self.almacen.leer_descifrado(nombre)
        self.assertIn("cortado", str(e.exception))

    def test_uno_con_el_largo_absurdo_no_reserva_memoria(self):
        """Sin el tope, un número inventado en el encabezado pedía gigas."""
        ruta = os.path.join(self.carpeta, "raro.pdf")
        with open(ruta, "wb") as f:
            f.write(CABECERA + struct.pack(">I", 4_000_000_000) + b"x")
        with self.assertRaises(ValueError) as e:
            self.almacen.leer_descifrado("raro.pdf")
        self.assertIn("dañado", str(e.exception))


class _ConExpediente(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="V-30719983", nombres="Benjamin",
            apellidos="Velazco", sede=sede)
        cls.tipo = TipoDocumento.objects.create(nombre="Cédula", orden=1)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def subir(self, contenido, nombre="cedula.pdf"):
        self.client.force_login(self.admin)
        return self.client.post(
            reverse("expedientes:documento_subir", args=[self.trabajador.pk]),
            {"tipo": self.tipo.pk,
             "archivo": SimpleUploadedFile(nombre, contenido,
                                           content_type="application/pdf")},
            follow=True)


class UnArchivoDemasiadoGrandeSeRechaza(_ConExpediente):

    @override_settings(DOCUMENTOS_MAX_BYTES=100_000)
    def test_no_se_guarda_y_se_explica_cuanto_pesa(self):
        r = self.subir(b"x" * 300_000)
        self.assertEqual(Documento.objects.count(), 0)
        cuerpo = r.content.decode()
        self.assertIn("0,3 MB", cuerpo)
        self.assertIn("0,1 MB", cuerpo)

    @override_settings(DOCUMENTOS_MAX_BYTES=100_000)
    def test_el_aviso_dice_que_hacer(self):
        """Un «no se puede» sin salida deja a la persona igual de trabada."""
        cuerpo = self.subir(b"x" * 300_000).content.decode()
        self.assertIn("menos calidad", cuerpo)

    @override_settings(DOCUMENTOS_MAX_BYTES=100_000)
    def test_uno_que_entra_si_se_guarda(self):
        """Testigo: si rechazara todo, los de arriba no probarían el límite."""
        self.subir(b"x" * 50_000)
        self.assertEqual(Documento.objects.count(), 1)
        self.assertEqual(Documento.objects.get().tamano_bytes, 50_000)

    def test_el_documento_guardado_se_puede_volver_a_bajar(self):
        """De punta a punta: sube, se cifra, se descifra y baja igual."""
        contenido = os.urandom(1_500_000)
        self.subir(contenido)
        doc = Documento.objects.get()
        r = self.client.get(reverse("expedientes:documento_descargar", args=[doc.pk]))
        self.assertEqual(b"".join(r.streaming_content), contenido)


class LaPeticionEnormeSeCortaAntes(_ConExpediente):
    """El corte temprano: se mira el encabezado, no el cuerpo.

    Sin esto, el servidor recibe y acomoda en disco los 300 MB antes de que
    ninguna vista pueda opinar.
    """

    @override_settings(SUBIDA_MAX_BYTES=2_000)
    def test_se_rechaza_sin_guardar_nada(self):
        r = self.subir(b"x" * 50_000)
        self.assertEqual(Documento.objects.count(), 0)
        self.assertIn("No se subió el documento", r.content.decode())

    @override_settings(SUBIDA_MAX_BYTES=2_000)
    def test_al_escaner_le_contesta_en_json(self):
        """La pantalla del escáner no recarga: un redirect no se vería."""
        self.client.force_login(self.admin)
        r = self.client.post(
            reverse("expedientes:documento_escanear", args=[self.trabajador.pk]),
            {"tipo": self.tipo.pk, "paginas": SimpleUploadedFile(
                "h.jpg", b"y" * 50_000, content_type="image/jpeg")},
            headers={"x-requested-with": "XMLHttpRequest"})
        self.assertEqual(r.status_code, 413)
        self.assertFalse(r.json()["ok"])
        self.assertIn("máximo", r.json()["error"])

    def test_una_peticion_normal_pasa(self):
        """Testigo: el corte es por tamaño, no un portazo a todo."""
        self.subir(b"x" * 50_000)
        self.assertEqual(Documento.objects.count(), 1)


class LaPantallaAvisaElLimite(_ConExpediente):

    def cuerpo(self):
        self.client.force_login(self.admin)
        return self.client.get(
            reverse("expedientes:trabajador_detail",
                    args=[self.trabajador.pk])).content.decode()

    def test_el_formulario_lleva_el_tope_que_usa_el_servidor(self):
        """Si estuviera escrito a mano, algún día diría otra cosa que el server."""
        self.assertIn(f'data-max-bytes="{settings.DOCUMENTOS_MAX_BYTES}"',
                      self.cuerpo())

    def test_se_lo_dice_a_la_persona_en_megas(self):
        mb = settings.DOCUMENTOS_MAX_BYTES // 1024 // 1024
        self.assertIn(f"Hasta {mb} MB por archivo", self.cuerpo())

    def test_carga_el_guion_que_muestra_el_progreso(self):
        self.assertIn("js/subida.js", self.cuerpo())
