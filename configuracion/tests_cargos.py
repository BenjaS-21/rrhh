"""El catálogo de Cargos en Configuración.

Antes no existía: los 805 cargos entraban solo por `cargar_datos.bat`, así que
una unidad organizativa sin cargos no se podía arreglar desde el sistema —el
desplegable quedaba vacío y no había ninguna pantalla adonde ir—.

Se prueba lo de siempre: que esté, que sea solo del Administrador, y que se
pueda encontrar un cargo entre cientos.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Cargo, Departamento, Zona

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class CatalogoDeCargos(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ventas = Departamento.objects.create(nombre="VENTAS")
        cls.deposito = Departamento.objects.create(nombre="DEPOSITO")
        Departamento.objects.create(nombre="UNIDAD VIEJA", activo=False)
        Cargo.objects.create(nombre="VENDEDOR", departamento=cls.ventas)
        Cargo.objects.create(nombre="CAJERO", departamento=cls.ventas)
        Cargo.objects.create(nombre="MONTACARGUISTA", departamento=cls.deposito)

        cls.admin = cls._usuario("adm", Usuario.Rol.ADMIN)
        cls.interior = cls._usuario("interior", Usuario.Rol.RRHH_INTERIOR)
        cls.lectura = cls._usuario("mira", Usuario.Rol.SOLO_LECTURA)

    @classmethod
    def _usuario(cls, username, rol):
        u = Usuario.objects.create_user(username=username, password=CLAVE)
        u.rol = rol
        u.zona = Zona.objects.first() or Zona.objects.create(nombre="MIRANDA")
        u.save()
        return u

    def lista(self, q=None):
        url = reverse("configuracion:lista", args=["cargos"])
        return url + ("?q=" + q if q else "")

    # --- Que exista y se vea ---------------------------------------------------
    def test_el_administrador_ve_los_cargos_cargados(self):
        self.client.force_login(self.admin)
        r = self.client.get(self.lista())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "VENDEDOR")
        self.assertContains(r, "MONTACARGUISTA")

    def test_aparece_en_el_indice_de_configuracion(self):
        """Si no está en el índice, la pantalla existe pero nadie la encuentra."""
        self.client.force_login(self.admin)
        r = self.client.get(reverse("configuracion:index"))
        self.assertContains(r, "Cargos")
        self.assertContains(r, reverse("configuracion:lista", args=["cargos"]))

    def test_el_aviso_del_formulario_apunta_a_una_pantalla_que_existe(self):
        """El alta le dice a quien elige una unidad vacía que vaya a
        Configuración → Cargos. Antes esa pantalla no existía."""
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.lista()).status_code, 200)

    # --- Quién puede qué ------------------------------------------------------
    def test_rrhh_interior_entra_y_agrega(self):
        """Cambió: el catálogo de cargos es el que más falta hace mientras se
        carga un expediente. Ver `tests_permisos_catalogos.py`."""
        self.client.force_login(self.interior)
        self.assertEqual(self.client.get(self.lista()).status_code, 200)
        self.client.post(reverse("configuracion:crear", args=["cargos"]),
                         {"nombre": "LIDER EXPERIENCIA INTERNA",
                          "departamento": self.ventas.pk, "activo": "on"})
        self.assertTrue(
            Cargo.objects.filter(nombre="LIDER EXPERIENCIA INTERNA").exists())

    def test_solo_lectura_no_puede_crear(self):
        self.client.force_login(self.lectura)
        r = self.client.post(reverse("configuracion:crear", args=["cargos"]),
                             {"nombre": "INVENTADO", "departamento": self.ventas.pk,
                              "activo": "on"}, follow=True)
        self.assertContains(r, "No tenés permiso")
        self.assertFalse(Cargo.objects.filter(nombre="INVENTADO").exists())

    def test_nadie_que_no_sea_admin_puede_desactivar(self):
        """La regla de siempre: los demás roles ven, agregan y editan; borrar
        —y desactivar es borrado lógico— es del Administrador."""
        cargo = Cargo.objects.get(nombre="VENDEDOR")
        self.client.force_login(self.interior)
        self.client.post(
            reverse("configuracion:toggle", args=["cargos", cargo.pk]), follow=True)
        cargo.refresh_from_db()
        self.assertTrue(cargo.activo)

    # --- Crear ------------------------------------------------------------------
    def test_crear_un_cargo_lo_deja_disponible_en_el_alta(self):
        """Es el punto de todo esto: que la unidad vacía deje de estarlo."""
        vacia = Departamento.objects.create(nombre="CONTRALORIA")
        self.client.force_login(self.admin)
        self.client.post(reverse("configuracion:crear", args=["cargos"]),
                         {"nombre": "CONTRALOR", "departamento": vacia.pk,
                          "activo": "on"})
        creado = Cargo.objects.get(nombre="CONTRALOR")
        self.assertEqual(creado.departamento, vacia)

        cuerpo = self.client.get(
            reverse("expedientes:trabajador_create")).content.decode()
        self.assertIn('data-unidad="%d"' % vacia.pk, cuerpo)

    def test_el_nombre_se_guarda_en_mayusculas(self):
        """El catálogo real es todo mayúsculas: en minúscula queda un duplicado
        que la restricción de unicidad no llega a ver."""
        self.client.force_login(self.admin)
        self.client.post(reverse("configuracion:crear", args=["cargos"]),
                         {"nombre": " supervisor ", "departamento": self.ventas.pk,
                          "activo": "on"})
        self.assertTrue(Cargo.objects.filter(nombre="SUPERVISOR").exists())

    def test_repetir_un_cargo_en_la_misma_unidad_se_explica(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("configuracion:crear", args=["cargos"]),
                             {"nombre": "VENDEDOR", "departamento": self.ventas.pk,
                              "activo": "on"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "ya tiene un cargo con ese nombre")
        self.assertEqual(Cargo.objects.filter(nombre="VENDEDOR").count(), 1)

    def test_el_mismo_nombre_en_otra_unidad_si_se_puede(self):
        """A propósito: ALMACENISTA existe en casi todas las unidades."""
        self.client.force_login(self.admin)
        self.client.post(reverse("configuracion:crear", args=["cargos"]),
                         {"nombre": "VENDEDOR", "departamento": self.deposito.pk,
                          "activo": "on"})
        self.assertEqual(Cargo.objects.filter(nombre="VENDEDOR").count(), 2)

    def test_solo_ofrece_unidades_activas(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(
            reverse("configuracion:crear", args=["cargos"])).content.decode()
        self.assertIn("VENTAS", cuerpo)
        self.assertNotIn("UNIDAD VIEJA", cuerpo)

    # --- Buscar -----------------------------------------------------------------
    def test_se_puede_buscar_por_nombre(self):
        """Son cientos: sin buscador la pantalla no se puede usar."""
        self.client.force_login(self.admin)
        r = self.client.get(self.lista(q="CAJERO"))
        self.assertContains(r, "CAJERO")
        self.assertNotContains(r, "MONTACARGUISTA")

    def test_se_puede_buscar_por_unidad(self):
        self.client.force_login(self.admin)
        r = self.client.get(self.lista(q="DEPOSITO"))
        self.assertContains(r, "MONTACARGUISTA")
        self.assertNotContains(r, "CAJERO")

    def test_sin_buscar_estan_todos(self):
        """Testigo: si el filtro se aplicara siempre, los de arriba no probarían
        que filtra, solo que la página muestra poco."""
        self.client.force_login(self.admin)
        r = self.client.get(self.lista())
        self.assertContains(r, "CAJERO")
        self.assertContains(r, "MONTACARGUISTA")

    def test_cuando_la_busqueda_no_encuentra_nada_lo_dice(self):
        self.client.force_login(self.admin)
        r = self.client.get(self.lista(q="ZZZZZ"))
        self.assertContains(r, "Ningún cargo coincide")

    def test_los_catalogos_sin_buscador_no_lo_muestran(self):
        """Testigo del buscador: es de los cargos, no de todas las pantallas."""
        self.client.force_login(self.admin)
        r = self.client.get(reverse("configuracion:lista", args=["zonas"]))
        self.assertNotContains(r, 'type="search"')
