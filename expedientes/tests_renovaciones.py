"""Página de renovaciones de contrato.

La ven los roles que editan (Admin, RRHH Interior y Principal); solo lectura
no entra. Filtra por rango de días al vencimiento —los vencidos aparecen en
todos los rangos, son los más urgentes— y permite corregir la fecha de fin
desde la misma lista.
"""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cuentas.models import Sede, Zona
from expedientes.models import DatosContratacion, RegistroAuditoria, Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class _Base(TestCase):

    @classmethod
    def setUpTestData(cls):
        hoy = timezone.localdate()
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()
        cls.lectura = Usuario.objects.create_user(username="lec", password=CLAVE)
        cls.lectura.rol = Usuario.Rol.SOLO_LECTURA
        cls.lectura.save()
        cls.principal = Usuario.objects.create_user(username="pri", password=CLAVE)
        cls.principal.rol = Usuario.Rol.RRHH_PRINCIPAL
        cls.principal.save()

        def _t(cedula, apellidos, fin, estado="ACTIVO"):
            t = Trabajador.objects.create(
                documento_identidad=cedula, nombres="Ana", apellidos=apellidos,
                sede=cls.sede, estado=estado,
                fecha_ingreso=datetime.date(2026, 8, 1))
            DatosContratacion.objects.create(
                trabajador=t, fecha_culminacion=fin)
            return t

        cls.vencido = _t("V-1", "Vencido", hoy - datetime.timedelta(days=3))
        cls.cerca = _t("V-2", "Cerca", hoy + datetime.timedelta(days=10))
        cls.medio = _t("V-3", "Medio", hoy + datetime.timedelta(days=45))
        cls.lejano = _t("V-4", "Lejano", hoy + datetime.timedelta(days=120))
        cls.sin_fecha = _t("V-5", "Sinfecha", None)
        cls.baja = _t("V-6", "Debaja", hoy - datetime.timedelta(days=1),
                      estado="BAJA")

    def ver(self, rango=None, usuario=None):
        self.client.force_login(usuario or self.admin)
        params = {"rango": rango} if rango else {}
        return self.client.get(reverse("expedientes:renovaciones"), params)

    def nombres(self, rango=None):
        return self.ver(rango).content.decode()


class ElFiltro(_Base):

    def test_por_defecto_muestra_90_dias(self):
        cuerpo = self.nombres()
        for nombre in ("Vencido", "Cerca", "Medio"):
            self.assertIn(nombre, cuerpo)
        self.assertNotIn("Lejano", cuerpo)

    def test_vencidos(self):
        cuerpo = self.nombres("vencidos")
        self.assertIn("Vencido", cuerpo)
        self.assertNotIn("Cerca", cuerpo)
        self.assertNotIn("Medio", cuerpo)

    def test_30_dias_incluye_a_los_vencidos(self):
        cuerpo = self.nombres("30")
        self.assertIn("Vencido", cuerpo)
        self.assertIn("Cerca", cuerpo)
        self.assertNotIn("Medio", cuerpo)

    def test_todos_los_que_tienen_fecha(self):
        cuerpo = self.nombres("todos")
        for nombre in ("Vencido", "Cerca", "Medio", "Lejano"):
            self.assertIn(nombre, cuerpo)
        self.assertNotIn("Sinfecha", cuerpo)

    def test_sin_fecha(self):
        cuerpo = self.nombres("sin-fecha")
        self.assertIn("Sinfecha", cuerpo)
        self.assertNotIn("Vencido", cuerpo)

    def test_los_de_baja_no_salen(self):
        self.assertNotIn("Debaja", self.nombres("vencidos"))

    def test_marca_al_vencido_como_tal(self):
        self.assertIn("Vencido hace", self.nombres("vencidos"))


class LosPermisos(_Base):

    def test_solo_lectura_no_entra(self):
        r = self.ver(usuario=self.lectura)
        self.assertRedirects(r, reverse("expedientes:panel"))

    def test_rrhh_principal_si_entra(self):
        self.assertEqual(self.ver(usuario=self.principal).status_code, 200)

    def test_en_la_barra_sale_para_quien_edita(self):
        self.client.force_login(self.principal)
        cuerpo = self.client.get(reverse("expedientes:panel")).content.decode()
        self.assertIn("Renovaciones", cuerpo)

    def test_en_la_barra_no_sale_para_solo_lectura(self):
        self.client.force_login(self.lectura)
        cuerpo = self.client.get(reverse("expedientes:panel")).content.decode()
        self.assertNotIn("Renovaciones", cuerpo)


class EditarLaFecha(_Base):

    def url(self, t=None):
        return reverse("expedientes:renovacion_guardar",
                       args=[(t or self.cerca).pk])

    def test_guarda_la_fecha_y_deduce_la_duracion(self):
        hoy = timezone.localdate()
        nueva = hoy + datetime.timedelta(days=60)
        self.client.force_login(self.admin)
        self.client.post(self.url(), {
            "fecha_culminacion": nueva.isoformat(), "rango": "90"})
        datos = DatosContratacion.objects.get(trabajador=self.cerca)
        self.assertEqual(datos.fecha_culminacion, nueva)
        # del 01/08/2026 a la fecha nueva, en días
        esperada = (nueva - datetime.date(2026, 8, 1)).days + 1
        self.assertEqual(datos.duracion_dias, esperada)

    def test_queda_en_la_auditoria(self):
        self.client.force_login(self.admin)
        self.client.post(self.url(), {
            "fecha_culminacion": "2027-01-15", "rango": "90"})
        asiento = RegistroAuditoria.objects.filter(
            entidad="Trabajador", objeto_id=str(self.cerca.pk),
            descripcion__contains="fin de contrato").get()
        self.assertIn("2027-01-15", asiento.descripcion)

    def test_vaciar_la_deja_sin_fecha(self):
        self.client.force_login(self.admin)
        self.client.post(self.url(), {"fecha_culminacion": "", "rango": "90"})
        datos = DatosContratacion.objects.get(trabajador=self.cerca)
        self.assertIsNone(datos.fecha_culminacion)

    def test_fecha_inventada_no_guarda(self):
        self.client.force_login(self.admin)
        self.client.post(self.url(), {
            "fecha_culminacion": "no-es-una-fecha", "rango": "90"})
        datos = DatosContratacion.objects.get(trabajador=self.cerca)
        self.assertIsNotNone(datos.fecha_culminacion)

    def test_solo_lectura_no_edita(self):
        self.client.force_login(self.lectura)
        r = self.client.post(self.url(), {
            "fecha_culminacion": "2027-01-15", "rango": "90"})
        self.assertEqual(r.status_code, 403)


class RenovarConUnClic(_Base):
    """El botón «Renovar 90 días»: encadena otro período al mismo expediente,
    sin crear fichas ni duplicar nada."""

    def url(self, t):
        return reverse("expedientes:renovacion_renovar", args=[t.pk])

    def test_vigente_encadena_al_fin_actual(self):
        hoy = timezone.localdate()
        fin = DatosContratacion.objects.get(trabajador=self.cerca).fecha_culminacion
        self.client.force_login(self.admin)
        self.client.post(self.url(self.cerca), {"rango": "90"})
        datos = DatosContratacion.objects.get(trabajador=self.cerca)
        self.assertEqual(datos.fecha_culminacion,
                         fin + datetime.timedelta(days=90))

    def test_vencido_arranca_de_hoy(self):
        hoy = timezone.localdate()
        self.client.force_login(self.admin)
        self.client.post(self.url(self.vencido), {"rango": "vencidos"})
        datos = DatosContratacion.objects.get(trabajador=self.vencido)
        self.assertEqual(datos.fecha_culminacion,
                         hoy + datetime.timedelta(days=90))

    def test_sin_fecha_arranca_de_hoy(self):
        hoy = timezone.localdate()
        self.client.force_login(self.admin)
        self.client.post(self.url(self.sin_fecha), {"rango": "sin-fecha"})
        datos = DatosContratacion.objects.get(trabajador=self.sin_fecha)
        self.assertEqual(datos.fecha_culminacion,
                         hoy + datetime.timedelta(days=90))

    def test_no_duplica_nada(self):
        trabajadores = Trabajador.objects.count()
        contratos = DatosContratacion.objects.count()
        self.client.force_login(self.admin)
        self.client.post(self.url(self.cerca), {"rango": "90"})
        self.assertEqual(Trabajador.objects.count(), trabajadores)
        self.assertEqual(DatosContratacion.objects.count(), contratos)

    def test_recalcula_la_duracion(self):
        self.client.force_login(self.admin)
        self.client.post(self.url(self.cerca), {"rango": "90"})
        datos = DatosContratacion.objects.get(trabajador=self.cerca)
        esperada = (datos.fecha_culminacion
                    - datetime.date(2026, 8, 1)).days + 1
        self.assertEqual(datos.duracion_dias, esperada)

    def test_queda_en_la_auditoria(self):
        self.client.force_login(self.admin)
        self.client.post(self.url(self.cerca), {"rango": "90"})
        asiento = RegistroAuditoria.objects.filter(
            entidad="Trabajador", objeto_id=str(self.cerca.pk),
            descripcion__contains="Renovó el contrato").get()
        self.assertIn("90 días", asiento.descripcion)

    def test_solo_lectura_no_renueva(self):
        self.client.force_login(self.lectura)
        r = self.client.post(self.url(self.cerca), {"rango": "90"})
        self.assertEqual(r.status_code, 403)
