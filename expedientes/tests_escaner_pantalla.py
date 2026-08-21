"""El panel del escáner se abre cuando se lo pide, y se cierra cuando se cierra.

Nace de un error real: el panel aparecía solo al entrar al expediente y el
botón de cerrar no hacía nada. La marca `hidden` estaba puesta, pero el CSS le
daba `display: flex` y el navegador le hace más caso al CSS que a `hidden`.

Se comprueba en un navegador de verdad porque es lo único que puede responder
la pregunta que importa: ¿el usuario lo ve o no lo ve? Donde no hay Chrome, la
clase se saltea.
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

# Se simula lo único que el script hace en un teléfono —mostrar la caja— y
# después se recorre el ciclo: entrar, abrir, cerrar.
# Se simula lo único que el script hace en un teléfono —mostrar la caja— y
# después se recorre el ciclo: entrar, abrir, cerrar. La cámara no existe en un
# Chrome sin pantalla, así que abrir y cerrar se hacen igual que en `escaner.js`.
GUION = """
<script>
  // Este script corre mientras se lee la página, así que llega antes que los
  // `defer` del escáner. Le hace creer que es un teléfono con cámara: sin esto
  // `escaner.js` se va sin hacer nada y no habría nada que probar.
  window.matchMedia = function () { return { matches: true, addListener: function () {} }; };
  navigator.mediaDevices = navigator.mediaDevices || {};
  navigator.mediaDevices.getUserMedia = function () {
    return Promise.reject(new Error("acá no hay cámara"));
  };
</script>
<script>
window.addEventListener("load", function () {
  setTimeout(function () {
    var r = {};
    var panel = document.getElementById("escaner-panel");
    function visible(e) {
      var c = e.getBoundingClientRect();
      return c.width > 0 && c.height > 0;
    }
    // El botón lo muestra `escaner.js`: si no se ve, se fue sin arrancar.
    r.hayBoton = visible(document.getElementById("escaner-abrir"));
    r.alEntrar = visible(panel);

    // Se baja hasta el final: el escáner vive abajo de todo el expediente.
    window.scrollTo(0, document.documentElement.scrollHeight);
    r.dondeEstaba = Math.round(window.pageYOffset);

    document.getElementById("escaner-abrir").click();      // abrir de verdad
    r.alAbrir = visible(panel);
    var caja = panel.getBoundingClientRect();
    r.panel = {arriba: Math.round(caja.top), alto: Math.round(caja.height)};
    r.ventana = {ancho: window.innerWidth, alto: window.innerHeight};

    // Dos hojas de mentira: acá no hay cámara, pero la tira se dibuja igual.
    var tira = document.getElementById("escaner-hojas");
    for (var i = 0; i < 2; i++) {
      var item = document.createElement("div");
      item.className = "escaner__hoja";
      var img = document.createElement("canvas");
      img.width = 60; img.height = 90;
      img.style.height = "76px"; img.style.width = "auto"; img.style.display = "block";
      var x = document.createElement("button");
      x.type = "button"; x.className = "escaner__quitar"; x.textContent = "x";
      item.appendChild(img); item.appendChild(x); tira.appendChild(item);
    }
    var hojas = tira.querySelectorAll(".escaner__hoja");
    var e0 = tira.querySelectorAll(".escaner__quitar")[0].getBoundingClientRect();
    var cajaTira = tira.getBoundingClientRect();
    r.equisCortada = e0.top < cajaTira.top - 0.5 || e0.right > cajaTira.right + 0.5;
    r.equisEnSuHoja = e0.right <= hojas[0].getBoundingClientRect().right + 0.5;

    // El recuadro de recorte: dónde arranca y si se puede mover con el dedo.
    var guia = document.getElementById("escaner-guia");
    var visorCaja = document.querySelector(".escaner__visor").getBoundingClientRect();
    function comoFraccion(e) {
      var c = e.getBoundingClientRect();
      return {
        x: (c.left - visorCaja.left) / visorCaja.width,
        y: (c.top - visorCaja.top) / visorCaja.height,
        an: c.width / visorCaja.width,
        al: c.height / visorCaja.height
      };
    }
    r.marcoAlPrincipio = comoFraccion(guia);
    r.tiradores = guia.querySelectorAll(".escaner__tirador").length;

    function tocar(nombre, x, y) {
      guia.dispatchEvent(new PointerEvent(nombre, {
        bubbles: true, clientX: x, clientY: y, pointerId: 1, pointerType: "touch"
      }));
    }
    var centro = guia.getBoundingClientRect();
    var desdeX = centro.left + centro.width / 2, desdeY = centro.top + centro.height / 2;
    tocar("pointerdown", desdeX, desdeY);
    tocar("pointermove", desdeX + 30, desdeY + 20);
    tocar("pointerup", desdeX + 30, desdeY + 20);
    r.marcoDespues = comoFraccion(guia);
    try { r.recordado = JSON.parse(localStorage.getItem("gde-escaner-marco")); }
    catch (e) { r.recordado = null; }

    // Lo último del paso 1 tiene que verse sin scrollear el panel.
    var nota = document.querySelector(".escaner__nota").getBoundingClientRect();
    r.notaEntera = nota.bottom <= window.innerHeight + 0.5;
    r.visor = Math.round(document.querySelector(".escaner__visor")
                                 .getBoundingClientRect().height);

    document.getElementById("escaner-cerrar").click();     // cerrar de verdad
    r.alCerrar = visible(panel);
    r.dondeQuedo = Math.round(window.pageYOffset);

    document.title = JSON.stringify(r);
  }, 400);
});
</script>
</body>"""

# Chrome no achica su ventana por debajo de ~522 px: el teléfono se simula con
# un iframe de 380x700, que es una pantalla chica de verdad.
MARCO = """<!doctype html><meta charset=utf-8>
<style>html,body{margin:0}iframe{width:380px;height:700px;border:0}</style>
<body><iframe id="m" src="%(pagina)s"></iframe>
<script>
document.getElementById("m").addEventListener("load", function () {
  var f = this;
  setTimeout(function () { document.title = f.contentDocument.title; }, 1100);
});
</script>"""


@unittest.skipUnless(CHROME, "Esta máquina no tiene Chrome: no se puede mirar la pantalla.")
class ElPanelSeAbreYSeCierra(TestCase):

    _cache = None

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        sede = Sede.objects.create(nombre="CCCT", zona=zona)
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="V-1", nombres="Ana", apellidos="Alvarez", sede=sede)
        TipoDocumento.objects.create(nombre="Cédula")
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def _mirar(self, hoja_de_estilos=None):
        """Abre la pantalla real en Chrome y devuelve qué se vio en cada paso."""
        base = Path(settings.BASE_DIR)
        css = (hoja_de_estilos or base / "static" / "css" / "estilos.css").as_uri()

        self.client.force_login(self.admin)
        with override_settings(ALLOWED_HOSTS=["testserver"]):
            html = self.client.get(
                reverse("expedientes:trabajador_detail",
                        args=[self.trabajador.pk])).content.decode()

        html = re.sub(r'href="/static/css/estilos\.css[^"]*"', f'href="{css}"', html)
        # htmx no hace falta acá; el escáner sí, con su ruta en disco.
        html = re.sub(r'<script src="/static/js/htmx[^"]*"[^>]*></script>', "", html)
        html = re.sub(
            r'src="/static/js/(escaner[\w-]*)\.js[^"]*"',
            lambda m: 'src="%s"' % (base / "static" / "js" / f"{m.group(1)}.js").as_uri(),
            html)
        html = html.replace("</body>", GUION)

        carpeta = tempfile.mkdtemp(prefix="gde-panel-")
        try:
            pagina = Path(carpeta) / "detalle.html"
            pagina.write_text(html, encoding="utf-8")
            marco = Path(carpeta) / "marco.html"
            marco.write_text(MARCO % {"pagina": pagina.as_uri()}, encoding="utf-8")
            salida = subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--allow-file-access-from-files",
                 "--virtual-time-budget=9000", "--window-size=560,820",
                 "--dump-dom", marco.as_uri()],
                capture_output=True, timeout=180,
                # Windows decodifica en cp1252 por defecto y la página trae
                # acentos y emojis: sin esto, la salida de Chrome se rompe.
                encoding="utf-8", errors="replace",
            ).stdout
            titulo = re.search(r"<title>(.*?)</title>", salida, re.S)
            if not titulo:
                raise AssertionError("Chrome no devolvió el resultado")
            return json.loads(titulo.group(1))
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)

    def _medida(self):
        """La misma medición para todos los tests: un solo Chrome, no cinco."""
        if ElPanelSeAbreYSeCierra._cache is None:
            ElPanelSeAbreYSeCierra._cache = self._mirar()
        return ElPanelSeAbreYSeCierra._cache

    def test_no_aparece_solo_al_entrar_al_expediente(self):
        self.assertFalse(self._medida()["alEntrar"],
                         "el panel tapa la pantalla sin que nadie lo pida")

    def test_el_boton_aparece_en_el_telefono(self):
        """Si `escaner.js` no arranca, nada de lo de abajo prueba nada."""
        self.assertTrue(self._medida()["hayBoton"])

    def test_se_abre_con_el_boton(self):
        self.assertTrue(self._medida()["alAbrir"])

    def test_se_cierra(self):
        self.assertFalse(self._medida()["alCerrar"],
                         "cerrar no lo cierra: queda tapando el expediente")

    def test_al_cerrar_el_expediente_queda_donde_estaba(self):
        """Trabar el fondo mandaba la página arriba de todo.

        El escáner está al final de un expediente largo. Si al cerrar se pierde
        la altura, hay que volver a bajar todo para seguir donde uno estaba.
        """
        m = self._medida()
        self.assertGreater(m["dondeEstaba"], 0, "la página de prueba no scrollea")
        self.assertEqual(m["dondeQuedo"], m["dondeEstaba"])

    def test_el_panel_ocupa_la_pantalla_entera(self):
        """Si sobra pantalla abajo, se ve el expediente asomando por atrás."""
        m = self._medida()
        self.assertEqual(m["panel"]["arriba"], 0)
        self.assertEqual(m["panel"]["alto"], m["ventana"]["alto"])

    def test_no_se_corta_nada_del_paso_de_sacar_hojas(self):
        """El visor se estira con lo que sobra, así que todo entra sin scroll."""
        m = self._medida()
        self.assertTrue(m["notaEntera"],
                        "la explicación de abajo queda fuera de la pantalla")
        self.assertGreater(m["visor"], 140, "el visor quedó demasiado chico")

    def test_el_recuadro_de_recorte_se_ve_sobre_la_camara(self):
        """Es el recorte, no un adorno: tiene que estar y tener sus esquinas."""
        m = self._medida()
        self.assertEqual(m["tiradores"], 4)
        marco = m["marcoAlPrincipio"]
        self.assertGreater(marco["an"], 0.3)
        self.assertGreater(marco["al"], 0.3)
        self.assertLessEqual(marco["x"] + marco["an"], 1.01)
        self.assertLessEqual(marco["y"] + marco["al"], 1.01)

    def test_el_recuadro_se_mueve_con_el_dedo_y_queda_recordado(self):
        """Si no se puede mover, no hay forma de corregir un recorte que erró.

        Y si no se recuerda, hay que reacomodarlo hoja por hoja.
        """
        m = self._medida()
        antes, despues = m["marcoAlPrincipio"], m["marcoDespues"]
        self.assertGreater(despues["x"], antes["x"] + 0.02, "no se movió")
        self.assertGreater(despues["y"], antes["y"] + 0.02, "no se movió")
        self.assertAlmostEqual(despues["an"], antes["an"], places=2,
                               msg="moverlo no debería cambiarle el tamaño")
        self.assertIsNotNone(m["recordado"], "no quedó anotado para la próxima")
        self.assertAlmostEqual(m["recordado"]["x"], despues["x"], places=2)

    def test_la_equis_de_la_miniatura_no_queda_cortada(self):
        """Estaba puesta afuera de la miniatura y la tira se la comía.

        La tira scrollea a lo ancho, y todo lo que sobresale de una caja que
        scrollea se corta. Además caía pegada a la miniatura siguiente, como si
        fuera el botón de esa otra hoja.
        """
        m = self._medida()
        self.assertFalse(m["equisCortada"], "la × de quitar la hoja se ve tajeada")
        self.assertTrue(m["equisEnSuHoja"],
                        "la × cae fuera de su miniatura y confunde de cuál es")

    def test_sin_la_regla_de_hidden_el_error_vuelve(self):
        """Testigo: se mide con una hoja de estilos sin la corrección.

        Sin esto, los tres de arriba pasarían aunque la regla se borrara por
        accidente, porque `hidden` funciona en casi todos los elementos y el
        problema solo se nota en los que tienen `display` propio.
        """
        base = Path(settings.BASE_DIR)
        original = (base / "static" / "css" / "estilos.css").read_text(encoding="utf-8")
        carpeta = tempfile.mkdtemp(prefix="gde-css-")
        try:
            copia = Path(carpeta) / "sin-regla.css"
            copia.write_text(
                original.replace("[hidden] { display: none !important; }", ""),
                encoding="utf-8")
            roto = self._mirar(hoja_de_estilos=copia)
            self.assertTrue(roto["alEntrar"])
            self.assertTrue(roto["alCerrar"])
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)


class LaReglaEstaEnLaHoja(TestCase):
    """Barata y rápida: corre siempre, haya Chrome o no."""

    def test_hidden_le_gana_a_cualquier_display(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "estilos.css").read_text(
            encoding="utf-8")
        self.assertIn("[hidden] { display: none !important; }", css)
