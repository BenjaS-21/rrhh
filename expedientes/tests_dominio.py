"""Qué nombres de servidor acepta el sistema.

El túnel de Cloudflare arma un subdominio por máquina y por puerto
(`6652-laptop.aplicacionesdamasco.com`). Sin el comodín, cada equipo nuevo daba
`DisallowedHost` y había que editar el `.env` a mano para que alguien pudiera
entrar.
"""

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse


class NombresDeServidorAceptados(TestCase):

    def entrar(self, host):
        return self.client.get(reverse("cuentas:login"), headers={"host": host})

    # --- Lo que tiene que entrar ---------------------------------------------
    def test_el_subdominio_del_tunel(self):
        self.assertEqual(self.entrar("6652-laptop.aplicacionesdamasco.com").status_code, 200)

    def test_cualquier_maquina_y_puerto(self):
        for host in ("8000-pc-rrhh.aplicacionesdamasco.com",
                     "rrhh.aplicacionesdamasco.com",
                     "gde.aplicacionesdamasco.com",
                     "aplicacionesdamasco.com"):
            with self.subTest(host=host):
                self.assertEqual(self.entrar(host).status_code, 200)

    def test_la_maquina_local_sigue_andando(self):
        for host in ("127.0.0.1", "localhost"):
            with self.subTest(host=host):
                self.assertEqual(self.entrar(host).status_code, 200)

    # --- Lo que no ------------------------------------------------------------
    def test_un_dominio_ajeno_sigue_rechazado(self):
        """El comodín es de un dominio, no de cualquiera.

        Aceptar todo (`*`) abre la puerta a los ataques de cabecera Host: un
        atacante hace que el sistema arme links —una invitación, por ejemplo—
        apuntando a su propio servidor.

        Los dos últimos son los que engañan a una comparación descuidada: uno
        agrega el dominio como prefijo, el otro lo pega con un guion.
        """
        for host in ("otraempresa.com", "aplicacionesdamasco.com.evil.net",
                     "evil-aplicacionesdamasco.com"):
            with self.subTest(host=host):
                self.assertEqual(self.entrar(host).status_code, 400)

    def test_este_archivo_no_aprueba_por_casualidad(self):
        """Testigo: sin el comodín, el subdominio del túnel tiene que fallar.

        Si no, los tests de arriba pasarían igual aunque la configuración no
        hiciera nada.
        """
        with override_settings(ALLOWED_HOSTS=["127.0.0.1", "localhost", "testserver"]):
            self.assertEqual(
                self.entrar("6652-laptop.aplicacionesdamasco.com").status_code, 400)

    def test_no_quedo_el_comodin_universal(self):
        self.assertNotIn("*", settings.ALLOWED_HOSTS)

    # --- Configuración --------------------------------------------------------
    def test_el_dominio_esta_permitido_con_sus_subdominios(self):
        self.assertIn(".aplicacionesdamasco.com", settings.ALLOWED_HOSTS)

    def test_los_formularios_del_subdominio_no_fallan_por_csrf(self):
        """Permitir el host y no el origen deja formularios que no se envían."""
        self.assertIn("https://*.aplicacionesdamasco.com",
                      settings.CSRF_TRUSTED_ORIGINS)

    def test_no_se_repite_si_ya_estaba_en_el_env(self):
        """Cargarlo dos veces no rompe, pero ensucia la configuración."""
        self.assertEqual(settings.ALLOWED_HOSTS.count(".aplicacionesdamasco.com"), 1)
        self.assertEqual(
            settings.CSRF_TRUSTED_ORIGINS.count("https://*.aplicacionesdamasco.com"), 1)

    def test_entrar_por_el_subdominio_lleva_al_login_de_verdad(self):
        cuerpo = self.entrar("6652-laptop.aplicacionesdamasco.com").content.decode()
        self.assertIn("GDE", cuerpo)
        self.assertIn("Ingres", cuerpo)
