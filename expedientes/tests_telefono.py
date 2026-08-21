"""Nada se sale de la pantalla de un teléfono chico.

"Unas cosas se cortan" es un reporte que no se puede verificar leyendo CSS: hay
que abrir cada pantalla al ancho de un teléfono y preguntarle al navegador
dónde terminó cada caja. Eso es lo que hace este módulo.

Chrome no deja achicar su ventana por debajo de ~522 px, así que la página va
adentro de un iframe de 360 px, que es un teléfono de los chicos de verdad
(un Galaxy A y cualquier gama baja andan por ahí).

Donde no hay Chrome, la clase se saltea: es verificación extra, no un requisito
para trabajar en el proyecto.
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
ANCHO_TELEFONO = 360

# Se listan las cajas que terminan fuera de la pantalla. Se perdonan las que
# están adentro de algo que scrollea a propósito —las tablas anchas viven en un
# `.tabla-scroll`, y ahí desbordar es la idea—.
GUION = """
<script>
window.addEventListener("load", function () {
  setTimeout(function () {
    function scrolleaSolo(e) {
      for (var n = e; n && n !== document.body; n = n.parentElement) {
        var o = getComputedStyle(n).overflowX;
        if (o === "auto" || o === "scroll") { return true; }
      }
      return false;
    }
    var fuera = [];
    document.querySelectorAll("body *").forEach(function (e) {
      var c = e.getBoundingClientRect();
      if (!c.width || scrolleaSolo(e)) { return; }
      if (c.right > window.innerWidth + 1 || c.left < -1) {
        fuera.push((e.tagName + "." + (e.className || "")).slice(0, 40)
                   + " «" + (e.textContent || "").trim().slice(0, 24) + "» "
                   + Math.round(c.left) + ".." + Math.round(c.right));
      }
    });
    document.title = JSON.stringify({
      ancho: document.documentElement.scrollWidth,
      ventana: window.innerWidth,
      fuera: fuera.slice(0, 6)
    });
  }, 400);
});
</script>
</body>"""

MARCO = """<!doctype html><meta charset=utf-8>
<style>html,body{margin:0}iframe{width:%(ancho)dpx;height:640px;border:0}</style>
<body><iframe id="m" src="%(pagina)s"></iframe>
<script>
document.getElementById("m").addEventListener("load", function () {
  var f = this;
  setTimeout(function () { document.title = f.contentDocument.title; }, 1200);
});
</script>"""


@unittest.skipUnless(CHROME, "Esta máquina no tiene Chrome: no se puede mirar la pantalla.")
class NadaSeSaleDeLaPantalla(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        sede = Sede.objects.create(nombre="CCCT", zona=zona)
        # Nombre largo y expediente casi vacío a propósito: así aparecen el
        # aviso de "faltan datos" y los textos que más empujan el ancho.
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="V-12345678", nombres="Ana Maria",
            apellidos="Alvarez Rodriguez", sede=sede)
        TipoDocumento.objects.create(nombre="Cédula")
        cls.admin = Usuario.objects.create_superuser(
            username="adm", password="Clave-De-Prueba-123", email="adm@damasco.test")
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def _medir(self, url, intruso=""):
        base = Path(settings.BASE_DIR)
        css = (base / "static" / "css" / "estilos.css").as_uri()
        with override_settings(ALLOWED_HOSTS=["testserver"]):
            html = self.client.get(url).content.decode()
        if intruso:
            html = html.replace("</main>", intruso + "</main>")
        html = re.sub(r'href="/static/css/estilos\.css[^"]*"', f'href="{css}"', html)
        # Los scripts no hacen falta para medir cajas y htmx no está en disco acá.
        html = re.sub(r'<script src="/static/js/[^"]*"[^>]*></script>', "", html)
        html = html.replace("</body>", GUION)

        carpeta = tempfile.mkdtemp(prefix="gde-telefono-")
        try:
            pagina = Path(carpeta) / "p.html"
            pagina.write_text(html, encoding="utf-8")
            marco = Path(carpeta) / "marco.html"
            marco.write_text(
                MARCO % {"pagina": pagina.as_uri(), "ancho": ANCHO_TELEFONO},
                encoding="utf-8")
            salida = subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--allow-file-access-from-files",
                 "--virtual-time-budget=9000", "--window-size=560,760",
                 "--dump-dom", marco.as_uri()],
                capture_output=True, timeout=180,
                # Windows decodifica en cp1252 y la página trae acentos.
                encoding="utf-8", errors="replace").stdout
            titulo = re.search(r"<title>(.*?)</title>", salida, re.S)
            if not titulo:
                raise AssertionError("Chrome no devolvió la medición")
            return json.loads(titulo.group(1))
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)

    def _pantallas(self):
        return {
            "panel": reverse("expedientes:panel"),
            "expedientes": reverse("expedientes:trabajador_list"),
            "detalle": reverse("expedientes:trabajador_detail", args=[self.trabajador.pk]),
            "editar": reverse("expedientes:trabajador_update", args=[self.trabajador.pk]),
            "nómina": reverse("expedientes:nomina"),
            "configuración": reverse("configuracion:index"),
            "tiendas": reverse("configuracion:lista", args=["tiendas"]),
            "invitaciones": reverse("cuentas:invitaciones"),
            "auditoría": reverse("expedientes:auditoria_list"),
        }

    def test_ninguna_pantalla_se_sale_a_lo_ancho(self):
        self.client.force_login(self.admin)
        for nombre, url in self._pantallas().items():
            with self.subTest(pantalla=nombre):
                medida = self._medir(url)
                self.assertEqual(
                    medida["fuera"], [],
                    f"en «{nombre}» hay cajas cortadas por el borde de la pantalla")
                self.assertLessEqual(
                    medida["ancho"], ANCHO_TELEFONO,
                    f"«{nombre}» obliga a mover la página de costado")

    def test_la_sonda_ve_lo_que_se_sale(self):
        """Testigo: se mete una caja más ancha que la pantalla a propósito.

        Sin esto, el test de arriba pasaría igual si la sonda estuviera rota y
        no midiera nada: una lista vacía de desbordes se lee igual que "todo
        bien". Acá tiene que aparecer el intruso y nadie más.
        """
        self.client.force_login(self.admin)
        medida = self._medir(
            reverse("expedientes:panel"),
            intruso='<div id="intruso" style="width:500px;height:8px"></div>')
        self.assertEqual(len(medida["fuera"]), 1, medida["fuera"])
        self.assertIn("DIV.", medida["fuera"][0])
        self.assertGreater(medida["ancho"], ANCHO_TELEFONO)
