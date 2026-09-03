"""Quién puede tocar los catálogos de Configuración.

Viene de un reporte de la gente que usa el sistema: un contrato salió con el
cargo equivocado. El cargo no se imprimía mal —eso se verificó generando el
documento para dos personas distintas—, el problema estaba antes: el cargo
real de la trabajadora, «LIDER EXPERIENCIA INTERNA», no era ninguno de los 805
del catálogo, y quien cargaba el expediente **no podía agregarlo**. Toda
Configuración era del Administrador. Así que tenía dos salidas: esperar, o
elegir cualquier otro cargo y seguir. El expediente quedaba mal por una traba
de permisos, no por un error de datos.

La regla de la casa es: los demás roles pueden **ver, añadir y editar**; solo
el Administrador **borra**. Los catálogos estaban del lado equivocado.

Así quedó repartido:

* **catálogos** (ver, agregar, editar) → Admin, RRHH Interior, RRHH Principal;
* **desactivar** un registro del catálogo → solo Admin (es borrado lógico);
* **pasar a mayúsculas en masa** → solo Admin (reescribe registros en uso);
* **usuarios, claves, respaldo, opciones, duplicados, pendientes de
  eliminar** → solo Admin. No son catálogos: es administración del sistema.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Cargo, Departamento

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"

# Las pantallas que NO son catálogos: administración del sistema.
SOLO_DEL_ADMIN = ["usuarios", "duplicados", "respaldo", "preferencias",
                  "pendientes"]

# El respaldo se le niega a los demás roles igual que las otras (el permiso
# corta antes de tocar la base), pero no se puede COMPROBAR acá que el
# Administrador sí entra: la API de respaldo de SQLite se queda esperando la
# transacción que `TestCase` deja abierta durante el test, y la prueba se
# cuelga sin decir nada. Ese lado lo cubre `tests_respaldo.py`, que por eso
# usa `TransactionTestCase`.
ADMIN_ENTRA = [p for p in SOLO_DEL_ADMIN if p != "respaldo"]


class _ConRoles(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.unidad = Departamento.objects.create(nombre="ADMINISTRACION")
        cls.cargo = Cargo.objects.create(nombre="ANALISTA", departamento=cls.unidad)
        cls.admin = cls._usuario("jefa", Usuario.Rol.ADMIN)
        cls.interior = cls._usuario("interior", Usuario.Rol.RRHH_INTERIOR)
        cls.principal = cls._usuario("principal", Usuario.Rol.RRHH_PRINCIPAL)
        cls.mirona = cls._usuario("mirona", Usuario.Rol.SOLO_LECTURA)

    @classmethod
    def _usuario(cls, username, rol):
        return Usuario.objects.create_user(
            username=username, password=CLAVE, rol=rol, acceso_nacional=True)

    def como(self, usuario):
        self.client.force_login(usuario)


class QuienCargaExpedientesPuedeAmpliarElCatalogo(_ConRoles):
    """El arreglo del reporte."""

    def test_rrhh_interior_entra_a_configuracion(self):
        self.como(self.interior)
        self.assertEqual(
            self.client.get(reverse("configuracion:index")).status_code, 200)

    def test_y_rrhh_principal_tambien(self):
        self.como(self.principal)
        self.assertEqual(
            self.client.get(reverse("configuracion:index")).status_code, 200)

    def test_ve_el_listado_de_cargos(self):
        self.como(self.interior)
        resp = self.client.get(reverse("configuracion:lista", args=["cargos"]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "ANALISTA")

    def test_agrega_el_cargo_que_le_faltaba(self):
        """El caso del reporte, de punta a punta."""
        self.como(self.interior)
        resp = self.client.post(
            reverse("configuracion:crear", args=["cargos"]),
            {"nombre": "LIDER EXPERIENCIA INTERNA",
             "departamento": self.unidad.pk, "activo": "on"}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            Cargo.objects.filter(nombre="LIDER EXPERIENCIA INTERNA").exists(),
            "no pudo agregar el cargo que necesitaba para el contrato")

    def test_y_puede_corregir_uno_mal_escrito(self):
        self.como(self.principal)
        self.client.post(
            reverse("configuracion:editar", args=["cargos", self.cargo.pk]),
            {"nombre": "ANALISTA DE COMPRAS", "departamento": self.unidad.pk,
             "activo": "on"}, follow=True)
        self.cargo.refresh_from_db()
        self.assertEqual(self.cargo.nombre, "ANALISTA DE COMPRAS")

    def test_el_menu_le_muestra_configuracion(self):
        """Un permiso que no se ve en el menú es un permiso que nadie usa."""
        self.como(self.interior)
        cuerpo = self.client.get(reverse("expedientes:panel")).content.decode()
        self.assertIn(reverse("configuracion:index"), cuerpo)


class SoloLecturaSigueAfuera(_ConRoles):
    """Testigo: el permiso se abrió a quien edita, no a todo el mundo."""

    def test_no_entra_al_indice(self):
        self.como(self.mirona)
        resp = self.client.get(reverse("configuracion:index"))
        self.assertEqual(resp.status_code, 302)

    def test_no_puede_agregar(self):
        self.como(self.mirona)
        self.client.post(reverse("configuracion:crear", args=["cargos"]),
                         {"nombre": "INVENTADO", "departamento": self.unidad.pk})
        self.assertFalse(Cargo.objects.filter(nombre="INVENTADO").exists())

    def test_no_puede_editar(self):
        self.como(self.mirona)
        self.client.post(
            reverse("configuracion:editar", args=["cargos", self.cargo.pk]),
            {"nombre": "CAMBIADO", "departamento": self.unidad.pk})
        self.cargo.refresh_from_db()
        self.assertEqual(self.cargo.nombre, "ANALISTA")

    def test_no_le_aparece_en_el_menu(self):
        self.como(self.mirona)
        cuerpo = self.client.get(reverse("expedientes:panel")).content.decode()
        self.assertNotIn(reverse("configuracion:index"), cuerpo)


class DesactivarSigueSiendoDelAdmin(_ConRoles):
    """Es borrado lógico. La regla no cambió: solo el Administrador borra."""

    def url(self):
        return reverse("configuracion:toggle", args=["cargos", self.cargo.pk])

    def test_rrhh_interior_no_puede_desactivar(self):
        self.como(self.interior)
        self.client.post(self.url())
        self.cargo.refresh_from_db()
        self.assertTrue(self.cargo.activo, "RRHH Interior desactivó un cargo")

    def test_rrhh_principal_tampoco(self):
        self.como(self.principal)
        self.client.post(self.url())
        self.cargo.refresh_from_db()
        self.assertTrue(self.cargo.activo)

    def test_el_admin_si(self):
        """Testigo: si nadie pudiera, la prueba de arriba no probaría nada."""
        self.como(self.admin)
        self.client.post(self.url())
        self.cargo.refresh_from_db()
        self.assertFalse(self.cargo.activo)

    def test_el_boton_no_se_le_muestra_a_quien_no_puede(self):
        self.como(self.interior)
        cuerpo = self.client.get(
            reverse("configuracion:lista", args=["cargos"])).content.decode()
        self.assertNotIn("Desactivar", cuerpo)

    def test_al_admin_si_se_le_muestra(self):
        self.como(self.admin)
        cuerpo = self.client.get(
            reverse("configuracion:lista", args=["cargos"])).content.decode()
        self.assertIn("Desactivar", cuerpo)


class LasMayusculasEnMasaSonDelAdmin(_ConRoles):
    """Reescribe registros que ya están en uso en cientos de expedientes."""

    def setUp(self):
        self.minuscula = Cargo.objects.create(nombre="cajera",
                                              departamento=self.unidad)

    def test_rrhh_interior_no_puede_correrlas(self):
        self.como(self.interior)
        self.client.post(reverse("configuracion:mayusculas", args=["cargos"]))
        self.minuscula.refresh_from_db()
        self.assertEqual(self.minuscula.nombre, "cajera")

    def test_el_admin_si(self):
        self.como(self.admin)
        self.client.post(reverse("configuracion:mayusculas", args=["cargos"]))
        self.minuscula.refresh_from_db()
        self.assertEqual(self.minuscula.nombre, "CAJERA")

    def test_el_boton_no_se_le_muestra_a_quien_no_puede(self):
        self.como(self.interior)
        cuerpo = self.client.get(
            reverse("configuracion:lista", args=["cargos"])).content.decode()
        self.assertNotIn("a mayúsculas", cuerpo)


class LaAdministracionDelSistemaNoSeAbrio(_ConRoles):
    """Usuarios, claves, respaldo y opciones siguen siendo del Administrador.

    Abrir los catálogos no puede arrastrar el resto de Configuración: ahí se
    cambian claves de otros, se descarga la base entera y se decide qué ve cada
    zona.
    """

    def test_ningun_rol_que_edita_entra(self):
        for usuario in (self.interior, self.principal):
            for nombre in SOLO_DEL_ADMIN:
                with self.subTest(rol=usuario.rol, pantalla=nombre):
                    self.como(usuario)
                    resp = self.client.get(reverse(f"configuracion:{nombre}"))
                    self.assertEqual(resp.status_code, 302)

    def test_el_admin_entra_a_todas(self):
        """Testigo: si estuvieran rotas, la prueba de arriba pasaría igual."""
        self.como(self.admin)
        for nombre in ADMIN_ENTRA:
            with self.subTest(pantalla=nombre):
                resp = self.client.get(reverse(f"configuracion:{nombre}"))
                self.assertEqual(resp.status_code, 200)

    def test_no_puede_cambiarle_la_clave_a_nadie(self):
        self.como(self.interior)
        self.client.post(
            reverse("configuracion:usuario_clave", args=[self.mirona.pk]),
            {"new_password1": "Otra-Clave-999", "new_password2": "Otra-Clave-999"})
        self.mirona.refresh_from_db()
        self.assertTrue(self.mirona.check_password(CLAVE),
                        "un rol que no es admin le cambió la clave a otro")

    def test_las_tarjetas_de_administracion_no_se_le_muestran(self):
        self.como(self.interior)
        cuerpo = self.client.get(reverse("configuracion:index")).content.decode()
        for nombre in SOLO_DEL_ADMIN:
            with self.subTest(pantalla=nombre):
                self.assertNotIn(reverse(f"configuracion:{nombre}"), cuerpo)

    def test_pero_las_de_los_catalogos_si(self):
        """Testigo: no se escondió media pantalla de más."""
        self.como(self.interior)
        cuerpo = self.client.get(reverse("configuracion:index")).content.decode()
        self.assertIn(reverse("configuracion:lista", args=["cargos"]), cuerpo)
