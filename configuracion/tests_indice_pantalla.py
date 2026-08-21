"""El índice de Configuración, medido en un Chrome de verdad y en un teléfono.

Las tarjetas tienen `overflow: hidden`: un botón que no entra no se acomoda, se
corta, y en el teléfono ni se sospecha que estaba. Ya pasó una vez con la × del
escáner, así que acá se mide en vez de mirar el código y suponer.

Se usa un iframe de 360px porque Chrome no abre ventanas más angostas que ~522px:
pedir `--window-size=360` da 522 y la medición no diría nada del teléfono.
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

from expedientes.tests_escaner_imagen import CHROME

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"
ANCHO_TELEFONO = 360

GUION = """
<script>
window.addEventListener("load", function () {
  var botones = [];
  document.querySelectorAll(".catalogo").forEach(function (tarjeta) {
    var caja = tarjeta.getBoundingClientRect();
    tarjeta.querySelectorAll(".catalogo__acciones .btn").forEach(function (b) {
      var m = b.getBoundingClientRect();
      botones.push({
        texto: b.textContent.trim(),
        sobra: Math.round(Math.max(0, m.right - caja.right)),
        visible: m.width > 0 && m.height > 0
      });
    });
  });
  document.title = JSON.stringify({
    botones: botones,
    desbordePagina: document.documentElement.scrollWidth
                  - document.documentElement.clientWidth
  });
});
</script>
</body>"""


@unittest.skipUnless(CHROME, "Esta maquina no tiene Chrome.")
class LosBotonesDeCadaTarjetaEntran(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def _medir(self):
        base = Path(settings.BASE_DIR)
        css = (base / "static" / "css" / "estilos.css").as_uri()
        self.client.force_login(self.admin)
        with override_settings(ALLOWED_HOSTS=["testserver"]):
            html = self.client.get(reverse("configuracion:index")).content.decode()
        html = re.sub(r'href="/static/css/estilos\.css[^"]*"', f'href="{css}"', html)
        html = re.sub(r'<script src="/static/js/[^"]*"[^>]*></script>', "", html)
        html = html.replace("</body>", GUION)

        carpeta = tempfile.mkdtemp(prefix="gde-indice-")
        try:
            (Path(carpeta) / "p.html").write_text(html, encoding="utf-8")
            marco = Path(carpeta) / "marco.html"
            marco.write_text(
                '<body style="margin:0"><iframe src="p.html" '
                f'style="width:{ANCHO_TELEFONO}px;height:1200px;border:0" '
                'onload="setTimeout(function(){document.title='
                'frames[0].document.title},600)"></iframe>',
                encoding="utf-8")
            salida = subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--allow-file-access-from-files", "--virtual-time-budget=9000",
                 "--window-size=900,1200", "--dump-dom", marco.as_uri()],
                capture_output=True, timeout=180,
                encoding="utf-8", errors="replace").stdout
            titulo = re.search(r"<title>(.*?)</title>", salida, re.S)
            if not titulo:
                raise AssertionError("Chrome no devolvio el resultado")
            return json.loads(titulo.group(1))
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)

    def medida(self):
        if not hasattr(LosBotonesDeCadaTarjetaEntran, "_cache"):
            LosBotonesDeCadaTarjetaEntran._cache = self._medir()
        return LosBotonesDeCadaTarjetaEntran._cache

    def test_hay_dos_botones_por_tarjeta(self):
        """Testigo: si no se dibujara ninguno, «nada se corta» daría verde."""
        botones = self.medida()["botones"]
        self.assertGreaterEqual(len(botones), 16)
        self.assertEqual(
            len([b for b in botones if b["texto"] == "Ver listado"]),
            len(botones) // 2)

    def test_ninguno_se_sale_de_su_tarjeta(self):
        cortados = [b for b in self.medida()["botones"] if b["sobra"] > 0]
        self.assertEqual(cortados, [], f"a 360px se cortan: {cortados}")

    def test_todos_se_dibujan(self):
        invisibles = [b["texto"] for b in self.medida()["botones"]
                      if not b["visible"]]
        self.assertEqual(invisibles, [])

    def test_la_pagina_no_se_va_para_el_costado(self):
        self.assertEqual(self.medida()["desbordePagina"], 0)
