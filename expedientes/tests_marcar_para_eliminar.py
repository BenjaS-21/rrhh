"""Marcar un documento para eliminar, sin poder eliminarlo.

Viene de un reporte: se sube un archivo equivocado y RRHH Interior no lo puede
sacar. Borrar es del Administrador y así se queda —eso no se toca—, pero
faltaba la otra mitad: quien sube es quien se da cuenta en el momento, y no
tenía forma de decirlo. El documento equivocado se quedaba en el expediente
hasta que alguien más lo mirara.

Ahora lo marca. La marca no borra: avisa. Los marcados se juntan en una lista
en Configuración, y de ahí salen por dos caminos: el Administrador confirma, o
se cumple el plazo que él mismo puso y se van solos.

Lo que más se cuida acá es que marcar NO se convierta en borrar por la puerta
de atrás. Varias de estas pruebas existen solo para eso.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from configuracion.models import Preferencias
from cuentas.models import Sede, Zona
from expedientes.models import Documento, RegistroAuditoria, TipoDocumento, Trabajador
from expedientes.purga import barrer, pendientes

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class _Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="TACHIRA")
        cls.sede = Sede.objects.create(nombre="SAN CRISTOBAL", zona=zona)
        cls.tipo = TipoDocumento.objects.create(nombre="Cédula", orden=1)
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="30719983", nombres="MARIANA",
            apellidos="QUINTERO", sede=cls.sede)

        cls.admin = cls._usuario("adm", Usuario.Rol.ADMIN)
        cls.interior = cls._usuario("interior", Usuario.Rol.RRHH_INTERIOR)
        cls.lectura = cls._usuario("mira", Usuario.Rol.SOLO_LECTURA)

    @classmethod
    def _usuario(cls, username, rol):
        u = Usuario.objects.create_user(username=username, password=CLAVE)
        u.rol = rol
        u.save()
        return u

    def setUp(self):
        self.doc = Documento.objects.create(
            trabajador=self.trabajador, tipo=self.tipo,
            archivo=SimpleUploadedFile("cedula.pdf", b"%PDF-1.4 contenido"),
            nombre_original="cedula.pdf", subido_por=self.interior)

    def marcar(self, usuario=None, **datos):
        self.client.force_login(usuario or self.interior)
        return self.client.post(
            reverse("expedientes:documento_marcar", args=[self.doc.pk]), datos)

    def desmarcar(self, usuario=None, **datos):
        self.client.force_login(usuario or self.interior)
        return self.client.post(
            reverse("expedientes:documento_desmarcar", args=[self.doc.pk]), datos)

    def recargar(self):
        self.doc.refresh_from_db()
        return self.doc


class RrhhInteriorPuedeMarcar(_Base):
    """El pedido, textual: «que ellos puedan marcar para eliminar»."""

    def test_marca_y_queda_registrado_quien_fue(self):
        self.assertEqual(self.marcar().status_code, 302)
        doc = self.recargar()
        self.assertTrue(doc.marcado)
        self.assertEqual(doc.marcado_por, self.interior)
        self.assertIsNotNone(doc.marcado_en)

    def test_puede_dejar_dicho_por_que(self):
        self.marcar(motivo="Subí la cédula del hermano")
        self.assertEqual(self.recargar().motivo_marca, "Subí la cédula del hermano")

    def test_y_desmarcar_si_se_equivoco(self):
        """El «en caso tal» del pedido."""
        self.marcar()
        self.assertEqual(self.desmarcar().status_code, 302)
        doc = self.recargar()
        self.assertFalse(doc.marcado)
        self.assertIsNone(doc.marcado_por)
        self.assertEqual(doc.motivo_marca, "")

    def test_el_administrador_tambien_puede_marcar(self):
        self.marcar(usuario=self.admin)
        self.assertTrue(self.recargar().marcado)

    def test_solo_lectura_no_puede(self):
        """Testigo: «ver, añadir y editar» no incluye a quien solo mira."""
        self.assertEqual(self.marcar(usuario=self.lectura).status_code, 403)
        self.assertFalse(self.recargar().marcado)

    def test_sin_sesion_tampoco(self):
        r = self.client.post(
            reverse("expedientes:documento_marcar", args=[self.doc.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn("ingresar", r["Location"])
        self.assertFalse(self.recargar().marcado)

    def test_no_se_marca_entrando_por_la_direccion(self):
        """Con un GET no cambia nada: si no, bastaría un enlace."""
        self.client.force_login(self.interior)
        r = self.client.get(reverse("expedientes:documento_marcar", args=[self.doc.pk]))
        self.assertEqual(r.status_code, 405)
        self.assertFalse(self.recargar().marcado)

    def test_queda_asentado_en_la_auditoria(self):
        self.marcar(motivo="No corresponde")
        ultimo = RegistroAuditoria.objects.filter(entidad="Documento").latest("id")
        self.assertIn("Marcó para eliminar", ultimo.descripcion)
        self.assertIn("No corresponde", ultimo.descripcion)
        self.assertEqual(ultimo.usuario_texto, "interior")


class PeroMarcarNoEsBorrar(_Base):
    """La parte que no puede aflojarse: sigue estando todo.

    La restricción de siempre es que solo el Administrador borra. Si marcar
    sacara el documento de la vista, o lo mandara a la papelera, sería lo mismo
    que borrar con otro nombre.
    """

    def setUp(self):
        super().setUp()
        self.marcar(motivo="No va")

    def test_el_documento_sigue_activo(self):
        self.assertTrue(self.recargar().activo)

    def test_sigue_apareciendo_en_el_expediente(self):
        self.client.force_login(self.interior)
        cuerpo = self.client.get(
            reverse("expedientes:trabajador_detail",
                    args=[self.trabajador.pk])).content.decode()
        self.assertIn("cedula.pdf", cuerpo)

    def test_y_se_puede_seguir_descargando(self):
        self.client.force_login(self.interior)
        r = self.client.get(
            reverse("expedientes:documento_descargar", args=[self.doc.pk]))
        self.assertEqual(r.status_code, 200)

    def test_el_archivo_no_se_toco(self):
        self.assertTrue(self.recargar().archivo.storage.exists(self.doc.archivo.name))

    def test_rrhh_interior_sigue_sin_poder_borrar(self):
        """Testigo del testigo: la puerta de siempre sigue cerrada."""
        self.client.force_login(self.interior)
        r = self.client.post(
            reverse("expedientes:documento_borrar", args=[self.doc.pk]))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(self.recargar().activo)

    def test_se_ve_en_pantalla_que_esta_marcado(self):
        """Si no se nota, dos personas marcan lo mismo y nadie sabe por qué."""
        self.client.force_login(self.interior)
        cuerpo = self.client.get(
            reverse("expedientes:trabajador_detail",
                    args=[self.trabajador.pk])).content.decode()
        self.assertIn("Marcado para eliminar", cuerpo)


class LaListaDePendientes(_Base):

    def url(self):
        return reverse("configuracion:pendientes")

    def test_el_marcado_aparece(self):
        self.marcar(motivo="Archivo repetido")
        self.client.force_login(self.admin)
        cuerpo = self.client.get(self.url()).content.decode()
        self.assertIn("QUINTERO", cuerpo)
        self.assertIn("Archivo repetido", cuerpo)

    def test_el_que_no_esta_marcado_no_aparece(self):
        """Testigo: una lista que muestre todo no es una lista de pendientes."""
        self.client.force_login(self.admin)
        self.assertNotIn("cedula.pdf", self.client.get(self.url()).content.decode())

    def test_solo_entra_el_administrador(self):
        self.marcar()
        self.client.force_login(self.interior)
        r = self.client.get(self.url(), follow=True)
        self.assertNotIn("Archivo repetido", r.content.decode())
        self.assertNotEqual(r.request["PATH_INFO"], self.url())

    def test_desde_ahi_se_elimina_y_vuelve_a_la_lista(self):
        self.marcar()
        self.client.force_login(self.admin)
        r = self.client.post(
            reverse("expedientes:documento_borrar", args=[self.doc.pk]),
            {"volver": self.url()})
        self.assertEqual(r["Location"], self.url())
        self.assertFalse(self.recargar().activo)

    def test_y_tambien_se_puede_devolver_al_expediente(self):
        self.marcar()
        self.client.force_login(self.admin)
        r = self.client.post(
            reverse("expedientes:documento_desmarcar", args=[self.doc.pk]),
            {"volver": self.url()})
        self.assertEqual(r["Location"], self.url())
        doc = self.recargar()
        self.assertFalse(doc.marcado)
        self.assertTrue(doc.activo)

    def test_el_ya_eliminado_deja_de_figurar(self):
        """Si siguiera, se «eliminaría» una y otra vez lo mismo."""
        self.marcar()
        self.doc.activo = False
        self.doc.save(update_fields=["activo"])
        self.assertEqual(pendientes().count(), 0)

    def test_el_volver_no_lleva_a_otro_sitio(self):
        """El destino viaja en el formulario: se valida como el `next` del login."""
        self.marcar()
        self.client.force_login(self.admin)
        r = self.client.post(
            reverse("expedientes:documento_desmarcar", args=[self.doc.pk]),
            {"volver": "https://sitio-falso.example/"})
        self.assertNotIn("sitio-falso", r["Location"])

    def test_el_indice_de_configuracion_dice_cuantos_hay(self):
        """Sin el número hay que entrar para saber que alguien está esperando."""
        self.marcar()
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("configuracion:index")).content.decode()
        self.assertIn("Pendientes de eliminar", cuerpo)
        self.assertIn("1 documento", cuerpo)


class ElPlazoAutomatico(_Base):

    def plazo(self, dias):
        Preferencias.objects.update_or_create(
            pk=1, defaults={"dias_para_eliminar_marcados": dias})

    def marcar_hace(self, dias):
        self.marcar()
        Documento.objects.filter(pk=self.doc.pk).update(
            marcado_en=timezone.now() - timedelta(days=dias))

    def test_sin_plazo_no_se_borra_nunca_solo(self):
        """El valor de fábrica. Que empiece a borrar solo es una decisión."""
        self.plazo(0)
        self.marcar_hace(3650)
        self.assertEqual(barrer(), 0)
        self.assertTrue(self.recargar().activo)

    def test_con_el_plazo_cumplido_pasa_a_la_papelera(self):
        self.plazo(7)
        self.marcar_hace(8)
        self.assertEqual(barrer(), 1)
        self.assertFalse(self.recargar().activo)

    def test_antes_del_plazo_no_se_toca(self):
        """Testigo: barrer todo lo marcado haría del plazo un adorno."""
        self.plazo(7)
        self.marcar_hace(3)
        self.assertEqual(barrer(), 0)
        self.assertTrue(self.recargar().activo)

    def test_va_a_la_papelera_y_no_se_destruye(self):
        """Un borrado por tiempo es un borrado sin nadie mirando.

        Si alguien marca mal y nadie revisa la lista a tiempo, de la papelera
        el archivo vuelve; destruido, no.
        """
        self.plazo(1)
        self.marcar_hace(2)
        barrer()
        self.assertTrue(Documento.objects.filter(pk=self.doc.pk).exists())
        self.assertTrue(self.recargar().archivo.storage.exists(self.doc.archivo.name))

    def test_el_desmarcado_se_salva_aunque_sea_viejo(self):
        self.plazo(1)
        self.marcar_hace(30)
        self.desmarcar()
        self.assertEqual(barrer(), 0)
        self.assertTrue(self.recargar().activo)

    def test_queda_asentado_a_nombre_del_sistema(self):
        """No lo borró quien abrió la pantalla: se cumplió un plazo."""
        self.plazo(1)
        self.marcar_hace(2)
        barrer()
        ultimo = RegistroAuditoria.objects.filter(entidad="Documento").latest("id")
        self.assertEqual(ultimo.usuario_texto, "sistema")
        self.assertIn("Papelera automática", ultimo.descripcion)

    def test_barrer_dos_veces_no_duplica_nada(self):
        self.plazo(1)
        self.marcar_hace(2)
        barrer()
        self.assertEqual(barrer(), 0)

    def test_abrir_la_lista_barre_sola(self):
        """Lo que el pedido llama «en el mismo listado»."""
        self.plazo(1)
        self.marcar_hace(2)
        self.client.force_login(self.admin)
        self.client.get(reverse("configuracion:pendientes"))
        self.assertFalse(self.recargar().activo)

    def test_el_comando_tambien_barre(self):
        """Para que el plazo se cumpla aunque nadie abra la pantalla."""
        from io import StringIO

        from django.core.management import call_command
        self.plazo(1)
        self.marcar_hace(2)
        call_command("purgar_marcados", stdout=StringIO())
        self.assertFalse(self.recargar().activo)

    def test_el_plazo_se_configura_desde_opciones(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("configuracion:preferencias")).content.decode()
        self.assertIn("dias_para_eliminar_marcados", cuerpo)

    def test_y_lo_cambia_solo_el_administrador(self):
        """Testigo: el plazo decide cuándo se borra sin preguntar. Es del admin."""
        self.client.force_login(self.interior)
        self.client.post(reverse("configuracion:preferencias"),
                         {"dias_para_eliminar_marcados": 1})
        self.assertEqual(Preferencias.obtener().dias_para_eliminar_marcados, 0)


class DejarElPlazoEnBlanco(_Base):
    """Vacío es «sin plazo», no un error.

    La columna no admite nulos, así que un campo vacío tenía que significar
    algo. Obligar a escribir un 0 para decir «no quiero que se borre solo» es
    pedir que se declare lo que ya es.
    """

    def guardar(self, **datos):
        self.client.force_login(self.admin)
        return self.client.post(reverse("configuracion:preferencias"), datos)

    def test_se_guarda_como_cero(self):
        r = self.guardar(dias_para_eliminar_marcados="")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Preferencias.obtener().dias_para_eliminar_marcados, 0)

    def test_y_entonces_no_se_borra_nada_solo(self):
        self.guardar(dias_para_eliminar_marcados="")
        self.marcar()
        Documento.objects.filter(pk=self.doc.pk).update(
            marcado_en=timezone.now() - timedelta(days=999))
        self.assertEqual(barrer(), 0)

    def test_un_plazo_escrito_se_respeta(self):
        """Testigo: si todo terminara en 0, el plazo no existiría."""
        self.guardar(dias_para_eliminar_marcados="15")
        self.assertEqual(Preferencias.obtener().dias_para_eliminar_marcados, 15)

    def test_guardar_las_opciones_no_prende_la_restriccion_por_zona(self):
        """Testigo del testigo: el otro ajuste sigue mandando lo suyo."""
        self.guardar(dias_para_eliminar_marcados="15")
        self.assertFalse(Preferencias.obtener().restringir_por_zona)
