"""La cámara busca la hoja sola y el recuadro la sigue.

No alcanza con probar que la función de búsqueda encuentra un rectángulo: lo
que hay que comprobar es que, con la cámara andando, el recuadro termina
encima de la hoja sin que nadie lo toque. Y que si uno lo corrige a mano, deja
de moverse solo —si no, en un cuarto de segundo le pisaría la corrección—.

La cámara se simula con un lienzo: se dibuja una hoja blanca sobre un
escritorio oscuro, se lo convierte en video con `captureStream()` y se le da
eso al escáner en lugar de la cámara. Para el escáner es indistinguible.
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

# La hoja, en fracciones del cuadro. El recuadro tiene que terminar acá.
HOJA = {"x": 0.30, "y": 0.20, "an": 0.40, "al": 0.55}

GUION = """
<script>
  // Corre mientras se lee la página, así que llega antes que los `defer` del
  // escáner: para cuando arranca, ya cree que es un teléfono con cámara.
  window.matchMedia = function () { return { matches: true, addListener: function () {} }; };

  var ANCHO = 640, ALTO = 480;
  var HOJA = %(hoja)s;
  var lienzo = document.createElement("canvas");
  lienzo.width = ANCHO; lienzo.height = ALTO;
  var ctx = lienzo.getContext("2d");
  function dibujar() {
    ctx.fillStyle = "#3b352c";                       // el escritorio
    ctx.fillRect(0, 0, ANCHO, ALTO);
    ctx.fillStyle = "#fff";                          // la hoja
    ctx.fillRect(HOJA.x * ANCHO, HOJA.y * ALTO, HOJA.an * ANCHO, HOJA.al * ALTO);
    ctx.fillStyle = "#222";                          // algo escrito
    for (var i = 0; i < 8; i++) {
      ctx.fillRect(HOJA.x * ANCHO + 14, HOJA.y * ALTO + 22 + i * 26,
                   HOJA.an * ANCHO - 40, 6);
    }
    requestAnimationFrame(dibujar);
  }
  dibujar();

  var flujo = lienzo.captureStream(20);
  navigator.mediaDevices = navigator.mediaDevices || {};
  navigator.mediaDevices.getUserMedia = function () { return Promise.resolve(flujo); };
</script>
<script>
window.addEventListener("load", function () {
  var r = {};
  var guia = document.getElementById("escaner-guia");
  var visor = document.querySelector(".escaner__visor");
  function comoFraccion() {
    var c = guia.getBoundingClientRect(), v = visor.getBoundingClientRect();
    return {
      x: (c.left - v.left) / v.width, y: (c.top - v.top) / v.height,
      an: c.width / v.width, al: c.height / v.height
    };
  }
  function terminar() { document.title = JSON.stringify(r); }

  setTimeout(function () {
    document.getElementById("escaner-abrir").click();
    r.autoAlPrincipio =
      document.getElementById("escaner-auto").getAttribute("aria-pressed");
    r.marcoAlAbrir = comoFraccion();

    // Un rato para que la cámara arranque y el recuadro se acomode solo.
    setTimeout(function () {
      var v = document.getElementById("escaner-video");
      r.video = { ancho: v.videoWidth, alto: v.videoHeight };
      var vc = visor.getBoundingClientRect();
      r.visor = { ancho: vc.width, alto: vc.height };
      r.marcoSolo = comoFraccion();

      // Ahora se lo corrige a mano: tiene que dejar de seguir la hoja.
      var c = guia.getBoundingClientRect();
      ["pointerdown", "pointermove", "pointerup"].forEach(function (n, i) {
        guia.dispatchEvent(new PointerEvent(n, {
          bubbles: true, pointerId: 1, pointerType: "touch",
          clientX: c.left + c.width / 2 + (i ? 40 : 0),
          clientY: c.top + c.height / 2
        }));
      });
      r.autoTrasArrastrar =
        document.getElementById("escaner-auto").getAttribute("aria-pressed");
      r.aviso = document.getElementById("escaner-aviso").textContent;
      var movido = comoFraccion();

      // Y un rato más: si siguiera detectando, lo devolvería a la hoja.
      setTimeout(function () {
        var despues = comoFraccion();
        r.sigueDondeLoDejaron = Math.abs(despues.x - movido.x) < 0.02;
        terminar();
      }, 1200);
    }, 2200);
  }, 300);
});
</script>
</body>"""

MARCO = """<!doctype html><meta charset=utf-8>
<style>html,body{margin:0}iframe{width:400px;height:760px;border:0}</style>
<body><iframe id="m" src="%(pagina)s"></iframe>
<script>
document.getElementById("m").addEventListener("load", function () {
  var f = this;
  setTimeout(function () { document.title = f.contentDocument.title; }, 5200);
});
</script>"""


@unittest.skipUnless(CHROME, "Esta máquina no tiene Chrome: no se puede probar la cámara.")
class ElRecuadroSigueALaHoja(TestCase):

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
        html = html.replace("</body>", GUION % {"hoja": json.dumps(HOJA)})

        carpeta = tempfile.mkdtemp(prefix="gde-auto-")
        try:
            pagina = Path(carpeta) / "detalle.html"
            pagina.write_text(html, encoding="utf-8")
            marco = Path(carpeta) / "marco.html"
            marco.write_text(MARCO % {"pagina": pagina.as_uri()}, encoding="utf-8")
            salida = subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--allow-file-access-from-files", "--autoplay-policy=no-user-gesture-required",
                 "--virtual-time-budget=20000", "--window-size=560,820",
                 "--dump-dom", marco.as_uri()],
                capture_output=True, timeout=240,
                encoding="utf-8", errors="replace").stdout
            titulo = re.search(r"<title>(.*?)</title>", salida, re.S)
            if not titulo:
                raise AssertionError("Chrome no devolvió el resultado")
            return json.loads(titulo.group(1))
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)

    def medida(self):
        if ElRecuadroSigueALaHoja._cache is None:
            ElRecuadroSigueALaHoja._cache = self._mirar()
        return ElRecuadroSigueALaHoja._cache

    def test_la_camara_de_mentira_esta_andando(self):
        """Testigo: sin video no hay nada que detectar y todo lo demás mentiría."""
        v = self.medida()["video"]
        self.assertEqual((v["ancho"], v["alto"]), (640, 480))

    def test_arranca_detectando(self):
        m = self.medida()
        self.assertEqual(m["autoAlPrincipio"], "true")

    def _donde_se_ve_la_hoja(self, visor, video):
        """Dónde cae la hoja en la pantalla, en fracciones del visor.

        La hoja está puesta en fracciones del cuadro de la cámara, y el
        recuadro vive en fracciones de lo que se ve. No es lo mismo: el video
        llena el visor con `object-fit: cover`, o sea que sobra por los
        costados y esa parte no se ve.

        La cuenta se rehace acá a propósito, en vez de llamar a la del
        navegador: si se usara la misma función que está bajo prueba, el test
        diría que sí aunque estuviera mal. La función en sí se prueba aparte,
        con números a mano, en `tests_recuadro`.
        """
        escala = max(visor["ancho"] / video["ancho"], visor["alto"] / video["alto"])
        sobra_x = (video["ancho"] * escala - visor["ancho"]) / 2
        sobra_y = (video["alto"] * escala - visor["alto"]) / 2

        def en_x(f):
            return (f * video["ancho"] * escala - sobra_x) / visor["ancho"]

        def en_y(f):
            return (f * video["alto"] * escala - sobra_y) / visor["alto"]

        return {
            "x": en_x(HOJA["x"]), "y": en_y(HOJA["y"]),
            "an": en_x(HOJA["x"] + HOJA["an"]) - en_x(HOJA["x"]),
            "al": en_y(HOJA["y"] + HOJA["al"]) - en_y(HOJA["y"]),
        }

    def test_el_recuadro_se_para_solo_sobre_la_hoja(self):
        """Nadie lo tocó: llegó ahí mirando lo que ve la cámara."""
        m = self.medida()
        antes, ahora = m["marcoAlAbrir"], m["marcoSolo"]
        self.assertNotAlmostEqual(ahora["x"], antes["x"], places=2,
                                  msg="el recuadro no se movió: no está detectando")
        esperado = self._donde_se_ve_la_hoja(m["visor"], m["video"])
        for clave in ("x", "y", "an", "al"):
            self.assertAlmostEqual(
                ahora[clave], esperado[clave], delta=0.06,
                msg=f"«{clave}»: el recuadro no cayó sobre la hoja "
                    f"(quedó en {ahora}, la hoja se ve en {esperado})")

    def test_moverlo_a_mano_apaga_la_deteccion(self):
        """Si no se apagara, en un cuarto de segundo pisaría la corrección."""
        m = self.medida()
        self.assertEqual(m["autoTrasArrastrar"], "false")
        self.assertIn("Detección apagada", m["aviso"])

    def test_una_vez_apagada_el_recuadro_se_queda_quieto(self):
        self.assertTrue(self.medida()["sigueDondeLoDejaron"],
                        "el recuadro volvió solo a la hoja y borró la corrección")
