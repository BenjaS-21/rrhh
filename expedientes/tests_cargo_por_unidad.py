"""El desplegable de Cargo ofrece los generales: una opción por nombre.

Antes ofrecía SIEMPRE todos los cargos: 800+ opciones con el mismo nombre
repetido por tienda (ALMACENISTA aparecía 64 veces). Desde que los cargos
tienen `es_general`, el desplegable muestra una fila por nombre —las generales
valen para cualquier tienda— y los duplicados por tienda quedan como
particulares, fuera de la oferta.

La excepción que importa: el cargo particular que YA tiene el expediente
aparece igual —marcado como particular— porque si no, editar la ficha lo
borraría sin aviso.

Antes de esta versión esto se probaba en un Chrome de verdad porque la lista
la reordenaba un script del navegador; al quedar la lista final en el servidor
no hace falta más que mirar el HTML.
"""

import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Cargo, Departamento, Sede, Zona
from expedientes.models import Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


def _opciones(cuerpo, id_select="id_puesto"):
    """(value, texto) de cada opción de un `<select>` del HTML."""
    trozo = re.search(
        r'<select[^>]*id="%s".*?</select>' % re.escape(id_select), cuerpo, re.S)
    if not trozo:
        return []
    return re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>',
                      trozo.group(0))


class _ConCatalogo(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="TACHIRA")
        cls.sede = Sede.objects.create(nombre="SAN CRISTOBAL", zona=zona)

        cls.tienda = Departamento.objects.create(nombre="TIENDA SAN CRISTOBAL")
        cls.otra = Departamento.objects.create(nombre="TIENDA BUENAVENTURA")
        # El mismo nombre en dos unidades: uno general y otro particular.
        cls.general = Cargo.objects.create(
            nombre="ALMACENISTA", departamento=cls.tienda, es_general=True)
        cls.particular = Cargo.objects.create(
            nombre="ALMACENISTA", departamento=cls.otra, es_general=False)
        cls.otro_general = Cargo.objects.create(
            nombre="CAJERO", departamento=cls.tienda, es_general=True)

        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def cuerpo(self, url):
        self.client.force_login(self.admin)
        return self.client.get(url).content.decode()


class LaOfertaEsGeneral(_ConCatalogo):

    def test_una_opcion_por_nombre(self):
        textos = [t for _, t in _opciones(
            self.cuerpo(reverse("expedientes:trabajador_create")))]
        self.assertEqual(textos.count("ALMACENISTA"), 1)
        self.assertEqual(textos.count("CAJERO"), 1)

    def test_los_particulares_no_se_ofrecen(self):
        valores = [v for v, _ in _opciones(
            self.cuerpo(reverse("expedientes:trabajador_create")))]
        self.assertNotIn(str(self.particular.pk), valores)
        self.assertIn(str(self.general.pk), valores)

    def test_el_inactivo_tampoco(self):
        Cargo.objects.filter(pk=self.general.pk).update(activo=False)
        valores = [v for v, _ in _opciones(
            self.cuerpo(reverse("expedientes:trabajador_create")))]
        self.assertNotIn(str(self.general.pk), valores)

    def test_los_cargos_nuevos_nacen_generales(self):
        nuevo = Cargo.objects.create(nombre="EMPACADOR", departamento=self.tienda)
        self.assertTrue(nuevo.es_general)


class ElCargoParticularDelExpedienteSeConserva(_ConCatalogo):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="V-1", nombres="Ana", apellidos="Alvarez",
            sede=cls.sede, departamento=cls.otra, puesto=cls.particular)

    def test_al_editar_aparece_marcado_como_particular(self):
        cuerpo = self.cuerpo(
            reverse("expedientes:trabajador_update", args=[self.trabajador.pk]))
        opciones = _opciones(cuerpo)
        valores = [v for v, _ in opciones]
        self.assertIn(str(self.particular.pk), valores)
        textos = dict(opciones)
        self.assertIn("particular", textos[str(self.particular.pk)])

    def test_y_queda_seleccionado(self):
        cuerpo = self.cuerpo(
            reverse("expedientes:trabajador_update", args=[self.trabajador.pk]))
        trozo = re.search(
            r'<option value="%d"[^>]*selected' % self.particular.pk, cuerpo)
        self.assertIsNotNone(trozo)

    def test_al_guardar_con_un_general_se_asigna(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("expedientes:trabajador_update", args=[self.trabajador.pk]),
            {"documento_identidad": "V-1", "nombres": "Ana",
             "apellidos": "Alvarez", "sede": self.sede.pk, "estado": "ACTIVO",
             "puesto": self.general.pk})
        self.trabajador.refresh_from_db()
        self.assertEqual(self.trabajador.puesto, self.general)


class DosGeneralesConElMismoNombreSeDistinguen(_ConCatalogo):
    """El catálogo es único por (nombre, unidad), no por nombre.

    O sea que nada impide dos generales llamados ALMACENISTA en unidades
    distintas. La migración deja uno solo por nombre, pero eso vale para el
    día que corre: desde que quien carga expedientes puede ampliar el catálogo
    —y el formulario de Cargo estrena los nuevos como generales— alguien va a
    crear el ALMACENISTA de una unidad que no lo tenía.

    Dos opciones con la misma letra son peores que las 800 de antes. Con 800
    se elegía mal por cansancio; con dos idénticas no hay nada que mirar, y el
    cargo que sale impreso en el contrato es el de otra unidad. Ya llegó un
    reporte por un cargo equivocado en un contrato: no conviene reestrenarlo.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gemelo = Cargo.objects.create(
            nombre="CAJERO", departamento=cls.otra, es_general=True)

    def textos(self):
        return [t for _, t in _opciones(
            self.cuerpo(reverse("expedientes:trabajador_create")))]

    def test_los_dos_llevan_su_unidad(self):
        textos = self.textos()
        for unidad in (self.tienda.nombre, self.otra.nombre):
            with self.subTest(unidad=unidad):
                self.assertIn(f"CAJERO — {unidad}", textos)

    def test_no_queda_ninguno_con_el_nombre_pelado(self):
        """Lo que se elige a ciegas: dos renglones que dicen lo mismo."""
        self.assertNotIn("CAJERO", self.textos())

    def test_el_que_no_se_repite_sigue_saliendo_limpio(self):
        """Testigo: si la unidad se agregara siempre, el desplegable volvería
        a leerse como la lista larga que este cambio vino a arreglar."""
        self.assertIn("ALMACENISTA", self.textos())

    def test_el_particular_se_sigue_marcando_como_particular(self):
        """Testigo de que no se pisó lo que ya andaba."""
        trabajador = Trabajador.objects.create(
            documento_identidad="11222333", nombres="ANA", apellidos="PEREZ",
            sede=self.sede, departamento=self.otra, puesto=self.particular)
        textos = [t for _, t in _opciones(self.cuerpo(
            reverse("expedientes:trabajador_update", args=[trabajador.pk])))]
        self.assertIn(f"ALMACENISTA — {self.otra.nombre} (particular)", textos)


class ElCampoSigueDiciendoCargo(_ConCatalogo):
    """En el modelo se llama `puesto`; en la pantalla dice CARGO.

    Así está en el catálogo de Configuración, en los contratos, en la lista de
    verificación del expediente y en los reportes que manda la gente. El campo
    del formulario se reemplaza entero para poder filtrar los generales, y al
    reemplazarlo se pierde el `verbose_name` del modelo: Django lo rebautiza
    «Puesto» solo, sin avisar.
    """

    def test_la_etiqueta_dice_cargo(self):
        from expedientes.forms import TrabajadorForm

        self.assertEqual(str(TrabajadorForm()["puesto"].label), "Cargo")

    def test_y_sale_asi_en_la_pantalla(self):
        cuerpo = self.cuerpo(reverse("expedientes:trabajador_create"))
        self.assertIn('<label for="id_puesto">Cargo</label>', cuerpo)
