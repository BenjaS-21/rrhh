"""
Modelos del expediente digital del trabajador.

- Trabajador: la persona. Pertenece a una Sede (y por lo tanto a una Zona).
- TipoDocumento: catálogo de tipos (CI, contrato, título...). Marca si es
  obligatorio y si vence.
- Documento: un archivo cargado, cifrado en disco, versionado y con borrado
  lógico. Se enlaza a un Trabajador y a un TipoDocumento.
- RegistroAuditoria: bitácora inmutable de accesos y cambios.
"""

import os
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from cuentas.models import Sede, Zona
from .storage import almacenamiento_documentos


def _validar_extension(archivo):
    ext = os.path.splitext(archivo.name)[1].lower()
    permitidas = settings.DOCUMENTOS_EXTENSIONES_PERMITIDAS
    if ext not in permitidas:
        raise ValidationError(
            f"Extensión '{ext}' no permitida. Permitidas: {', '.join(permitidas)}"
        )


def _ruta_documento(instance, filename):
    """Ruta ofuscada: media/documentos/<trabajador_id>/<uuid><ext>."""
    ext = os.path.splitext(filename)[1].lower()
    nombre = f"{uuid.uuid4().hex}{ext}"
    return f"documentos/{instance.trabajador_id}/{nombre}"


class Trabajador(models.Model):
    """Persona cuyo expediente se gestiona."""

    class Estado(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        BAJA = "BAJA", "Baja"

    documento_identidad = models.CharField(
        "documento de identidad", max_length=30, unique=True,
        help_text="CI / DNI. Identifica de forma única al trabajador.",
    )
    nombres = models.CharField(max_length=120)
    apellidos = models.CharField(max_length=120)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=40, blank=True)

    sede = models.ForeignKey(
        Sede, on_delete=models.PROTECT, related_name="trabajadores",
        verbose_name="tienda",
    )
    departamento = models.ForeignKey(
        "cuentas.Departamento", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="trabajadores",
        help_text="Departamento/área en el que trabaja.",
    )
    puesto = models.CharField("cargo", max_length=120, blank=True)
    fecha_ingreso = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVO)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "trabajador"
        verbose_name_plural = "trabajadores"
        ordering = ["apellidos", "nombres"]
        indexes = [
            models.Index(fields=["apellidos", "nombres"]),
            models.Index(fields=["documento_identidad"]),
        ]

    def __str__(self):
        return f"{self.apellidos}, {self.nombres} ({self.documento_identidad})"

    @property
    def nombre_completo(self):
        return f"{self.nombres} {self.apellidos}"

    @property
    def zona(self) -> Zona:
        return self.sede.zona

    @property
    def documentos_activos(self):
        return self.documentos.filter(activo=True)

    def estado_completitud(self):
        """Devuelve (cargados, requeridos, faltantes[list]) según tipos obligatorios."""
        obligatorios = TipoDocumento.objects.filter(activo=True, obligatorio=True)
        tipos_cargados = set(
            self.documentos_activos.values_list("tipo_id", flat=True)
        )
        faltantes = [t for t in obligatorios if t.id not in tipos_cargados]
        requeridos = obligatorios.count()
        return (requeridos - len(faltantes), requeridos, faltantes)


class TipoDocumento(models.Model):
    """Catálogo de tipos de documento que componen un expediente."""

    nombre = models.CharField(max_length=120, unique=True)
    descripcion = models.CharField(max_length=255, blank=True)
    obligatorio = models.BooleanField(
        default=False, help_text="Si es obligatorio, cuenta para la completitud del expediente.",
    )
    requiere_vencimiento = models.BooleanField(
        default=False, help_text="Si vence (ej: carnet de salud), se pedirá fecha de vencimiento.",
    )
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=100)

    class Meta:
        verbose_name = "tipo de documento"
        verbose_name_plural = "tipos de documento"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class Documento(models.Model):
    """Archivo del expediente, cifrado en disco, versionado y con borrado lógico."""

    trabajador = models.ForeignKey(
        Trabajador, on_delete=models.CASCADE, related_name="documentos"
    )
    tipo = models.ForeignKey(
        TipoDocumento, on_delete=models.PROTECT, related_name="documentos"
    )
    archivo = models.FileField(
        upload_to=_ruta_documento,
        storage=almacenamiento_documentos,
        validators=[_validar_extension],
    )
    nombre_original = models.CharField(max_length=255, blank=True)
    tamano_bytes = models.PositiveBigIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    observaciones = models.CharField(max_length=255, blank=True)

    activo = models.BooleanField(default=True, help_text="Borrado lógico: False = en papelera.")
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, related_name="documentos_subidos",
    )
    subido_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "documento"
        verbose_name_plural = "documentos"
        ordering = ["-subido_en"]
        indexes = [
            models.Index(fields=["trabajador", "tipo", "activo"]),
        ]

    def __str__(self):
        return f"{self.tipo} — {self.trabajador} (v{self.version})"

    @property
    def extension(self):
        return os.path.splitext(self.archivo.name)[1].lower()

    @property
    def es_imagen(self):
        return self.extension in {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp"}

    @property
    def esta_vencido(self):
        return bool(self.fecha_vencimiento and self.fecha_vencimiento < timezone.localdate())

    @property
    def vence_pronto(self):
        if not self.fecha_vencimiento:
            return False
        hoy = timezone.localdate()
        return hoy <= self.fecha_vencimiento <= hoy + timedelta(days=30)


class RegistroAuditoria(models.Model):
    """Bitácora de acciones sobre el sistema. No se edita ni se borra."""

    class Accion(models.TextChoices):
        LOGIN = "LOGIN", "Inicio de sesión"
        LOGIN_FALLIDO = "LOGIN_FALLIDO", "Inicio de sesión fallido"
        LOGOUT = "LOGOUT", "Cierre de sesión"
        VER = "VER", "Consulta"
        DESCARGAR = "DESCARGAR", "Descarga de documento"
        CREAR = "CREAR", "Creación"
        EDITAR = "EDITAR", "Edición"
        SUBIR = "SUBIR", "Carga de documento"
        BORRAR = "BORRAR", "Envío a papelera"
        RESTAURAR = "RESTAURAR", "Restauración"
        ACCESO_DENEGADO = "ACCESO_DENEGADO", "Acceso denegado"

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="auditorias",
    )
    usuario_texto = models.CharField(max_length=150, blank=True,
                                     help_text="Copia del usuario por si se elimina la cuenta.")
    accion = models.CharField(max_length=20, choices=Accion.choices)
    entidad = models.CharField(max_length=60, blank=True)
    objeto_id = models.CharField(max_length=40, blank=True)
    descripcion = models.CharField(max_length=400, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "registro de auditoría"
        verbose_name_plural = "registros de auditoría"
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["-creado_en"]),
            models.Index(fields=["accion"]),
        ]

    def __str__(self):
        return f"[{self.creado_en:%Y-%m-%d %H:%M}] {self.usuario_texto} · {self.get_accion_display()}"
