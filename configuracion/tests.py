"""Pantalla de Configuración: catálogos y opciones del sistema.

Dos cosas que costaron encontrar en pantalla y que acá quedan fijadas: que
registrar una tienda se pueda hacer desde Configuración, y que el interruptor
de "sin zona asignada" esté a la vista y funcione.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Sede, Zona
from expedientes.models import RegistroAuditoria

from .models import Preferencias
from .views import CATALOGOS

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class BaseConfig(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.zona = Zona.objects.create(nombre="MIRANDA")
        cls.admin = cls._usuario("adm", Usuario.Rol.ADMIN)
        cls.rrhh = cls._usuario("rrhh", Usuario.Rol.RRHH_INTERIOR, cls.zona)

    @classmethod
    def _usuario(cls, username, rol, zona=None):
        u = Usuario.objects.create_user(username=username, password=CLAVE)
        u.rol, u.zona = rol, zona
        u.save()
        return u


class RegistrarTiendas(BaseConfig):
    """"En configuración no me sale nada para registrar las tiendas"."""

    def test_la_tarjeta_de_tiendas_esta_en_configuracion(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("configuracion:index")).content.decode()
        self.assertIn("Tiendas", cuerpo)
        self.assertIn(reverse("configuracion:lista", args=["tiendas"]), cuerpo)

    def test_desde_el_indice_se_llega_directo_a_cargar_una(self):
        """Antes había que entrar a la lista y recién ahí aparecía «+ Nuevo»."""
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("configuracion:index")).content.decode()
        self.assertIn(reverse("configuracion:crear", args=["tiendas"]), cuerpo)
        self.assertIn("Agregar tienda", cuerpo)

    def test_el_formulario_pide_lo_necesario(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(
            reverse("configuracion:crear", args=["tiendas"])).content.decode()
        for campo in ("nombre", "zona", "direccion", "es_central", "activa"):
            self.assertIn(f'name="{campo}"', cuerpo)

    def test_se_registra_y_queda_disponible(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("configuracion:crear", args=["tiendas"]), {
            "nombre": "CCCT", "zona": self.zona.pk,
            "direccion": "Av. Principal", "activa": "on"})
        self.assertEqual(r.status_code, 302)
        tienda = Sede.objects.get(nombre="CCCT")
        self.assertEqual(tienda.zona, self.zona)
        self.assertTrue(tienda.activa)

    def test_queda_asentado_en_la_auditoria(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("configuracion:crear", args=["tiendas"]), {
            "nombre": "TRINIDAD", "zona": self.zona.pk, "activa": "on"})
        ultima = RegistroAuditoria.objects.filter(entidad="Tiendas").latest("id")
        self.assertIn("TRINIDAD", ultima.descripcion)

    def test_no_se_escapa_ningun_comentario_de_plantilla_a_la_pantalla(self):
        """Un {# … #} de varias líneas no es comentario: se imprime tal cual."""
        self.client.force_login(self.admin)
        for url in (reverse("configuracion:index"),
                    reverse("configuracion:preferencias"),
                    reverse("configuracion:lista", args=["tiendas"]),
                    reverse("configuracion:crear", args=["tiendas"])):
            with self.subTest(url=url):
                cuerpo = self.client.get(url).content.decode()
                self.assertNotIn("{#", cuerpo)
                self.assertNotIn("#}", cuerpo)
                self.assertNotIn("{%", cuerpo)

    def test_el_nombre_del_catalogo_no_queda_cortado(self):
        """"Departamentos" no entraba en la tarjeta y se veía tajeado."""
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("configuracion:index")).content.decode()
        self.assertIn("catalogo__nombre", cuerpo)
        self.assertNotIn('class="metrica"', cuerpo)

    def test_solo_el_admin_entra_a_configuracion(self):
        self.client.force_login(self.rrhh)
        r = self.client.get(reverse("configuracion:index"))
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("configuracion", r["Location"])

    def test_un_rol_que_no_es_admin_tampoco_puede_crear_por_POST(self):
        self.client.force_login(self.rrhh)
        self.client.post(reverse("configuracion:crear", args=["tiendas"]),
                         {"nombre": "COLADA", "zona": self.zona.pk, "activa": "on"})
        self.assertFalse(Sede.objects.filter(nombre="COLADA").exists())


class OpcionesDelSistema(BaseConfig):

    def url(self):
        return reverse("configuracion:preferencias")

    def test_viene_apagada_de_fabrica(self):
        """Sin configurar nada, todos ven todas las tiendas y todo expediente."""
        self.assertFalse(Preferencias.obtener().restringir_por_zona)

    def test_hay_una_sola_fila_pase_lo_que_pase(self):
        """Guardar una instancia nueva pisa la existente en vez de duplicarla."""
        Preferencias.obtener()
        Preferencias(restringir_por_zona=True).save()
        self.assertEqual(Preferencias.objects.count(), 1)
        self.assertTrue(Preferencias.obtener().restringir_por_zona)

    def test_se_prende_desde_la_pantalla(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.url(), {"restringir_por_zona": "on"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Preferencias.obtener().restringir_por_zona)

    def test_se_vuelve_a_apagar(self):
        """Con la casilla sin marcar el POST llega vacío: tiene que apagarla igual."""
        self.client.force_login(self.admin)
        self.client.post(self.url(), {"restringir_por_zona": "on"})
        self.client.post(self.url(), {})
        self.assertFalse(Preferencias.obtener().restringir_por_zona)

    def test_guarda_quien_la_cambio(self):
        self.client.force_login(self.admin)
        self.client.post(self.url(), {"restringir_por_zona": "on"})
        self.assertEqual(Preferencias.obtener().actualizado_por, self.admin)

    def test_el_cambio_queda_en_la_auditoria(self):
        self.client.force_login(self.admin)
        self.client.post(self.url(), {"restringir_por_zona": "on"})
        ultima = RegistroAuditoria.objects.filter(
            entidad="Opciones del sistema").latest("id")
        self.assertIn("Activó", ultima.descripcion)
        self.assertIn("zona", ultima.descripcion)

    def test_guardar_sin_cambiar_nada_no_ensucia_la_auditoria(self):
        self.client.force_login(self.admin)
        self.client.post(self.url(), {})
        self.assertFalse(RegistroAuditoria.objects.filter(
            entidad="Opciones del sistema").exists())

    def test_se_ve_en_que_posicion_esta_desde_el_indice(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("configuracion:index")).content.decode()
        self.assertIn("Todos ven todas las tiendas", cuerpo)
        self.client.post(self.url(), {"restringir_por_zona": "on"})
        cuerpo = self.client.get(reverse("configuracion:index")).content.decode()
        self.assertIn("Cada usuario ve solo su zona", cuerpo)

    def test_solo_el_admin_la_toca(self):
        self.client.force_login(self.rrhh)
        r = self.client.post(self.url(), {"restringir_por_zona": "on"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Preferencias.obtener().restringir_por_zona)

    def test_la_url_de_opciones_no_se_confunde_con_un_catalogo(self):
        """"opciones" convive con el patrón <slug>/ de los catálogos."""
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("configuracion:lista",
                                    args=["tiendas"])).status_code, 200)
        self.assertEqual(self.client.get("/configuracion/inventado/").status_code, 404)


class CadaTarjetaDejaVerYAgregar(BaseConfig):
    """"En configuración solo tengo botón de añadir, no de ver el listado".

    El título de la tarjeta siempre llevó a la lista, pero un título no parece
    un destino: a la vista había un solo botón. Ahora los dos caminos son
    botones, y esto lo fija para todos los catálogos, no solo para el que se
    revisó a mano.
    """

    def cuerpo(self):
        self.client.force_login(self.admin)
        return self.client.get(reverse("configuracion:index")).content.decode()

    def test_todos_los_catalogos_tienen_boton_de_ver_listado(self):
        cuerpo = self.cuerpo()
        for slug in CATALOGOS:
            with self.subTest(catalogo=slug):
                destino = reverse("configuracion:lista", args=[slug])
                self.assertIn(f'class="btn sec chico" href="{destino}"', cuerpo)

    def test_y_siguen_teniendo_el_de_agregar(self):
        """Testigo: el botón nuevo no tenía que reemplazar al que ya estaba."""
        cuerpo = self.cuerpo()
        for slug in CATALOGOS:
            with self.subTest(catalogo=slug):
                destino = reverse("configuracion:crear", args=[slug])
                self.assertIn(f'class="btn chico" href="{destino}"', cuerpo)

    def test_dice_ver_listado_en_criollo(self):
        self.assertIn("Ver listado", self.cuerpo())

    def test_los_cargos_tambien_estan(self):
        """Es el catálogo que se acaba de agregar: que no quede afuera."""
        cuerpo = self.cuerpo()
        self.assertIn("Cargos", cuerpo)
        self.assertIn(reverse("configuracion:lista", args=["cargos"]), cuerpo)
        self.assertIn("Agregar cargo", cuerpo)
