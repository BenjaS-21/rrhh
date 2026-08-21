"""Un desplegable con muchas opciones tiene que dejar ver que son muchas.

Viene de un reporte: «cuando coloco una organización no me sale la mayoría de
los departamentos». Estaban todos: el sistema mandaba las 85 unidades
organizativas y el panel las dibujaba todas. Lo que fallaba era el alto —la
lista entraba en 240px, o sea SEIS opciones a la vez— y que nada decía que
hubiera más. Abrir, ver seis y concluir que el sistema no tiene el resto es la
lectura correcta de esa pantalla.

Así que se mide lo que se ve, no lo que se manda: cuántas entran de una y si el
panel dice cuántas hay en total.
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

from cuentas.models import Departamento, Sede, Zona
from expedientes.tests_buscable import MARCO
from expedientes.tests_escaner_imagen import CHROME

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"
CUANTAS = 40

GUION = """
<script>
window.addEventListener("load", function () {
  setTimeout(function () {
    var caja = document.getElementById("id_departamento").closest(".buscable");
    var r = {tieneBuscador: !!caja};
    if (caja) {
      caja.querySelector(".buscable__valor").click();
      var panel = caja.querySelector(".buscable__panel");
      var lista = caja.querySelector(".buscable__lista");
      var cuenta = caja.querySelector(".buscable__cuenta");
      var items = caja.querySelectorAll(".buscable__opcion");

      var cajaLista = lista.getBoundingClientRect();
      var dentro = 0;
      for (var i = 0; i < items.length; i++) {
        var c = items[i].getBoundingClientRect();
        if (c.top >= cajaLista.top - 1 && c.bottom <= cajaLista.bottom + 1) { dentro++; }
      }
      r.dibujadas = items.length;
      r.entranALaVista = dentro;
      r.sePuedeDeslizar = lista.scrollHeight > lista.clientHeight + 1;
      r.panelEntraEnLaPantalla =
        panel.getBoundingClientRect().bottom <= window.innerHeight + 1;
      r.cuenta = cuenta ? cuenta.textContent : null;
      r.cuentaVisible = !!cuenta && !cuenta.hidden;

      // Y al filtrar, cuántas quedaron de cuántas.
      var buscar = caja.querySelector(".buscable__buscar");
      buscar.value = "gerencia 7";
      buscar.dispatchEvent(new Event("input"));
      r.cuentaFiltrada = cuenta ? cuenta.textContent : null;
    }
    document.title = JSON.stringify(r);
  }, 700);
});
</script>
</body>"""


@unittest.skipUnless(CHROME, "Esta maquina no tiene Chrome.")
class ConMuchasUnidadesSeVenMuchas(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        Sede.objects.create(nombre="TRINIDAD", zona=zona)
        for i in range(1, CUANTAS + 1):
            Departamento.objects.create(nombre=f"GERENCIA {i}")
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def _manejar(self):
        base = Path(settings.BASE_DIR)
        css = (base / "static" / "css" / "estilos.css").as_uri()
        self.client.force_login(self.admin)
        with override_settings(ALLOWED_HOSTS=["testserver"]):
            html = self.client.get(
                reverse("expedientes:trabajador_create")).content.decode()
        html = re.sub(r'href="/static/css/estilos\.css[^"]*"', f'href="{css}"', html)
        html = re.sub(r'<script src="/static/js/htmx[^"]*"[^>]*></script>', "", html)
        html = re.sub(
            r'src="/static/js/([\w-]+)\.js[^"]*"',
            lambda m: 'src="%s"' % (base / "static" / "js" / f"{m.group(1)}.js").as_uri(),
            html)
        html = html.replace("</body>", GUION)

        carpeta = tempfile.mkdtemp(prefix="gde-largo-")
        try:
            pagina = Path(carpeta) / "p.html"
            pagina.write_text(html, encoding="utf-8")
            marco = Path(carpeta) / "marco.html"
            marco.write_text(MARCO % {"pagina": pagina.as_uri()}, encoding="utf-8")
            salida = subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--allow-file-access-from-files",
                 "--virtual-time-budget=9000", "--window-size=560,900",
                 "--dump-dom", marco.as_uri()],
                capture_output=True, timeout=180,
                encoding="utf-8", errors="replace").stdout
            titulo = re.search(r"<title>(.*?)</title>", salida, re.S)
            if not titulo:
                raise AssertionError("Chrome no devolvio el resultado")
            return json.loads(titulo.group(1))
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)

    def medida(self):
        """Una sola pasada de Chrome por clase.

        Se guarda en el `__dict__` de la clase concreta y no con `hasattr`: la
        clase de abajo hereda estos tests con OTROS datos, y `hasattr` habría
        encontrado el resultado del padre y medido lo que no era.
        """
        clase = type(self)
        if "_cache" not in clase.__dict__:
            clase._cache = self._manejar()
        return clase.__dict__["_cache"]

    def test_estan_todas_dibujadas(self):
        """Testigo: el problema nunca fue que faltaran; era que no se veían."""
        # Las 40 más la vacía de "— Elegí… —".
        self.assertEqual(self.medida()["dibujadas"], CUANTAS + 1)

    def test_entran_bastantes_de_una_sola_vez(self):
        """Con 240px de alto entraban SEIS de 85. Seis se lee como «hay seis»."""
        entran = self.medida()["entranALaVista"]
        self.assertGreaterEqual(
            entran, 9,
            f"solo entran {entran} opciones a la vista: el resto parece no existir")

    def test_el_panel_sigue_entrando_en_la_pantalla(self):
        """Testigo del de arriba: agrandarlo no puede empujarlo fuera de la vista."""
        self.assertTrue(self.medida()["panelEntraEnLaPantalla"],
                        "el panel crecio hasta salirse de la pantalla")

    def test_dice_cuantas_opciones_hay_en_total(self):
        """Lo que faltaba: que se sepa que la lista sigue más abajo."""
        m = self.medida()
        self.assertTrue(m["cuentaVisible"])
        self.assertIn(f"{CUANTAS} opciones", m["cuenta"])
        self.assertIn("deslizá", m["cuenta"])

    def test_se_puede_deslizar_para_ver_el_resto(self):
        self.assertTrue(self.medida()["sePuedeDeslizar"])

    def test_al_buscar_dice_cuantas_quedaron_de_cuantas(self):
        """«1 de 40» explica por qué se ve poco; una lista corta y muda, no."""
        self.assertEqual(self.medida()["cuentaFiltrada"], f"1 de {CUANTAS}")


@unittest.skipUnless(CHROME, "Esta maquina no tiene Chrome.")
class ConPocasOpcionesNoMolesta(ConMuchasUnidadesSeVenMuchas):
    """Testigo del renglón de la cuenta: con pocas opciones no dice de más.

    Si el aviso de «deslizá» saliera siempre, no estaría informando nada.
    """

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        Sede.objects.create(nombre="TRINIDAD", zona=zona)
        for i in range(1, 10):        # nueve: pasa el mínimo del buscador
            Departamento.objects.create(nombre=f"GERENCIA {i}")
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def test_estan_todas_dibujadas(self):
        self.assertEqual(self.medida()["dibujadas"], 10)

    def test_entran_bastantes_de_una_sola_vez(self):
        self.assertEqual(self.medida()["entranALaVista"], 10)

    def test_dice_cuantas_opciones_hay_en_total(self):
        m = self.medida()
        self.assertEqual(m["cuenta"], "9 opciones")

    def test_se_puede_deslizar_para_ver_el_resto(self):
        self.assertFalse(self.medida()["sePuedeDeslizar"],
                         "nueve opciones entran enteras: no hay nada que deslizar")

    def test_al_buscar_dice_cuantas_quedaron_de_cuantas(self):
        self.assertEqual(self.medida()["cuentaFiltrada"], "1 de 9")
