"""Pasar a MAYÚSCULAS los nombres de un catálogo.

El catálogo real de la empresa está todo en mayúsculas. Lo que se carga a mano
entra como se escribió, y entonces conviven "Sistemas" y "GERENCIA DE SISTEMAS"
como si fueran dos unidades distintas: la lista se desordena y en los
desplegables parecen duplicados.

Lo delicado no es pasar a mayúsculas: es qué pasa cuando al hacerlo dos nombres
chocan. Ahí no se pisa nada y se dice cuál fue.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Cargo, Departamento, Sede, Zona
from expedientes.models import Moneda, RegistroAuditoria, TipoDocumento

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class PasarNombresAMayusculas(TestCase):

    @classmethod
    def setUpTestData(cls):
        Departamento.objects.create(nombre="GERENCIA DE SISTEMAS")
        Departamento.objects.create(nombre="Recursos Humanos")
        Departamento.objects.create(nombre="Administración")   # con tilde
        Departamento.objects.create(nombre="ventas",
                                    descripcion="No se toca la descripción")

        cls.admin = cls._usuario("adm", Usuario.Rol.ADMIN)
        cls.interior = cls._usuario("interior", Usuario.Rol.RRHH_INTERIOR)
        cls.lectura = cls._usuario("mira", Usuario.Rol.SOLO_LECTURA)

    @classmethod
    def _usuario(cls, username, rol):
        u = Usuario.objects.create_user(username=username, password=CLAVE)
        u.rol = rol
        u.save()
        return u

    def lista(self, slug="departamentos"):
        return reverse("configuracion:lista", args=[slug])

    def apretar(self, slug="departamentos", usuario=None):
        self.client.force_login(usuario or self.admin)
        return self.client.post(
            reverse("configuracion:mayusculas", args=[slug]), follow=True)

    def nombres(self):
        return sorted(Departamento.objects.values_list("nombre", flat=True))

    # --- El botón --------------------------------------------------------------
    def test_el_boton_aparece_y_dice_cuantos_son(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(self.lista()).content.decode()
        self.assertIn(reverse("configuracion:mayusculas", args=["departamentos"]),
                      cuerpo)
        self.assertIn("Pasar 3 a mayúsculas", cuerpo)

    def test_no_aparece_cuando_ya_estan_todos_en_mayusculas(self):
        """Testigo: un botón que no va a hacer nada hay que apretarlo para saberlo."""
        Departamento.objects.all().delete()
        Departamento.objects.create(nombre="DEPOSITO")
        self.client.force_login(self.admin)
        cuerpo = self.client.get(self.lista()).content.decode()
        self.assertNotIn(reverse("configuracion:mayusculas", args=["departamentos"]),
                         cuerpo)

    def test_cuenta_todo_el_catalogo_aunque_haya_una_busqueda(self):
        """El botón no se limita a lo que quedó en pantalla; el número tampoco."""
        self.client.force_login(self.admin)
        cuerpo = self.client.get(self.lista() + "?q=ventas").content.decode()
        self.assertIn("Pasar 3 a mayúsculas", cuerpo)

    # --- Lo que hace -----------------------------------------------------------
    def test_pasa_a_mayusculas_los_que_hacia_falta(self):
        self.apretar()
        self.assertEqual(
            self.nombres(),
            ["ADMINISTRACIÓN", "GERENCIA DE SISTEMAS", "RECURSOS HUMANOS", "VENTAS"])

    def test_los_que_ya_estaban_no_se_tocan(self):
        """Testigo: si reescribiera todo, no se notaría la diferencia acá."""
        antes = Departamento.objects.get(nombre="GERENCIA DE SISTEMAS")
        self.apretar()
        antes.refresh_from_db()
        self.assertEqual(antes.nombre, "GERENCIA DE SISTEMAS")

    def test_las_tildes_se_conservan(self):
        self.apretar()
        self.assertTrue(Departamento.objects.filter(nombre="ADMINISTRACIÓN").exists())

    def test_no_toca_ningun_otro_campo(self):
        self.apretar()
        d = Departamento.objects.get(nombre="VENTAS")
        self.assertEqual(d.descripcion, "No se toca la descripción")

    def test_dice_cuantos_cambio(self):
        self.assertContains(self.apretar(), "3 nombres pasados a mayúsculas")

    def test_apretarlo_de_nuevo_no_rompe_nada_y_lo_dice(self):
        self.apretar()
        r = self.apretar()
        self.assertContains(r, "ya estaban todos en mayúsculas")
        self.assertEqual(Departamento.objects.count(), 4)

    def test_queda_asentado_en_la_auditoria(self):
        self.apretar()
        registro = RegistroAuditoria.objects.filter(entidad="Departamentos").latest("id")
        self.assertIn("3 nombres a mayúsculas", registro.descripcion)
        self.assertEqual(registro.usuario_texto, "adm")

    # --- Cuando dos nombres chocan --------------------------------------------
    def test_si_ya_existe_el_mismo_en_mayusculas_no_se_pisa(self):
        """El caso que importa: "Sistemas" y "SISTEMAS" cargados los dos.

        Unificarlos es una decisión con consecuencias —a cuál se le reasignan
        los trabajadores—, así que la toma una persona, no el botón.
        """
        Departamento.objects.create(nombre="SISTEMAS")
        Departamento.objects.create(nombre="Sistemas")

        r = self.apretar()

        self.assertTrue(Departamento.objects.filter(nombre="Sistemas").exists())
        self.assertTrue(Departamento.objects.filter(nombre="SISTEMAS").exists())
        self.assertContains(r, "No se cambiaron 1")
        self.assertContains(r, "Sistemas")

    def test_y_los_demas_se_cambian_igual(self):
        """Que uno choque no puede dejar al resto sin corregir."""
        Departamento.objects.create(nombre="SISTEMAS")
        Departamento.objects.create(nombre="Sistemas")
        self.apretar()
        self.assertTrue(Departamento.objects.filter(nombre="RECURSOS HUMANOS").exists())

    # --- Quién puede -----------------------------------------------------------
    def test_solo_el_administrador(self):
        r = self.apretar(usuario=self.interior)
        self.assertContains(r, "Solo el administrador")
        self.assertTrue(Departamento.objects.filter(nombre="Recursos Humanos").exists())

    def test_solo_lectura_tampoco(self):
        self.apretar(usuario=self.lectura)
        self.assertTrue(Departamento.objects.filter(nombre="Recursos Humanos").exists())

    def test_no_se_dispara_entrando_por_la_direccion(self):
        """Con un GET no cambia nada: si no, bastaría un enlace para ejecutarlo."""
        self.client.force_login(self.admin)
        r = self.client.get(reverse("configuracion:mayusculas", args=["departamentos"]))
        self.assertEqual(r.status_code, 405)
        self.assertTrue(Departamento.objects.filter(nombre="Recursos Humanos").exists())


class SirveEnTodosLosCatalogos(TestCase):
    """No es una función de Departamentos: es del listado, sea cual sea.

    Cada catálogo tiene su propia regla de nombre único —global en unos, por
    zona o por unidad en otros—, y el botón tiene que andar en todos.
    """

    @classmethod
    def setUpTestData(cls):
        cls.zona = Zona.objects.create(nombre="miranda")
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def apretar(self, slug):
        self.client.force_login(self.admin)
        return self.client.post(
            reverse("configuracion:mayusculas", args=[slug]), follow=True)

    def test_tiendas(self):
        Sede.objects.create(nombre="la trinidad", zona=self.zona)
        self.apretar("tiendas")
        self.assertTrue(Sede.objects.filter(nombre="LA TRINIDAD").exists())

    def test_zonas(self):
        self.apretar("zonas")
        self.zona.refresh_from_db()
        self.assertEqual(self.zona.nombre, "MIRANDA")

    def test_cargos(self):
        unidad = Departamento.objects.create(nombre="VENTAS")
        Cargo.objects.create(nombre="vendedor", departamento=unidad)
        self.apretar("cargos")
        self.assertTrue(Cargo.objects.filter(nombre="VENDEDOR").exists())

    def test_tipos_de_documento(self):
        TipoDocumento.objects.create(nombre="Cédula", orden=1)
        self.apretar("tipos-documento")
        self.assertTrue(TipoDocumento.objects.filter(nombre="CÉDULA").exists())

    def test_monedas(self):
        # VES ya viene cargada por la migración de monedas iniciales.
        Moneda.objects.update_or_create(
            codigo="VES", defaults={"nombre": "Bolívar", "simbolo": "Bs"})
        self.apretar("monedas")
        self.assertTrue(Moneda.objects.filter(nombre="BOLÍVAR").exists())

    def test_un_catalogo_inventado_no_existe(self):
        """Testigo: la dirección no acepta cualquier cosa."""
        self.client.force_login(self.admin)
        r = self.client.post(reverse("configuracion:mayusculas", args=["inventado"]))
        self.assertEqual(r.status_code, 404)
