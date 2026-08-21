"""Qué tiendas ve cada rol en los desplegables, y qué pasa cuando no ve ninguna.

Un desplegable vacío sin explicación es indistinguible de un sistema roto: acá
se prueba que, cuando no hay nada para elegir, la pantalla diga por qué y qué
hacer.
"""

import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Sede, Zona
from expedientes.forms import FiltroTrabajadorForm, TrabajadorForm
from configuracion.models import Preferencias
from expedientes.permisos import trabajadores_visibles, ve_todo_el_pais

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class TiendasSegunElRol(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.miranda = Zona.objects.create(nombre="MIRANDA")
        cls.zulia = Zona.objects.create(nombre="ZULIA")
        cls.vacia = Zona.objects.create(nombre="ZONA SIN TIENDAS")

        cls.mir1 = Sede.objects.create(nombre="CCCT", zona=cls.miranda)
        cls.mir2 = Sede.objects.create(nombre="TRINIDAD", zona=cls.miranda)
        cls.zul1 = Sede.objects.create(nombre="MARACAIBO", zona=cls.zulia)
        cls.apagada = Sede.objects.create(nombre="CERRADA", zona=cls.miranda,
                                          activa=False)

        cls.admin = cls._usuario("adm", Usuario.Rol.ADMIN, None)
        cls.rrhh = cls._usuario("rrhh", Usuario.Rol.RRHH_INTERIOR, cls.miranda)
        cls.rrhh_vacio = cls._usuario("rrhh_v", Usuario.Rol.RRHH_INTERIOR, cls.vacia)
        cls.rrhh_sin_zona = cls._usuario("rrhh_sz", Usuario.Rol.RRHH_INTERIOR, None)
        cls.lectura = cls._usuario("lect", Usuario.Rol.SOLO_LECTURA, cls.miranda)

    @classmethod
    def _usuario(cls, username, rol, zona):
        u = Usuario.objects.create_user(username=username, password=CLAVE)
        u.rol, u.zona = rol, zona
        u.save()
        return u

    def restringir(self, activo):
        """Prende o apaga «Restringir cada usuario a su zona»."""
        Preferencias.objects.update_or_create(
            pk=1, defaults={"restringir_por_zona": activo})

    def setUp(self):
        # De fábrica el sistema no restringe. Casi todo este archivo describe el
        # modo restringido, así que se prende acá; los pocos casos que miran el
        # comportamiento de fábrica lo apagan y lo dicen en su nombre.
        self.restringir(True)

    def opciones(self, usuario):
        return set(TrabajadorForm(usuario=usuario).fields["sede"].queryset
                   .values_list("nombre", flat=True))

    def casillas(self, usuario):
        return set(FiltroTrabajadorForm(usuario=usuario).fields["sedes"].queryset
                   .values_list("nombre", flat=True))

    # --- Quién ve qué --------------------------------------------------------
    def test_el_admin_ve_todas_las_activas(self):
        self.assertEqual(self.opciones(self.admin), {"CCCT", "TRINIDAD", "MARACAIBO"})

    def test_una_tienda_desactivada_no_se_ofrece_a_nadie(self):
        for u in (self.admin, self.rrhh):
            with self.subTest(usuario=u.username):
                self.assertNotIn("CERRADA", self.opciones(u))

    def test_rrhh_interior_ve_solo_las_de_su_zona(self):
        self.assertEqual(self.opciones(self.rrhh), {"CCCT", "TRINIDAD"})

    def test_solo_lectura_tambien_ve_las_de_su_zona_en_el_filtro(self):
        self.assertEqual(self.casillas(self.lectura), {"CCCT", "TRINIDAD"})

    def test_el_filtro_y_el_alta_ofrecen_lo_mismo(self):
        """Dos listas distintas de tiendas para el mismo usuario confundirían."""
        for u in (self.admin, self.rrhh, self.rrhh_vacio, self.rrhh_sin_zona):
            with self.subTest(usuario=u.username):
                self.assertEqual(self.opciones(u), self.casillas(u))

    # --- Sin zona asignada ---------------------------------------------------
    def test_sin_zona_y_restringido_no_ve_ninguna_tienda(self):
        """Lo que no puede pasar es ver tiendas y no ver sus expedientes.

        Eso dejaba dar de alta a alguien que después no aparecía en ningún
        listado. Las dos mitades tienen que moverse juntas.
        """
        self.assertEqual(self.opciones(self.rrhh_sin_zona), set())
        self.assertEqual(trabajadores_visibles(self.rrhh_sin_zona).count(), 0)

    def test_sin_restriccion_ve_todas(self):
        self.restringir(False)
        self.assertEqual(self.opciones(self.rrhh_sin_zona),
                         {"CCCT", "TRINIDAD", "MARACAIBO"})
        self.assertEqual(self.casillas(self.rrhh_sin_zona),
                         {"CCCT", "TRINIDAD", "MARACAIBO"})

    def test_sin_restriccion_hasta_el_de_zona_ve_todas(self):
        """Apagada la restricción, la zona del usuario deja de importar."""
        self.restringir(False)
        self.assertEqual(self.opciones(self.rrhh),
                         {"CCCT", "TRINIDAD", "MARACAIBO"})
        self.assertEqual(self.opciones(self.rrhh_sin_zona),
                         {"CCCT", "TRINIDAD", "MARACAIBO"})

    def test_sin_restriccion_igual_no_se_habilita_a_borrar(self):
        self.restringir(False)
        self.assertFalse(self.rrhh_sin_zona.puede_borrar)
        self.assertFalse(self.lectura.puede_editar)

    def test_lo_que_puede_elegir_coincide_con_lo_que_puede_ver(self):
        """Nunca puede dar de alta en una tienda cuyos expedientes no verá."""
        for u in (self.admin, self.rrhh, self.rrhh_vacio, self.rrhh_sin_zona):
            with self.subTest(usuario=u.username):
                elegibles = TrabajadorForm(usuario=u).fields["sede"].queryset
                for sede in elegibles:
                    self.assertTrue(
                        ve_todo_el_pais(u) or sede.zona_id == u.zona_id,
                        f"{u.username} podría crear en {sede} y no verla",
                    )

    # --- El aviso cuando no hay nada -----------------------------------------
    def test_zona_sin_tiendas_explica_el_vacio_y_dice_a_quien_pedirle(self):
        campo = TrabajadorForm(usuario=self.rrhh_vacio).fields["sede"]
        self.assertEqual(campo.queryset.count(), 0)
        self.assertIn("ZONA SIN TIENDAS", campo.help_text)
        self.assertIn("Administrador", campo.help_text)

    def test_sin_zona_el_aviso_dice_que_falta_la_zona(self):
        campo = TrabajadorForm(usuario=self.rrhh_sin_zona).fields["sede"]
        self.assertIn("zona asignada", campo.help_text)

    def test_el_aviso_menciona_las_tres_salidas(self):
        """Quien lee el aviso tiene que poder resolverlo sin preguntar."""
        texto = TrabajadorForm(usuario=self.rrhh_sin_zona).fields["sede"].help_text
        self.assertIn("asigne una", texto)
        self.assertIn("acceso a todas las zonas", texto)
        self.assertIn("Restringir cada usuario a su zona", texto)

    def test_con_tiendas_no_aparece_ningun_aviso(self):
        campo = TrabajadorForm(usuario=self.rrhh).fields["sede"]
        self.assertFalse(campo.help_text)

    def test_el_aviso_llega_a_la_pantalla_de_alta(self):
        self.client.force_login(self.rrhh_vacio)
        cuerpo = self.client.get(reverse("expedientes:trabajador_create")).content.decode()
        seleccion = re.search(r'<select name="sede".*?</select>', cuerpo, re.S)
        self.assertIsNotNone(seleccion)
        self.assertEqual(len(re.findall(r'<option value="\d+"', seleccion.group(0))), 0)
        self.assertIn("todavía no tiene tiendas cargadas", cuerpo)

    def test_el_panel_de_filtros_tambien_explica_el_vacio(self):
        self.client.force_login(self.rrhh_vacio)
        cuerpo = self.client.get(reverse("expedientes:trabajador_list")).content.decode()
        self.assertNotIn('name="sedes" value=', cuerpo)
        self.assertIn("todavía no tiene tiendas cargadas", cuerpo)

    def test_el_admin_sin_ninguna_tienda_cargada_tambien_recibe_aviso(self):
        Sede.objects.all().delete()
        campo = TrabajadorForm(usuario=self.admin).fields["sede"]
        self.assertIn("Configuración", campo.help_text)

    # --- Que la restricción se siga aplicando al guardar ---------------------
    def test_no_puede_forzar_una_tienda_de_otra_zona(self):
        form = TrabajadorForm(
            data={"documento_identidad": "V-1", "nombres": "A", "apellidos": "B",
                  "sede": self.zul1.pk, "estado": "ACTIVO"},
            usuario=self.rrhh)
        self.assertFalse(form.is_valid())
        self.assertIn("sede", form.errors)

    def test_sin_zona_no_puede_forzar_ninguna_estando_restringido(self):
        form = TrabajadorForm(
            data={"documento_identidad": "V-2", "nombres": "A", "apellidos": "B",
                  "sede": self.mir1.pk, "estado": "ACTIVO"},
            usuario=self.rrhh_sin_zona)
        self.assertFalse(form.is_valid())
        self.assertIn("sede", form.errors)
