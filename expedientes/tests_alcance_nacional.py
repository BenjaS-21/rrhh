"""Acceso a todas las zonas para un rol que no es el Administrador.

Nace de un caso real: para que un usuario de RRHH Interior viera todo el país
había que inventarle una zona llamada "TODAS". Esa zona no tenía ninguna tienda
adentro, así que el desplegable de tiendas le quedaba vacío y no podía cargar
expedientes.

Ahora el alcance es un permiso explícito, separado del rol: quién ve qué (zona
o país) y qué puede hacer (ver, agregar, editar, borrar) son dos cosas
distintas. Borrar sigue siendo solo del Administrador.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from configuracion.models import Preferencias
from cuentas.forms import InvitacionForm
from cuentas.models import InvitacionRegistro, Sede, Zona
from expedientes.forms import FiltroTrabajadorForm, TrabajadorForm
from expedientes.models import Trabajador
from expedientes.permisos import trabajadores_visibles

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class BaseAlcance(TestCase):

    @classmethod
    def setUpTestData(cls):
        # "Acceso a todas las zonas" solo se nota con la restricción prendida:
        # apagada, todos ven todo igual y no habría nada que probar.
        Preferencias.objects.update_or_create(
            pk=1, defaults={"restringir_por_zona": True})
        cls.miranda = Zona.objects.create(nombre="MIRANDA")
        cls.zulia = Zona.objects.create(nombre="ZULIA")

        cls.mir1 = Sede.objects.create(nombre="CCCT", zona=cls.miranda)
        cls.zul1 = Sede.objects.create(nombre="MARACAIBO", zona=cls.zulia)
        cls.apagada = Sede.objects.create(nombre="CERRADA", zona=cls.zulia,
                                          activa=False)

        cls.rrhh_zona = cls._usuario("rrhh_mir", Usuario.Rol.RRHH_INTERIOR,
                                     zona=cls.miranda)
        cls.rrhh_pais = cls._usuario("rrhh_pais", Usuario.Rol.RRHH_INTERIOR,
                                     nacional=True)

    @classmethod
    def _usuario(cls, username, rol, zona=None, nacional=False):
        u = Usuario.objects.create_user(username=username, password=CLAVE)
        u.rol, u.zona, u.acceso_nacional = rol, zona, nacional
        u.save()
        return u

    def opciones(self, usuario):
        return set(TrabajadorForm(usuario=usuario).fields["sede"].queryset
                   .values_list("nombre", flat=True))

    def casillas(self, usuario):
        return set(FiltroTrabajadorForm(usuario=usuario).fields["sedes"].queryset
                   .values_list("nombre", flat=True))


class LoQueVeUnUsuarioNacional(BaseAlcance):

    def test_ve_las_tiendas_de_todas_las_zonas(self):
        self.assertEqual(self.opciones(self.rrhh_pais), {"CCCT", "MARACAIBO"})

    def test_una_tienda_desactivada_le_sigue_sin_aparecer(self):
        self.assertNotIn("CERRADA", self.opciones(self.rrhh_pais))

    def test_el_filtro_le_ofrece_lo_mismo_que_el_alta(self):
        self.assertEqual(self.opciones(self.rrhh_pais),
                         self.casillas(self.rrhh_pais))

    def test_no_le_aparece_ningun_aviso_de_desplegable_vacio(self):
        campo = TrabajadorForm(usuario=self.rrhh_pais).fields["sede"]
        self.assertFalse(campo.help_text)

    def test_ve_los_expedientes_de_todas_las_zonas(self):
        """De nada sirve poder elegir la tienda si después no ve el expediente."""
        for sede in (self.mir1, self.zul1):
            Trabajador.objects.create(documento_identidad=f"V-{sede.pk}",
                                      nombres="N", apellidos="A", sede=sede)
        self.assertEqual(trabajadores_visibles(self.rrhh_pais).count(), 2)
        # Y el de zona sigue viendo solo el suyo.
        self.assertEqual(trabajadores_visibles(self.rrhh_zona).count(), 1)

    def test_lo_que_puede_elegir_coincide_con_lo_que_puede_ver(self):
        elegibles = TrabajadorForm(usuario=self.rrhh_pais).fields["sede"].queryset
        for sede in elegibles:
            t = Trabajador.objects.create(documento_identidad=f"V-x{sede.pk}",
                                          nombres="N", apellidos="A", sede=sede)
            self.assertIn(t, trabajadores_visibles(self.rrhh_pais),
                          f"podría dar de alta en {sede} y después no verlo")

    def test_puede_dar_de_alta_en_una_tienda_de_otra_zona(self):
        form = TrabajadorForm(
            data={"documento_identidad": "V-77", "nombres": "A", "apellidos": "B",
                  "sede": self.zul1.pk, "estado": "ACTIVO"},
            usuario=self.rrhh_pais)
        self.assertTrue(form.is_valid(), form.errors.as_json())


class ElAlcanceNoEsRango(BaseAlcance):
    """Ver todo el país no convierte a nadie en administrador."""

    def test_sigue_sin_poder_borrar(self):
        self.assertFalse(self.rrhh_pais.puede_borrar)
        self.assertFalse(self.rrhh_pais.es_admin)
        self.assertTrue(self.rrhh_pais.puede_editar)

    def test_solo_lectura_con_alcance_nacional_ve_todo_pero_no_edita(self):
        u = self._usuario("lect_pais", Usuario.Rol.SOLO_LECTURA, nacional=True)
        self.assertEqual(self.opciones(u), {"CCCT", "MARACAIBO"})
        self.assertFalse(u.puede_editar)
        self.assertFalse(u.puede_borrar)

    def test_no_entra_al_admin_de_django(self):
        u = self.rrhh_pais
        self.assertFalse(u.is_staff)
        self.assertFalse(u.is_superuser)

    def test_hay_que_darlo_a_mano(self):
        """El valor por defecto no puede ser 've todo'."""
        u = Usuario.objects.create_user(username="recien", password=CLAVE)
        self.assertFalse(u.acceso_nacional)
        self.assertFalse(u.alcance_nacional)
        self.assertEqual(trabajadores_visibles(u).count(), 0)


class ElAlcanceSeVeEnPantalla(BaseAlcance):
    """Si no se ve con qué alcance entró, se vuelve a inventar una zona 'TODAS'."""

    def test_el_texto_del_encabezado(self):
        sin_zona = self._usuario("pelado", Usuario.Rol.SOLO_LECTURA)
        self.assertEqual(self.rrhh_pais.descripcion_alcance, "Todas las zonas")
        self.assertEqual(self.rrhh_zona.descripcion_alcance, "MIRANDA")
        self.assertEqual(sin_zona.descripcion_alcance, "Sin zona asignada")

    def test_el_encabezado_lo_muestra(self):
        self.client.force_login(self.rrhh_pais)
        cuerpo = self.client.get(reverse("expedientes:trabajador_list")).content.decode()
        self.assertIn("Todas las zonas", cuerpo)

    def test_al_de_zona_le_muestra_su_zona(self):
        self.client.force_login(self.rrhh_zona)
        cuerpo = self.client.get(reverse("expedientes:trabajador_list")).content.decode()
        self.assertIn("MIRANDA", cuerpo)
        self.assertNotIn("Todas las zonas", cuerpo)


class InvitacionConAlcance(BaseAlcance):
    """La invitación es donde se decide el alcance de cada persona."""

    def form(self, **cambios):
        datos = {"rol": Usuario.Rol.RRHH_INTERIOR, "zona": "",
                 "acceso_nacional": "", "departamento": "", "email": "",
                 "nota": "", "expira_en": "2030-01-01"}
        datos.update(cambios)
        return InvitacionForm(data=datos)

    def test_sin_zona_ni_acceso_nacional_no_deja_generar_el_link(self):
        f = self.form()
        self.assertFalse(f.is_valid())
        self.assertIn("zona", f.errors)
        self.assertIn("todas las zonas", f.errors["zona"][0])

    def test_con_zona_sale_restringida(self):
        f = self.form(zona=self.miranda.pk)
        self.assertTrue(f.is_valid(), f.errors.as_json())
        self.assertEqual(f.cleaned_data["zona"], self.miranda)
        self.assertFalse(f.cleaned_data["acceso_nacional"])

    def test_con_acceso_nacional_ya_no_pide_zona(self):
        f = self.form(acceso_nacional="on")
        self.assertTrue(f.is_valid(), f.errors.as_json())
        self.assertTrue(f.cleaned_data["acceso_nacional"])

    def test_la_zona_se_descarta_si_igual_la_eligieron(self):
        """Dejarla puesta haría creer que restringe algo, y no restringe nada."""
        f = self.form(zona=self.miranda.pk, acceso_nacional="on")
        self.assertTrue(f.is_valid(), f.errors.as_json())
        self.assertIsNone(f.cleaned_data["zona"])

    def test_el_admin_no_arrastra_ni_zona_ni_la_casilla(self):
        f = self.form(rol=Usuario.Rol.ADMIN, zona=self.miranda.pk,
                      acceso_nacional="on")
        self.assertTrue(f.is_valid(), f.errors.as_json())
        self.assertIsNone(f.cleaned_data["zona"])
        self.assertFalse(f.cleaned_data["acceso_nacional"])

    def test_el_que_se_registra_hereda_el_alcance(self):
        inv = InvitacionRegistro.objects.create(
            rol=Usuario.Rol.RRHH_INTERIOR, acceso_nacional=True)
        r = self.client.post(inv.get_ruta(), {
            "username": "nuevo", "first_name": "A", "last_name": "B",
            "email": "a@b.com", "password1": CLAVE, "password2": CLAVE})
        self.assertEqual(r.status_code, 302)
        u = Usuario.objects.get(username="nuevo")
        self.assertTrue(u.acceso_nacional)
        self.assertEqual(self.opciones(u), {"CCCT", "MARACAIBO"})
        self.assertFalse(u.puede_borrar)

    def test_el_que_se_registra_con_zona_no_hereda_el_pais(self):
        inv = InvitacionRegistro.objects.create(
            rol=Usuario.Rol.RRHH_INTERIOR, zona=self.miranda)
        self.client.post(inv.get_ruta(), {
            "username": "nuevo2", "first_name": "A", "last_name": "B",
            "email": "a@b.com", "password1": CLAVE, "password2": CLAVE})
        u = Usuario.objects.get(username="nuevo2")
        self.assertFalse(u.acceso_nacional)
        self.assertEqual(self.opciones(u), {"CCCT"})

    def test_la_casilla_llega_al_formulario_en_pantalla(self):
        admin = self._usuario("jefe", Usuario.Rol.ADMIN)
        self.client.force_login(admin)
        cuerpo = self.client.get(reverse("cuentas:invitaciones")).content.decode()
        self.assertIn('name="acceso_nacional"', cuerpo)
        self.assertIn("Acceso a todas las zonas", cuerpo)
