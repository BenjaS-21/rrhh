"""El filtro de tiendas del listado tiene que traer a todos los que hay.

Reporte de quien usa el sistema: «al filtrar por tienda hay usuarios que no me
los trae el filtro».

Son dos fallas distintas, y cada una se equivoca para el lado contrario:

**Una tienda desactivada desaparece del filtro, pero su gente sigue en la
lista.** Las opciones del filtro salen de las tiendas ACTIVAS; el listado, de
todos los expedientes que el usuario puede ver, sin mirar si la tienda sigue
activa. Desactivar una tienda con gente adentro es normal —una tienda que
cierra no se borra, porque los expedientes se conservan— y a partir de ahí esa
gente no se puede encontrar filtrando: no hay casilla que tildar. El propio
comentario de `_tiendas_del_usuario` dice que las dos listas tienen que
coincidir, y para las tiendas desactivadas no coincidían.

**Un enlace guardado con una tienda que ya no está tira abajo TODOS los
filtros.** El listado hacía `if form.is_valid()`: con una sola tienda inválida
en la URL el formulario entero quedaba inválido y salía la nómina completa, sin
filtrar por nada. Quien filtró por estado y tienda veía de golpe a todo el
mundo. La nómina ya tenía esto resuelto —aplica los filtros de a uno, con el
motivo escrito— y el listado se quedó atrás.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Cargo, Departamento, Sede, TipoDocumentoIdentidad, Zona
from expedientes.models import Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class _ConDosTiendas(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.abierta = Sede.objects.create(nombre="TIENDA GUATIRE", zona=zona)
        cls.cerrada = Sede.objects.create(nombre="TIENDA SANTA TERESA", zona=zona)
        unidad = Departamento.objects.create(nombre="ADMINISTRACION")
        cargo = Cargo.objects.create(nombre="ASESOR", departamento=unidad)
        tipo = TipoDocumentoIdentidad.objects.get(codigo="V")
        cls.de_la_abierta = Trabajador.objects.create(
            documento_identidad="26045681", tipo_documento=tipo,
            nombres="ANA", apellidos="PEREZ", sede=cls.abierta,
            departamento=unidad, puesto=cargo, fecha_ingreso=date(2026, 8, 3))
        cls.de_la_cerrada = Trabajador.objects.create(
            documento_identidad="30111222", tipo_documento=tipo,
            nombres="LUIS", apellidos="GOMEZ", sede=cls.cerrada,
            departamento=unidad, puesto=cargo, fecha_ingreso=date(2026, 8, 3))
        # La tienda cierra DESPUÉS de tener gente: es el caso real. No se borra
        # —los expedientes se conservan—, se desactiva.
        cls.cerrada.activa = False
        cls.cerrada.save()

        cls.admin = Usuario.objects.create_user(
            username="jefa", password=CLAVE, rol=Usuario.Rol.ADMIN)

    def setUp(self):
        self.client.force_login(self.admin)

    def listado(self, **filtros):
        return self.client.get(reverse("expedientes:trabajador_list"), filtros)

    def apellidos(self, respuesta):
        return sorted(t.apellidos for t in respuesta.context["pagina"])


class LaTiendaCerradaSeSiguePudiendoFiltrar(_ConDosTiendas):

    def test_su_gente_esta_en_el_listado_sin_filtrar(self):
        """Testigo: si no estuviera, no habría nada que filtrar."""
        self.assertIn("GOMEZ", self.apellidos(self.listado()))

    def test_y_la_tienda_se_ofrece_en_el_filtro(self):
        opciones = self.listado().context["form"].fields["sedes"].queryset
        self.assertIn(self.cerrada, opciones,
                      "la tienda cerrada no se puede tildar: su gente queda "
                      "imposible de encontrar filtrando")

    def test_filtrando_por_ella_sale_su_gente(self):
        resp = self.listado(sedes=self.cerrada.pk)
        self.assertEqual(self.apellidos(resp), ["GOMEZ"])

    def test_y_el_filtro_sigue_separando(self):
        """Testigo: ofrecerla no puede significar que salgan todos."""
        resp = self.listado(sedes=self.abierta.pk)
        self.assertEqual(self.apellidos(resp), ["PEREZ"])

    def test_una_tienda_cerrada_y_vacia_no_ensucia_el_filtro(self):
        """Se ofrecen las cerradas que tienen gente, no todas las cerradas.

        Si no, el filtro se llenaría de tiendas viejas sin nadie adentro y
        volvería a ser una lista imposible de leer.
        """
        vacia = Sede.objects.create(nombre="TIENDA VIEJA",
                                    zona=self.abierta.zona, activa=False)
        opciones = self.listado().context["form"].fields["sedes"].queryset
        self.assertNotIn(vacia, opciones)

    def test_al_dar_de_alta_no_se_ofrece_la_cerrada(self):
        """La otra mitad: filtrar por una tienda cerrada sí; asignarle gente
        nueva, no. Una tienda que cerró no recibe ingresos."""
        cuerpo = self.client.get(
            reverse("expedientes:trabajador_create")).content.decode()
        self.assertIn(self.abierta.nombre, cuerpo)
        self.assertNotIn(self.cerrada.nombre, cuerpo)


class UnaTiendaInventadaEnLaUrlNoBorraLosDemasFiltros(_ConDosTiendas):
    """Pasa con un enlace guardado, o con el historial del navegador."""

    def test_los_demas_filtros_se_siguen_aplicando(self):
        resp = self.listado(sedes=99999, q="PEREZ")
        self.assertEqual(
            self.apellidos(resp), ["PEREZ"],
            "una tienda inválida en la URL tiró abajo el filtro de búsqueda")

    def test_no_devuelve_la_lista_entera(self):
        resp = self.listado(sedes=99999, estado=Trabajador.Estado.ACTIVO, q="GOMEZ")
        self.assertNotIn("PEREZ", self.apellidos(resp))
