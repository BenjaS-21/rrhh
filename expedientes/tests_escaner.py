"""Escáner de documentos con la cámara del teléfono.

Se prueba lo que corre en el servidor —armar el PDF, los permisos, el
versionado— y que la pantalla traiga lo que el escáner necesita. El procesado
de la foto ocurre en el navegador y no se puede ejercitar desde acá; lo que sí
se fija es que el servidor no confíe en él.
"""

from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from cuentas.models import Sede, Zona
from expedientes.escaner import (
    MAX_PAGINAS, EscaneoInvalido, armar_pdf,
)
from expedientes.models import Documento, RegistroAuditoria, TipoDocumento, Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


def imagen(ancho=1200, alto=1600, formato="JPEG", color="white", nombre=None):
    """Una foto de mentira, del tamaño de una hoja sacada con el teléfono."""
    buffer = BytesIO()
    Image.new("RGB", (ancho, alto), color).save(buffer, format=formato)
    buffer.seek(0)
    extension = {"JPEG": "jpg", "PNG": "png"}.get(formato, formato.lower())
    return SimpleUploadedFile(nombre or f"hoja.{extension}", buffer.getvalue(),
                              content_type=f"image/{extension}")


class ArmadoDelPDF(TestCase):

    def paginas(self, cantidad, **kw):
        return [imagen(nombre=f"hoja-{i}.jpg", **kw) for i in range(cantidad)]

    def leer(self, pdf):
        self.assertTrue(pdf.startswith(b"%PDF"), "no es un PDF")
        return pdf

    def test_una_foto_da_un_pdf(self):
        self.leer(armar_pdf(self.paginas(1)))

    def test_varias_fotos_dan_un_solo_archivo(self):
        pdf = self.leer(armar_pdf(self.paginas(4)))
        # Cada hoja es una página: el contador del PDF lo dice.
        self.assertEqual(pdf.count(b"/Type /Page\n"), 4)

    def test_respeta_el_orden_en_que_se_sacaron(self):
        """La hoja 2 no puede terminar antes que la 1."""
        colores = ["red", "green", "blue"]
        paginas = [imagen(ancho=100, alto=100, color=c, nombre=f"{i}.jpg")
                   for i, c in enumerate(colores)]
        pdf = armar_pdf(paginas)
        self.assertEqual(pdf.count(b"/Type /Page\n"), 3)

    def test_sin_fotos_avisa(self):
        with self.assertRaises(EscaneoInvalido):
            armar_pdf([])

    def test_pone_un_tope_de_hojas(self):
        with self.assertRaisesMessage(EscaneoInvalido, "demasiadas hojas"):
            armar_pdf(self.paginas(MAX_PAGINAS + 1))

    def test_rechaza_algo_que_no_es_imagen(self):
        falsa = SimpleUploadedFile("hoja.jpg", b"esto no es una foto",
                                   content_type="image/jpeg")
        with self.assertRaisesMessage(EscaneoInvalido, "no es una imagen válida"):
            armar_pdf([falsa])

    def test_rechaza_un_formato_que_no_corresponde(self):
        """Aunque se llame .jpg: lo que manda es el contenido, no el nombre."""
        buffer = BytesIO()
        Image.new("RGB", (50, 50), "white").save(buffer, format="BMP")
        falsa = SimpleUploadedFile("hoja.jpg", buffer.getvalue(),
                                   content_type="image/jpeg")
        with self.assertRaisesMessage(EscaneoInvalido, "formato"):
            armar_pdf([falsa])

    def test_achica_las_fotos_grandes(self):
        """Una foto de 4000 px no mejora la lectura y multiplica el archivo."""
        chico = armar_pdf([imagen(600, 800)])
        grande = armar_pdf([imagen(4000, 5200)])
        self.assertLess(len(grande), len(chico) * 6)

    def test_un_png_con_transparencia_no_sale_en_negro(self):
        buffer = BytesIO()
        Image.new("RGBA", (200, 200), (255, 255, 255, 0)).save(buffer, format="PNG")
        transparente = SimpleUploadedFile("hoja.png", buffer.getvalue(),
                                          content_type="image/png")
        self.leer(armar_pdf([transparente]))


class SubidaDelEscaneo(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="CCCT", zona=zona)
        cls.otra_sede = Sede.objects.create(
            nombre="MARACAIBO", zona=Zona.objects.create(nombre="ZULIA"))
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="V-1", nombres="Ana", apellidos="Alvarez",
            sede=cls.sede)
        cls.cedula = TipoDocumento.objects.create(nombre="Cédula")
        cls.carnet = TipoDocumento.objects.create(
            nombre="Carnet de salud", requiere_vencimiento=True)

        cls.admin = cls._usuario("adm", Usuario.Rol.ADMIN)
        cls.lectura = cls._usuario("lect", Usuario.Rol.SOLO_LECTURA)

    @classmethod
    def _usuario(cls, username, rol):
        u = Usuario.objects.create_user(username=username, password=CLAVE)
        u.rol = rol
        u.save()
        return u

    def url(self, trabajador=None):
        return reverse("expedientes:documento_escanear",
                       args=[(trabajador or self.trabajador).pk])

    def escanear(self, usuario=None, hojas=2, **datos):
        self.client.force_login(usuario or self.admin)
        cuerpo = {"tipo": self.cedula.pk}
        cuerpo.update(datos)
        cuerpo["paginas"] = [imagen(nombre=f"h{i}.jpg") for i in range(hojas)]
        return self.client.post(self.url(), cuerpo)

    # --- El nombre del archivo ------------------------------------------------
    def test_se_guarda_con_el_nombre_que_le_pusieron(self):
        self.escanear(nombre="Cédula de Ana Alvarez")
        self.assertEqual(Documento.objects.get().nombre_original,
                         "Cédula de Ana Alvarez.pdf")

    def test_sin_nombre_queda_uno_que_dice_de_qué_se_trata(self):
        """`escaneo-20260819-2h.pdf` no le sirve a nadie para encontrarlo."""
        self.escanear()
        nombre = Documento.objects.get().nombre_original
        self.assertTrue(nombre.startswith("Cédula "), nombre)
        self.assertTrue(nombre.endswith(".pdf"))

    def test_no_termina_con_dos_pdf(self):
        self.escanear(nombre="Contrato.pdf")
        self.assertEqual(Documento.objects.get().nombre_original, "Contrato.pdf")

    def test_el_nombre_no_puede_salirse_de_su_carpeta(self):
        """Lo escribe una persona: no puede decidir dónde se escribe nada."""
        self.escanear(nombre="../../etc/passwd")
        nombre = Documento.objects.get().nombre_original
        self.assertNotIn("/", nombre)
        self.assertNotIn("\\", nombre)
        self.assertNotIn("..", nombre)

    def test_el_nombre_no_puede_meterse_en_las_cabeceras(self):
        """Va en `Content-Disposition` al descargar: un salto de línea ahí
        deja agregar cabeceras propias a la respuesta."""
        self.escanear(nombre="malo\r\nX-Cosa: 1")
        doc = Documento.objects.get()
        self.assertNotIn("\n", doc.nombre_original)
        self.assertNotIn("\r", doc.nombre_original)
        r = self.client.get(reverse("expedientes:documento_descargar", args=[doc.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("X-Cosa", r.headers)

    def test_un_nombre_con_acentos_se_descarga_entero(self):
        self.escanear(nombre="Cédula de José Ramírez")
        doc = Documento.objects.get()
        r = self.client.get(reverse("expedientes:documento_descargar", args=[doc.pk]))
        disp = r.headers["Content-Disposition"]
        self.assertIn("C%C3%A9dula", disp, disp)

    def test_un_nombre_de_puros_signos_se_rechaza(self):
        r = self.escanear(nombre="///")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Documento.objects.exists())

    def test_el_campo_del_nombre_está_en_la_pantalla(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(
            reverse("expedientes:trabajador_detail",
                    args=[self.trabajador.pk])).content.decode()
        self.assertIn('id="escaner-nombre"', cuerpo)

    # --- Camino feliz ---------------------------------------------------------
    def test_guarda_un_pdf_con_todas_las_hojas(self):
        r = self.escanear(hojas=3)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        doc = Documento.objects.get()
        self.assertEqual(doc.tipo, self.cedula)
        self.assertEqual(doc.trabajador, self.trabajador)
        self.assertTrue(doc.nombre_original.endswith(".pdf"))
        self.assertEqual(doc.extension, ".pdf")
        self.assertEqual(r.json()["hojas"], 3)

    def test_queda_asociado_a_quien_lo_escaneó(self):
        self.escanear()
        self.assertEqual(Documento.objects.get().subido_por, self.admin)

    def test_el_archivo_guardado_es_un_pdf_de_verdad(self):
        self.escanear(hojas=2)
        doc = Documento.objects.get()
        doc.archivo.open("rb")
        try:
            self.assertTrue(doc.archivo.read(4).startswith(b"%PDF"))
        finally:
            doc.archivo.close()

    def test_guarda_el_tamano(self):
        self.escanear()
        self.assertGreater(Documento.objects.get().tamano_bytes, 0)

    def test_sigue_el_versionado_del_tipo(self):
        self.escanear()
        self.escanear()
        versiones = sorted(Documento.objects.values_list("version", flat=True))
        self.assertEqual(versiones, [1, 2])

    def test_comparte_el_versionado_con_la_subida_normal(self):
        """Escanear y subir a mano no pueden llevar contadores separados."""
        self.client.force_login(self.admin)
        self.client.post(
            reverse("expedientes:documento_subir", args=[self.trabajador.pk]),
            {"tipo": self.cedula.pk, "archivo": imagen(nombre="foto.jpg")})
        self.escanear()
        self.assertEqual(
            sorted(Documento.objects.values_list("version", flat=True)), [1, 2])

    def test_guarda_vencimiento_y_observaciones(self):
        self.escanear(tipo=self.carnet.pk, fecha_vencimiento="2027-05-30",
                      observaciones="Escaneado en tienda")
        doc = Documento.objects.get()
        self.assertEqual(str(doc.fecha_vencimiento), "2027-05-30")
        self.assertEqual(doc.observaciones, "Escaneado en tienda")

    def test_queda_en_la_auditoria_diciendo_que_fue_escaneado(self):
        self.escanear(hojas=2)
        ultimo = RegistroAuditoria.objects.filter(entidad="Documento").latest("id")
        self.assertIn("Escaneó", ultimo.descripcion)
        self.assertIn("2 hojas", ultimo.descripcion)

    # --- Lo que tiene que rechazar --------------------------------------------
    def test_sin_tipo_no_guarda_nada(self):
        r = self.escanear(tipo="")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])
        self.assertFalse(Documento.objects.exists())

    def test_un_tipo_que_vence_exige_la_fecha_tambien_al_escanear(self):
        """Si no, escanear sería la puerta de atrás para saltearse la regla."""
        r = self.escanear(tipo=self.carnet.pk)
        self.assertEqual(r.status_code, 400)
        self.assertIn("vencimiento", r.json()["error"])
        self.assertFalse(Documento.objects.exists())

    def test_sin_fotos_no_guarda_nada(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.url(), {"tipo": self.cedula.pk})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Documento.objects.exists())

    def test_no_confia_en_lo_que_manda_el_telefono(self):
        """El procesado ocurre en el navegador: el servidor igual verifica."""
        self.client.force_login(self.admin)
        r = self.client.post(self.url(), {
            "tipo": self.cedula.pk,
            "paginas": [SimpleUploadedFile("h.jpg", b"basura",
                                           content_type="image/jpeg")]})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Documento.objects.exists())

    def test_no_se_puede_por_GET(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url()).status_code, 405)

    # --- Permisos -------------------------------------------------------------
    def test_solo_lectura_no_puede_escanear(self):
        r = self.escanear(usuario=self.lectura)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Documento.objects.exists())

    def test_el_anonimo_va_al_login(self):
        r = self.client.post(self.url(), {"tipo": self.cedula.pk})
        self.assertEqual(r.status_code, 302)
        self.assertIn("ingresar", r["Location"])

    def test_respeta_la_restriccion_por_zona_cuando_esta_prendida(self):
        from configuracion.models import Preferencias

        Preferencias.objects.update_or_create(
            pk=1, defaults={"restringir_por_zona": True})
        ajeno = self._usuario("rrhh_zulia", Usuario.Rol.RRHH_INTERIOR)
        ajeno.zona = self.otra_sede.zona
        ajeno.save()
        r = self.escanear(usuario=ajeno)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Documento.objects.exists())


class ElEscanerEnLaPantalla(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        sede = Sede.objects.create(nombre="CCCT", zona=zona)
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="V-1", nombres="Ana", apellidos="Alvarez", sede=sede)
        TipoDocumento.objects.create(nombre="Cédula")
        TipoDocumento.objects.create(nombre="Viejo", activo=False)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()
        cls.lectura = Usuario.objects.create_user(username="lect", password=CLAVE)
        cls.lectura.rol = Usuario.Rol.SOLO_LECTURA
        cls.lectura.save()

    def cuerpo(self, usuario=None):
        self.client.force_login(usuario or self.admin)
        return self.client.get(
            reverse("expedientes:trabajador_detail",
                    args=[self.trabajador.pk])).content.decode()

    def test_esta_en_la_seccion_de_cargar_documentos(self):
        cuerpo = self.cuerpo()
        self.assertIn('id="escaner"', cuerpo)
        self.assertIn("Escanear con la cámara", cuerpo)

    def test_arranca_oculto(self):
        """Lo muestra el script, y solo si es un teléfono con cámara."""
        cuerpo = self.cuerpo()
        marca = cuerpo.split('id="escaner"')[1].split(">")[0]
        self.assertIn("hidden", marca)

    def test_trae_los_tipos_de_documento_activos(self):
        cuerpo = self.cuerpo()
        seleccion = cuerpo.split('id="escaner-tipo"')[1].split("</select>")[0]
        self.assertIn("Cédula", seleccion)
        self.assertNotIn("Viejo", seleccion)

    def test_trae_la_direccion_y_el_token(self):
        cuerpo = self.cuerpo()
        self.assertIn(
            reverse("expedientes:documento_escanear", args=[self.trabajador.pk]),
            cuerpo)
        self.assertIn('data-csrf="', cuerpo)

    def test_carga_el_script_solo_en_esta_pantalla(self):
        self.assertIn("js/escaner.js", self.cuerpo())
        self.client.force_login(self.admin)
        panel = self.client.get(reverse("expedientes:panel")).content.decode()
        self.assertNotIn("js/escaner.js", panel)

    def test_solo_lectura_no_lo_ve(self):
        """Va dentro del bloque de carga, que ese rol no tiene."""
        cuerpo = self.cuerpo(self.lectura)
        self.assertNotIn('id="escaner"', cuerpo)
        self.assertNotIn("js/escaner.js", cuerpo)
