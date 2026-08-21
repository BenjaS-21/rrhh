"""La hoja de estilos tiene que llegar actualizada al navegador.

Un cambio de CSS que el navegador no busca de nuevo se ve exactamente igual que
un cambio que no se hizo: la pantalla queda con el estilo viejo y no hay forma
de darse cuenta desde el servidor.
"""

import os
import re
from pathlib import Path

from django.conf import settings
from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse


class VersionDeLaHojaDeEstilos(TestCase):

    def render(self, ruta="css/estilos.css"):
        return Template(
            "{% load estaticos %}{% estatico ruta %}"
        ).render(Context({"ruta": ruta}))

    def test_la_url_lleva_version(self):
        url = self.render()
        self.assertIn("/static/css/estilos.css?v=", url)

    def test_la_version_sale_de_la_fecha_del_archivo(self):
        archivo = Path(settings.BASE_DIR) / "static" / "css" / "estilos.css"
        esperada = str(int(archivo.stat().st_mtime))
        self.assertTrue(self.render().endswith(f"?v={esperada}"))

    def test_si_el_archivo_cambia_cambia_la_version(self):
        """Sin reiniciar nada: se lee el archivo en cada pantalla."""
        archivo = Path(settings.BASE_DIR) / "static" / "css" / "estilos.css"
        original = archivo.stat().st_mtime
        antes = self.render()
        try:
            os.utime(archivo, (original + 10, original + 10))
            self.assertNotEqual(self.render(), antes)
        finally:
            os.utime(archivo, (original, original))

    def test_un_archivo_que_no_existe_no_rompe_la_pantalla(self):
        """Preferible una URL sin versión que una página que no carga."""
        self.assertEqual(self.render("css/no-existe.css"), "/static/css/no-existe.css")

    def test_la_pantalla_de_login_ya_la_usa(self):
        cuerpo = self.client.get(reverse("cuentas:login")).content.decode()
        enlace = re.search(r'<link rel="stylesheet" href="([^"]+)"', cuerpo)
        self.assertIsNotNone(enlace)
        self.assertIn("?v=", enlace.group(1))
