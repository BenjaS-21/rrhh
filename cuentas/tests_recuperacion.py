"""El link público de recuperación de clave.

Lo genera el Administrador desde Configuración → Usuarios y la persona elige
su clave nueva sin entrar al sistema. Un solo uso, vence a las 48 horas, y al
usarse anula los demás links activos de la misma cuenta.
"""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cuentas.models import RecuperacionClave

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class _ConLink(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.usuario = Usuario.objects.create_user(username="ana", password=CLAVE)
        cls.rec = RecuperacionClave.objects.create(usuario=cls.usuario)

    def url(self, rec=None):
        rec = rec or self.rec
        return reverse("cuentas:recuperar", args=[rec.token])


class ElLinkVigente(_ConLink):

    def test_abre_el_formulario(self):
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Clave nueva", r.content)

    def test_cambia_la_clave_y_se_gasta(self):
        r = self.client.post(self.url(), {
            "new_password1": "Clave-Nueva-789", "new_password2": "Clave-Nueva-789"})
        self.assertRedirects(r, reverse("cuentas:login"))
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password("Clave-Nueva-789"))
        self.rec.refresh_from_db()
        self.assertTrue(self.rec.esta_usada)

    def test_no_pide_la_clave_vieja(self):
        """El POST va directo: el link ya es la prueba."""
        cuerpo = self.client.get(self.url()).content.decode()
        self.assertNotIn("old_password", cuerpo)

    def test_al_usarse_anula_los_demas_links(self):
        otro = RecuperacionClave.objects.create(usuario=self.usuario)
        self.client.post(self.url(), {
            "new_password1": "Clave-Nueva-789", "new_password2": "Clave-Nueva-789"})
        otro.refresh_from_db()
        self.assertFalse(otro.activa)


class ElLinkGastadoNoSirve(_ConLink):

    def test_una_vez_usado_da_410(self):
        self.client.post(self.url(), {
            "new_password1": "Clave-Nueva-789", "new_password2": "Clave-Nueva-789"})
        self.assertEqual(self.client.get(self.url()).status_code, 410)

    def test_expirado_da_410(self):
        RecuperacionClave.objects.filter(pk=self.rec.pk).update(
            expira_en=timezone.now() - datetime.timedelta(hours=1))
        self.assertEqual(self.client.get(self.url()).status_code, 410)

    def test_anulado_da_410(self):
        RecuperacionClave.objects.filter(pk=self.rec.pk).update(activa=False)
        self.assertEqual(self.client.get(self.url()).status_code, 410)

    def test_usuario_desactivado_da_410(self):
        self.usuario.is_active = False
        self.usuario.save()
        self.assertEqual(self.client.get(self.url()).status_code, 410)

    def test_token_inventado_da_404(self):
        r = self.client.get(reverse("cuentas:recuperar", args=["token-falso"]))
        self.assertEqual(r.status_code, 404)
