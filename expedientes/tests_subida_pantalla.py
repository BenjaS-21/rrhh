"""El indicador de subida, manejado en un Chrome de verdad.

Lo que se prueba es el momento en que la persona elige el archivo: si pesa
demasiado, la pantalla le ofrece comprimirlo ahí —con el archivo a mano— en
vez de dejar que suba 25 MB por la conexión de la tienda sin saber que podía
ser más rápido. No se prueba que FRENE la subida, porque ya no la frena: el
archivo entra igual; la compresión es una oferta, no un peaje.

Se maneja el `<input type=file>` de verdad, con `DataTransfer`, porque poner un
archivo ahí es justo lo que el navegador no deja hacer de cualquier manera: si
se simulara, la prueba no diría nada del caso real.
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from cuentas.models import Sede, Zona
from expedientes.models import TipoDocumento, Trabajador
from expedientes.tests_escaner_imagen import CHROME

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"

# El tope real son 20 MB. Acá se baja a 1000 bytes para no armar un archivo de
# 21 MB dentro del navegador: lo que se prueba es la regla, no el número.
TOPE = 1000

GUION = """
<script>
// Corre al parsear, antes que subida.js (que va con defer): asi el guion lee
// este tope y no el de produccion.
document.getElementById("subir-documento").dataset.maxBytes = "%(tope)d";
</script>
<script>
window.addEventListener("load", function () {
  var formulario = document.getElementById("subir-documento");
  var campo = formulario.querySelector('input[type="file"]');

  function elegir(bytes) {
    var dt = new DataTransfer();
    dt.items.add(new File([new ArrayBuffer(bytes)], "escaneo.pdf",
                          {type: "application/pdf"}));
    campo.files = dt.files;
    campo.dispatchEvent(new Event("change", {bubbles: true}));
  }

  function mirar() {
    var panel = formulario.querySelector(".subida");
    var estado = formulario.querySelector(".subida__estado");
    var comprimir = formulario.querySelector(".subida__comprimir");
    return {
      hay: !!panel,
      visible: !!panel && !panel.hidden,
      mal: !!panel && panel.classList.contains("subida--mal"),
      texto: estado ? estado.textContent : "",
      ofreceComprimir: !!comprimir && !comprimir.hidden,
      botonTrabado: formulario.querySelector('button[type="submit"]').disabled
    };
  }

  var r = {};
  elegir(%(chico)d);   r.chico = mirar();
  elegir(%(grande)d);  r.grande = mirar();
  elegir(%(chico)d);   r.deNuevoChico = mirar();
  document.title = JSON.stringify(r);
});
</script>
</body>""" % {"tope": TOPE, "chico": TOPE // 2, "grande": TOPE * 3}


@unittest.skipUnless(CHROME, "Esta maquina no tiene Chrome.")
class AvisaAntesDeSubir(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="V-1", nombres="Ana", apellidos="Alvarez",
            sede=sede)
        TipoDocumento.objects.create(nombre="Cédula", orden=1)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def _mirar(self):
        base = Path(settings.BASE_DIR)
        css = (base / "static" / "css" / "estilos.css").as_uri()
        self.client.force_login(self.admin)
        with override_settings(ALLOWED_HOSTS=["testserver"]):
            html = self.client.get(
                reverse("expedientes:trabajador_detail",
                        args=[self.trabajador.pk])).content.decode()
        html = re.sub(r'href="/static/css/estilos\.css[^"]*"', f'href="{css}"', html)
        html = re.sub(r'<script src="/static/js/htmx[^"]*"[^>]*></script>', "", html)
        html = re.sub(
            r'src="/static/js/([\w-]+)\.js[^"]*"',
            lambda m: 'src="%s"' % (base / "static" / "js" / f"{m.group(1)}.js").as_uri(),
            html)
        html = html.replace("</body>", GUION)

        carpeta = tempfile.mkdtemp(prefix="gde-subida-")
        try:
            pagina = Path(carpeta) / "p.html"
            pagina.write_text(html, encoding="utf-8")
            salida = subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--allow-file-access-from-files", "--virtual-time-budget=9000",
                 "--window-size=900,900", "--dump-dom", pagina.as_uri()],
                capture_output=True, timeout=180,
                encoding="utf-8", errors="replace").stdout
            titulo = re.search(r"<title>(.*?)</title>", salida, re.S)
            if not titulo:
                raise AssertionError("Chrome no devolvio el resultado")
            return json.loads(titulo.group(1))
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)

    def medida(self):
        if not hasattr(AvisaAntesDeSubir, "_cache"):
            AvisaAntesDeSubir._cache = self._mirar()
        return AvisaAntesDeSubir._cache

    def test_el_panel_de_progreso_existe_en_la_pantalla(self):
        """Testigo: sin esto, «no se ve el aviso» daría verde por otro motivo."""
        self.assertTrue(self.medida()["chico"]["hay"],
                        "subida.js no llego a armar el panel de progreso")

    def test_con_un_archivo_que_entra_no_molesta(self):
        chico = self.medida()["chico"]
        self.assertFalse(chico["visible"])
        self.assertFalse(chico["botonTrabado"])

    def test_con_uno_demasiado_grande_ofrece_comprimir_al_elegirlo(self):
        grande = self.medida()["grande"]
        self.assertTrue(grande["visible"], "eligio un archivo grande y no dijo nada")
        self.assertFalse(grande["mal"], "lo mostro como error: es una oferta, no un rechazo")
        self.assertTrue(grande["ofreceComprimir"], "no aparecio el boton de comprimir")

    def test_el_aviso_dice_cuanto_pesa_y_que_entra_igual(self):
        texto = self.medida()["grande"]["texto"]
        self.assertRegex(texto, r"\d+,\d+ MB")
        self.assertIn("Se sube igual", texto)

    def test_al_cambiarlo_por_uno_chico_el_aviso_se_va(self):
        """Un aviso que no se borra deja pensando que sigue estando mal."""
        de_nuevo = self.medida()["deNuevoChico"]
        self.assertFalse(de_nuevo["visible"])
        self.assertFalse(de_nuevo["mal"])
