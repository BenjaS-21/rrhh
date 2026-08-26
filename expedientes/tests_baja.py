"""Dar de baja / reactivar un expediente desde su detalle.

La baja no borra nada: el trabajador deja de contarse como activo en los
listados (el filtro de estado del listado ya estaba). La pueden dar el
Administrador y RRHH Interior —este último, solo dentro de su zona cuando la
restricción está prendida—. Solo lectura no.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from configuracion.models import Preferencias
from cuentas.models import Sede, Zona
from expedientes.models import RegistroAuditoria, Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class _ConExpediente(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.zona = Zona.objects.create(nombre="MIRANDA")
        sede = Sede.objects.create(nombre="TRINIDAD", zona=cls.zona)
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="V-1", nombres="Ana", apellidos="Alvarez",
            sede=sede)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def url(self):
        return reverse("expedientes:trabajador_estado", args=[self.trabajador.pk])

    def estado(self):
        return Trabajador.objects.get(pk=self.trabajador.pk).estado


class ElAdminDaDeBajaYReactiva(_ConExpediente):

    def test_dar_de_baja(self):
        self.client.force_login(self.admin)
        self.client.post(self.url())
        self.assertEqual(self.estado(), Trabajador.Estado.BAJA)

    def test_queda_en_la_auditoria(self):
        self.client.force_login(self.admin)
        self.client.post(self.url())
        asiento = RegistroAuditoria.objects.filter(
            entidad="Trabajador", objeto_id=str(self.trabajador.pk)).get()
        self.assertIn("Dio de baja", asiento.descripcion)

    def test_reactivar(self):
        Trabajador.objects.filter(pk=self.trabajador.pk).update(estado="BAJA")
        self.client.force_login(self.admin)
        self.client.post(self.url())
        self.assertEqual(self.estado(), Trabajador.Estado.ACTIVO)

    def test_por_get_no(self):
        self.client.force_login(self.admin)
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 405)
        self.assertEqual(self.estado(), Trabajador.Estado.ACTIVO)


class LosPermisosSonLosDeEditar(_ConExpediente):

    def _usuario(self, username, zona=None):
        u = Usuario.objects.create_user(username=username, password=CLAVE)
        u.rol = Usuario.Rol.RRHH_INTERIOR
        u.zona = zona
        u.save()
        return u

    def test_interior_de_la_zona_si_puede(self):
        Preferencias.obtener()
        Preferencias.objects.filter(pk=1).update(restringir_por_zona=True)
        self.client.force_login(self._usuario("int", zona=self.zona))
        self.client.post(self.url())
        self.assertEqual(self.estado(), Trabajador.Estado.BAJA)

    def test_interior_de_otra_zona_no(self):
        Preferencias.obtener()
        Preferencias.objects.filter(pk=1).update(restringir_por_zona=True)
        otra = Zona.objects.create(nombre="LARA")
        self.client.force_login(self._usuario("otra", zona=otra))
        r = self.client.post(self.url())
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.estado(), Trabajador.Estado.ACTIVO)

    def test_solo_lectura_no(self):
        u = Usuario.objects.create_user(username="lec", password=CLAVE)
        u.rol = Usuario.Rol.SOLO_LECTURA
        u.save()
        self.client.force_login(u)
        r = self.client.post(self.url())
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.estado(), Trabajador.Estado.ACTIVO)

    def test_principal_si_puede(self):
        u = Usuario.objects.create_user(username="pri", password=CLAVE)
        u.rol = Usuario.Rol.RRHH_PRINCIPAL
        u.save()
        self.client.force_login(u)
        self.client.post(self.url())
        self.assertEqual(self.estado(), Trabajador.Estado.BAJA)


class LasObservacionesDeLaBaja(_ConExpediente):

    def _detalle(self):
        return self.client.get(
            reverse("expedientes:trabajador_detail",
                    args=[self.trabajador.pk])).content.decode()

    def test_se_guardan_al_dar_de_baja(self):
        self.client.force_login(self.admin)
        self.client.post(self.url(), {"observaciones": "Renuncia voluntaria"})
        t = Trabajador.objects.get(pk=self.trabajador.pk)
        self.assertEqual(t.observaciones_baja, "Renuncia voluntaria")

    def test_quedan_en_la_auditoria(self):
        self.client.force_login(self.admin)
        self.client.post(self.url(), {"observaciones": "Fin de contrato"})
        asiento = RegistroAuditoria.objects.filter(
            entidad="Trabajador", objeto_id=str(self.trabajador.pk)).get()
        self.assertIn("Fin de contrato", asiento.descripcion)

    def test_reactivar_limpia(self):
        Trabajador.objects.filter(pk=self.trabajador.pk).update(
            estado="BAJA", observaciones_baja="Despido")
        self.client.force_login(self.admin)
        self.client.post(self.url())
        t = Trabajador.objects.get(pk=self.trabajador.pk)
        self.assertEqual(t.observaciones_baja, "")

    def test_se_muestran_en_el_detalle(self):
        Trabajador.objects.filter(pk=self.trabajador.pk).update(
            estado="BAJA", observaciones_baja="Renuncia voluntaria")
        self.client.force_login(self.admin)
        self.assertIn("Renuncia voluntaria", self._detalle())

    def test_solo_lectura_no_las_ve_en_el_detalle(self):
        Trabajador.objects.filter(pk=self.trabajador.pk).update(
            estado="BAJA", observaciones_baja="Renuncia voluntaria")
        u = Usuario.objects.create_user(username="lec3", password=CLAVE)
        u.rol = Usuario.Rol.SOLO_LECTURA
        u.save()
        self.client.force_login(u)
        self.assertNotIn("Renuncia voluntaria", self._detalle())


class ElBotonEnLaPantalla(_ConExpediente):

    def test_activo_ofrece_dar_de_baja(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(
            reverse("expedientes:trabajador_detail",
                    args=[self.trabajador.pk])).content.decode()
        self.assertIn("Dar de baja", cuerpo)
        self.assertIn(self.url(), cuerpo)

    def test_de_baja_ofrece_reactivar(self):
        Trabajador.objects.filter(pk=self.trabajador.pk).update(estado="BAJA")
        self.client.force_login(self.admin)
        cuerpo = self.client.get(
            reverse("expedientes:trabajador_detail",
                    args=[self.trabajador.pk])).content.decode()
        self.assertIn("Reactivar", cuerpo)

    def test_solo_lectura_no_lo_ve(self):
        u = Usuario.objects.create_user(username="lec2", password=CLAVE)
        u.rol = Usuario.Rol.SOLO_LECTURA
        u.save()
        self.client.force_login(u)
        cuerpo = self.client.get(
            reverse("expedientes:trabajador_detail",
                    args=[self.trabajador.pk])).content.decode()
        self.assertNotIn("Dar de baja", cuerpo)
