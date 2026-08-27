"""El respaldo de la base de datos desde Configuración.

Solo los datos (el .sqlite3): los archivos de los expedientes se respaldan
aparte. Lo descarga el Administrador; los demás roles no pasan del decorador
que protege toda la sección.
"""

import os
import sqlite3
import tempfile

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse

from expedientes.models import RegistroAuditoria

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class _ConUsuarios(TransactionTestCase):
    """TransactionTestCase: el respaldo usa la API de SQLite, que no puede
    trabajar con la transacción que TestCase deja abierta durante el test
    (se queda esperando el candado para siempre). Acá no hay transacción.

    Por lo mismo, los datos se crean en `setUp` y no en `setUpTestData`:
    esta clase vacía las tablas entre prueba y prueba.
    """

    def setUp(self):
        self.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        self.admin.rol = Usuario.Rol.ADMIN
        self.admin.save()
        self.interior = Usuario.objects.create_user(username="int", password=CLAVE)
        self.interior.rol = Usuario.Rol.RRHH_INTERIOR
        self.interior.save()

    def descargar(self):
        return self.client.get(reverse("configuracion:respaldo"))


class ElRespaldoSeDescarga(_ConUsuarios):

    def test_es_un_sqlite_de_verdad(self):
        self.client.force_login(self.admin)
        r = self.descargar()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"SQLite format 3"))

    def test_el_nombre_dice_que_es_y_cuando(self):
        self.client.force_login(self.admin)
        disposicion = self.descargar()["Content-Disposition"]
        self.assertIn("attachment", disposicion)
        self.assertIn("gde-respaldo-", disposicion)
        self.assertIn(".sqlite3", disposicion)

    def test_la_copia_abre_y_tiene_el_esquema(self):
        """No alcanza con que empiece como sqlite: tiene que leerse."""
        self.client.force_login(self.admin)
        datos = self.descargar().content
        temporal = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        try:
            temporal.write(datos)
            temporal.close()
            con = sqlite3.connect(temporal.name)
            try:
                tablas = {f[0] for f in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                con.close()
        finally:
            os.unlink(temporal.name)
        self.assertIn("expedientes_trabajador", tablas)
        self.assertIn("cuentas_usuario", tablas)

    def test_queda_en_la_auditoria(self):
        self.client.force_login(self.admin)
        self.descargar()
        asiento = RegistroAuditoria.objects.filter(entidad="BaseDeDatos").get()
        self.assertEqual(asiento.usuario_texto, "adm")

    def test_se_ofrece_en_el_indice(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(reverse("configuracion:index")).content.decode()
        self.assertIn("Respaldar base de datos", cuerpo)
        self.assertIn(reverse("configuracion:respaldo"), cuerpo)


class LosPermisosSonLosDeTodaLaSeccion(_ConUsuarios):

    def test_rrhh_no_entra(self):
        self.client.force_login(self.interior)
        r = self.descargar()
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("SQLite format 3", r.content.decode(errors="ignore"))

    def test_sin_sesion_al_login(self):
        r = self.descargar()
        self.assertEqual(r.status_code, 302)
        self.assertIn("/cuentas/", r["Location"])
