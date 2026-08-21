"""Tests de la carga de datos maestros y del catálogo de cargos.

Van aparte de `tests.py` porque `seed_damasco` carga las planillas reales
(49 tiendas, 78 unidades, 805 cargos) y conviene poder correrlos solos.
"""

from io import StringIO

from django import forms
from django.core.management import call_command
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Cargo, Departamento, Sede, Zona
from expedientes import documentos as generador
from expedientes.management.commands._datos_damasco import ORGANIGRAMA, TIENDAS
from expedientes.models import Trabajador
from expedientes.tests import CLAVE, BasePagos


class SeedDamasco(TestCase):
    """Carga de los datos maestros: tiendas, unidades organizativas y cargos."""

    def cargar(self, *args):
        salida = StringIO()
        call_command("seed_damasco", *args, stdout=salida, stderr=salida)
        return salida.getvalue()

    def test_carga_las_49_tiendas_con_su_direccion(self):
        self.cargar()
        self.assertEqual(Sede.objects.count(), len(TIENDAS))
        self.assertFalse(Sede.objects.filter(direccion="").exists(),
                         "toda tienda tiene que quedar con dirección")

        ciudad = Sede.objects.get(nombre="CIUDAD DAMASCO")
        self.assertEqual(ciudad.zona.nombre, "DIST. CAPITAL")
        self.assertIn("CALLE COLOMBIA", ciudad.direccion)

    def test_unifica_los_estados_escritos_de_dos_formas(self):
        """CAPITAL y DIST. CAPITAL son el mismo estado: una sola zona."""
        self.cargar()
        self.assertFalse(Zona.objects.filter(nombre="CAPITAL").exists())
        self.assertEqual(Sede.objects.get(nombre="YAGUARA").zona.nombre,
                         "DIST. CAPITAL")

    def test_carga_el_organigrama_completo(self):
        self.cargar()
        self.assertEqual(Departamento.objects.count(), len(ORGANIGRAMA))
        self.assertEqual(Cargo.objects.count(),
                         sum(len(c) for c in ORGANIGRAMA.values()))

        unidad = Departamento.objects.get(nombre="TIENDA DAMASCO MARACAY I")
        self.assertEqual(set(unidad.cargos.values_list("nombre", flat=True)),
                         set(ORGANIGRAMA["TIENDA DAMASCO MARACAY I"]))

    def test_el_mismo_cargo_existe_en_varias_unidades(self):
        """ALMACENISTA se repite por unidad: es lo que permite filtrar."""
        self.cargar()
        self.assertGreater(Cargo.objects.filter(nombre="ALMACENISTA").count(), 10)

    def test_correrlo_dos_veces_no_duplica_nada(self):
        self.cargar()
        conteos = (Zona.objects.count(), Sede.objects.count(),
                   Departamento.objects.count(), Cargo.objects.count())
        self.cargar()
        self.assertEqual(
            (Zona.objects.count(), Sede.objects.count(),
             Departamento.objects.count(), Cargo.objects.count()), conteos)

    def test_actualiza_la_direccion_si_cambio(self):
        self.cargar()
        sede = Sede.objects.get(nombre="CIUDAD DAMASCO")
        Sede.objects.filter(pk=sede.pk).update(direccion="ALGO VIEJO")
        self.cargar()
        sede.refresh_from_db()
        self.assertIn("CALLE COLOMBIA", sede.direccion)

    def test_reactiva_lo_que_estaba_apagado(self):
        self.cargar()
        Sede.objects.filter(nombre="CIUDAD DAMASCO").update(activa=False)
        Cargo.objects.filter(nombre="ALMACENISTA").update(activo=False)
        self.cargar()
        self.assertTrue(Sede.objects.get(nombre="CIUDAD DAMASCO").activa)
        self.assertFalse(
            Cargo.objects.filter(nombre="ALMACENISTA", activo=False).exists())

    def test_no_toca_los_trabajadores_ya_cargados(self):
        self.cargar()
        unidad = Departamento.objects.get(nombre="TIENDA DAMASCO MARACAY I")
        cargo = unidad.cargos.get(nombre="ASESOR DE VENTAS")
        t = Trabajador.objects.create(
            documento_identidad="V-999", nombres="Rosa", apellidos="Silva",
            sede=Sede.objects.get(nombre="MARACAY"), puesto=cargo,
            departamento=unidad,
        )
        self.cargar()
        t.refresh_from_db()
        self.assertEqual(t.puesto, cargo)

    def test_limpiar_desactiva_lo_que_sobra_sin_borrarlo(self):
        self.cargar()
        vieja = Sede.objects.create(nombre="TIENDA QUE YA NO EXISTE",
                                    zona=Zona.objects.first())
        self.cargar("--limpiar")
        vieja.refresh_from_db()
        self.assertFalse(vieja.activa)
        self.assertTrue(Sede.objects.filter(pk=vieja.pk).exists(), "no se borra")

    def test_avisa_de_las_diferencias_entre_las_dos_planillas(self):
        salida = self.cargar()
        self.assertIn("Para revisar", salida)
        self.assertIn("CAPITAL", salida)
        self.assertIn("SABANA GARANDE", salida)

    def test_marca_una_sola_sede_central(self):
        self.cargar()
        centrales = list(Sede.objects.filter(es_central=True))
        self.assertEqual(len(centrales), 1)
        self.assertEqual(centrales[0].nombre, "CORPORACION")


class CargoEnElExpediente(BasePagos):
    """El cargo se elige del catálogo y tiene que ser de la unidad indicada."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.otra_unidad = Departamento.objects.create(nombre="OTRA UNIDAD")
        cls.cargo_ajeno = Cargo.objects.create(nombre="CHOFER",
                                               departamento=cls.otra_unidad)

    def alta(self, **cambios):
        self.client.login(username="admin_nac", password=CLAVE)
        datos = {
            "documento_identidad": "V-777", "nombres": "Rosa",
            "apellidos": "Silva", "sede": self.sede_norte.pk,
            "fecha_ingreso": "2026-09-01",
        }
        datos.update(cambios)
        return self.client.post(reverse("expedientes:trabajador_create"), datos)

    def test_el_cargo_baja_como_lista_y_no_como_texto(self):
        self.client.login(username="admin_nac", password=CLAVE)
        r = self.client.get(reverse("expedientes:trabajador_create"))
        self.assertIsInstance(r.context["form"]["puesto"].field,
                              forms.ModelChoiceField)
        self.assertIn("CAJERA", r.content.decode())

    def test_cada_opcion_dice_a_que_unidad_pertenece(self):
        """El data-unidad es lo que usa el filtrado del formulario."""
        self.client.login(username="admin_nac", password=CLAVE)
        cuerpo = self.client.get(
            reverse("expedientes:trabajador_create")).content.decode()
        self.assertIn('data-unidad="%s"' % self.unidad.pk, cuerpo)

    def test_un_cargo_de_otra_unidad_se_acepta(self):
        """El catálogo cuelga cada cargo de una unidad, pero eso no es una regla.

        En una tienda trabaja gente con cargos que el catálogo tiene cargados
        bajo otra gerencia —mantenimiento, seguridad, sistemas—. Exigir que
        coincidieran dejaba sin poder registrar a esa persona.
        """
        r = self.alta(departamento=self.unidad.pk, puesto=self.cargo_ajeno.pk)
        self.assertEqual(r.status_code, 302)
        t = Trabajador.objects.get(documento_identidad="V-777")
        self.assertEqual(t.puesto, self.cargo_ajeno)
        # La unidad queda la que se eligió, no la del catálogo del cargo.
        self.assertEqual(t.departamento, self.unidad)

    def test_sin_unidad_no_se_inventa_ninguna(self):
        """Se completaba sola con la del cargo, y eso ensuciaba expedientes.

        El mismo nombre de cargo está cargado en decenas de unidades, así que
        la que venía pegada a la fila elegida podía ser de otro estado.
        """
        r = self.alta(puesto=self.cargo_cajera.pk)
        self.assertEqual(r.status_code, 302)
        t = Trabajador.objects.get(documento_identidad="V-777")
        self.assertIsNone(t.departamento)
        self.assertEqual(t.puesto, self.cargo_cajera)

    def test_el_cargo_llega_a_los_documentos(self):
        t = Trabajador.objects.create(
            documento_identidad="V-888", nombres="Luis", apellidos="Gomez",
            sede=self.sede_norte, puesto=self.cargo_cajera,
            departamento=self.unidad,
        )
        self.assertEqual(t.cargo_nombre, "CAJERA")
        self.assertEqual(generador.contexto_documentos(t)["Cargo"], "CAJERA")

    def test_sin_cargo_no_rompe_nada(self):
        t = Trabajador.objects.create(
            documento_identidad="V-889", nombres="Ana", apellidos="Ruiz",
            sede=self.sede_norte,
        )
        self.assertEqual(t.cargo_nombre, "")
        self.assertEqual(generador.contexto_documentos(t)["Cargo"], "")

    def test_no_se_puede_borrar_un_cargo_con_gente(self):
        """PROTECT: borrarlo dejaría expedientes sin el dato."""
        Trabajador.objects.create(
            documento_identidad="V-890", nombres="Eva", apellidos="Diaz",
            sede=self.sede_norte, puesto=self.cargo_cajera,
            departamento=self.unidad,
        )
        with self.assertRaises(ProtectedError):
            self.cargo_cajera.delete()
