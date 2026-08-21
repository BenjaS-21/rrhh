"""Que las pantallas entren en un teléfono.

No se puede medir el ancho real sin un navegador, así que se verifica lo que sí
se puede afirmar desde el servidor y es lo que en la práctica rompe el diseño:
que exista el meta viewport, que ninguna tabla pueda desbordar la página, que
no queden anchos fijos en el contenido, y que la hoja de estilos traiga los
cortes responsive.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Departamento, Sede, Zona
from expedientes.models import Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"
CSS = Path(settings.BASE_DIR) / "static" / "css" / "estilos.css"
CORTES = ("1024px", "800px", "640px")


def hoja():
    return CSS.read_text(encoding="utf-8")


def bloque(corte):
    """El contenido de un `@media (max-width: X)`, contando llaves.

    Partir el texto por el `@media` siguiente no sirve: bastaba una regla
    suelta con el mismo ancho en otra parte del archivo para leer el bloque
    equivocado y que el test aprobara mirando otra cosa.
    """
    css = hoja()
    inicio = css.index(f"@media (max-width: {corte})")
    abre = css.index("{", inicio)
    nivel, i = 0, abre
    while i < len(css):
        if css[i] == "{":
            nivel += 1
        elif css[i] == "}":
            nivel -= 1
            if nivel == 0:
                return css[abre + 1:i]
        i += 1
    raise AssertionError(f"el bloque de {corte} no cierra")


class BuscadorDeTablas(HTMLParser):
    """Encuentra tablas que no estén dentro de un contenedor deslizante.

    Una tabla ancha sin `.tabla-scroll` no se desborda a sí misma: desborda la
    página entera, y el usuario termina moviendo todo el sitio de costado para
    leer una columna.
    """

    def __init__(self):
        super().__init__()
        self.pila = []
        self.sueltas = 0

    def handle_starttag(self, tag, attrs):
        clases = dict(attrs).get("class", "") or ""
        if tag == "table" and not any("tabla-scroll" in c for c in self.pila):
            self.sueltas += 1
        if tag not in ("br", "img", "input", "meta", "link", "hr"):
            self.pila.append(clases)

    def handle_endtag(self, tag):
        if self.pila:
            self.pila.pop()


class PantallasEnUnTelefono(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="CCCT", zona=zona)
        depto = Departamento.objects.create(nombre="VENTAS")
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="V-1", nombres="Ana", apellidos="Alvarez",
            sede=cls.sede, departamento=depto)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.is_staff = cls.admin.is_superuser = True
        cls.admin.save()

    def pantallas(self):
        return [
            reverse("expedientes:panel"),
            reverse("expedientes:trabajador_list"),
            reverse("expedientes:trabajador_create"),
            reverse("expedientes:trabajador_detail", args=[self.trabajador.pk]),
            reverse("expedientes:trabajador_update", args=[self.trabajador.pk]),
            reverse("expedientes:papelera", args=[self.trabajador.pk]),
            reverse("expedientes:nomina"),
            reverse("expedientes:auditoria_list"),
            reverse("configuracion:index"),
            reverse("configuracion:preferencias"),
            reverse("configuracion:lista", args=["tiendas"]),
            reverse("configuracion:crear", args=["tiendas"]),
            reverse("cuentas:invitaciones"),
        ]

    def cuerpo(self, url):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, url)
        return r.content.decode()

    # --- Lo que tiene que estar en todas -------------------------------------
    def test_todas_declaran_el_viewport(self):
        """Sin esto el teléfono simula una pantalla de escritorio y achica todo."""
        self.client.force_login(self.admin)
        for url in self.pantallas() + [reverse("cuentas:login")]:
            with self.subTest(url=url):
                cuerpo = self.client.get(url, follow=True).content.decode()
                self.assertIn('name="viewport"', cuerpo)
                self.assertIn("width=device-width", cuerpo)

    def test_ninguna_tabla_puede_desbordar_la_pagina(self):
        self.client.force_login(self.admin)
        for url in self.pantallas():
            with self.subTest(url=url):
                buscador = BuscadorDeTablas()
                buscador.feed(self.cuerpo(url))
                self.assertEqual(buscador.sueltas, 0,
                                 "hay una tabla fuera de .tabla-scroll")

    def test_no_hay_anchos_fijos_en_el_contenido(self):
        """`max-width` sí; `width: 800px` no: en un teléfono no achica."""
        self.client.force_login(self.admin)
        for url in self.pantallas():
            with self.subTest(url=url):
                cuerpo = self.cuerpo(url)
                # Se permiten anchos chicos (íconos, columnas de tabla, barras).
                anchos = re.findall(r"[^-]width: *(\d{3,})px", cuerpo)
                grandes = [a for a in anchos if int(a) > 260]
                self.assertEqual(grandes, [], f"anchos fijos: {grandes}")

    # --- La hoja de estilos ---------------------------------------------------
    def test_la_hoja_trae_los_cortes(self):
        css = hoja()
        for corte in CORTES:
            with self.subTest(corte=corte):
                self.assertIn(f"@media (max-width: {corte})", css)

    def test_los_cortes_van_de_mayor_a_menor(self):
        """El más angosto tiene que ir último para poder pisar a los anteriores."""
        css = hoja()
        posiciones = [css.index(f"@media (max-width: {c})") for c in CORTES]
        self.assertEqual(posiciones, sorted(posiciones))

    def test_cada_corte_esta_una_sola_vez(self):
        """Dos bloques del mismo ancho en distintos lugares se contradicen.

        Ya pasó: uno escondía la marca del login y otro la mostraba, y cuál
        ganaba dependía del orden en el archivo.
        """
        css = hoja()
        for corte in CORTES:
            with self.subTest(corte=corte):
                self.assertEqual(css.count(f"@media (max-width: {corte})"), 1)

    def test_el_modo_compacto_no_depende_de_un_ancho_fijo(self):
        """Un administrador ve siete entradas y otro rol tres.

        Con un ancho fijo, el mismo corte le queda grande a uno y chico al otro:
        por eso el modo compacto es una clase que pone el script después de
        medir, y no una consulta de medios.
        """
        css = hoja()
        self.assertIn(".topbar.compacto", css)
        for corte in CORTES:
            with self.subTest(corte=corte):
                self.assertNotIn(".menu-boton", bloque(corte))

    def test_con_el_menu_guardado_aparece_el_boton(self):
        css = hoja()
        self.assertIn(".topbar.compacto .menu-boton", css)
        self.assertIn(".topbar.compacto nav { display: none; }", css)
        self.assertIn(".topbar.compacto .menu-check:checked ~ nav", css)

    def test_el_menu_desplegado_va_en_vertical(self):
        css = hoja()
        desplegado = css.split(".topbar.compacto .menu-check:checked ~ nav {")[1].split("}")[0]
        self.assertIn("flex-direction: column", desplegado)

    def test_el_boton_no_aparece_cuando_el_menu_entra(self):
        """Sin la clase, el menú se ve completo y el botón no existe."""
        self.assertIn(".menu-boton { display: none; }", hoja())

    def test_la_barra_desborda_en_vez_de_apretarse(self):
        """Si se acomodara sola, el script nunca se enteraría de que no entra."""
        css = hoja()
        barra = css.split(".topbar {")[1].split("}")[0]
        self.assertIn("flex-wrap: nowrap", barra)
        self.assertIn("white-space: nowrap", css.split(".topbar nav a {")[1].split("}")[0])

    def test_la_barra_arranca_compacta(self):
        """Al revés se vería un instante el menú desbordado antes de guardarse.

        Y si el script no llega a correr, quedarse con el botón es lo que
        siempre funciona.
        """
        self.client.force_login(self.admin)
        cuerpo = self.cuerpo(reverse("expedientes:panel"))
        self.assertIn('class="topbar compacto"', cuerpo)

    def test_el_script_mide_y_vuelve_a_medir(self):
        self.client.force_login(self.admin)
        cuerpo = self.cuerpo(reverse("expedientes:panel"))
        guion = cuerpo.split('id="topbar"')[1]
        self.assertIn("scrollWidth", guion)
        self.assertIn('addEventListener("resize"', guion)
        self.assertIn("ResizeObserver", guion)
        # Poppins se carga después del primer dibujo y cambia los anchos.
        self.assertIn("document.fonts", guion)

    def test_la_flechita_del_filtro_se_ancla_a_su_caja(self):
        """Sin esto se iba al borde derecho de la pantalla en un teléfono."""
        css = hoja()
        resumen = css.split(".multi > summary {")[1].split("}")[0]
        self.assertIn("position: relative", resumen)

    def test_el_menu_esta_en_todas_las_pantallas(self):
        self.client.force_login(self.admin)
        for url in self.pantallas():
            with self.subTest(url=url):
                cuerpo = self.cuerpo(url)
                self.assertIn('id="menu-check"', cuerpo)
                self.assertIn('for="menu-check"', cuerpo)

    def test_el_menu_funciona_sin_javascript(self):
        """Si un script falla, el sistema no puede quedarse sin navegación."""
        self.client.force_login(self.admin)
        cuerpo = self.cuerpo(reverse("expedientes:panel"))
        boton = cuerpo.split('class="menu-boton"')[1].split("</label>")[0]
        self.assertNotIn("onclick", boton)
        self.assertIn('type="checkbox"', cuerpo)

    def test_las_tablas_se_deslizan_dentro_de_su_caja(self):
        self.assertIn(".tabla-scroll { overflow-x: auto; }", hoja())

    def test_las_dos_columnas_pasan_a_una(self):
        self.assertIn(".grid-2 { grid-template-columns: 1fr; }", bloque("640px"))

    def test_los_inputs_no_hacen_zoom_en_iphone(self):
        """Menos de 16px y iOS hace zoom solo al tocar el campo."""
        self.assertIn("font-size: 16px", bloque("640px"))

    def test_el_desplegable_de_tiendas_no_se_sale_de_la_pantalla(self):
        telefono = bloque("640px")
        self.assertIn(".multi__panel", telefono)
        self.assertIn("position: static", telefono)

    def test_el_login_conserva_la_marca(self):
        """Antes se escondía entera y la pantalla quedaba sin identidad."""
        chico = bloque("800px")
        franja = chico.split(".login-marca {")[1].split("}")[0]
        self.assertIn("display: flex", franja)
        # El párrafo largo sí se esconde: en un teléfono ocupa media pantalla y
        # no dice nada que el usuario necesite para entrar.
        self.assertIn(".login-marca p { display: none; }", chico)
