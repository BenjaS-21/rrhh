"""En el telefono, los botones de la lista de pendientes tienen que alcanzarse.

La tabla no entra en una pantalla angosta y se desliza de costado, que es la
regla de la casa. Pero justo lo que queda afuera son las acciones, o sea que la
pagina se ve entera y no se puede usar: para eso esta la pantalla.

La columna de acciones queda pegada al borde derecho mientras el resto se
desliza por debajo. Aca se mide en un Chrome de verdad que los tres botones
esten dentro de la ventana, porque esto pasa en el navegador y no en el HTML.
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
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from cuentas.models import Sede, Zona
from expedientes.models import Documento, TipoDocumento, Trabajador
from expedientes.tests_escaner_imagen import CHROME

Usuario = get_user_model()
ANCHO = 560

GUION = """
<script>
window.addEventListener("load", function () {
  setTimeout(function () {
    var celda = document.querySelector("td.acciones");
    var r = {hayCelda: !!celda};
    if (celda) {
      var botones = celda.querySelectorAll(".btn");
      r.cuantosBotones = botones.length;
      r.todosVisibles = true;
      r.masADerecha = 0;
      for (var i = 0; i < botones.length; i++) {
        var c = botones[i].getBoundingClientRect();
        if (c.right > window.innerWidth + 1 || c.left < -1) { r.todosVisibles = false; }
        r.masADerecha = Math.max(r.masADerecha, c.right);
      }
      r.pegada = getComputedStyle(celda).position;
      // La celda tiene que tapar lo de atras, no dejarlo leer entre medio.
      r.tieneFondo = getComputedStyle(celda).backgroundColor;
      r.altoCelda = celda.getBoundingClientRect().height;
      r.altoFila = celda.parentNode.getBoundingClientRect().height;
    }
    r.laPaginaNoSeDesliza = document.body.scrollWidth <= window.innerWidth + 1;
    document.title = JSON.stringify(r);
  }, 600);
});
</script>
</body>"""


@unittest.skipUnless(CHROME, "Esta maquina no tiene Chrome.")
class LosBotonesSeAlcanzanEnElTelefono(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="TACHIRA")
        sede = Sede.objects.create(nombre="TIENDA SAN CRISTOBAL", zona=zona)
        tipo = TipoDocumento.objects.create(nombre="Cedula de identidad", orden=1)
        cls.admin = Usuario.objects.create_user(username="adm", password="x")
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()
        interior = Usuario.objects.create_user(username="lchacon", password="x")
        interior.rol = Usuario.Rol.RRHH_INTERIOR
        interior.save()

        t = Trabajador.objects.create(
            documento_identidad="30719983", nombres="MARIANA",
            apellidos="QUINTERO", sede=sede)
        doc = Documento.objects.create(
            trabajador=t, tipo=tipo,
            archivo=SimpleUploadedFile("cedula.pdf", b"%PDF-1.4 x"),
            nombre_original="cedula.pdf", subido_por=interior)
        doc.marcar(interior, "Un motivo largo para que la columna empuje")

    def _mirar(self):
        base = Path(settings.BASE_DIR)
        css = (base / "static" / "css" / "estilos.css").as_uri()
        self.client.force_login(self.admin)
        with override_settings(ALLOWED_HOSTS=["testserver"]):
            html = self.client.get(
                reverse("configuracion:pendientes")).content.decode()
        html = re.sub(r'href="/static/css/estilos\.css[^"]*"', f'href="{css}"', html)
        html = re.sub(r'<script src="/static/js/[^"]*"[^>]*></script>', "", html)
        html = html.replace("</body>", GUION)

        carpeta = tempfile.mkdtemp(prefix="gde-pend-")
        try:
            pagina = Path(carpeta) / "p.html"
            pagina.write_text(html, encoding="utf-8")
            salida = subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--allow-file-access-from-files", "--virtual-time-budget=9000",
                 f"--window-size={ANCHO},900", "--dump-dom", pagina.as_uri()],
                capture_output=True, timeout=180,
                encoding="utf-8", errors="replace").stdout
            titulo = re.search(r"<title>(.*?)</title>", salida, re.S)
            if not titulo:
                raise AssertionError("Chrome no devolvio el resultado")
            return json.loads(titulo.group(1))
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)

    def medida(self):
        if "_cache" not in type(self).__dict__:
            type(self)._cache = self._mirar()
        return type(self)._cache

    def test_estan_los_tres_botones(self):
        m = self.medida()
        self.assertTrue(m["hayCelda"], "no se encontro la celda de acciones")
        self.assertEqual(m["cuantosBotones"], 3)

    def test_entran_los_tres_en_la_pantalla(self):
        m = self.medida()
        self.assertTrue(
            m["todosVisibles"],
            f"algun boton queda fuera de los {ANCHO}px: el mas a la derecha "
            f"termina en {m['masADerecha']}")

    def test_la_columna_queda_pegada_al_borde(self):
        """Testigo: sin esto entran solo porque la tabla arranca sin deslizar."""
        self.assertEqual(self.medida()["pegada"], "sticky")

    def test_la_celda_tapa_lo_que_pasa_por_detras(self):
        """Sin fondo propio, el texto de las otras columnas se lee entre los botones."""
        fondo = self.medida()["tieneFondo"]
        self.assertNotIn("rgba(0, 0, 0, 0)", fondo, "la celda quedo transparente")

    def test_y_ocupa_todo_el_alto_de_la_fila(self):
        """Con `display:flex` en el `td` la celda se achica y deja ver por arriba."""
        m = self.medida()
        self.assertAlmostEqual(m["altoCelda"], m["altoFila"], delta=2)

    def test_la_pagina_entera_no_se_desliza(self):
        """La regla de la casa: se desliza la tabla dentro de su caja, no la pagina."""
        self.assertTrue(self.medida()["laPaginaNoSeDesliza"])
