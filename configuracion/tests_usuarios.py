"""Configuración → Usuarios: búsqueda, cambio de clave y link de recuperación.

Nace de la operación diaria: alguien llama diciendo «no puedo entrar» y lo
único que se tiene a mano es su correo, su usuario, su nombre o su cédula.
El link de recuperación vale 48 horas y es de un solo uso; generar uno nuevo
anula el anterior.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import RecuperacionClave

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class _Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()
        cls.analista = Usuario.objects.create_user(
            username="ymartinez", password=CLAVE, email="yusmary@correo.com",
            first_name="Yusmary", last_name="Martinez", cedula="V-30111222")
        cls.analista.rol = Usuario.Rol.RRHH_PRINCIPAL
        cls.analista.save()

    def url(self):
        return reverse("configuracion:usuarios")


class LaBusqueda(_Base):

    def encontrados(self, q):
        """(salio el analista, salio el admin) en la tabla de resultados.

        Se mira la URL de acción de cada fila: el encabezado de la página ya
        muestra el nombre del admin logueado y confunde cualquier búsqueda de
        texto plano.
        """
        self.client.force_login(self.admin)
        cuerpo = self.client.get(self.url(), {"q": q}).content.decode()
        return (f"usuarios/{self.analista.pk}/clave/" in cuerpo,
                f"usuarios/{self.admin.pk}/clave/" in cuerpo)

    def test_por_usuario(self):
        self.assertEqual(self.encontrados("ymartinez"), (True, False))

    def test_por_correo(self):
        self.assertEqual(self.encontrados("yusmary@correo"), (True, False))

    def test_por_nombre_y_apellido(self):
        self.assertEqual(self.encontrados("Yusmary"), (True, False))
        self.assertEqual(self.encontrados("Martinez"), (True, False))

    def test_por_cedula(self):
        self.assertEqual(self.encontrados("30111222"), (True, False))

    def test_sin_filtro_salen_todos(self):
        self.assertEqual(self.encontrados(""), (True, True))

    def test_se_ofrece_en_el_indice_de_configuracion(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("configuracion:index")).content.decode()
        self.assertIn("Usuarios", cuerpo)
        self.assertIn(self.url(), cuerpo)

    def test_rrhh_no_entra(self):
        self.client.force_login(self.analista)
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 302)


class CambiarClave(_Base):

    def url(self):
        return reverse("configuracion:usuario_clave", args=[self.analista.pk])

    def test_cambia_la_clave(self):
        self.client.force_login(self.admin)
        self.client.post(self.url(), {
            "new_password1": "Nueva-Clave-456", "new_password2": "Nueva-Clave-456"})
        self.analista.refresh_from_db()
        self.assertTrue(self.analista.check_password("Nueva-Clave-456"))

    def test_si_no_coinciden_no_cambia(self):
        self.client.force_login(self.admin)
        self.client.post(self.url(), {
            "new_password1": "Nueva-Clave-456", "new_password2": "Otra-Cosa-789"})
        self.analista.refresh_from_db()
        self.assertTrue(self.analista.check_password(CLAVE))

    def test_queda_en_la_auditoria(self):
        from expedientes.models import RegistroAuditoria
        self.client.force_login(self.admin)
        self.client.post(self.url(), {
            "new_password1": "Nueva-Clave-456", "new_password2": "Nueva-Clave-456"})
        asiento = RegistroAuditoria.objects.filter(
            entidad="Usuario", objeto_id=str(self.analista.pk)).get()
        self.assertIn("Cambió la clave", asiento.descripcion)


class ElLinkDeRecuperacion(_Base):

    def url(self):
        return reverse("configuracion:usuario_recuperacion", args=[self.analista.pk])

    def test_genera_el_link_y_lo_muestra(self):
        self.client.force_login(self.admin)
        r = self.client.post(self.url(), follow=True)
        rec = RecuperacionClave.objects.get(usuario=self.analista)
        self.assertIn(rec.get_link_absoluto(), r.content.decode())

    def test_uno_nuevo_anula_el_anterior(self):
        self.client.force_login(self.admin)
        self.client.post(self.url())
        viejo = RecuperacionClave.objects.get(usuario=self.analista)
        self.client.post(self.url())
        viejo.refresh_from_db()
        self.assertFalse(viejo.activa)
        self.assertEqual(
            RecuperacionClave.objects.filter(usuario=self.analista, activa=True).count(), 1)

    def test_usuario_desactivado_no(self):
        self.analista.is_active = False
        self.analista.save()
        self.client.force_login(self.admin)
        self.client.post(self.url())
        self.assertEqual(RecuperacionClave.objects.count(), 0)

    def test_rrhh_no_puede(self):
        self.client.force_login(self.analista)
        self.client.post(self.url())
        self.assertEqual(RecuperacionClave.objects.count(), 0)
