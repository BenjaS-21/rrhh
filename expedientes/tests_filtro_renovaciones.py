"""Buscar y filtrar en la pantalla de Renovaciones de contrato.

Pedido de quien usa el sistema, con la pantalla abierta: «aquí necesito un
filtro por nombre, cédula, etc o tienda».

La pantalla listaba a todos los activos del rango elegido y lo único que se
podía cambiar era el rango. Con una nómina de varias tiendas eso es buscar a
mano en una tabla larga para renovarle el contrato a una persona.

Se reusa el formulario del listado de expedientes en vez de escribir otro: así
«buscar» significa lo mismo en las dos pantallas —nombre, apellido o cédula— y
el recorte por zona de las tiendas no puede quedar distinto en una que en otra.

Lo que hay que cuidar es que filtrar no se pelee con lo que la pantalla hace,
que es guardar fechas: después de guardar hay que volver al mismo filtro, o
renovar una tanda significa volver a filtrar en cada renglón.
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cuentas.models import Cargo, Departamento, Sede, TipoDocumentoIdentidad, Zona
from expedientes.models import DatosContratacion, Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class _ConRenovaciones(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.guatire = Sede.objects.create(nombre="CENTRO DE DISTRIBUCION GUATIRE I",
                                          zona=zona)
        cls.caracas = Sede.objects.create(nombre="TIENDA CARIBIA", zona=zona)
        unidad = Departamento.objects.create(nombre="ALMACEN")
        cargo = Cargo.objects.create(nombre="ALMACENISTA", departamento=unidad)
        tipo = TipoDocumentoIdentidad.objects.get(codigo="V")
        hoy = timezone.localdate()

        def alta(cedula, nombres, apellidos, sede, dentro_de):
            t = Trabajador.objects.create(
                documento_identidad=cedula, tipo_documento=tipo,
                nombres=nombres, apellidos=apellidos, sede=sede,
                departamento=unidad, puesto=cargo,
                fecha_ingreso=hoy - timedelta(days=90))
            DatosContratacion.objects.create(
                trabajador=t, fecha_culminacion=hoy + timedelta(days=dentro_de))
            return t

        cls.jhon = alta("18752507", "JHON EDUARDO", "CONTRERA RANGEL",
                        cls.guatire, 10)
        cls.jose = alta("11223344", "JOSE GREGORIO", "GONZALEZ INOJOSA",
                        cls.guatire, 20)
        cls.maria = alta("27254018", "MARIA ALEJANDRA", "ACEDO APOLINARES",
                         cls.caracas, 15)

        cls.admin = Usuario.objects.create_user(
            username="diana", password=CLAVE, rol=Usuario.Rol.ADMIN)
        cls.mirona = Usuario.objects.create_user(
            username="mirona", password=CLAVE, rol=Usuario.Rol.SOLO_LECTURA,
            acceso_nacional=True)

    def setUp(self):
        self.client.force_login(self.admin)

    def url(self):
        return reverse("expedientes:renovaciones")

    def apellidos(self, **filtros):
        resp = self.client.get(self.url(), filtros)
        self.assertEqual(resp.status_code, 200)
        return sorted(t.apellidos for t in resp.context["filas"])


class SePuedeBuscarYAcotarPorTienda(_ConRenovaciones):

    def test_sin_filtro_salen_todos_los_del_rango(self):
        """Testigo: si no salieran todos, filtrar no probaría nada."""
        self.assertEqual(len(self.apellidos(rango="30")), 3)

    def test_por_apellido(self):
        self.assertEqual(self.apellidos(rango="30", q="CONTRERA"),
                         ["CONTRERA RANGEL"])

    def test_por_nombre(self):
        self.assertEqual(self.apellidos(rango="30", q="MARIA"),
                         ["ACEDO APOLINARES"])

    def test_por_cedula(self):
        """Es lo que se tiene a mano cuando llama la tienda."""
        self.assertEqual(self.apellidos(rango="30", q="18752507"),
                         ["CONTRERA RANGEL"])

    def test_por_parte_de_la_cedula(self):
        self.assertEqual(self.apellidos(rango="30", q="27254"),
                         ["ACEDO APOLINARES"])

    def test_sin_importar_mayusculas(self):
        self.assertEqual(self.apellidos(rango="30", q="contrera"),
                         ["CONTRERA RANGEL"])

    def test_por_tienda(self):
        self.assertEqual(self.apellidos(rango="30", sedes=self.guatire.pk),
                         ["CONTRERA RANGEL", "GONZALEZ INOJOSA"])

    def test_por_varias_tiendas(self):
        resp = self.client.get(
            self.url(), {"rango": "30",
                         "sedes": [self.guatire.pk, self.caracas.pk]})
        self.assertEqual(len(resp.context["filas"]), 3)

    def test_los_dos_juntos_se_suman(self):
        """Buscar Y tienda: no se reemplazan, se acumulan."""
        self.assertEqual(
            self.apellidos(rango="30", q="GONZALEZ", sedes=self.guatire.pk),
            ["GONZALEZ INOJOSA"])
        self.assertEqual(
            self.apellidos(rango="30", q="GONZALEZ", sedes=self.caracas.pk), [])

    def test_el_rango_sigue_mandando(self):
        """Testigo: el filtro acota lo del rango, no lo reemplaza. Alguien que
        vence en 20 días no puede aparecer buscándolo en el rango de 15."""
        self.assertEqual(self.apellidos(rango="vencidos", q="GONZALEZ"), [])

    def test_una_tienda_inventada_no_devuelve_la_lista_entera(self):
        """El mismo cuidado que en el listado: los filtros se aplican de a uno,
        así un enlace viejo no termina mostrando a todo el mundo."""
        self.assertEqual(self.apellidos(rango="30", sedes=99999, q="CONTRERA"),
                         ["CONTRERA RANGEL"])


class LosFiltrosEstanEnLaPantalla(_ConRenovaciones):

    def cuerpo(self, **filtros):
        return self.client.get(self.url(), filtros).content.decode()

    def test_hay_caja_de_busqueda_y_desplegable_de_tiendas(self):
        cuerpo = self.cuerpo(rango="30")
        self.assertIn('name="q"', cuerpo)
        self.assertIn('name="sedes"', cuerpo)

    def test_el_rango_viaja_en_el_mismo_formulario(self):
        """Si estuvieran en formularios distintos, elegir un rango borraría la
        búsqueda y buscar borraría el rango."""
        cuerpo = self.cuerpo(rango="30")
        formulario = cuerpo.split('method="get"')[1].split("</form>")[0]
        self.assertIn('name="rango"', formulario)
        self.assertIn('name="q"', formulario)
        self.assertIn('name="sedes"', formulario)

    def test_cuando_no_coincide_nadie_lo_dice_por_el_filtro(self):
        """Y no «nadie vence en ese rango», que con un filtro puesto es
        mentira: hay tres, no coincide ninguno."""
        cuerpo = self.cuerpo(rango="30", q="NADIE")
        self.assertIn("Nadie coincide con lo que buscaste", cuerpo)
        self.assertNotIn("Nadie vence en ese rango", cuerpo)

    def test_sin_filtro_el_mensaje_sigue_siendo_el_del_rango(self):
        """Testigo del anterior."""
        cuerpo = self.cuerpo(rango="vencidos")
        self.assertIn("Ningún contrato vencido", cuerpo)

    def test_solo_lectura_no_entra(self):
        """Testigo: el filtro nuevo no puede haber abierto la pantalla."""
        self.client.force_login(self.mirona)
        resp = self.client.get(self.url())
        self.assertEqual(resp.status_code, 302)


class GuardarUnaFechaNoBorraElFiltro(_ConRenovaciones):
    """Lo que hace usable la pantalla: se filtra una vez y se renueva la tanda.

    Antes se volvía con `?rango=` solo, así que después de cada Guardar había
    que volver a escribir la búsqueda y a marcar la tienda.
    """

    def volver(self, url_post, **extra):
        datos = {"volver": f"rango=30&q=CONTRERA&sedes={self.guatire.pk}"}
        datos.update(extra)
        return self.client.post(url_post, datos)

    def test_al_guardar_una_fecha(self):
        resp = self.volver(
            reverse("expedientes:renovacion_guardar", args=[self.jhon.pk]),
            fecha_culminacion="2026-12-31")
        self.assertEqual(resp.status_code, 302)
        for trozo in ("rango=30", "q=CONTRERA", f"sedes={self.guatire.pk}"):
            with self.subTest(trozo=trozo):
                self.assertIn(trozo, resp["Location"])

    def test_y_al_renovar_90_dias(self):
        resp = self.volver(
            reverse("expedientes:renovacion_renovar", args=[self.jhon.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("q=CONTRERA", resp["Location"])

    def test_la_fecha_igual_se_guardo(self):
        """Testigo: conservar el filtro no puede costar el guardado."""
        self.volver(
            reverse("expedientes:renovacion_guardar", args=[self.jhon.pk]),
            fecha_culminacion="2026-12-31")
        self.jhon.refresh_from_db()
        self.assertEqual(self.jhon.contratacion.fecha_culminacion,
                         date(2026, 12, 31))

    def test_sin_filtros_vuelve_al_rango_de_siempre(self):
        resp = self.client.post(
            reverse("expedientes:renovacion_guardar", args=[self.jhon.pk]),
            {"volver": "", "rango": "60", "fecha_culminacion": "2026-12-31"})
        self.assertIn("rango=60", resp["Location"])

    def test_no_se_puede_colar_una_redireccion_a_otro_sitio(self):
        """`volver` viene del navegador. Se rearma desde las claves conocidas
        y la URL la construye el servidor, así que no hay a dónde escaparse."""
        resp = self.client.post(
            reverse("expedientes:renovacion_guardar", args=[self.jhon.pk]),
            {"volver": "rango=30&next=https://ejemplo.com/&otra=1",
             "fecha_culminacion": "2026-12-31"})
        self.assertTrue(resp["Location"].startswith(
            reverse("expedientes:renovaciones")))
        self.assertNotIn("ejemplo.com", resp["Location"])
        self.assertNotIn("otra=1", resp["Location"])
