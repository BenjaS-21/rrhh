"""El semáforo de la nómina: qué tan completo está cada quien para el Excel.

Lo que importa comprobar no es que el porcentaje se calcule, sino que sea el
mismo dato que va al archivo. Si la pantalla revisara una lista y el Excel
exportara otra, alguien vería «100%» en verde y abriría un archivo con celdas
vacías, que es exactamente lo que este semáforo viene a evitar.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook
from io import BytesIO

from cuentas.models import Cargo, Departamento, Sede, Zona
from expedientes.completitud import (
    DATOS_BASE, DATOS_DE_PAGO, completitud, datos_revisados,
)
from expedientes.models import DatosContratacion, Trabajador

Usuario = get_user_model()
CLAVE = "Clave-De-Prueba-123"


class CuantoFalta(TestCase):
    """La cuenta, sin pantalla de por medio."""

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        cls.unidad = Departamento.objects.create(nombre="CONTRALORIA")
        cls.cargo = Cargo.objects.create(nombre="CONTRALOR", departamento=cls.unidad)

    def _trabajador(self, **campos):
        datos = {"documento_identidad": "V-30719983", "nombres": "Benjamin",
                 "apellidos": "Velazco", "sede": self.sede}
        datos.update(campos)
        return Trabajador.objects.create(**datos)

    def _completo(self):
        t = self._trabajador(puesto=self.cargo, departamento=self.unidad,
                             fecha_ingreso=date(2025, 3, 1))
        DatosContratacion.objects.create(
            trabajador=t, talla_camisa="M", talla_pantalon="32", talla_zapato="41",
            banco="BANESCO", prefijo="0134", numero_cuenta="1234567890123456")
        return t

    def test_todo_cargado_da_cien(self):
        c = completitud(self._completo(), con_pagos=True)
        self.assertEqual(c.porcentaje, 100)
        self.assertEqual(c.faltan, ())
        self.assertEqual(c.nivel, "completo")

    def test_recien_dado_de_alta_da_cero(self):
        """Alta mínima: nombre, cédula y tienda. Nada más cargado."""
        c = completitud(self._trabajador(), con_pagos=True)
        self.assertEqual(c.porcentaje, 0)
        self.assertEqual(c.nivel, "vacio")

    def test_a_medio_cargar_queda_en_amarillo(self):
        t = self._trabajador(puesto=self.cargo, departamento=self.unidad)
        c = completitud(t, con_pagos=True)
        self.assertEqual(c.nivel, "parcial")
        self.assertGreater(c.porcentaje, 0)
        self.assertLess(c.porcentaje, 100)

    def test_dice_exactamente_qué_falta(self):
        """Un color avisa que hay un problema; no dice qué hacer."""
        t = self._completo()
        t.contratacion.talla_zapato = ""
        t.contratacion.banco = ""
        t.contratacion.save()
        t.refresh_from_db()
        c = completitud(t, con_pagos=True)
        self.assertEqual(set(c.faltan), {"Talla de zapato", "Banco"})
        self.assertIn("Talla de zapato", c.detalle)

    def test_sin_datos_de_contratacion_no_revienta(self):
        """La tabla de contratación puede no existir todavía."""
        c = completitud(self._trabajador(), con_pagos=True)
        self.assertEqual(c.porcentaje, 0)

    def test_a_solo_lectura_no_se_le_reclaman_los_datos_de_pago(self):
        """Esas columnas ni salen en su Excel: pedirle que las complete sería
        mandarlo a llenar algo que no puede ni mirar."""
        t = self._trabajador(puesto=self.cargo, departamento=self.unidad,
                             fecha_ingreso=date(2025, 3, 1))
        DatosContratacion.objects.create(
            trabajador=t, talla_camisa="M", talla_pantalon="32", talla_zapato="41")
        self.assertEqual(completitud(t, con_pagos=False).porcentaje, 100)
        self.assertLess(completitud(t, con_pagos=True).porcentaje, 100)

    def test_cero_hijos_no_es_un_dato_faltante(self):
        """Es una respuesta, no un vacío."""
        revisados = [etiqueta for etiqueta, _ in datos_revisados(True)]
        self.assertNotIn("Hijos", revisados)


class ElSemaforoYElExcelMiranLoMismo(TestCase):
    """La razón de ser del módulo: que no se contradigan.

    Sin esto, agregar una columna al Excel dejaría el semáforo mirando la lista
    vieja, y diría «completo» sobre un archivo con huecos.
    """

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        cls.trabajador = Trabajador.objects.create(
            documento_identidad="V-30719983", nombres="Benjamin",
            apellidos="Velazco", sede=cls.sede)
        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()

    def test_cada_dato_que_revisa_el_semaforo_es_una_columna_del_excel(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("expedientes:nomina_export"))
        hoja = load_workbook(BytesIO(r.content)).active
        encabezados = {c.value for c in hoja[1] if c.value}

        # El nombre que ve la persona no siempre es el título de la columna:
        # se emparejan a mano y el test avisa si aparece uno nuevo sin pareja.
        equivalencias = {
            "Cargo": "Cargo",
            "Departamento": "Departamento",
            "Fecha de ingreso": "Fecha de ingreso",
            "Talla de camisa": "Talla camisa",
            "Talla de pantalón": "Talla pantalón",
            "Talla de zapato": "Talla zapato",
            "Banco": "Banco",
            "Prefijo del banco": "Prefijo",
            "Número de cuenta": "Número de cuenta",
        }
        for etiqueta, _ in DATOS_BASE + DATOS_DE_PAGO:
            with self.subTest(dato=etiqueta):
                columna = equivalencias.get(etiqueta)
                self.assertIsNotNone(
                    columna, f"«{etiqueta}» se revisa pero nadie sabe qué columna es")
                self.assertIn(
                    columna, encabezados,
                    f"el semáforo reclama «{etiqueta}» y el Excel no lo exporta")


class LaColumnaEnLaPantalla(TestCase):

    @classmethod
    def setUpTestData(cls):
        zona = Zona.objects.create(nombre="MIRANDA")
        cls.sede = Sede.objects.create(nombre="TRINIDAD", zona=zona)
        unidad = Departamento.objects.create(nombre="CONTRALORIA")
        cargo = Cargo.objects.create(nombre="CONTRALOR", departamento=unidad)

        cls.pelado = Trabajador.objects.create(
            documento_identidad="V-1", nombres="Ana", apellidos="Aaa", sede=cls.sede)
        cls.lleno = Trabajador.objects.create(
            documento_identidad="V-2", nombres="Beto", apellidos="Bbb",
            sede=cls.sede, puesto=cargo, departamento=unidad,
            fecha_ingreso=date(2025, 1, 2))
        DatosContratacion.objects.create(
            trabajador=cls.lleno, talla_camisa="M", talla_pantalon="32",
            talla_zapato="41", banco="BANESCO", prefijo="0134",
            numero_cuenta="1234567890123456")

        cls.admin = Usuario.objects.create_user(username="adm", password=CLAVE)
        cls.admin.rol = Usuario.Rol.ADMIN
        cls.admin.save()
        cls.lectura = Usuario.objects.create_user(username="lec", password=CLAVE)
        cls.lectura.rol = Usuario.Rol.SOLO_LECTURA
        cls.lectura.save()

    def cuerpo(self, usuario=None):
        self.client.force_login(usuario or self.admin)
        return self.client.get(reverse("expedientes:nomina")).content.decode()

    def test_la_columna_esta(self):
        self.assertIn("<th>Datos</th>", self.cuerpo())

    def test_el_completo_sale_en_verde_y_el_pelado_en_rojo(self):
        cuerpo = self.cuerpo()
        self.assertIn('class="badge verde"', cuerpo)
        self.assertIn('class="badge rojo"', cuerpo)
        self.assertIn("100%", cuerpo)
        self.assertIn("0%", cuerpo)

    def test_dice_qué_falta_sin_tener_que_entrar_al_expediente(self):
        self.assertIn("Falta cargar:", self.cuerpo())

    def test_tambien_aparece_al_filtrar_en_vivo(self):
        """La tabla se reemplaza sola con htmx: si el semáforo se calculara
        fuera de esa respuesta, la columna quedaría vacía al buscar."""
        self.client.force_login(self.admin)
        r = self.client.get(reverse("expedientes:nomina"), {"q": "Beto"},
                            headers={"HX-Request": "true"})
        cuerpo = r.content.decode()
        self.assertIn("100%", cuerpo)
        self.assertIn('class="badge verde"', cuerpo)

    def test_no_cuesta_una_consulta_por_trabajador(self):
        """Se calcula sobre lo que ya trajo la página, no consultando de nuevo.

        Se mide con 2 trabajadores y con 25: el número de consultas tiene que
        ser el mismo. Fijar un número a mano solo diría "hoy son nueve";
        comparar los dos casos dice lo que importa, que no crece con la nómina.
        Si alguien sacara el `select_related` de contratación, acá se nota.
        """
        self.client.force_login(self.admin)
        con_pocos = self._consultas()

        for i in range(23):
            Trabajador.objects.create(
                documento_identidad=f"V-9{i}", nombres="X", apellidos=f"Z{i}",
                sede=self.sede)
        con_muchos = self._consultas()

        self.assertEqual(
            con_pocos, con_muchos,
            f"con 2 trabajadores son {con_pocos} consultas y con 25 son "
            f"{con_muchos}: el semáforo está yendo a la base por cada fila")

    def _consultas(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as capturadas:
            respuesta = self.client.get(reverse("expedientes:nomina"))
        self.assertEqual(respuesta.status_code, 200)
        return len(capturadas)
