"""Cómo funciona el sistema de fábrica: sin restricción por zona.

Todos ven todas las tiendas y todos los expedientes, y pueden registrar y
filtrar a quien sea. La zona sigue existiendo como dato —cada tienda pertenece
a una— pero no recorta lo que cada usuario ve, salvo que en Configuración se
prenda «Restringir cada usuario a su zona».

Lo único que el rol sigue decidiendo: solo el Administrador borra.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Sede, Zona
from configuracion.models import Preferencias
from expedientes.forms import FiltroTrabajadorForm, TrabajadorForm
from expedientes.models import Trabajador
from expedientes.permisos import trabajadores_visibles

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class SinRestriccion(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.miranda = Zona.objects.create(nombre="MIRANDA")
        cls.zulia = Zona.objects.create(nombre="ZULIA")
        cls.ccct = Sede.objects.create(nombre="CCCT", zona=cls.miranda)
        cls.maracaibo = Sede.objects.create(nombre="MARACAIBO", zona=cls.zulia)
        cls.cerrada = Sede.objects.create(nombre="CERRADA", zona=cls.zulia,
                                          activa=False)

        cls.ana = Trabajador.objects.create(documento_identidad="V-1",
                                            nombres="Ana", apellidos="Miranda",
                                            sede=cls.ccct)
        cls.beto = Trabajador.objects.create(documento_identidad="V-2",
                                             nombres="Beto", apellidos="Zulia",
                                             sede=cls.maracaibo)

        cls.admin = cls._usuario("adm", Usuario.Rol.ADMIN)
        cls.rrhh = cls._usuario("rrhh", Usuario.Rol.RRHH_INTERIOR, cls.miranda)
        cls.pelado = cls._usuario("pelado", Usuario.Rol.RRHH_INTERIOR)
        cls.lectura = cls._usuario("lect", Usuario.Rol.SOLO_LECTURA, cls.miranda)

    @classmethod
    def _usuario(cls, username, rol, zona=None):
        u = Usuario.objects.create_user(username=username, password=CLAVE)
        u.rol, u.zona = rol, zona
        u.save()
        return u

    def todos(self):
        return (self.admin, self.rrhh, self.pelado, self.lectura)

    # --- De fábrica -----------------------------------------------------------
    def test_no_hace_falta_configurar_nada(self):
        self.assertFalse(Preferencias.obtener().restringir_por_zona)

    def test_todos_ven_todas_las_tiendas(self):
        for u in self.todos():
            with self.subTest(usuario=u.username):
                opciones = set(TrabajadorForm(usuario=u).fields["sede"]
                               .queryset.values_list("nombre", flat=True))
                self.assertEqual(opciones, {"CCCT", "MARACAIBO"})

    def test_todos_ven_todos_los_expedientes(self):
        for u in self.todos():
            with self.subTest(usuario=u.username):
                self.assertEqual(trabajadores_visibles(u).count(), 2)

    def test_una_tienda_desactivada_sigue_sin_ofrecerse(self):
        """Lo que se apagó a mano no vuelve por la ventana."""
        for u in self.todos():
            with self.subTest(usuario=u.username):
                opciones = TrabajadorForm(usuario=u).fields["sede"].queryset
                self.assertNotIn(self.cerrada, opciones)

    def test_el_filtro_ofrece_las_mismas_que_el_alta(self):
        for u in self.todos():
            with self.subTest(usuario=u.username):
                alta = set(TrabajadorForm(usuario=u).fields["sede"].queryset)
                filtro = set(FiltroTrabajadorForm(usuario=u).fields["sedes"].queryset)
                self.assertEqual(alta, filtro)

    def test_ningun_desplegable_queda_vacio_ni_con_avisos(self):
        for u in self.todos():
            with self.subTest(usuario=u.username):
                self.assertFalse(TrabajadorForm(usuario=u).fields["sede"].help_text)

    # --- Registrar y filtrar a quien sea --------------------------------------
    def test_registra_en_la_tienda_de_otra_zona(self):
        self.client.force_login(self.rrhh)
        r = self.client.post(reverse("expedientes:trabajador_create"), {
            "documento_identidad": "V-99", "nombres": "Nuevo",
            "apellidos": "Cualquiera", "sede": self.maracaibo.pk})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Trabajador.objects.filter(documento_identidad="V-99").exists())

    def test_filtra_por_una_tienda_de_otra_zona(self):
        self.client.force_login(self.rrhh)
        cuerpo = self.client.get(reverse("expedientes:trabajador_list"),
                                 {"sedes": self.maracaibo.pk}).content.decode()
        self.assertIn("Beto", cuerpo)
        self.assertNotIn("Ana", cuerpo)

    def test_abre_el_expediente_de_otra_zona(self):
        self.client.force_login(self.rrhh)
        r = self.client.get(reverse("expedientes:trabajador_detail", args=[self.beto.pk]))
        self.assertEqual(r.status_code, 200)

    def test_edita_el_expediente_de_otra_zona(self):
        self.client.force_login(self.rrhh)
        r = self.client.post(reverse("expedientes:trabajador_update", args=[self.beto.pk]), {
            "documento_identidad": "V-2", "nombres": "Beto", "apellidos": "Editado",
            "sede": self.maracaibo.pk, "estado": "ACTIVO"})
        self.assertEqual(r.status_code, 302)
        self.beto.refresh_from_db()
        self.assertEqual(self.beto.apellidos, "Editado")

    # --- Lo que NO cambió -----------------------------------------------------
    def test_borrar_sigue_siendo_solo_del_administrador(self):
        for u in (self.rrhh, self.pelado, self.lectura):
            with self.subTest(usuario=u.username):
                self.assertFalse(u.puede_borrar)
        self.assertTrue(self.admin.puede_borrar)

    def test_solo_lectura_sigue_sin_poder_editar(self):
        self.client.force_login(self.lectura)
        r = self.client.post(reverse("expedientes:trabajador_update", args=[self.ana.pk]), {
            "documento_identidad": "V-1", "nombres": "Ana", "apellidos": "Hackeada",
            "sede": self.ccct.pk, "estado": "ACTIVO"})
        self.assertEqual(r.status_code, 403)
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.apellidos, "Miranda")

    def test_el_anonimo_sigue_yendo_al_login(self):
        r = self.client.get(reverse("expedientes:trabajador_list"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("ingresar", r["Location"])

    # --- Y se puede volver atrás ---------------------------------------------
    def test_prendiendo_la_opcion_vuelve_la_restriccion(self):
        Preferencias.objects.update_or_create(
            pk=1, defaults={"restringir_por_zona": True})
        opciones = set(TrabajadorForm(usuario=self.rrhh).fields["sede"]
                       .queryset.values_list("nombre", flat=True))
        self.assertEqual(opciones, {"CCCT"})
        self.assertEqual(trabajadores_visibles(self.rrhh).count(), 1)
