"""El filtro por cantidad de documentos del listado de expedientes.

Nació de la recuperación de datos: había que saber qué expedientes quedaron
con 0 documentos y cuáles ya tienen sus recaudos. El desplegable detecta solo
el máximo entre los expedientes visibles y ofrece de 0 a ese número.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Sede, Zona
from expedientes.models import Documento, TipoDocumento, Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class _ConExpedientes(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        tipo = TipoDocumento.objects.create(nombre="Recaudos", orden=1)

        def persona(ci, apellido, cuantos_docs):
            t = Trabajador.objects.create(
                documento_identidad=ci, nombres="Ana", apellidos=apellido,
                sede=sede)
            for n in range(cuantos_docs):
                # Solo hace falta la fila: el conteo no mira el archivo.
                Documento.objects.create(
                    trabajador=t, tipo=tipo,
                    archivo=f"documentos/{t.pk}/falso-{n}.pdf")
            return t

        cls.sin_docs = persona("V-1", "SinDocs", 0)
        cls.con_uno = persona("V-2", "ConUno", 1)
        cls.con_tres = persona("V-3", "ConTres", 3)

        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def listado(self, parametros=""):
        self.client.force_login(self.admin)
        return self.client.get(
            reverse("expedientes:trabajador_list") + parametros)

    def nombres_en(self, respuesta):
        cuerpo = respuesta.content.decode()
        return {a for a in ("SinDocs", "ConUno", "ConTres") if a in cuerpo}


class FiltraPorCantidadExacta(_ConExpedientes):

    def test_los_que_no_tienen_ninguno(self):
        """El caso de uso: qué expedientes quedaron vacíos."""
        self.assertEqual(self.nombres_en(self.listado("?docs=0")), {"SinDocs"})

    def test_los_que_tienen_tres(self):
        self.assertEqual(self.nombres_en(self.listado("?docs=3")), {"ConTres"})

    def test_sin_el_filtro_salen_todos(self):
        self.assertEqual(self.nombres_en(self.listado()),
                         {"SinDocs", "ConUno", "ConTres"})

    def test_una_cantidad_que_ya_no_existe_no_rompe_nada(self):
        """Un link guardado con docs=9: no sale nadie, pero no explota ni
        arrastra a los demás filtros."""
        r = self.listado("?docs=9")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.nombres_en(r), set())


class ElDesplegableDetectaElMaximo(_ConExpedientes):

    def test_ofrece_de_cero_al_maximo_detectado(self):
        cuerpo = self.listado().content.decode()
        for n in ("0", "1", "2", "3"):
            self.assertIn(f'value="{n}"', cuerpo)

    def test_y_se_actualiza_solo(self):
        """Si mañana alguien llega a 5, el 5 aparece sin tocar código."""
        for n in range(2):
            Documento.objects.create(
                trabajador=self.con_tres,
                tipo=TipoDocumento.objects.get(),
                archivo=f"documentos/{self.con_tres.pk}/extra-{n}.pdf")
        cuerpo = self.listado().content.decode()
        self.assertIn('value="5"', cuerpo)


class ConviveConLosOtrosFiltros(_ConExpedientes):

    def test_con_busqueda_de_texto_a_la_vez(self):
        r = self.listado("?docs=0&q=SinDocs")
        self.assertEqual(self.nombres_en(r), {"SinDocs"})

    def test_con_estado_a_la_vez(self):
        Trabajador.objects.filter(pk=self.sin_docs.pk).update(estado="BAJA")
        r = self.listado("?docs=0&estado=BAJA")
        self.assertEqual(self.nombres_en(r), {"SinDocs"})


class ElContadorDebajoDelFiltro(_ConExpedientes):

    def test_dice_cuantos_se_muestran_de_cuantos_hay(self):
        self.assertIn("Mostrando 3 de 3 expedientes",
                      self.listado().content.decode())

    def test_cuenta_lo_filtrado_y_en_singular_si_es_uno(self):
        self.assertIn("Mostrando 1 de 1 expediente",
                      self.listado("?docs=0").content.decode())
