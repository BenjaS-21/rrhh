"""
Modelos de organización geográfica y usuarios del sistema.

Diseño de permisos:
- Una ZONA agrupa varias SEDES (sucursales). Ej: zona "Norte" con sedes
  "Salta" y "Jujuy". La Sede Central es una sede marcada con es_central=True.
- Cada USUARIO tiene un ROL y (para RRHH Interior) una ZONA asignada. El rol y
  la zona determinan qué trabajadores puede ver o modificar.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Zona(models.Model):
    """Región geográfica que agrupa una o más sedes."""

    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.CharField(max_length=255, blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "zona"
        verbose_name_plural = "zonas"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Sede(models.Model):
    """Sucursal u oficina. Pertenece a una zona."""

    nombre = models.CharField(max_length=120)
    zona = models.ForeignKey(Zona, on_delete=models.PROTECT, related_name="sedes")
    direccion = models.CharField(max_length=255, blank=True)
    es_central = models.BooleanField(
        default=False,
        help_text="Marca la Sede Central (administración nacional).",
    )
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "sede"
        verbose_name_plural = "sedes"
        ordering = ["zona__nombre", "nombre"]
        constraints = [
            models.UniqueConstraint(fields=["nombre", "zona"], name="sede_unica_por_zona"),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.zona.nombre})"


class Departamento(models.Model):
    """Área/departamento organizativo de los usuarios (RRHH, Ventas, Sistemas…).

    Es informativo: no restringe el acceso (eso lo define el rol + la zona). Se
    guarda para poder generar más adelante auditorías/reportes por departamento.
    """

    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.CharField(max_length=255, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "departamento"
        verbose_name_plural = "departamentos"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Area(models.Model):
    """Sub-área dentro de un departamento (ej. Ventas → Caja, Piso, Depósito)."""

    nombre = models.CharField(max_length=100)
    departamento = models.ForeignKey(
        Departamento, on_delete=models.CASCADE, related_name="areas"
    )
    descripcion = models.CharField(max_length=255, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "área"
        verbose_name_plural = "áreas"
        ordering = ["departamento__nombre", "nombre"]
        constraints = [
            models.UniqueConstraint(fields=["nombre", "departamento"],
                                    name="area_unica_por_departamento"),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.departamento})"


class Usuario(AbstractUser):
    """Usuario del sistema con rol y ámbito geográfico."""

    class Rol(models.TextChoices):
        ADMIN = "ADMIN", "Administrador (Sede Central)"
        RRHH_INTERIOR = "RRHH_INTERIOR", "RRHH Interior (zona restringida)"
        SOLO_LECTURA = "SOLO_LECTURA", "Solo lectura"

    rol = models.CharField(
        max_length=20,
        choices=Rol.choices,
        default=Rol.SOLO_LECTURA,
    )
    zona = models.ForeignKey(
        Zona,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="usuarios",
        help_text="Zona a la que queda restringido un usuario de RRHH Interior. "
                  "Los administradores no necesitan zona (acceso nacional).",
    )
    departamento = models.ForeignKey(
        Departamento,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usuarios",
        help_text="Área/departamento del usuario. Informativo (no afecta permisos).",
    )
    telefono = models.CharField(max_length=40, blank=True)

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    def __str__(self):
        nombre = self.get_full_name() or self.username
        return f"{nombre} — {self.get_rol_display()}"

    # --- Ayudas de permisos -------------------------------------------------
    @property
    def es_admin(self) -> bool:
        return self.rol == self.Rol.ADMIN or self.is_superuser

    @property
    def es_interior(self) -> bool:
        return self.rol == self.Rol.RRHH_INTERIOR

    @property
    def es_solo_lectura(self) -> bool:
        return self.rol == self.Rol.SOLO_LECTURA

    @property
    def puede_editar(self) -> bool:
        """¿Puede crear/editar/subir? Solo Admin y RRHH Interior."""
        return self.es_admin or self.es_interior

    @property
    def puede_borrar(self) -> bool:
        """Solo el Administrador nacional puede borrar (borrado lógico)."""
        return self.es_admin

    @property
    def alcance_nacional(self) -> bool:
        return self.es_admin


def _generar_token() -> str:
    return secrets.token_urlsafe(32)


def _expiracion_por_defecto():
    return timezone.now() + timedelta(days=7)


class InvitacionRegistro(models.Model):
    """Link tokenizado para que una persona se registre con un rol predefinido.

    El administrador crea una invitación (elige rol y, si corresponde, zona) desde
    el admin de Django. Se genera un token único; el link resultante permite a la
    persona crear su usuario una sola vez. La invitación caduca y es de un solo uso.
    """

    token = models.CharField(
        max_length=64, unique=True, default=_generar_token, editable=False,
        help_text="Se genera automáticamente. Forma parte del link de registro.",
    )
    rol = models.CharField(
        max_length=20, choices=Usuario.Rol.choices,
        help_text="Rol con el que quedará la persona que use este link.",
    )
    zona = models.ForeignKey(
        Zona, on_delete=models.CASCADE, null=True, blank=True,
        related_name="invitaciones",
        help_text="Obligatoria para RRHH Interior y Solo lectura (define su alcance).",
    )
    departamento = models.ForeignKey(
        Departamento, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invitaciones",
        help_text="Departamento con el que quedará la persona que use este link (informativo).",
    )
    email = models.EmailField(
        blank=True, help_text="Opcional: a quién se le envió (solo informativo).",
    )
    nota = models.CharField(
        max_length=120, blank=True, help_text="Etiqueta opcional para identificar la invitación.",
    )

    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invitaciones_creadas",
    )
    creada_en = models.DateTimeField(auto_now_add=True)
    expira_en = models.DateTimeField(default=_expiracion_por_defecto)

    activa = models.BooleanField(default=True)
    usada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invitacion_usada",
    )
    usada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "invitación de registro"
        verbose_name_plural = "invitaciones de registro"
        ordering = ["-creada_en"]

    def __str__(self):
        return f"Invitación {self.get_rol_display()}{f' · {self.zona}' if self.zona else ''}"

    @property
    def esta_expirada(self) -> bool:
        return timezone.now() > self.expira_en

    @property
    def esta_usada(self) -> bool:
        return self.usada_por_id is not None

    @property
    def esta_vigente(self) -> bool:
        return self.activa and not self.esta_usada and not self.esta_expirada

    @property
    def estado(self) -> str:
        if self.esta_usada:
            return "Usada"
        if not self.activa:
            return "Anulada"
        if self.esta_expirada:
            return "Expirada"
        return "Vigente"

    def get_ruta(self) -> str:
        return reverse("cuentas:registro", args=[self.token])

    def get_link_absoluto(self) -> str:
        base = getattr(settings, "SITE_URL", "").rstrip("/")
        return f"{base}{self.get_ruta()}"
