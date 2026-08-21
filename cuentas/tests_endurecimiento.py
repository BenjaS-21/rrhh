"""Endurecer el sistema para producción: DAM-263.

Está publicado en una dirección de internet, así que lo que en una red interna
era una molestia acá es una puerta. Cada arreglo tiene su prueba testigo: si
alguien deshace el arreglo, la prueba se cae y dice por qué.

Los seis puntos que se cierran acá:

1. `?next=` mandaba a cualquier sitio después de entrar.
2. Cerrar sesión andaba por GET.
3. No había tope de intentos de contraseña.
4. La IP de la bitácora se leía de una cabecera que escribe el cliente.
5. `seed_demo` dejaba una invitación de administrador lista para usar.
6. `DEBUG` venía prendido por omisión.
"""

from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import reverse

from cuentas.models import InvitacionRegistro
from expedientes.auditoria import obtener_ip
from expedientes.models import RegistroAuditoria

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class _ConUsuario(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.usuario = Usuario.objects.create_user(username="benja", password=CLAVE)
        cls.usuario.rol = Usuario.Rol.ADMIN
        cls.usuario.save()

    def setUp(self):
        # El freno vive en la caché y es de todo el proceso: sin limpiarla, una
        # prueba le deja los intentos gastados a la siguiente.
        cache.clear()

    def entrar(self, **extra):
        return self.client.post(reverse("cuentas:login"),
                                {"username": "benja", "password": CLAVE}, **extra)


class ElNextNoLlevaAfuera(_ConUsuario):
    """Un login propio que deposita a la persona en otro sitio."""

    def test_un_destino_de_afuera_se_ignora(self):
        r = self.client.post(
            reverse("cuentas:login") + "?next=https://sitio-falso.example/",
            {"username": "benja", "password": CLAVE,
             "next": "https://sitio-falso.example/"})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("sitio-falso", r["Location"])
        self.assertEqual(r["Location"], reverse("expedientes:panel"))

    def test_ni_disfrazado_de_ruta(self):
        """`//sitio/` sin esquema lo lee el navegador como dominio ajeno."""
        r = self.client.post(reverse("cuentas:login"),
                             {"username": "benja", "password": CLAVE,
                              "next": "//sitio-falso.example/robar"})
        self.assertEqual(r["Location"], reverse("expedientes:panel"))

    def test_ni_con_javascript(self):
        r = self.client.post(reverse("cuentas:login"),
                             {"username": "benja", "password": CLAVE,
                              "next": "javascript:alert(1)"})
        self.assertEqual(r["Location"], reverse("expedientes:panel"))

    def test_pero_un_destino_propio_sigue_andando(self):
        """Testigo: rechazar todo sería más fácil y rompería el `next` legítimo.

        Quien entra a una ficha sin sesión iniciada tiene que volver a esa ficha
        después de identificarse, no al panel.
        """
        destino = reverse("expedientes:nomina")
        r = self.client.post(reverse("cuentas:login"),
                             {"username": "benja", "password": CLAVE, "next": destino})
        self.assertEqual(r["Location"], destino)

    def test_sin_next_va_al_panel(self):
        self.assertEqual(self.entrar()["Location"], reverse("expedientes:panel"))


class CerrarSesionSoloPorPost(_ConUsuario):

    def test_por_get_no_cierra_nada(self):
        """Bastaba una imagen apuntando a /salir/ en cualquier página."""
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("cuentas:logout"))
        self.assertEqual(r.status_code, 405)
        self.assertTrue(self.client.session.get("_auth_user_id"))

    def test_por_post_si(self):
        """Testigo: cerrar sesión tiene que seguir funcionando."""
        self.client.force_login(self.usuario)
        r = self.client.post(reverse("cuentas:logout"))
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(self.client.session.get("_auth_user_id"))

    def test_el_boton_de_la_barra_manda_por_post(self):
        """De nada sirve el candado si la pantalla sigue usando un enlace."""
        self.client.force_login(self.usuario)
        cuerpo = self.client.get(reverse("expedientes:panel")).content.decode()
        salida = reverse("cuentas:logout")
        self.assertNotIn('href="%s"' % salida, cuerpo)
        self.assertIn('action="%s"' % salida, cuerpo)


class TopeDeIntentos(_ConUsuario):

    def fallar(self, veces=1, usuario="benja"):
        respuesta = None
        for _ in range(veces):
            respuesta = self.client.post(reverse("cuentas:login"),
                                         {"username": usuario, "password": "mala"})
        return respuesta

    def test_despues_de_varios_fallos_no_deja_seguir_probando(self):
        self.fallar(settings.LOGIN_INTENTOS_MAX)
        r = self.entrar()
        self.assertEqual(r.status_code, 200,
                         "entró con la contraseña buena estando frenado")
        self.assertIsNone(self.client.session.get("_auth_user_id"))

    def test_dice_cuanto_hay_que_esperar(self):
        """Un "no" sin explicación se lee como cuenta rota y genera un llamado."""
        self.fallar(settings.LOGIN_INTENTOS_MAX)
        cuerpo = self.entrar(follow=True).content.decode()
        self.assertIn(str(settings.LOGIN_BLOQUEO_SEGUNDOS // 60), cuerpo)

    def test_un_fallo_suelto_no_molesta_a_nadie(self):
        """Testigo: equivocarse una vez es lo normal, no un ataque."""
        self.fallar(settings.LOGIN_INTENTOS_MAX - 1)
        self.entrar()
        self.assertTrue(self.client.session.get("_auth_user_id"))

    def test_acertar_borra_la_cuenta_de_fallos(self):
        """Si no, los fallos de ayer frenan a quien hoy escribe bien."""
        self.fallar(settings.LOGIN_INTENTOS_MAX - 1)
        self.entrar()
        self.client.post(reverse("cuentas:logout"))
        self.fallar(settings.LOGIN_INTENTOS_MAX - 1)
        self.entrar()
        self.assertTrue(self.client.session.get("_auth_user_id"))

    def test_frenar_a_uno_no_frena_a_los_demas(self):
        """Testigo: contar solo por origen dejaría afuera a toda una tienda.

        En una sucursal todas las computadoras salen por la misma IP.
        """
        self.fallar(settings.LOGIN_INTENTOS_MAX, usuario="otro")
        self.entrar()
        self.assertTrue(self.client.session.get("_auth_user_id"))

    def test_queda_asentado_el_bloqueo(self):
        self.fallar(settings.LOGIN_INTENTOS_MAX)
        self.entrar()
        ultimo = RegistroAuditoria.objects.latest("id")
        self.assertEqual(ultimo.accion, RegistroAuditoria.Accion.LOGIN_FALLIDO)
        self.assertIn("bloqueado", ultimo.descripcion)


class LaIpDeLaBitacoraNoSeLaDictaCualquiera(TestCase):
    """La auditoría es prueba de quién hizo qué. Si se puede escribir, no lo es."""

    def pedir(self, **cabeceras):
        return obtener_ip(RequestFactory().get("/", **cabeceras))

    def test_de_afuera_no_se_le_cree_la_cabecera(self):
        ip = self.pedir(REMOTE_ADDR="200.44.1.5", HTTP_X_FORWARDED_FOR="8.8.8.8")
        self.assertEqual(ip, "200.44.1.5",
                         "se firmó la acción con una IP inventada")

    def test_desde_el_tunel_si(self):
        """Testigo: si no, toda la bitácora diría 127.0.0.1 y no serviría."""
        self.assertEqual(
            self.pedir(REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="190.202.3.4"),
            "190.202.3.4")

    def test_cloudflare_manda_sobre_la_lista(self):
        self.assertEqual(
            self.pedir(REMOTE_ADDR="127.0.0.1",
                       HTTP_CF_CONNECTING_IP="190.202.3.4",
                       HTTP_X_FORWARDED_FOR="1.2.3.4, 5.6.7.8"),
            "190.202.3.4")

    def test_basura_en_la_cabecera_no_entra_al_registro(self):
        self.assertEqual(
            self.pedir(REMOTE_ADDR="127.0.0.1",
                       HTTP_X_FORWARDED_FOR="no soy una ip"),
            "127.0.0.1")

    def test_sin_cabeceras_vale_la_conexion(self):
        self.assertEqual(self.pedir(REMOTE_ADDR="192.168.1.20"), "192.168.1.20")


class SeedDemoNoRegalaUnAdministrador(TestCase):

    def test_no_queda_ninguna_invitacion_de_admin(self):
        """El link es válido: quien lo abra se hace administrador nacional."""
        call_command("seed_demo", stdout=StringIO())
        self.assertFalse(
            InvitacionRegistro.objects.filter(
                rol=Usuario.Rol.ADMIN, activa=True).exists(),
            "seed_demo dejó una invitación de administrador lista para usar")

    def test_pero_sigue_creando_las_otras(self):
        """Testigo: vaciar la lista entera dejaría el comando sin sentido."""
        call_command("seed_demo", stdout=StringIO())
        self.assertTrue(InvitacionRegistro.objects.exists())


class LaConfiguracionFallaHaciaElLadoSeguro(TestCase):
    """Lo que pasa cuando alguien se olvida de poner una variable."""

    def test_debug_apagado_por_omision(self):
        import os

        from config.settings import env_bool
        anterior = os.environ.pop("DJANGO_DEBUG", None)
        try:
            self.assertFalse(env_bool("DJANGO_DEBUG", False))
        finally:
            if anterior is not None:
                os.environ["DJANGO_DEBUG"] = anterior

    def test_los_documentos_no_se_sirven_por_una_direccion_adivinable(self):
        self.assertNotEqual(settings.MEDIA_URL, "/media/")

    def test_la_cookie_de_sesion_no_se_lee_desde_javascript(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)

    def test_la_base_espera_su_turno_en_vez_de_fallar(self):
        """Dos personas guardando a la vez: SQLite deja escribir a una sola."""
        opciones = settings.DATABASES["default"].get("OPTIONS", {})
        self.assertGreaterEqual(opciones.get("timeout", 0), 5)
