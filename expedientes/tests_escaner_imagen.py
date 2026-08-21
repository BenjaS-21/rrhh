"""El recorte de la hoja y el filtro de escáner, ejercitados de verdad.

Ese código corre en el navegador del teléfono, así que Django no lo puede
ejecutar. Lo que se hace acá es armar una foto simulada —hoja blanca sobre un
escritorio oscuro, con la sombra que deja el cuerpo al sacar la foto— y
correrle encima el JavaScript real en un Chrome sin ventana.

Donde no hay Chrome, la clase se saltea entera: es una verificación extra, no
un requisito para trabajar en el proyecto.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

MODULO = Path(settings.BASE_DIR) / "static" / "js" / "escaner-imagen.js"


def _buscar_chrome():
    for nombre in ("chrome", "google-chrome", "chromium"):
        ruta = shutil.which(nombre)
        if ruta:
            return ruta
    candidatos = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for ruta in candidatos:
        if os.path.exists(ruta):
            return ruta
    return None


CHROME = _buscar_chrome()

PAGINA = """<!doctype html><meta charset=utf-8>
<body><div id="salida">sin resultado</div>
<script src="%(modulo)s"></script>
<script>
var ANCHO = 900, ALTO = 1200, PAPEL = %(papel)s;
var lienzo = document.createElement("canvas");
lienzo.width = ANCHO; lienzo.height = ALTO;
var c = lienzo.getContext("2d");
c.fillStyle = "#4a4237"; c.fillRect(0, 0, ANCHO, ALTO);
c.fillStyle = "#fff"; c.fillRect(PAPEL.x, PAPEL.y, PAPEL.w, PAPEL.h);
c.fillStyle = "#111";
var renglones = [];
var cuantos = Math.floor((PAPEL.h - 110) / 40);
for (var i = 0; i < cuantos; i++) {
  var ry = PAPEL.y + 70 + i * 40, rx = PAPEL.x + 50, rw = PAPEL.w - 100 - (i %% 4) * 30;
  c.fillRect(rx, ry, rw, 12);
  renglones.push({ x: rx, y: ry, w: rw });
}
%(sombra)s
var api = window.EscanerImagen;
var recorte = api.buscarHoja(api.aGris(c.getImageData(0, 0, ANCHO, ALTO)), ANCHO, ALTO);

var salida = document.createElement("canvas");
salida.width = recorte.ancho; salida.height = recorte.alto;
var s = salida.getContext("2d");
s.drawImage(lienzo, recorte.x, recorte.y, recorte.ancho, recorte.alto,
            0, 0, recorte.ancho, recorte.alto);

// Antes de filtrar: sirve de testigo de que la sombra realmente está pintada.
// Sin esta medición, "el filtro borra la sombra" pasaría igual aunque la foto
// simulada no tuviera ninguna sombra.
var crudo = s.getImageData(0, 0, recorte.ancho, recorte.alto).data;
var claros = 0;
for (var k = 0; k < crudo.length; k += 4) { if (crudo[k] > 235) claros++; }
var blancoCrudo = Math.round(claros / (crudo.length / 4) * 100);

s.putImageData(api.filtroEscaner(s.getImageData(0, 0, recorte.ancho, recorte.alto)), 0, 0);

var px = s.getImageData(0, 0, recorte.ancho, recorte.alto).data;
var blancos = 0, negros = 0;
for (var i = 0; i < px.length; i += 4) {
  if (px[i] > 235) blancos++; else if (px[i] < 60) negros++;
}
function valor(x, y) {
  var i = ((y - recorte.y) * recorte.ancho + (x - recorte.x)) * 4;
  return px[i];
}
var conTinta = 0, papelBlanco = 0;
renglones.forEach(function (r) {
  if (valor(r.x + 10, r.y + 6) < 90) conTinta++;
  if (valor(r.x + r.w + 30, r.y + 6) > 200) papelBlanco++;
});
document.getElementById("salida").textContent = JSON.stringify({
  recorte: recorte, papel: PAPEL, hallada: recorte.hallada, blancoCrudo: blancoCrudo,
  blanco: Math.round(blancos / (px.length / 4) * 100),
  negro: Math.round(negros / (px.length / 4) * 100),
  renglones: renglones.length, conTinta: conTinta, papelBlanco: papelBlanco
});
</script>"""

SOMBRA = """
var g = c.createLinearGradient(0, 0, ANCHO, ALTO);
g.addColorStop(0, "rgba(0,0,0,0)"); g.addColorStop(1, "rgba(0,0,0,0.45)");
c.fillStyle = g; c.fillRect(0, 0, ANCHO, ALTO);
"""


@unittest.skipUnless(CHROME, "Esta máquina no tiene Chrome: no se puede correr el JavaScript.")
class RecorteYFiltro(SimpleTestCase):
    """La foto simulada entra sucia y tiene que salir como fotocopia."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.con_sombra = cls._correr(SOMBRA)
        cls.sin_sombra = cls._correr("")
        cls.chica = cls._correr("", cls.HOJA_CHICA)
        cls.vacia = cls._correr("", cls.SIN_HOJA)

    # Una hoja grande, apoyada de frente: el caso de todos los días.
    HOJA_GRANDE = "{ x: 120, y: 90, w: 640, h: 980 }"
    # Una cédula, o una hoja sacada desde más lejos: no llega ni a un tercio
    # del encuadre. Este es el caso que antes se perdía.
    HOJA_CHICA = "{ x: 300, y: 400, w: 280, h: 380 }"
    # La cámara mirando la mesa sola, una pared, o tapada: no hay hoja.
    SIN_HOJA = "{ x: 0, y: 0, w: 0, h: 0 }"

    @classmethod
    def _correr(cls, sombra, papel=None):
        carpeta = tempfile.mkdtemp(prefix="gde-escaner-")
        try:
            pagina = Path(carpeta) / "prueba.html"
            pagina.write_text(
                PAGINA % {"modulo": MODULO.as_uri(), "sombra": sombra,
                          "papel": papel or cls.HOJA_GRANDE},
                encoding="utf-8")
            salida = subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--virtual-time-budget=8000", "--dump-dom", pagina.as_uri()],
                capture_output=True, timeout=120,
                # Windows decodifica en cp1252 por defecto y la página trae
                # acentos y emojis: sin esto, la salida de Chrome se rompe.
                encoding="utf-8", errors="replace",
            ).stdout
            crudo = re.search(r'<div id="salida">(.*?)</div>', salida, re.S)
            if not crudo:
                raise AssertionError("Chrome no devolvió el resultado")
            return json.loads(crudo.group(1))
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)

    # --- Encontrar la hoja ----------------------------------------------------
    def test_encuentra_la_hoja_dentro_del_encuadre(self):
        """El recorte cae sobre el papel, no sobre el escritorio."""
        r, papel = self.con_sombra["recorte"], self.con_sombra["papel"]
        self.assertAlmostEqual(r["x"], papel["x"], delta=20)
        self.assertAlmostEqual(r["y"], papel["y"], delta=20)
        self.assertAlmostEqual(r["ancho"], papel["w"], delta=40)
        self.assertAlmostEqual(r["alto"], papel["h"], delta=40)

    def test_no_se_come_el_borde_de_la_hoja(self):
        """Mejor un poco de escritorio que perder la primera línea del texto."""
        r, papel = self.con_sombra["recorte"], self.con_sombra["papel"]
        self.assertLessEqual(r["x"], papel["x"])
        self.assertLessEqual(r["y"], papel["y"])
        self.assertGreaterEqual(r["x"] + r["ancho"], papel["x"] + papel["w"])
        self.assertGreaterEqual(r["y"] + r["alto"], papel["y"] + papel["h"])

    def test_saca_el_escritorio_de_alrededor(self):
        r = self.con_sombra["recorte"]
        self.assertLess(r["ancho"] * r["alto"], 900 * 1200 * 0.75)

    # --- El filtro ------------------------------------------------------------
    def test_el_papel_queda_blanco(self):
        self.assertGreater(self.con_sombra["blanco"], 65)

    def test_la_letra_sigue_negra(self):
        self.assertGreater(self.con_sombra["negro"], 10)

    def test_no_se_pierde_ningun_renglon(self):
        r = self.con_sombra
        self.assertEqual(r["conTinta"], r["renglones"])

    def test_la_foto_simulada_tiene_sombra_de_verdad(self):
        """Testigo del test de abajo.

        Si la sombra no estuviera pintada, "el filtro la borra" pasaría sin
        que el filtro hiciera nada.
        """
        # Sin sombra el papel ya sale blanco; con sombra, casi nada llega a
        # blanco: 77% contra 2%. Esa diferencia es la sombra.
        self.assertGreater(self.sin_sombra["blancoCrudo"], 60)
        self.assertLess(self.con_sombra["blancoCrudo"], 20)

    def test_borra_la_sombra_del_cuerpo(self):
        """Un umbral fijo dejaría la esquina sombreada entera en negro.

        Se compara la misma hoja con y sin sombra: antes del filtro son muy
        distintas (lo dice el test de arriba) y después tienen que quedar
        prácticamente iguales. Eso es lo que separa una foto de un escaneo.
        """
        self.assertAlmostEqual(self.con_sombra["blanco"],
                               self.sin_sombra["blanco"], delta=6)
        self.assertEqual(self.con_sombra["papelBlanco"],
                         self.con_sombra["renglones"])

    def test_el_papel_al_lado_del_texto_no_se_ensucia(self):
        r = self.con_sombra
        self.assertEqual(r["papelBlanco"], r["renglones"])

    # --- Hojas que no llenan el encuadre --------------------------------------
    def test_encuentra_una_hoja_que_no_llega_a_la_mitad_del_encuadre(self):
        """Una cédula, o una hoja sacada desde más lejos.

        El corte se medía contra el ancho de la foto ("más de la mitad de la
        fila tiene que ser clara"), y una hoja chica nunca llega. Antes se
        devolvía la foto entera: el documento quedaba perdido en el medio de la
        mesa, chiquito y torcido.
        """
        r, papel = self.chica["recorte"], self.chica["papel"]
        self.assertAlmostEqual(r["x"], papel["x"], delta=20)
        self.assertAlmostEqual(r["y"], papel["y"], delta=20)
        self.assertAlmostEqual(r["ancho"], papel["w"], delta=30)
        self.assertAlmostEqual(r["alto"], papel["h"], delta=30)

    def test_la_hoja_chica_es_chica_de_verdad(self):
        """Testigo del de arriba: sin esto no probaría el caso difícil."""
        papel = self.chica["papel"]
        self.assertLess(papel["w"], 900 * 0.5)
        self.assertLess(papel["h"], 1200 * 0.5)

    def test_tambien_a_la_hoja_chica_no_se_le_come_ningun_renglon(self):
        r = self.chica
        self.assertGreater(r["renglones"], 3)
        self.assertEqual(r["conTinta"], r["renglones"])

    # --- Cuando no hay ninguna hoja -------------------------------------------
    def test_dice_cuando_encontro_la_hoja(self):
        self.assertTrue(self.con_sombra["hallada"])
        self.assertTrue(self.chica["hallada"])

    def test_una_superficie_lisa_no_es_una_hoja(self):
        """La cámara apuntando a la mesa sola, a una pared, o tapada.

        Antes esto salía como "hoja encontrada, del tamaño de la pantalla":
        todas las filas son igual de claras, así que la franja va de borde a
        borde. Buscando en vivo, el recuadro se abría de par en par cada vez
        que la cámara perdía la hoja de vista.
        """
        self.assertFalse(self.vacia["hallada"])
