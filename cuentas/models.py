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
    ciudad = models.CharField(
        max_length=120, blank=True,
        help_text="La ciudad donde esta la tienda: GUATIRE, VALENCIA, MARACAY. "
                  "Es la que sale como lugar en los documentos ('GUATIRE, 24 de "
                  "agosto de 2026'). Si se deja vacia sale la zona, que es el "
                  "estado, asi que nunca queda en blanco.",
    )
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

    @property
    def lugar(self):
        """Donde se firman los documentos de esta tienda.

        La ciudad si esta cargada; si no, la zona, que es el estado. Nunca
        queda vacio: un documento que dice ", 24 de agosto de 2026" se ve peor
        que uno que dice el estado en vez de la ciudad.
        """
        return self.ciudad.strip() or self.zona.nombre


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


class TipoDocumentoIdentidad(models.Model):
    """La letra que va delante de la cédula: V, E, J, P…

    Es un catálogo y no una lista fija en el código porque cambia sin avisar y
    no siempre igual en todos lados: hoy son las venezolanas, mañana puede
    hacer falta una para un caso que no vimos. Se administra desde el admin de
    Django.

    El código es lo que se imprime en los documentos, así que se guarda en
    mayúsculas y sin puntos.
    """

    codigo = models.CharField(
        "código", max_length=5, unique=True,
        help_text="La letra que se antepone: V, E, J, P, G.",
    )
    nombre = models.CharField(
        max_length=60, help_text="Cómo se lee: Venezolano, Extranjero…")
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(
        default=100, help_text="Menor primero en el desplegable.")

    class Meta:
        verbose_name = "tipo de cédula"
        verbose_name_plural = "tipos de cédula"
        ordering = ["orden", "codigo"]

    def __str__(self):
        return f"{self.codigo} — {self.nombre}"

    def save(self, *args, **kwargs):
        self.codigo = (self.codigo or "").strip().upper().replace(".", "")
        super().save(*args, **kwargs)


class Cargo(models.Model):
    """Puesto que existe dentro de una unidad organizativa.

    El mismo nombre se repite en varias unidades a propósito (ALMACENISTA
    existe en casi todas las tiendas): así, al elegir la unidad, solo bajan los
    cargos que de verdad corresponden a ella.
    """

    nombre = models.CharField(max_length=150)
    departamento = models.ForeignKey(
        Departamento, on_delete=models.CASCADE, related_name="cargos",
        verbose_name="unidad organizativa",
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "cargo"
        verbose_name_plural = "cargos"
        ordering = ["departamento__nombre", "nombre"]
        constraints = [
            models.UniqueConstraint(fields=["nombre", "departamento"],
                                    name="cargo_unico_por_unidad"),
        ]

    def __str__(self):
        return self.nombre

    @property
    def etiqueta_completa(self):
        return f"{self.nombre} — {self.departamento.nombre}"


class Usuario(AbstractUser):
    """Usuario del sistema con rol y ámbito geográfico."""

    class Rol(models.TextChoices):
        ADMIN = "ADMIN", "Administrador (Sede Central)"
        # El alcance ya no viene con el rol (lo define la zona o `acceso_nacional`),
        # así que la etiqueta dice lo que el rol sí decide: qué puede hacer.
        RRHH_INTERIOR = "RRHH_INTERIOR", "RRHH Interior (carga y edita)"
        # Mismos permisos que RRHH Interior: existe como rol aparte para
        # distinguir al personal de Gestión Humana de la Sede Central.
        RRHH_PRINCIPAL = "RRHH_PRINCIPAL", "RRHH Principal (carga y edita)"
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
    acceso_nacional = models.BooleanField(
        "acceso a todas las zonas",
        default=False,
        help_text="Para RRHH Interior o Solo lectura que trabajan con todo el país: "
                  "ven las tiendas y los expedientes de todas las zonas. "
                  "Con esto tildado la zona no hace falta.",
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
    def es_principal(self) -> bool:
        return self.rol == self.Rol.RRHH_PRINCIPAL

    @property
    def es_solo_lectura(self) -> bool:
        return self.rol == self.Rol.SOLO_LECTURA

    @property
    def puede_editar(self) -> bool:
        """¿Puede crear/editar/subir? Admin, RRHH Interior y RRHH Principal."""
        return self.es_admin or self.es_interior or self.es_principal

    @property
    def puede_borrar(self) -> bool:
        """Solo el Administrador nacional puede borrar (borrado lógico)."""
        return self.es_admin

    @property
    def alcance_nacional(self) -> bool:
        """¿Ve todo el país? El Administrador siempre; los demás si se lo dieron.

        Es un permiso que el Administrador otorga a mano, no el valor por
        defecto: un usuario recién creado no ve nada hasta que se le asigna una
        zona o este acceso.
        """
        return self.es_admin or self.acceso_nacional

    @property
    def descripcion_alcance(self) -> str:
        """Lo que se muestra al lado del rol, para que nadie tenga que adivinar."""
        if self.alcance_nacional:
            return "Todas las zonas"
        return str(self.zona) if self.zona_id else "Sin zona asignada"


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
        help_text="Obligatoria para RRHH Interior y Solo lectura, salvo que se les "
                  "dé acceso a todas las zonas.",
    )
    acceso_nacional = models.BooleanField(
        "acceso a todas las zonas",
        default=False,
        help_text="La persona verá las tiendas y los expedientes de todo el país. "
                  "Con esto tildado no hace falta elegir zona.",
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
        if self.acceso_nacional:
            detalle = " · todas las zonas"
        else:
            detalle = f" · {self.zona}" if self.zona else ""
        return f"Invitación {self.get_rol_display()}{detalle}"

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
