"""Los desplegables largos se pueden buscar escribiendo.

Con 49 tiendas, elegir una en un desplegable común es bajar la lista entera
mirando. Acá se comprueba que el buscador aparece donde hace falta, que filtra
de verdad, y —lo más importante— que el `<select>` de siempre sigue siendo el
que manda: es el que se envía, el que valida el navegador y del que dependen
los otros scripts de la página.

Se maneja el desplegable en un Chrome de verdad, porque la pregunta que importa
es si al escribir y tocar una opción queda elegida, y eso no se lee en el
código.
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

from cuentas.models import Cargo, Departamento, Sede, Zona
from expedientes.models import Trabajador
from expedientes.tests_escaner_imagen import CHROME

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"

FIN = """
<script>
window.addEventListener("load", function () {
  setTimeout(function () {
    var r = {};
    var sede = document.getElementById("id_sede");
    var caja = sede.closest(".buscable");
    r.tieneBuscador = !!caja;

    if (caja) {
      var boton = caja.querySelector(".buscable__valor");
      var buscar = caja.querySelector(".buscable__buscar");
      r.panelCerradoAlPrincipio = caja.querySelector(".buscable__panel").hidden;

      boton.click();
      r.panelAbierto = !caja.querySelector(".buscable__panel").hidden;
      // La tienda está al final de un formulario largo: abajo no hay lugar.
      r.seAbreHaciaArriba = caja.classList.contains("buscable--arriba");
      var cajaPanel = caja.querySelector(".buscable__panel").getBoundingClientRect();
      r.panelEntraEnLaPantalla =
        cajaPanel.top >= -1 && cajaPanel.bottom <= window.innerHeight + 1;
      r.opcionesAlAbrir = caja.querySelectorAll(".buscable__opcion").length;

      // Sin acento y en minúscula: tiene que encontrar "MÉRIDA".
      buscar.value = "merida";
      buscar.dispatchEvent(new Event("input"));
      r.textosFiltrados = Array.prototype.map.call(
        caja.querySelectorAll(".buscable__opcion"),
        function (e) { return e.firstChild.textContent; });

      // Lo que importa: al tocarla, ¿queda elegida en el select de verdad?
      var avisos = 0;
      sede.addEventListener("change", function () { avisos++; });
      caja.querySelector(".buscable__opcion").click();
      r.avisoDeCambio = avisos;
      r.valorDelSelect = sede.options[sede.selectedIndex].text;
      r.textoDelBoton = boton.textContent.trim();
      r.panelCerradoAlElegir = caja.querySelector(".buscable__panel").hidden;

      // Nada coincide.
      boton.click();
      buscar.value = "zzzzz";
      buscar.dispatchEvent(new Event("input"));
      r.sinResultados = caja.querySelectorAll(".buscable__opcion").length;
      r.avisaQueNoHay = !caja.querySelector(".buscable__nada").hidden;
      boton.click();
    }

    // Un desplegable corto se deja como está: el del teléfono es mejor.
    var unidad = document.getElementById("id_departamento");
    r.cortoTieneBuscador = !!unidad.closest(".buscable");
    r.opcionesDelCorto = unidad.options.length;

    // El cargo se rehace al cambiar de unidad: el buscador tiene que enterarse.
    var cargo = document.getElementById("id_puesto");
    r.cargoTieneBuscador = !!cargo.closest(".buscable");
    if (cargo.closest(".buscable")) {
      unidad.value = unidad.options[1].value;
      unidad.dispatchEvent(new Event("change"));
      var cajaCargo = cargo.closest(".buscable");
      cajaCargo.querySelector(".buscable__valor").click();
      var ops = cajaCargo.querySelectorAll(".buscable__opcion");
      r.cargosOfrecidos = ops.length;
      r.cargosEnElSelect = cargo.options.length;
      r.unidadPuesta = unidad.options[unidad.selectedIndex].text;
      // El grupo va en un <span> aparte: dice de que unidad es cada cargo.
      r.gruposDeLosPrimeros = Array.prototype.slice.call(ops, 1, 4).map(
        function (e) {
          var g = e.querySelector(".buscable__grupo");
          return g ? g.textContent : "";
        });
    }

    document.title = JSON.stringify(r);
  }, 500);
});
</script>
</body>"""

FILTRO = """
<script>
window.addEventListener("load", function () {
  setTimeout(function () {
    var r = {};
    var panel = document.querySelector(".multi__panel");
    var buscar = panel.querySelector(".buscable__buscar");
    r.tieneBuscador = !!buscar;
    var etiquetas = panel.querySelectorAll("label");
    r.tiendas = etiquetas.length;
    if (buscar) {
      buscar.value = "merida";
      buscar.dispatchEvent(new Event("input"));
      r.visibles = Array.prototype.filter.call(etiquetas, function (l) {
        return l.getBoundingClientRect().height > 0;
      }).map(function (l) { return l.textContent.trim(); });

      // Las casillas marcadas no se pierden al filtrar: siguen enviándose.
      var casilla = panel.querySelector('input[type=checkbox]');
      casilla.checked = true;
      buscar.value = "zzz";
      buscar.dispatchEvent(new Event("input"));
      r.sigueMarcada = casilla.checked;
      r.avisaQueNoHay = !panel.querySelector(".buscable__nada").hidden;
    }
    document.title = JSON.stringify(r);
  }, 500);
});
</script>
</body>"""

MARCO = """<!doctype html><meta charset=utf-8>
<style>html,body{margin:0}iframe{width:400px;height:820px;border:0}</style>
<body><iframe id="m" src="%(pagina)s"></iframe>
<script>
document.getElementById("m").addEventListener("load", function () {
  var f = this;
  setTimeout(function () { document.title = f.contentDocument.title; }, 1400);
});
</script>"""


@unittest.skipUnless(CHROME, "Esta máquina no tiene Chrome: no se puede manejar el desplegable.")
class LosDesplegablesLargosSeBuscan(TestCase):

    @classmethod
    def setUpTestData(cls):
        # Doce tiendas repartidas en dos zonas: pasa el mínimo para que valga
        # la pena el buscador, y hay una con acento para probar la búsqueda.
        miranda = Zona.objects.create(nombre="MIRANDA")
        andes = Zona.objects.create(nombre="ANDES")
        Sede.objects.create(nombre="MÉRIDA CENTRO", zona=andes)
        Sede.objects.create(nombre="MÉRIDA SUR", zona=andes)
        for i in range(10):
            Sede.objects.create(nombre=f"CARACAS {i}", zona=miranda)

        ventas = Departamento.objects.create(nombre="VENTAS")
        deposito = Departamento.objects.create(nombre="DEPOSITO")
        for i in range(9):
            Cargo.objects.create(nombre=f"VENDEDOR {i}", departamento=ventas)
        for i in range(4):
            Cargo.objects.create(nombre=f"MONTACARGUISTA {i}", departamento=deposito)

        cls.trabajador = Trabajador.objects.create(
            documento_identidad="V-1", nombres="Ana", apellidos="Alvarez",
            sede=Sede.objects.first())
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def _manejar(self, url, guion):
        base = Path(settings.BASE_DIR)
        css = (base / "static" / "css" / "estilos.css").as_uri()
        with override_settings(ALLOWED_HOSTS=["testserver"]):
            html = self.client.get(url).content.decode()
        html = re.sub(r'href="/static/css/estilos\.css[^"]*"', f'href="{css}"', html)
        html = re.sub(r'<script src="/static/js/htmx[^"]*"[^>]*></script>', "", html)
        html = re.sub(
            r'src="/static/js/([\w-]+)\.js[^"]*"',
            lambda m: 'src="%s"' % (base / "static" / "js" / f"{m.group(1)}.js").as_uri(),
            html)
        html = html.replace("</body>", guion)

        carpeta = tempfile.mkdtemp(prefix="gde-buscable-")
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
                raise AssertionError("Chrome no devolvió el resultado")
            return json.loads(titulo.group(1))
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)

    @classmethod
    def _cache(cls, clave, hacer):
        if not hasattr(cls, "_guardado"):
            cls._guardado = {}
        if clave not in cls._guardado:
            cls._guardado[clave] = hacer()
        return cls._guardado[clave]

    def alta(self):
        self.client.force_login(self.admin)
        return self._cache("alta", lambda: self._manejar(
            reverse("expedientes:trabajador_create"), FIN))

    def filtro(self):
        self.client.force_login(self.admin)
        return self._cache("filtro", lambda: self._manejar(
            reverse("expedientes:trabajador_list"), FILTRO))

    # --- El alta de un expediente ---------------------------------------------
    def test_la_tienda_tiene_buscador(self):
        r = self.alta()
        self.assertTrue(r["tieneBuscador"], "el desplegable de tienda quedó pelado")
        self.assertTrue(r["panelCerradoAlPrincipio"])
        self.assertTrue(r["panelAbierto"])
        self.assertGreaterEqual(r["opcionesAlAbrir"], 12)

    def test_el_panel_no_se_abre_fuera_de_la_pantalla(self):
        """La tienda está al final de un formulario largo: si se abre para
        abajo, la lista queda medio tapada por el borde y no hay cómo verla."""
        r = self.alta()
        self.assertTrue(r["seAbreHaciaArriba"],
                        "abajo no había lugar y se abrió igual para abajo")
        self.assertTrue(r["panelEntraEnLaPantalla"])

    def test_buscar_sin_acentos_encuentra_igual(self):
        """Nadie escribe «MÉRIDA» con acento y en mayúscula para buscar."""
        encontradas = self.alta()["textosFiltrados"]
        self.assertEqual(len(encontradas), 2, encontradas)
        for texto in encontradas:
            self.assertIn("MÉRIDA", texto)

    def test_elegir_una_opcion_la_deja_puesta_en_el_select_de_verdad(self):
        """Es lo que se envía al servidor: si no queda ahí, no se guarda nada."""
        r = self.alta()
        self.assertIn("MÉRIDA", r["valorDelSelect"])
        self.assertEqual(r["textoDelBoton"], r["valorDelSelect"])
        self.assertTrue(r["panelCerradoAlElegir"])

    def test_elegir_avisa_al_resto_de_la_pagina(self):
        """Sin el aviso de cambio, la búsqueda en vivo y el filtro de cargos
        por unidad se quedarían dormidos."""
        self.assertEqual(self.alta()["avisoDeCambio"], 1)

    def test_cuando_no_hay_nada_lo_dice(self):
        r = self.alta()
        self.assertEqual(r["sinResultados"], 0)
        self.assertTrue(r["avisaQueNoHay"], "una lista vacía sin explicación")

    def test_un_desplegable_corto_se_deja_como_estaba(self):
        """Para tres opciones, el desplegable del teléfono es mejor."""
        r = self.alta()
        self.assertLess(r["opcionesDelCorto"], 8)
        self.assertFalse(r["cortoTieneBuscador"])

    def test_la_unidad_ordena_los_cargos_pero_no_los_recorta(self):
        """El script vacía y rellena el select; el buscador tiene que enterarse.

        Elegir la unidad NO saca cargos de la lista: los 13 siguen ahí, con los
        de la unidad elegida arriba de todo.
        """
        r = self.alta()
        self.assertTrue(r["cargoTieneBuscador"])
        self.assertEqual(r["cargosOfrecidos"], r["cargosEnElSelect"])
        # 13 cargos + el renglón vacío.
        self.assertEqual(r["cargosOfrecidos"], 14, "elegir la unidad recortó la lista")

    def test_y_los_de_la_unidad_elegida_van_primero(self):
        """Testigo del de arriba: ofrecer todo sin ordenar no sería una mejora."""
        r = self.alta()
        self.assertEqual(r["gruposDeLosPrimeros"],
                         [r["unidadPuesta"]] * 3)

    # --- El filtro de tiendas del listado -------------------------------------
    def test_el_filtro_de_tiendas_tiene_buscador(self):
        r = self.filtro()
        self.assertTrue(r["tieneBuscador"], "el panel de tiendas quedó sin buscar")
        self.assertEqual(r["tiendas"], 12)

    def test_el_filtro_deja_solo_lo_buscado(self):
        visibles = self.filtro()["visibles"]
        self.assertEqual(len(visibles), 2, visibles)
        for texto in visibles:
            self.assertIn("MÉRIDA", texto)

    def test_filtrar_no_desmarca_lo_ya_marcado(self):
        """Se ocultan, no se apagan: si se apagaran, buscar cambiaría el filtro."""
        r = self.filtro()
        self.assertTrue(r["sigueMarcada"])
        self.assertTrue(r["avisaQueNoHay"])


class ElSelectOriginalSigueAhi(TestCase):
    """Barata y rápida: corre siempre, haya Chrome o no."""

    def test_el_select_se_esconde_sin_sacarlo_de_la_pantalla(self):
        """Con `display: none` el navegador no puede avisar «elegí una opción»
        en un campo obligatorio: se niega a señalar algo que no se ve, y el
        formulario no se envía nunca sin decir por qué."""
        css = (Path(settings.BASE_DIR) / "static" / "css" / "estilos.css").read_text(
            encoding="utf-8")
        regla = re.search(r"\.buscable__real \{[^}]*\}", css)
        self.assertTrue(regla, "no está la regla que esconde el select original")
        self.assertNotIn("display: none", regla.group(0))
        self.assertNotIn("visibility: hidden", regla.group(0))
        self.assertIn("opacity: 0", regla.group(0))

    def test_el_script_se_carga_en_todas_las_pantallas(self):
        zona = Zona.objects.create(nombre="MIRANDA")
        Sede.objects.create(nombre="CCCT", zona=zona)
        admin = Usuario.objects.create_user(username="adm2", password=CLAVE)
        admin.rol = Usuario.Rol.ADMIN
        admin.save()
        self.client.force_login(admin)
        for url in (reverse("expedientes:panel"),
                    reverse("expedientes:trabajador_list"),
                    reverse("expedientes:trabajador_create"),
                    reverse("configuracion:index")):
            with self.subTest(url=url):
                self.assertIn("js/buscable.js",
                              self.client.get(url).content.decode())
