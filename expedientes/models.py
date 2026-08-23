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


def _mb(n):
    """Bytes a un texto que se entienda: 1572864 -> '1,5 MB'."""
    return f"{n / 1024 / 1024:.1f}".replace(".", ",") + " MB"


def _validar_tamano(archivo):
    """Un documento no puede pesar cualquier cosa.

    No es capricho: el archivo se cifra en memoria antes de ir a disco, y sin
    tope una subida grande se llevaba puesto al servidor entero. Está acá, en
    el modelo, para que también valga por el admin y por cualquier script.
    """
    tope = settings.DOCUMENTOS_MAX_BYTES
    if archivo.size > tope:
        raise ValidationError(
            f"El archivo pesa {_mb(archivo.size)} y el máximo es {_mb(tope)}. "
            "Si es un PDF escaneado, volvé a escanearlo en blanco y negro o "
            "con menos calidad; o subilo partido en varios documentos."
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

    tipo_documento = models.ForeignKey(
        "cuentas.TipoDocumentoIdentidad", on_delete=models.PROTECT,
        null=True, blank=True, related_name="trabajadores",
        verbose_name="tipo de cédula",
        help_text="La letra que va delante: V, E, J…",
    )
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
    puesto = models.ForeignKey(
        "cuentas.Cargo", on_delete=models.PROTECT, null=True, blank=True,
        related_name="trabajadores", verbose_name="cargo",
        help_text="Se elige de los cargos de la unidad organizativa.",
    )
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
        return f"{self.apellidos}, {self.nombres} ({self.cedula_completa})"

    @property
    def cedula_completa(self):
        """«V-30719983». Sin tipo cargado, el número tal cual está.

        Existe en un solo lugar porque la cédula se escribe en la ficha, en la
        nómina, en el Excel y en los documentos Word: armarla en cada uno
        garantiza que alguno quede distinto.

        Los expedientes viejos traen el prefijo pegado dentro del número
        («V-30719983») y no tienen tipo. Para esos no se agrega nada: si no,
        saldría «V-V-30719983».
        """
        if not self.tipo_documento_id:
            return self.documento_identidad
        return f"{self.tipo_documento.codigo}-{self.documento_identidad}"

    @property
    def nombre_completo(self):
        return f"{self.nombres} {self.apellidos}"

    @property
    def zona(self) -> Zona:
        return self.sede.zona

    @property
    def cantidad_hijos(self) -> int:
        return self.hijos.count()

    @property
    def cargo_nombre(self) -> str:
        """Nombre del cargo, o cadena vacía. Para el Excel y los Word."""
        return self.puesto.nombre if self.puesto_id else ""

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
        validators=[_validar_extension, _validar_tamano],
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

    # --- Marcado para eliminar -------------------------------------------------
    # Borrar sigue siendo del Administrador. Pero quien sube el archivo es quien
    # se da cuenta en el momento de que subió el que no era, y hasta ahora no
    # tenía forma de decirlo: el documento equivocado se quedaba en el
    # expediente hasta que alguien más lo mirara. Marcar no borra nada, avisa.
    marcado_en = models.DateTimeField(null=True, blank=True)
    marcado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="documentos_marcados",
    )
    motivo_marca = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "documento"
        verbose_name_plural = "documentos"
        ordering = ["-subido_en"]
        indexes = [
            models.Index(fields=["trabajador", "tipo", "activo"]),
            # La lista de pendientes los busca por acá, y el barrido automático
            # también: sin índice, cada visita recorre todos los documentos.
            models.Index(fields=["marcado_en", "activo"]),
        ]

    def __str__(self):
        return f"{self.tipo} — {self.trabajador} (v{self.version})"

    @property
    def marcado(self):
        return self.marcado_en is not None

    def marcar(self, usuario, motivo=""):
        """Lo deja pedido para eliminar. No lo saca de la vista de nadie."""
        self.marcado_en = timezone.now()
        self.marcado_por = usuario
        self.motivo_marca = (motivo or "").strip()[:255]
        self.save(update_fields=["marcado_en", "marcado_por", "motivo_marca"])

    def desmarcar(self):
        """Vuelve atrás la marca. Es el «en caso tal» de haberse equivocado."""
        self.marcado_en = None
        self.marcado_por = None
        self.motivo_marca = ""
        self.save(update_fields=["marcado_en", "marcado_por", "motivo_marca"])

    def se_borra_el(self, dias):
        """Cuándo lo va a barrer solo el sistema, o None si no hay plazo.

        `dias` en 0 significa que no se borra nada solo: la lista queda como
        una bandeja de pendientes y decide una persona.
        """
        if not self.marcado_en or not dias:
            return None
        return self.marcado_en + timedelta(days=dias)

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


class Hijo(models.Model):
    """Hijo o hija de un trabajador.

    Se guarda la fecha de nacimiento y no la edad: la edad cambia sola y una
    cifra escrita a mano queda vieja al año siguiente. De acá salen los
    listados por edad (juguetes de Navidad, útiles escolares, guardería).
    """

    trabajador = models.ForeignKey(
        Trabajador, on_delete=models.CASCADE, related_name="hijos"
    )
    nombre_completo = models.CharField(
        "nombre y apellido", max_length=200,
        help_text="Como figura en la partida de nacimiento.",
    )
    fecha_nacimiento = models.DateField()
    documento_identidad = models.CharField(
        "cédula", max_length=30, blank=True,
        help_text="Si ya tiene. Opcional.",
    )
    observaciones = models.CharField(max_length=255, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="hijos_cargados",
    )

    class Meta:
        verbose_name = "hijo"
        verbose_name_plural = "hijos"
        ordering = ["fecha_nacimiento", "nombre_completo"]
        constraints = [
            # Evita cargar dos veces al mismo por error de doble clic.
            models.UniqueConstraint(
                fields=["trabajador", "nombre_completo", "fecha_nacimiento"],
                name="hijo_no_repetido",
            ),
        ]

    def __str__(self):
        return self.nombre_completo

    @property
    def edad(self):
        """Años cumplidos a hoy."""
        hoy = timezone.localdate()
        n = self.fecha_nacimiento
        return hoy.year - n.year - ((hoy.month, hoy.day) < (n.month, n.day))

    @property
    def es_menor(self):
        return self.edad < 18


class DatosContratacion(models.Model):
    """Datos que solo hacen falta para armar los documentos corporativos.

    Van aparte de la ficha del trabajador porque no siempre se tienen al dar
    de alta a la persona: se completan cuando llega el momento de generar el
    contrato y sus anexos.
    """

    class EstadoCivil(models.TextChoices):
        SOLTERO = "SOLTERO(A)", "Soltero/a"
        CASADO = "CASADO(A)", "Casado/a"
        DIVORCIADO = "DIVORCIADO(A)", "Divorciado/a"
        VIUDO = "VIUDO(A)", "Viudo/a"
        CONCUBINO = "CONCUBINO(A)", "Concubino/a"

    trabajador = models.OneToOneField(
        Trabajador, on_delete=models.CASCADE, related_name="contratacion"
    )
    estado_civil = models.CharField(
        max_length=20, choices=EstadoCivil.choices, blank=True,
    )
    direccion = models.CharField(
        "dirección de habitación", max_length=400, blank=True,
        help_text="Domicilio del trabajador, como debe salir en el contrato.",
    )
    ciudad_nacimiento = models.CharField(
        "ciudad de nacimiento", max_length=150, blank=True,
        help_text="Ej: CARACAS, DISTRITO CAPITAL",
    )
    horario = models.CharField(
        "horario de trabajo", max_length=600, blank=True,
        help_text="Texto tal cual va en el contrato. Ej: 8:00AM a 5:00PM de lunes a sábado.",
    )
    motivo_contratacion = models.CharField(
        "motivo de contratación", max_length=300, blank=True,
        help_text="Ej: Temporada Navidad, Temporada Día del Niño.",
    )
    duracion_dias = models.PositiveIntegerField(
        "duración del contrato (días)", null=True, blank=True,
        help_text="Se puede cargar esto o la fecha de fin: el otro se calcula solo.",
    )
    fecha_culminacion = models.DateField(
        "fecha fin de contrato", null=True, blank=True,
    )
    ciudad_firma = models.CharField(
        "ciudad de firma", max_length=120, blank=True, default="CARACAS",
    )

    # --- Datos bancarios ----------------------------------------------------
    # No los usa ninguna de las plantillas Word; se guardan para la nómina.
    banco = models.CharField(max_length=120, blank=True)
    prefijo = models.CharField(
        "prefijo del banco", max_length=4, blank=True,
        help_text="Los 4 primeros dígitos de la cuenta. Ej: 0102",
    )
    numero_cuenta = models.CharField(
        "número de cuenta", max_length=20, blank=True,
        help_text="Los 16 dígitos restantes.",
    )

    # --- Tallas de uniforme --------------------------------------------------
    # Tampoco las usa ninguna plantilla Word: sirven para pedir la dotación.
    # Van como texto porque conviven "M"/"38"/"S-M" según la prenda y la marca.
    talla_camisa = models.CharField(
        "talla de camisa", max_length=10, blank=True,
        help_text="Ej: S, M, L, XL, 38.",
    )
    talla_pantalon = models.CharField(
        "talla de pantalón", max_length=10, blank=True,
        help_text="Ej: 30, 32, M.",
    )
    talla_zapato = models.CharField(
        "talla de zapato", max_length=10, blank=True,
        help_text="Ej: 38, 41, 42.5.",
    )

    observaciones = models.CharField(max_length=400, blank=True)
    responsable = models.CharField(
        max_length=150, blank=True,
        help_text="Quién de RRHH procesó el ingreso.",
    )

    actualizado_en = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="contrataciones_editadas",
    )

    class Meta:
        verbose_name = "datos de contratación"
        verbose_name_plural = "datos de contratación"

    def __str__(self):
        return f"Datos de contratación de {self.trabajador}"

    @property
    def cuenta_bancaria(self) -> str:
        """Cuenta completa: prefijo + número (20 dígitos en Venezuela)."""
        if not (self.prefijo or self.numero_cuenta):
            return ""
        return f"{self.prefijo}{self.numero_cuenta}"

    @property
    def tallas(self) -> str:
        """Resumen legible de la dotación. Vacío si no se cargó ninguna."""
        partes = [f"{etiqueta} {valor}" for etiqueta, valor in (
            ("Camisa", self.talla_camisa),
            ("Pantalón", self.talla_pantalon),
            ("Zapato", self.talla_zapato),
        ) if valor]
        return " · ".join(partes)


class Moneda(models.Model):
    """Moneda en la que se expresa un monto del expediente (Bs, $, €).

    No se guardan tasas de cambio: cada monto queda registrado en su propia
    moneda y los totales se muestran separados por moneda, nunca sumados entre sí.
    """

    codigo = models.CharField(
        "código", max_length=3, unique=True,
        help_text="Código ISO de 3 letras: VES, USD, EUR.",
    )
    nombre = models.CharField(max_length=40)
    simbolo = models.CharField("símbolo", max_length=5, help_text="Bs, $, €")
    es_nacional = models.BooleanField(
        "es la moneda nacional", default=False,
        help_text="Marca la moneda del país. Las demás se consideran divisas.",
    )
    activa = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=100)

    class Meta:
        verbose_name = "moneda"
        verbose_name_plural = "monedas"
        ordering = ["orden", "codigo"]

    def __str__(self):
        return f"{self.simbolo} — {self.nombre}"

    def save(self, *args, **kwargs):
        self.codigo = self.codigo.strip().upper()
        super().save(*args, **kwargs)
        # Solo puede haber una moneda nacional.
        if self.es_nacional:
            Moneda.objects.exclude(pk=self.pk).filter(es_nacional=True).update(
                es_nacional=False
            )

    def formatear(self, monto) -> str:
        """Formato local: 1234.5 -> '1.234,50 Bs'."""
        entero, _, decimales = f"{monto:,.2f}".partition(".")
        return f"{entero.replace(',', '.')},{decimales} {self.simbolo}"


class ConceptoPago(models.Model):
    """Catálogo de conceptos remunerativos (sueldo base, bono de transporte…).

    Define QUÉ se paga. El CUÁNTO se carga por trabajador en AsignacionPago,
    porque el monto varía de persona a persona.
    """

    class Clase(models.TextChoices):
        SUELDO = "SUELDO", "Sueldo / salario"
        BONO = "BONO", "Bono"

    nombre = models.CharField(max_length=120, unique=True)
    descripcion = models.CharField(max_length=255, blank=True)
    clase = models.CharField(
        max_length=10, choices=Clase.choices, default=Clase.BONO,
        help_text="Solo agrupa el listado; no cambia los cálculos.",
    )
    moneda = models.ForeignKey(
        Moneda, on_delete=models.PROTECT, related_name="conceptos",
        help_text="Moneda en la que se paga este concepto. Se propone sola al "
                  "cargarlo en un expediente y ahí se puede cambiar si hace falta.",
    )
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=100)

    class Meta:
        verbose_name = "concepto de pago"
        verbose_name_plural = "conceptos de pago"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class AsignacionPago(models.Model):
    """Monto vigente que cobra un trabajador por un concepto.

    Refleja lo que la persona cobra HOY: se edita cuando cambia. Cada fila es
    un monto en UNA moneda; un mismo trabajador puede tener varias filas en
    monedas distintas (ej. 180 Bs de sueldo + 400 $ de bono).

    El concepto sale del catálogo (`concepto`) o es un bono extra escrito a
    mano (`nombre_libre`). Siempre uno de los dos, nunca ambos.
    """

    trabajador = models.ForeignKey(
        Trabajador, on_delete=models.CASCADE, related_name="pagos"
    )
    concepto = models.ForeignKey(
        ConceptoPago, on_delete=models.PROTECT, related_name="asignaciones",
        null=True, blank=True,
        help_text="Concepto del catálogo. Dejalo vacío para un bono extra con nombre libre.",
    )
    nombre_libre = models.CharField(
        "nombre del bono extra", max_length=120, blank=True,
        help_text="Solo si no elegiste un concepto del catálogo.",
    )

    monto = models.DecimalField(max_digits=14, decimal_places=2)
    moneda = models.ForeignKey(Moneda, on_delete=models.PROTECT, related_name="asignaciones")
    observaciones = models.CharField(max_length=255, blank=True)

    activo = models.BooleanField(default=True, help_text="Borrado lógico: False = dado de baja.")
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="pagos_cargados",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "asignación de pago"
        verbose_name_plural = "asignaciones de pago"
        ordering = [models.F("concepto__orden").asc(nulls_last=True), "id"]
        indexes = [
            models.Index(fields=["trabajador", "activo"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(concepto__isnull=False, nombre_libre="")
                    | (models.Q(concepto__isnull=True) & ~models.Q(nombre_libre=""))
                ),
                name="pago_concepto_del_catalogo_o_nombre_libre",
            ),
        ]

    def __str__(self):
        return f"{self.etiqueta}: {self.monto_formateado} — {self.trabajador}"

    @property
    def etiqueta(self) -> str:
        """Nombre a mostrar, venga del catálogo o sea un bono extra."""
        return self.concepto.nombre if self.concepto_id else self.nombre_libre

    @property
    def es_bono_extra(self) -> bool:
        return self.concepto_id is None

    @property
    def monto_formateado(self) -> str:
        return self.moneda.formatear(self.monto)


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
