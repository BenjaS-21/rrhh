"""Regla: solo el Administrador borra. Los demás roles ven, agregan y editan.

Este archivo recorre TODOS los puntos donde se saca algo del sistema y prueba
cada uno contra cada rol. La idea es que agregar un borrado nuevo sin sumarlo
acá se note: si mañana aparece una URL con "borrar" que no esté en la lista, el
último test de la clase falla.
"""

from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from expedientes.models import (
    AsignacionPago, Documento, Hijo, TipoDocumento, Trabajador,
)
from expedientes.tests import CLAVE, BasePagos


class BaseBorrado(BasePagos):
    """Un expediente con un bono, un hijo y un documento para intentar borrar."""

    def setUp(self):
        self.bono = AsignacionPago.objects.create(
            trabajador=self.trab_norte, nombre_libre="Bono puntualidad",
            monto=50, moneda=self.usd,
        )
        self.hijo = Hijo.objects.create(
            trabajador=self.trab_norte, nombre_completo="ANA PEREZ",
            fecha_nacimiento=date(2015, 3, 12),
        )
        tipo, _ = TipoDocumento.objects.get_or_create(nombre="Cédula")
        self.documento = Documento.objects.create(
            trabajador=self.trab_norte, tipo=tipo,
            archivo=SimpleUploadedFile("ci.pdf", b"%PDF-1.4 contenido"),
            nombre_original="ci.pdf", subido_por=self.admin,
        )

    def como(self, usuario):
        self.client.force_login(usuario)


class SoloElAdminBorra(BaseBorrado):

    def borrados(self):
        """(nombre legible, url, sigue existiendo?) de cada punto de borrado."""
        return [
            ("bono extra",
             reverse("expedientes:pago_borrar", args=[self.bono.pk]),
             lambda: AsignacionPago.objects.get(pk=self.bono.pk).activo),
            ("hijo",
             reverse("expedientes:hijo_borrar", args=[self.hijo.pk]),
             lambda: Hijo.objects.filter(pk=self.hijo.pk).exists()),
            ("documento",
             reverse("expedientes:documento_borrar", args=[self.documento.pk]),
             lambda: Documento.objects.get(pk=self.documento.pk).activo),
        ]

    # --- Los que NO pueden ---------------------------------------------------
    def test_rrhh_interior_no_puede_borrar_nada_ni_en_su_zona(self):
        self.como(self.rrhh_norte)
        for etiqueta, url, sigue in self.borrados():
            with self.subTest(item=etiqueta):
                r = self.client.post(url)
                self.assertEqual(r.status_code, 403, f"{etiqueta}: no dio 403")
                self.assertTrue(sigue(), f"{etiqueta}: se borró igual")

    def test_solo_lectura_no_puede_borrar_nada(self):
        self.como(self.lectura_norte)
        for etiqueta, url, sigue in self.borrados():
            with self.subTest(item=etiqueta):
                self.assertEqual(self.client.post(url).status_code, 403)
                self.assertTrue(sigue())

    def test_rrhh_de_otra_zona_tampoco(self):
        self.como(self.rrhh_sur)
        for etiqueta, url, sigue in self.borrados():
            with self.subTest(item=etiqueta):
                self.assertEqual(self.client.post(url).status_code, 403)
                self.assertTrue(sigue())

    # --- El que sí -----------------------------------------------------------
    def test_el_admin_si_puede_borrar_todo(self):
        self.como(self.admin)
        for etiqueta, url, sigue in self.borrados():
            with self.subTest(item=etiqueta):
                r = self.client.post(url)
                self.assertEqual(r.status_code, 302, f"{etiqueta}: no lo dejó")
                self.assertFalse(sigue(), f"{etiqueta}: no se borró")

    def test_restaurar_de_la_papelera_tambien_es_del_admin(self):
        self.documento.activo = False
        self.documento.save(update_fields=["activo"])
        url = reverse("expedientes:documento_restaurar", args=[self.documento.pk])

        for usuario in (self.rrhh_norte, self.lectura_norte):
            with self.subTest(usuario=usuario.username):
                self.como(usuario)
                self.assertEqual(self.client.post(url).status_code, 403)

        self.como(self.admin)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertTrue(Documento.objects.get(pk=self.documento.pk).activo)

    def test_la_papelera_solo_la_ve_el_admin(self):
        url = reverse("expedientes:papelera", args=[self.trab_norte.pk])
        self.como(self.rrhh_norte)
        self.assertEqual(self.client.get(url).status_code, 302)  # lo saca
        self.como(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)

    # --- Que no quede ningún borrado sin cubrir ------------------------------
    def test_no_hay_urls_de_borrado_fuera_de_esta_lista(self):
        """Si aparece un borrado nuevo, hay que sumarlo a los tests de arriba."""
        conocidas = {
            "expedientes:pago_borrar", "expedientes:hijo_borrar",
            "expedientes:documento_borrar",
            # Configuración es entera del Administrador (decorador
            # `admin_requerido`) y además no borra: desactiva.
            "configuracion:toggle",
        }
        # El admin de Django borra de todo, pero está detrás de `is_staff` y
        # solo el Administrador lo es. Eso se prueba en
        # `SinAtajosPorElAdminDeDjango`, no acá.
        encontradas = {u for u in _urls_de_borrado() if not u.startswith("admin:")}
        # Primero: que el rastreo sirva para algo. Un centinela que no encuentra
        # nada pasaría siempre y no protegería nada.
        self.assertIn("expedientes:hijo_borrar", encontradas)
        self.assertIn("expedientes:documento_borrar", encontradas)

        nuevas = encontradas - conocidas
        self.assertFalse(
            nuevas,
            f"Borrados sin cubrir en los tests de permisos: {sorted(nuevas)}",
        )


def _urls_de_borrado(patrones=None, prefijo="", ruta=""):
    """Nombres (con namespace) de todas las rutas que borran algo.

    Hay que recorrer el árbol a mano: los nombres con namespace no aparecen en
    el `reverse_dict` de la raíz, así que buscarlos ahí devuelve un conjunto
    vacío y el centinela quedaría siempre en verde.
    """
    if patrones is None:
        patrones = get_resolver().url_patterns

    encontradas = set()
    for p in patrones:
        if isinstance(p, URLResolver):
            ns = p.namespace or ""
            encontradas |= _urls_de_borrado(
                p.url_patterns,
                f"{prefijo}{ns}:" if ns else prefijo,
                ruta + str(p.pattern),
            )
        elif isinstance(p, URLPattern):
            nombre = f"{prefijo}{p.name}" if p.name else ""
            completa = ruta + str(p.pattern)
            if any(x in (p.name or "") or x in completa
                   for x in ("borrar", "eliminar", "delete")):
                encontradas.add(nombre or completa)
    return encontradas


class LosDemasRolesSiguenTrabajando(BaseBorrado):
    """La restricción no puede dejar a RRHH Interior sin poder hacer su trabajo."""

    def test_puede_agregar_un_hijo(self):
        self.como(self.rrhh_norte)
        r = self.client.post(
            reverse("expedientes:hijo_agregar", args=[self.trab_norte.pk]),
            {"hijo-nombre_completo": "Carlos Perez",
             "hijo-fecha_nacimiento": "2019-09-04",
             "hijo-documento_identidad": "", "hijo-observaciones": ""})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Hijo.objects.filter(trabajador=self.trab_norte).count(), 2)

    def test_puede_agregar_y_editar_un_bono(self):
        self.como(self.rrhh_norte)
        r = self.client.post(
            reverse("expedientes:pago_editar", args=[self.bono.pk]),
            {"extra-nombre_libre": "Bono puntualidad", "extra-monto": "80",
             "extra-moneda": self.usd.pk, "extra-observaciones": ""})
        self.assertEqual(r.status_code, 302)
        self.bono.refresh_from_db()
        self.assertEqual(self.bono.monto, 80)

    def test_puede_editar_el_expediente(self):
        self.como(self.rrhh_norte)
        r = self.client.post(
            reverse("expedientes:trabajador_update", args=[self.trab_norte.pk]),
            {"documento_identidad": "V-1", "nombres": "Ana", "apellidos": "Norte",
             "sede": self.sede_norte.pk, "estado": "ACTIVO",
             "contrato-talla_camisa": "M"})
        self.assertEqual(r.status_code, 302)

    def test_puede_subir_un_documento(self):
        self.como(self.rrhh_norte)
        tipo = TipoDocumento.objects.first()
        r = self.client.post(
            reverse("expedientes:documento_subir", args=[self.trab_norte.pk]),
            {"tipo": tipo.pk,
             "archivo": SimpleUploadedFile("otro.pdf", b"%PDF-1.4 x")})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            Documento.objects.filter(trabajador=self.trab_norte, activo=True).count(), 2)

    def test_no_le_aparecen_botones_que_van_a_dar_403(self):
        self.como(self.rrhh_norte)
        cuerpo = self.client.get(self.url_detalle(self.trab_norte)).content.decode()
        for url in (reverse("expedientes:pago_borrar", args=[self.bono.pk]),
                    reverse("expedientes:hijo_borrar", args=[self.hijo.pk]),
                    reverse("expedientes:documento_borrar", args=[self.documento.pk])):
            self.assertNotIn(url, cuerpo, f"sigue el botón de {url}")
        # Pero los datos los ve, y puede agregar.
        self.assertIn("ANA PEREZ", cuerpo)
        self.assertIn("Agregar hijo", cuerpo)

    def test_al_admin_si_le_aparecen(self):
        self.como(self.admin)
        cuerpo = self.client.get(self.url_detalle(self.trab_norte)).content.decode()
        self.assertIn(reverse("expedientes:hijo_borrar", args=[self.hijo.pk]), cuerpo)
        self.assertIn(reverse("expedientes:pago_borrar", args=[self.bono.pk]), cuerpo)


class VaciarLaGrillaEsBorrar(BasePagos):
    """Vaciar el casillero saca el concepto del expediente: eso es borrar."""

    def setUp(self):
        self.asignado = AsignacionPago.objects.create(
            trabajador=self.trab_norte, concepto=self.sueldo,
            monto=180, moneda=self.bs,
        )

    def guardar(self, usuario, monto):
        self.client.force_login(usuario)
        return self.client.post(
            self.url_grilla(self.trab_norte),
            {f"rem-concepto_{self.sueldo.pk}": monto}, follow=True)

    def test_rrhh_interior_puede_cambiar_el_monto(self):
        self.guardar(self.rrhh_norte, "250")
        self.asignado.refresh_from_db()
        self.assertEqual(self.asignado.monto, 250)
        self.assertTrue(self.asignado.activo)

    def test_rrhh_interior_no_puede_vaciarlo(self):
        r = self.guardar(self.rrhh_norte, "")
        self.asignado.refresh_from_db()
        self.assertTrue(self.asignado.activo, "se dio de baja igual")
        self.assertEqual(self.asignado.monto, 180, "se perdió el monto")
        mensajes = " ".join(str(m) for m in r.context["messages"])
        self.assertIn("Administrador", mensajes)
        self.assertIn("Sueldo base", mensajes)

    def test_poner_cero_tampoco_lo_saca(self):
        self.guardar(self.rrhh_norte, "0")
        self.asignado.refresh_from_db()
        self.assertTrue(self.asignado.activo)

    def test_el_admin_si_puede_vaciarlo(self):
        self.guardar(self.admin, "")
        self.asignado.refresh_from_db()
        self.assertFalse(self.asignado.activo)


class SinAtajosPorElAdminDeDjango(BasePagos):
    """El admin de Django borraría sin pasar por ninguna de estas reglas."""

    def test_los_roles_que_no_son_admin_no_son_staff(self):
        for usuario in (self.rrhh_norte, self.rrhh_sur, self.lectura_norte):
            with self.subTest(usuario=usuario.username):
                self.assertFalse(usuario.is_staff)

    def test_no_pueden_entrar_al_admin_de_django(self):
        for usuario in (self.rrhh_norte, self.lectura_norte):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)
                r = self.client.get("/gestion-django/", follow=True)
                self.assertNotContains(r, "Administración del sitio",
                                       status_code=200)
