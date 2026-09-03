"""Dar de alta un expediente: a dónde se llega, y qué pasa cuando no se guarda.

Nace de un reporte de que al crear un expediente no se llegaba al detalle de la
persona. La redirección estaba y funcionaba; lo que fallaba era otra cosa: el
formulario son cinco tarjetas largas, así que cuando un dato no validaba la
página volvía al principio, el aviso quedaba tres pantallas más abajo, y se veía
el mismo formulario de siempre —como si el botón Guardar no hiciera nada—.

Así que se prueban las dos mitades: que al guardar bien se llegue al detalle, y
que al no guardar quede dicho arriba de todo y en criollo.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Cargo, Departamento, Sede, Zona
from expedientes.models import DatosContratacion, Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class AlCrearSeLlegaAlExpediente(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        cls.unidad = Departamento.objects.create(nombre="CONTRALORIA")
        cls.cargo = Cargo.objects.create(nombre="CONTRALOR", departamento=cls.unidad)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def alta(self, **cambios):
        datos = {"documento_identidad": "V-30719983", "nombres": "Benjamin",
                 "apellidos": "Velazco", "sede": self.sede.pk}
        datos.update(cambios)
        self.client.force_login(self.admin)
        return self.client.post(reverse("expedientes:trabajador_create"), datos)

    def test_termina_en_el_detalle_de_quien_se_acaba_de_crear(self):
        r = self.alta()
        creado = Trabajador.objects.get()
        self.assertRedirects(
            r, reverse("expedientes:trabajador_detail", args=[creado.pk]))

    def test_la_pantalla_a_la_que_llega_es_la_de_esa_persona(self):
        """No alcanza con que redirija: tiene que abrir de verdad."""
        r = self.client.get(self.alta()["Location"])
        self.assertEqual(r.status_code, 200)
        cuerpo = r.content.decode()
        self.assertIn("VELAZCO", cuerpo)
        self.assertIn("Documentos del expediente", cuerpo)
        self.assertIn("Expediente creado correctamente", cuerpo)

    def test_editar_tambien_vuelve_al_detalle(self):
        self.alta()
        t = Trabajador.objects.get()
        self.client.force_login(self.admin)
        r = self.client.post(
            reverse("expedientes:trabajador_update", args=[t.pk]),
            {"documento_identidad": t.documento_identidad, "nombres": "Benjamin",
             "apellidos": "Velazquez", "sede": self.sede.pk, "estado": "ACTIVO"})
        self.assertRedirects(
            r, reverse("expedientes:trabajador_detail", args=[t.pk]))


class CuandoNoSeGuardaSeNota(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        cls.ventas = Departamento.objects.create(nombre="VENTAS")
        cls.deposito = Departamento.objects.create(nombre="DEPOSITO")
        cls.cargo_ventas = Cargo.objects.create(nombre="VENDEDOR",
                                                departamento=cls.ventas)
        cls.ya_esta = Trabajador.objects.create(
            documento_identidad="V-30719983", nombres="Benjamin",
            apellidos="Velazco", sede=cls.sede)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def intentar(self, **cambios):
        datos = {"documento_identidad": "V-11111111", "nombres": "Ana",
                 "apellidos": "Alvarez", "sede": self.sede.pk}
        datos.update(cambios)
        self.client.force_login(self.admin)
        return self.client.post(reverse("expedientes:trabajador_create"), datos)

    def test_una_cedula_repetida_se_avisa_arriba_de_todo(self):
        """El caso más común: la persona ya estaba cargada."""
        r = self.intentar(documento_identidad="V-30719983")
        self.assertEqual(r.status_code, 200)
        cuerpo = r.content.decode()
        self.assertIn("No se guardó el expediente", cuerpo)
        # El aviso va antes que el campo: es lo primero que se ve al volver.
        self.assertLess(cuerpo.index("No se guardó el expediente"),
                        cuerpo.index('name="documento_identidad"'))
        self.assertEqual(Trabajador.objects.count(), 1)

    def test_el_aviso_enlaza_al_campo_que_hay_que_arreglar(self):
        r = self.intentar(documento_identidad="V-30719983")
        self.assertIn('href="#id_documento_identidad"', r.content.decode())

    def test_el_campo_con_problema_queda_marcado(self):
        r = self.intentar(documento_identidad="V-30719983")
        self.assertIn("campo--mal", r.content.decode())

    def test_un_dato_mal_en_una_tarjeta_de_abajo_tambien_sube(self):
        """Es el que más se pierde: la tarjeta está tres pantallas abajo.

        Los datos de contratación viajan con el prefijo `contrato-`, que es
        como los nombra su formulario.
        """
        r = self.intentar(**{"contrato-talla_camisa": "X" * 50})
        cuerpo = r.content.decode()
        self.assertIn("No se guardó el expediente", cuerpo)
        self.assertIn("Talla de camisa", cuerpo)
        self.assertIn('href="#id_contrato-talla_camisa"', cuerpo)
        self.assertLess(cuerpo.index("No se guardó el expediente"),
                        cuerpo.index("Tallas de uniforme"))

    def test_dice_cuantos_datos_hay_que_revisar(self):
        r = self.intentar(documento_identidad="", nombres="")
        self.assertIn("Revisá 2 datos", r.content.decode())

    def test_un_cargo_de_otra_unidad_no_impide_guardar(self):
        """Antes lo frenaba. Cualquier cargo vale con cualquier unidad: el
        catálogo dice de dónde salió el nombre, no dónde puede usarse."""
        r = self.intentar(departamento=self.deposito.pk,
                          puesto=self.cargo_ventas.pk)
        self.assertEqual(r.status_code, 302)
        creado = Trabajador.objects.get(documento_identidad="V-11111111")
        self.assertEqual(creado.puesto, self.cargo_ventas)
        self.assertEqual(creado.departamento, self.deposito)

    def test_cuando_todo_esta_bien_no_aparece_ningun_aviso(self):
        """Testigo: si el aviso saliera siempre, los de arriba no probarían nada."""
        creado = self.intentar()
        self.assertEqual(creado.status_code, 302)
        cuerpo = self.client.get(creado["Location"]).content.decode()
        self.assertNotIn("No se guardó el expediente", cuerpo)
        self.assertNotIn("campo--mal", cuerpo)

    def test_al_editar_tambien_avisa(self):
        DatosContratacion.objects.create(trabajador=self.ya_esta)
        self.client.force_login(self.admin)
        r = self.client.post(
            reverse("expedientes:trabajador_update", args=[self.ya_esta.pk]),
            {"documento_identidad": "", "nombres": "Benjamin",
             "apellidos": "Velazco", "sede": self.sede.pk, "estado": "ACTIVO"})
        self.assertIn("No se guardó el expediente", r.content.decode())

    def test_lo_que_ya_se_habia_escrito_no_se_pierde(self):
        """Volver a tipear todo por un dato mal es la peor parte del error."""
        r = self.intentar(documento_identidad="V-30719983",
                          fecha_ingreso="2025-03-01")
        cuerpo = r.content.decode()
        self.assertIn('value="Ana"', cuerpo)
        self.assertIn('value="2025-03-01"', cuerpo)


class ElRifEsOpcionalYQuedaEnLaFicha(TestCase):
    """El RIF se pidió aparte de la cédula: opcional, debajo de ella en el
    formulario, y visible en la ficha solo cuando está cargado."""

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def alta(self, **cambios):
        datos = {"documento_identidad": "V-30719983", "nombres": "Benjamin",
                 "apellidos": "Velazco", "sede": self.sede.pk}
        datos.update(cambios)
        self.client.force_login(self.admin)
        return self.client.post(reverse("expedientes:trabajador_create"), datos)

    def detalle(self):
        t = Trabajador.objects.get()
        self.client.force_login(self.admin)
        return self.client.get(
            reverse("expedientes:trabajador_detail", args=[t.pk])).content.decode()

    def test_se_guarda_en_el_alta(self):
        self.alta(rif="J-30719983-1")
        self.assertEqual(Trabajador.objects.get().rif, "J-30719983-1")

    def test_sin_rif_tambien_se_puede(self):
        r = self.alta()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Trabajador.objects.get().rif, "")

    def test_en_el_formulario_va_debajo_de_la_cedula(self):
        self.client.force_login(self.admin)
        cuerpo = self.client.get(
            reverse("expedientes:trabajador_create")).content.decode()
        self.assertLess(cuerpo.index('name="documento_identidad"'),
                        cuerpo.index('name="rif"'))

    def test_al_editar_se_carga(self):
        self.alta()
        t = Trabajador.objects.get()
        self.client.force_login(self.admin)
        self.client.post(
            reverse("expedientes:trabajador_update", args=[t.pk]),
            {"documento_identidad": t.documento_identidad, "nombres": "Benjamin",
             "apellidos": "Velazco", "sede": self.sede.pk, "estado": "ACTIVO",
             "rif": "J-30719983-1"})
        t.refresh_from_db()
        self.assertEqual(t.rif, "J-30719983-1")

    def test_en_el_detalle_se_ve_cuando_tiene(self):
        self.alta(rif="J-30719983-1")
        self.assertIn("J-30719983-1", self.detalle())

    def test_en_el_detalle_no_sale_cuando_esta_vacio(self):
        self.alta()
        self.assertNotIn("<th>RIF</th>", self.detalle())


class LoQueSeEscribeEntraEnMayusculas(TestCase):
    """La empresa trabaja la data en mayúsculas; el formulario lo garantiza
    para que no vuelva a entrar "Ana" conviviendo con "ANA"."""

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def alta(self, **cambios):
        datos = {"documento_identidad": "V-30719983", "nombres": "Benjamin",
                 "apellidos": "Velazco", "sede": self.sede.pk}
        datos.update(cambios)
        self.client.force_login(self.admin)
        return self.client.post(reverse("expedientes:trabajador_create"), datos)

    def test_nombres_y_apellidos(self):
        self.alta(nombres="benjamin gabriel", apellidos="velazco mora")
        t = Trabajador.objects.get()
        self.assertEqual(t.nombres, "BENJAMIN GABRIEL")
        self.assertEqual(t.apellidos, "VELAZCO MORA")

    def test_los_datos_de_contratacion(self):
        self.alta(**{"contrato-direccion": "calle bolivar, casa 5",
                     "contrato-banco": "banco de venezuela",
                     "contrato-ciudad_nacimiento": "caracas",
                     "contrato-ciudad_firma": "guatire",
                     "contrato-responsable": "maria perez"})
        c = DatosContratacion.objects.get()
        self.assertEqual(c.direccion, "CALLE BOLIVAR, CASA 5")
        self.assertEqual(c.banco, "BANCO DE VENEZUELA")
        self.assertEqual(c.ciudad_nacimiento, "CARACAS")
        self.assertEqual(c.ciudad_firma, "GUATIRE")
        self.assertEqual(c.responsable, "MARIA PEREZ")

    def test_el_horario_queda_como_se_escribio(self):
        """Es prosa impresa en el contrato: ahí las mayúsculas se leen peor."""
        self.alta(**{"contrato-horario": "8:00AM a 5:00PM de lunes a sábado"})
        c = DatosContratacion.objects.get()
        self.assertEqual(c.horario, "8:00AM a 5:00PM de lunes a sábado")


class DuracionSinIngresoNoPasa(TestCase):
    """El caso real: la fecha de ingreso tecleada en «fecha fin» y el
    expediente quedaba sin ingreso. Con duración o fecha fin cargadas, el
    ingreso es obligatorio; solo así no vuelve a pasar."""

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def alta(self, **cambios):
        datos = {"documento_identidad": "V-30719983", "nombres": "Benjamin",
                 "apellidos": "Velazco", "sede": self.sede.pk}
        datos.update(cambios)
        self.client.force_login(self.admin)
        return self.client.post(reverse("expedientes:trabajador_create"), datos)

    def test_duracion_sin_ingreso_no_guarda(self):
        r = self.alta(**{"contrato-duracion_dias": "90"})
        self.assertEqual(Trabajador.objects.count(), 0)
        self.assertIn("la fecha de ingreso hace falta", r.content.decode())

    def test_fecha_fin_sin_ingreso_no_guarda(self):
        r = self.alta(**{"contrato-fecha_culminacion": "2026-11-29"})
        self.assertEqual(Trabajador.objects.count(), 0)
        self.assertIn("la fecha de ingreso hace falta", r.content.decode())

    def test_sin_ingreso_y_sin_contrato_si_se_puede(self):
        """El ingreso sigue siendo opcional por sí solo: se frena la mezcla."""
        r = self.alta()
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(Trabajador.objects.get().fecha_ingreso)

    def test_con_ingreso_y_duracion_calcula_la_fin(self):
        self.alta(fecha_ingreso="2026-09-01",
                  **{"contrato-duracion_dias": "90"})
        t = Trabajador.objects.get()
        import datetime
        self.assertEqual(t.contratacion.fecha_culminacion,
                         datetime.date(2026, 11, 30))
