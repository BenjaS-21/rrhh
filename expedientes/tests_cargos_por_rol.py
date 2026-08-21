"""Los cargos que se ofrecen no dependen del rol.

Viene de un reporte: «como root me salen cargos y a RRHH Interior no le salen
los mismos al filtrar». Los cargos son un catálogo del sistema —no son datos de
nadie—, así que no hay motivo para que un rol vea unos y otro vea otros. Estos
tests fijan esa regla: si mañana alguien recorta el catálogo por rol, acá se
entera.

Se compara lo que realmente llega a cada pantalla, no la intención del código.
"""

import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from configuracion.models import Preferencias
from cuentas.models import Cargo, Departamento, Sede, Zona
from expedientes.models import Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


def _opciones(cuerpo, id_select):
    """Los `value` que ofrece un `<select>` del HTML que se mandó."""
    trozo = re.search(
        r'<select[^>]*id="%s".*?</select>' % re.escape(id_select), cuerpo, re.S)
    if not trozo:
        return None
    return re.findall(r'<option value="([^"]*)"', trozo.group(0))


class LosCargosSonLosMismosParaTodos(TestCase):

    @classmethod
    def setUpTestData(cls):
        miranda = Zona.objects.create(nombre="MIRANDA")
        zulia = Zona.objects.create(nombre="ZULIA")
        cls.sede = Sede.objects.create(nombre="TRINIDAD", zona=miranda)
        Sede.objects.create(nombre="MARACAIBO", zona=zulia)

        ventas = Departamento.objects.create(nombre="VENTAS")
        deposito = Departamento.objects.create(nombre="DEPOSITO")
        # Uno inactivo: ese sí tiene que desaparecer, pero para los dos por igual.
        vieja = Departamento.objects.create(nombre="UNIDAD VIEJA", activo=False)
        for i in range(6):
            Cargo.objects.create(nombre=f"VENDEDOR {i}", departamento=ventas)
        for i in range(4):
            Cargo.objects.create(nombre=f"MONTACARGUISTA {i}", departamento=deposito)
        Cargo.objects.create(nombre="CARGO DE UNIDAD VIEJA", departamento=vieja)
        Cargo.objects.create(nombre="CARGO DADO DE BAJA", departamento=ventas,
                             activo=False)

        cls.trabajador = Trabajador.objects.create(
            documento_identidad="V-1", nombres="Ana", apellidos="Alvarez",
            sede=cls.sede, departamento=ventas)

        cls.root = cls._usuario("root", Usuario.Rol.ADMIN)
        cls.root.is_superuser = True
        cls.root.save()
        cls.interior = cls._usuario("interior", Usuario.Rol.RRHH_INTERIOR,
                                    zona=miranda)

    @classmethod
    def _usuario(cls, username, rol, zona=None):
        u = Usuario.objects.create_user(username=username, password=CLAVE)
        u.rol = rol
        u.zona = zona
        u.save()
        return u

    def cuerpo(self, usuario, url):
        self.client.force_login(usuario)
        return self.client.get(url).content.decode()

    # --- El alta de un expediente ---------------------------------------------
    def test_el_alta_ofrece_los_mismos_cargos(self):
        url = reverse("expedientes:trabajador_create")
        self.assertEqual(_opciones(self.cuerpo(self.root, url), "id_puesto"),
                         _opciones(self.cuerpo(self.interior, url), "id_puesto"))

    def test_y_son_todos_los_del_catalogo(self):
        """Testigo: comparar dos listas vacías también daría «iguales»."""
        ofrecidos = _opciones(
            self.cuerpo(self.interior, reverse("expedientes:trabajador_create")),
            "id_puesto")
        # Menos la opción vacía, tienen que estar los 10 cargos activos de
        # unidades activas. El dado de baja y el de la unidad vieja, no.
        self.assertEqual(len([o for o in ofrecidos if o]), 10)

    def test_la_edicion_tambien(self):
        url = reverse("expedientes:trabajador_update", args=[self.trabajador.pk])
        self.assertEqual(_opciones(self.cuerpo(self.root, url), "id_puesto"),
                         _opciones(self.cuerpo(self.interior, url), "id_puesto"))

    def test_las_unidades_del_alta_tambien(self):
        url = reverse("expedientes:trabajador_create")
        self.assertEqual(_opciones(self.cuerpo(self.root, url), "id_departamento"),
                         _opciones(self.cuerpo(self.interior, url), "id_departamento"))

    # --- Los filtros -----------------------------------------------------------
    def test_el_filtro_de_la_nomina_ofrece_las_mismas_unidades(self):
        url = reverse("expedientes:nomina")
        self.assertEqual(_opciones(self.cuerpo(self.root, url), "id_departamento"),
                         _opciones(self.cuerpo(self.interior, url), "id_departamento"))

    def test_el_filtro_de_la_nomina_existe_de_verdad(self):
        """Testigo del de arriba: sin esto, `None == None` daría «iguales».

        Pasó: el mismo test apuntado a la lista de expedientes comparaba dos
        `None`, porque esa pantalla no tiene filtro por unidad organizativa.
        """
        ofrecidas = _opciones(
            self.cuerpo(self.root, reverse("expedientes:nomina")), "id_departamento")
        self.assertIsNotNone(ofrecidas, "la nómina no tiene filtro por unidad")
        self.assertEqual(len([o for o in ofrecidas if o]), 2)

    def test_el_filtro_de_expedientes_ofrece_lo_mismo(self):
        """Esa pantalla filtra por estado, no por unidad."""
        url = reverse("expedientes:trabajador_list")
        del_root = _opciones(self.cuerpo(self.root, url), "id_estado")
        self.assertIsNotNone(del_root)
        self.assertEqual(del_root, _opciones(self.cuerpo(self.interior, url), "id_estado"))

    # --- Con la restricción por zona prendida ---------------------------------
    def test_ni_siquiera_restringiendo_por_zona_cambian_los_cargos(self):
        """La restricción es sobre las PERSONAS, no sobre el catálogo.

        Prendida, RRHH Interior ve solo los expedientes de su zona. Los cargos
        que puede elegir siguen siendo todos: si se recortaran, no podría
        cargar a alguien con un cargo que existe.
        """
        preferencias = Preferencias.obtener()
        preferencias.restringir_por_zona = True
        preferencias.save()

        url = reverse("expedientes:trabajador_create")
        self.assertEqual(_opciones(self.cuerpo(self.root, url), "id_puesto"),
                         _opciones(self.cuerpo(self.interior, url), "id_puesto"))

    def test_lo_que_si_cambia_al_restringir_son_las_tiendas(self):
        """Testigo del de arriba: prueba que la restricción estaba haciendo algo.

        Sin esto, «los cargos son iguales» pasaría igual aunque la preferencia
        no se hubiera aplicado.
        """
        preferencias = Preferencias.obtener()
        preferencias.restringir_por_zona = True
        preferencias.save()

        url = reverse("expedientes:trabajador_create")
        del_root = _opciones(self.cuerpo(self.root, url), "id_sede")
        del_interior = _opciones(self.cuerpo(self.interior, url), "id_sede")
        self.assertNotEqual(del_root, del_interior)
        self.assertEqual(len([o for o in del_interior if o]), 1)
