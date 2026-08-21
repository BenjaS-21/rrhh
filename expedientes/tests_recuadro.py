"""Lo que queda adentro del recuadro es lo que se guarda.

El recuadro se dibuja sobre lo que se ve en el visor, pero la foto que saca la
cámara es más grande: el video se muestra con `object-fit: cover`, o sea que
llena la pantalla y le sobra por los costados o por arriba. Traducir de una
medida a la otra es la cuenta que decide qué pedazo del documento se guarda, y
si está corrida no hay ningún síntoma visible: sale un recorte equivocado y
listo.

Por eso se ejercita el JavaScript de verdad en un Chrome sin ventana, en vez de
confiar en leerlo.
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from expedientes.tests_escaner_imagen import CHROME, MODULO

PAGINA = """<!doctype html><meta charset=utf-8>
<body><div id="salida">sin resultado</div>
<script src="%(modulo)s"></script>
<script>
var api = window.EscanerImagen;
var r = {};

// Un teléfono común: visor alto y angosto, cámara apaisada. Al llenar el visor
// con `cover`, la foto se recorta por los costados y se ve solo el centro.
var CAJA = { ancho: 360, alto: 480 };
var FOTO = { ancho: 1920, alto: 1080 };

// Todo el visor -> la franja central de la foto, entera de arriba abajo.
r.todo = api.recuadroEnLaFoto({ x: 0, y: 0, an: 1, al: 1 }, CAJA, FOTO);

// La mitad de arriba del visor.
r.mitadArriba = api.recuadroEnLaFoto({ x: 0, y: 0, an: 1, al: 0.5 }, CAJA, FOTO);

// Un recuadro cualquiera, y su vuelta: tiene que caer donde estaba.
var marco = { x: 0.2, y: 0.15, an: 0.55, al: 0.6 };
var zona = api.recuadroEnLaFoto(marco, CAJA, FOTO);
r.marco = marco;
r.zona = zona;
r.vuelta = api.recuadroEnPantalla(zona, CAJA, FOTO);

// Con la pantalla girada la foto sobra por arriba y por abajo, no de costado.
var APAISADO = { ancho: 640, alto: 360 };
r.girado = api.recuadroEnLaFoto({ x: 0, y: 0, an: 1, al: 1 }, APAISADO, FOTO);

// El recuadro nunca puede pedir píxeles que la foto no tiene.
r.borde = api.recuadroEnLaFoto({ x: 0.97, y: 0.97, an: 0.5, al: 0.5 }, CAJA, FOTO);

document.getElementById("salida").textContent = JSON.stringify(r);
</script>"""


@unittest.skipUnless(CHROME, "Esta máquina no tiene Chrome: no se puede correr el JavaScript.")
class ElRecuadroApuntaDondeSeVe(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        carpeta = tempfile.mkdtemp(prefix="gde-recuadro-")
        try:
            pagina = Path(carpeta) / "prueba.html"
            pagina.write_text(PAGINA % {"modulo": MODULO.as_uri()}, encoding="utf-8")
            salida = subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--virtual-time-budget=8000", "--dump-dom", pagina.as_uri()],
                capture_output=True, timeout=120,
                encoding="utf-8", errors="replace").stdout
            crudo = re.search(r'<div id="salida">(.*?)</div>', salida, re.S)
            if not crudo:
                raise AssertionError("Chrome no devolvió el resultado")
            cls.r = json.loads(crudo.group(1))
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)

    def test_el_visor_entero_es_la_franja_que_se_ve_y_no_la_foto_entera(self):
        """Con `cover`, media foto queda fuera de pantalla: no se guarda."""
        todo = self.r["todo"]
        # 1080 de alto llenan los 480 del visor -> escala 0.444, y 360 px de
        # ancho de visor son 810 px de foto. Los otros 1110 no se ven.
        self.assertEqual(todo["alto"], 1080)
        self.assertAlmostEqual(todo["ancho"], 810, delta=2)
        self.assertAlmostEqual(todo["x"], (1920 - 810) / 2, delta=2)
        self.assertEqual(todo["y"], 0)

    def test_la_mitad_de_arriba_del_visor_es_la_mitad_de_arriba_de_la_foto(self):
        m = self.r["mitadArriba"]
        self.assertEqual(m["y"], 0)
        self.assertAlmostEqual(m["alto"], 540, delta=2)

    def test_ir_y_volver_devuelve_el_mismo_recuadro(self):
        """Es la garantía de que lo que se ve es lo que se guarda.

        `ajustarALaHoja` hace el camino de vuelta: si las dos cuentas no fueran
        una la inversa de la otra, el recuadro saltaría de lugar solo.
        """
        marco, vuelta = self.r["marco"], self.r["vuelta"]
        for clave in ("x", "y", "an", "al"):
            self.assertAlmostEqual(vuelta[clave], marco[clave], places=2,
                                   msg=f"«{clave}» no vuelve a su lugar")

    def test_con_la_pantalla_girada_sobra_por_arriba_y_no_de_costado(self):
        g = self.r["girado"]
        self.assertEqual(g["x"], 0)
        self.assertEqual(g["ancho"], 1920)
        self.assertAlmostEqual(g["alto"], 1080, delta=2)

    def test_nunca_pide_pixeles_que_la_foto_no_tiene(self):
        """Pedir de más hace que `getImageData` devuelva negro o reviente."""
        b = self.r["borde"]
        self.assertGreaterEqual(b["x"], 0)
        self.assertGreaterEqual(b["y"], 0)
        self.assertLessEqual(b["x"] + b["ancho"], 1920)
        self.assertLessEqual(b["y"] + b["alto"], 1080)
        self.assertGreater(b["ancho"], 0)
        self.assertGreater(b["alto"], 0)


class ElVisorYElRecorteMiranLoMismo(SimpleTestCase):
    """Barata y rápida: corre siempre, haya Chrome o no.

    El recorte se calcula suponiendo `cover`. Si mañana el CSS vuelve a
    `contain`, la cuenta queda corrida y el recorte agarra otro pedazo, sin que
    se note en la pantalla.
    """

    def test_el_video_se_muestra_con_cover(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "estilos.css").read_text(
            encoding="utf-8")
        regla = re.search(r"\.escaner__visor video \{[^}]*\}", css)
        self.assertTrue(regla, "no está la regla del video del escáner")
        self.assertIn("object-fit: cover", regla.group(0))
