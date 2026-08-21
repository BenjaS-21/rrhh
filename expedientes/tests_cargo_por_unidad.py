"""El desplegable de Cargo ofrece SIEMPRE todos los cargos.

Antes se dejaban solo los de la unidad organizativa elegida. La regla parecía
razonable y estaba mal: el catálogo cuelga cada cargo de una unidad, pero eso
es de dónde salió el nombre, no dónde puede usarse. En una tienda trabaja gente
con cargos que el catálogo tiene bajo otra gerencia —mantenimiento, seguridad,
sistemas— y filtrando no había forma de registrarla.

Además el filtro traía dos daños propios: dejaba el campo vacío en las unidades
sin cargos, y al cambiar de unidad borraba sin aviso el cargo ya elegido.

Lo que la unidad sí hace es ORDENAR: sus cargos suben al principio. Se ofrece
todo y se propone lo probable.

Se maneja el formulario en un Chrome de verdad porque esto pasa en el navegador.
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

# 5 en la tienda + 1 de otra gerencia + 0 en la unidad vacía.
TOTAL = 6

GUION = """
<script>
window.addEventListener("load", function () {
  setTimeout(function () {
    var unidad = document.getElementById("id_departamento");
    var cargo = document.getElementById("id_puesto");

    function porNombre(select, texto) {
      for (var i = 0; i < select.options.length; i++) {
        if (select.options[i].text === texto) { return select.options[i].value; }
      }
      return null;
    }

    function poner(select, texto) {
      select.value = porNombre(select, texto);
      select.dispatchEvent(new Event("change", {bubbles: true}));
    }

    function mirar() {
      var reales = Array.prototype.filter.call(
        cargo.options, function (o) { return o.value; });
      return {
        vacio: cargo.options.length ? cargo.options[0].text : null,
        ofrecidos: reales.length,
        // Los tres primeros, con el encabezado del grupo al que pertenecen.
        primeros: reales.slice(0, 3).map(function (o) {
          var g = o.parentNode && o.parentNode.tagName === "OPTGROUP"
            ? o.parentNode.label : "";
          return o.text + " | " + g;
        }),
        elegido: cargo.value ? cargo.options[cargo.selectedIndex].text : ""
      };
    }

    var r = {};
    r.alPrincipio = mirar();

    poner(unidad, "TIENDA SAN CRISTOBAL");
    r.conUnidadQueTiene = mirar();

    poner(unidad, "UNIDAD VACIA");
    r.conUnidadSinCargos = mirar();

    // Al reves: primero el cargo, despues una unidad que no lo tiene.
    unidad.value = "";
    unidad.dispatchEvent(new Event("change", {bubbles: true}));
    poner(cargo, "AUXILIAR DE MANTENIMIENTO");
    r.cargoElegidoSinUnidad = mirar();
    poner(unidad, "TIENDA SAN CRISTOBAL");
    r.despuesDeCambiarLaUnidad = mirar();

    document.title = JSON.stringify(r);
  }, 700);
});
</script>
</body>"""


class _ConCatalogo(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="TACHIRA")
        cls.sede = Sede.objects.create(nombre="SAN CRISTOBAL", zona=zona)

        cls.tienda = Departamento.objects.create(nombre="TIENDA SAN CRISTOBAL")
        for nombre in ("ALMACENISTA", "ASESOR DE VENTAS", "CAJERO",
                       "GERENTE DE TIENDA", "SUBGERENTE DE TIENDA"):
            Cargo.objects.create(nombre=nombre, departamento=cls.tienda)

        # Un cargo real que el catálogo cuelga de otra gerencia.
        otra = Departamento.objects.create(nombre="GERENCIA DE SERVICIOS")
        cls.ajeno = Cargo.objects.create(nombre="AUXILIAR DE MANTENIMIENTO",
                                         departamento=otra)

        cls.vacia = Departamento.objects.create(nombre="UNIDAD VACIA")

        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()


@unittest.skipUnless(CHROME, "Esta maquina no tiene Chrome.")
class EnLaPantallaSalenTodos(_ConCatalogo):

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

        carpeta = tempfile.mkdtemp(prefix="gde-cargo-")
        try:
            pagina = Path(carpeta) / "p.html"
            pagina.write_text(html, encoding="utf-8")
            salida = subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--allow-file-access-from-files", "--virtual-time-budget=9000",
                 "--window-size=1000,900", "--dump-dom", pagina.as_uri()],
                capture_output=True, timeout=180,
                encoding="utf-8", errors="replace").stdout
            titulo = re.search(r"<title>(.*?)</title>", salida, re.S)
            if not titulo:
                raise AssertionError("Chrome no devolvio el resultado")
            return json.loads(titulo.group(1))
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)

    def medida(self):
        if "_cache" not in EnLaPantallaSalenTodos.__dict__:
            EnLaPantallaSalenTodos._cache = self._manejar()
        return EnLaPantallaSalenTodos._cache

    # --- Lo que pidió el reporte -----------------------------------------------
    def test_con_una_unidad_elegida_siguen_estando_todos(self):
        """El pedido, textual: «en todas las unidades deben salir todos»."""
        self.assertEqual(self.medida()["conUnidadQueTiene"]["ofrecidos"], TOTAL)

    def test_incluso_en_una_unidad_que_no_tiene_ninguno_propio(self):
        """Era el peor caso: el campo quedaba vacío y no se podía seguir."""
        self.assertEqual(self.medida()["conUnidadSinCargos"]["ofrecidos"], TOTAL)

    def test_sin_elegir_unidad_tambien(self):
        self.assertEqual(self.medida()["alPrincipio"]["ofrecidos"], TOTAL)

    # --- Pero ordenados --------------------------------------------------------
    def test_los_de_la_unidad_elegida_van_primero_y_dicen_de_donde_son(self):
        """Ofrecer 805 sin orden sería cambiar un problema por otro."""
        primeros = self.medida()["conUnidadQueTiene"]["primeros"]
        for entrada in primeros:
            self.assertTrue(entrada.endswith("| TIENDA SAN CRISTOBAL"), primeros)

    def test_los_demas_quedan_abajo_bajo_su_propio_encabezado(self):
        """Testigo: si el encabezado fuera el mismo, no estaría ordenando nada."""
        m = self.medida()["conUnidadSinCargos"]["primeros"]
        for entrada in m:
            self.assertTrue(entrada.endswith("| Todos los cargos"), m)

    def test_sin_unidad_elegida_no_se_agrupa(self):
        """No hay con qué agrupar todavía: un encabezado ahí sería inventado."""
        for entrada in self.medida()["alPrincipio"]["primeros"]:
            self.assertTrue(entrada.endswith("| "), entrada)

    # --- Y ya no se pierde nada -------------------------------------------------
    def test_cambiar_de_unidad_ya_no_borra_el_cargo_elegido(self):
        """Desaparecía solo y sin aviso: eso es lo que parecía un error."""
        m = self.medida()
        self.assertEqual(m["cargoElegidoSinUnidad"]["elegido"],
                         "AUXILIAR DE MANTENIMIENTO")
        self.assertEqual(m["despuesDeCambiarLaUnidad"]["elegido"],
                         "AUXILIAR DE MANTENIMIENTO",
                         "cambiar la unidad se llevo puesto el cargo elegido")

    def test_el_renglon_vacio_deja_de_pedir_la_unidad_una_vez_elegida(self):
        """Pedía «Elegí primero la unidad» con la unidad ya puesta."""
        m = self.medida()
        self.assertIn("Elegí primero la unidad", m["alPrincipio"]["vacio"])
        self.assertIn("Elegí el cargo", m["conUnidadQueTiene"]["vacio"])


class YAlGuardarloTambien(_ConCatalogo):
    """La pantalla y el servidor tienen que decir lo mismo.

    Si la lista ofreciera todo y el servidor rechazara lo que no coincide, la
    persona elegiría una opción que el sistema mismo le propuso para que
    después le dijeran que no.
    """

    def alta(self, **cambios):
        datos = {"documento_identidad": "V-30719983", "nombres": "Benjamin",
                 "apellidos": "Velazco", "sede": self.sede.pk}
        datos.update(cambios)
        self.client.force_login(self.admin)
        return self.client.post(reverse("expedientes:trabajador_create"), datos)

    def test_un_cargo_de_otra_gerencia_en_una_tienda_se_guarda(self):
        r = self.alta(departamento=self.tienda.pk, puesto=self.ajeno.pk)
        self.assertEqual(r.status_code, 302)
        t = Trabajador.objects.get()
        self.assertEqual(t.puesto, self.ajeno)
        self.assertEqual(t.departamento, self.tienda)

    def test_en_una_unidad_sin_cargos_propios_tambien(self):
        r = self.alta(departamento=self.vacia.pk, puesto=self.ajeno.pk)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Trabajador.objects.get().departamento, self.vacia)

    def test_sin_unidad_el_expediente_queda_sin_unidad(self):
        """El caso que ensució un expediente real.

        Antes se completaba sola con la unidad del cargo. Como el mismo nombre
        está repetido en decenas de unidades, a alguien de San Cristóbal le
        quedó «CENDIS GUATIRE I» —una tienda de otro estado— sin que nadie la
        eligiera. En blanco es lo correcto: el semáforo de la nómina lo marca
        incompleto y una persona lo completa.
        """
        self.alta(puesto=self.ajeno.pk)
        self.assertIsNone(Trabajador.objects.get().departamento)

    def test_pero_el_cargo_si_queda_puesto(self):
        """Testigo: no completar la unidad no puede costar el dato que sí se eligió."""
        self.alta(puesto=self.ajeno.pk)
        self.assertEqual(Trabajador.objects.get().puesto, self.ajeno)

    def test_la_unidad_que_se_elige_es_la_que_queda(self):
        """Testigo del testigo: cuando se elige, se respeta tal cual."""
        self.alta(departamento=self.tienda.pk, puesto=self.ajeno.pk)
        self.assertEqual(Trabajador.objects.get().departamento, self.tienda)

    def test_el_cargo_queda_en_la_ficha(self):
        self.alta(departamento=self.tienda.pk, puesto=self.ajeno.pk)
        self.assertEqual(Trabajador.objects.get().cargo_nombre,
                         "AUXILIAR DE MANTENIMIENTO")
