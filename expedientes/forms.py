"""Formularios de GDE — Gestión Digital de Expedientes."""

import re
from datetime import timedelta
from decimal import Decimal

from django import forms
from django.db.models import Count, Max, Q
from django.utils import timezone

from cuentas.models import Cargo, Departamento, Sede, TipoDocumentoIdentidad
from cuentas.widgets import FechaInput, SelectCargo
from .permisos import trabajadores_visibles, ve_todo_el_pais
from .models import (
    AsignacionPago, ConceptoPago, DatosContratacion, Documento, Hijo, Moneda,
    TipoDocumento, Trabajador,
)


_INPUT = "input"
_SELECT = "select"


def _tiendas_del_usuario(usuario):
    """Tiendas que este usuario tiene permitido elegir.

    Tiene que devolver exactamente las tiendas cuyos expedientes después va a
    poder ver (`trabajadores_visibles`); si no, podría dar de alta a alguien y
    perderlo de vista para siempre.

    De fábrica las ve todas. Solo se recorta si en Configuración se prendió
    «Restringir cada usuario a su zona»: ahí quedan las de su zona, o ninguna
    si no tiene zona asignada.
    """
    activas = Sede.objects.filter(activa=True).select_related("zona")
    if usuario is None or ve_todo_el_pais(usuario):
        return activas
    if not usuario.zona_id:
        return activas.none()
    return activas.filter(zona_id=usuario.zona_id)


def _explicar_si_no_hay_tiendas(campo, usuario):
    """Un desplegable vacío no dice nada; este texto sí.

    Pasa cuando al usuario le asignaron una zona que todavía no tiene tiendas
    cargadas, o directamente ninguna zona ni acceso nacional.
    """
    if campo.queryset.exists():
        return
    campo.help_text = _motivo_sin_tiendas(usuario)


def _motivo_sin_tiendas(usuario):
    """Por qué no hay tiendas para elegir, y qué hacer al respecto.

    Lo usan el alta y el panel de filtros; una sola redacción para que las dos
    pantallas nunca digan cosas distintas.
    """
    if usuario is None or ve_todo_el_pais(usuario):
        if usuario is not None and usuario.es_admin:
            return ("No hay tiendas activas. Agregalas en Configuración → "
                    "Tiendas → + Nuevo.")
        return ("No hay tiendas activas. Pedile al Administrador que las "
                "agregue en Configuración → Tiendas.")
    # De acá para abajo, solo con «Restringir cada usuario a su zona» prendido.
    if not usuario.zona_id:
        return ("Está prendida la restricción por zona y vos no tenés zona "
                "asignada. Pedile al Administrador que te asigne una, que te "
                "dé acceso a todas las zonas, o que apague «Restringir cada "
                "usuario a su zona» en Configuración → Opciones del sistema.")
    cierre = ("Pedile al Administrador que las agregue en Configuración → Tiendas."
              if not usuario.es_admin else
              "Agregalas en Configuración → Tiendas → + Nuevo.")
    return f"Tu zona ({usuario.zona}) todavía no tiene tiendas cargadas. {cierre}"


class TrabajadorForm(forms.ModelForm):
    class Meta:
        model = Trabajador
        fields = [
            "tipo_documento", "documento_identidad", "rif", "nombres", "apellidos",
            "fecha_nacimiento",
            "email", "telefono", "sede", "departamento", "puesto",
            "fecha_ingreso", "estado",
        ]
        widgets = {
            "fecha_nacimiento": FechaInput(),
            "fecha_ingreso": FechaInput(),
            "puesto": SelectCargo,
        }

    def __init__(self, *args, usuario=None, creando=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        # Al dar de alta no se pregunta el estado: siempre entra como Activo.
        if creando:
            self.fields.pop("estado", None)
        self.fields["sede"].queryset = _tiendas_del_usuario(usuario)
        _explicar_si_no_hay_tiendas(self.fields["sede"], usuario)
        self.fields["departamento"].queryset = Departamento.objects.filter(activo=True)
        self.fields["departamento"].label = "Unidad organizativa"

        # Solo los tipos activos, más el que ya tenga el expediente aunque lo
        # hayan dado de baja: si no, al abrir una ficha vieja el campo aparece
        # vacío y guardar la borraría sin que nadie lo haya pedido.
        tipos = TipoDocumentoIdentidad.objects.filter(activo=True)
        actual = getattr(self.instance, "tipo_documento_id", None)
        if actual:
            tipos = TipoDocumentoIdentidad.objects.filter(
                Q(activo=True) | Q(pk=actual))
        self.fields["tipo_documento"].queryset = tipos
        self.fields["tipo_documento"].label = "Tipo"
        self.fields["tipo_documento"].empty_label = "—"
        self.fields["tipo_documento"].help_text = ""
        # Los expedientes viejos traen la letra pegada dentro del número
        # ("V-30719983"): por eso no es obligatorio.
        self.fields["documento_identidad"].label = "Cédula"
        self.fields["puesto"].queryset = (
            Cargo.objects.filter(activo=True, departamento__activo=True)
            .select_related("departamento")
        )
        self.fields["puesto"].empty_label = "— Elegí primero la unidad —"
        # Decía "Se elige de los cargos de la unidad organizativa", que dejó de
        # ser cierto: están todos siempre. La unidad solo los ordena.
        self.fields["puesto"].help_text = (
            "Están todos los cargos. Al elegir la unidad, los de esa unidad "
            "suben al principio de la lista."
        )
        for campo in self.fields.values():
            css = _SELECT if isinstance(campo.widget, forms.Select) else _INPUT
            campo.widget.attrs.setdefault("class", css)

    def clean_sede(self):
        """Segunda barrera, por si alguien manda la tienda a mano en el POST.

        Usa la misma regla que arma el desplegable (`ve_todo_el_pais`): si las
        dos no coinciden, el formulario rechaza opciones que él mismo ofrece, o
        al revés.
        """
        sede = self.cleaned_data["sede"]
        u = self.usuario
        if u is not None and not ve_todo_el_pais(u) and sede.zona_id != u.zona_id:
            raise forms.ValidationError("No podés asignar una tienda fuera de tu zona.")
        return sede

    def clean(self):
        """La unidad organizativa se deja como la cargó la persona. Nada más.

        Antes, si quedaba en blanco, se completaba sola con la unidad del cargo
        elegido. Tenía sentido cuando el cargo pertenecía a una sola unidad; ya
        no. El mismo nombre está repetido en decenas de unidades —ALMACENISTA
        aparece 64 veces, AUXILIAR DE MANTENIMIENTO 59—, así que al elegir un
        cargo se elige un NOMBRE, y la unidad que venía pegada a esa fila era la
        de cualquiera de las decenas: una tienda de Guatire para alguien de San
        Cristóbal. Pasó de verdad, en un expediente real.

        Un dato inventado es peor que un dato faltante: el faltante se ve en el
        semáforo de la nómina y alguien lo completa; el inventado se ve
        completo y nadie lo mira nunca.

        Cualquier cargo vale con cualquier unidad, a propósito: el catálogo
        cuelga cada cargo de una unidad, pero eso es de dónde salió el nombre,
        no dónde puede usarse.
        """
        return super().clean()


class DocumentoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ["tipo", "archivo", "fecha_vencimiento", "observaciones"]
        widgets = {
            "fecha_vencimiento": FechaInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tipo"].queryset = TipoDocumento.objects.filter(activo=True)
        for nombre, campo in self.fields.items():
            css = _SELECT if isinstance(campo.widget, forms.Select) else _INPUT
            campo.widget.attrs.setdefault("class", css)

    def clean(self):
        datos = super().clean()
        _exigir_vencimiento(self, datos)
        return datos


def _exigir_vencimiento(form, datos):
    """Un tipo marcado como 'vence' no puede quedar sin fecha.

    La comparten el formulario de subida y el del escáner: si viviera en uno
    solo, escanear sería la puerta de atrás para saltearse la regla.
    """
    tipo = datos.get("tipo")
    if tipo and tipo.requiere_vencimiento and not datos.get("fecha_vencimiento"):
        form.add_error("fecha_vencimiento",
                       f"El tipo '{tipo}' requiere fecha de vencimiento.")


class EscaneoForm(forms.Form):
    """Los datos que acompañan a las fotos del escáner del teléfono.

    Las fotos no son un campo del formulario: llegan como varios archivos con
    el mismo nombre y se validan en `escaner.armar_pdf`.
    """

    tipo = forms.ModelChoiceField(
        queryset=TipoDocumento.objects.none(), label="tipo de documento")
    nombre = forms.CharField(max_length=120, required=False,
                             label="nombre del archivo")
    fecha_vencimiento = forms.DateField(required=False)
    observaciones = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tipo"].queryset = TipoDocumento.objects.filter(activo=True)

    def clean_nombre(self):
        """Un nombre puesto a mano no puede decidir dónde se escribe el archivo.

        Se le sacan las barras y los dos puntos —con eso alcanza para salir de
        la carpeta del expediente o para pisar otro archivo— y se le saca el
        `.pdf` si lo trae, porque se lo agrega la vista.
        """
        crudo = (self.cleaned_data.get("nombre") or "").strip()
        if not crudo:
            return ""
        limpio = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", " ", crudo)
        limpio = re.sub(r"\s+", " ", limpio).strip(" .")
        if limpio.lower().endswith(".pdf"):
            limpio = limpio[:-4].strip(" .")
        if not limpio:
            raise forms.ValidationError(
                "Ese nombre no tiene ninguna letra ni número aprovechable.")
        return limpio[:100]

    def clean(self):
        datos = super().clean()
        _exigir_vencimiento(self, datos)
        return datos


class RemuneracionForm(forms.Form):
    """Grilla de remuneración del expediente.

    Cada concepto activo del catálogo (Configuración → Conceptos de pago) baja
    como un ítem con su casillero de monto. Se completan los que la persona
    cobra y se dejan vacíos los demás; la moneda la define el concepto.
    """

    prefix = "rem"

    def __init__(self, *args, trabajador=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.trabajador = trabajador
        self.conceptos = list(
            ConceptoPago.objects.filter(activo=True).select_related("moneda")
        )

        # Monto vigente de cada concepto para este trabajador.
        self.actuales = {}
        self.duplicados = []
        if trabajador is not None:
            for p in (trabajador.pagos
                      .filter(activo=True, concepto__isnull=False)
                      .order_by("id")):
                # La grilla es de un ítem por concepto: si quedaron filas
                # repetidas de la carga anterior, se conserva la más reciente.
                anterior = self.actuales.get(p.concepto_id)
                if anterior is not None:
                    self.duplicados.append(anterior)
                self.actuales[p.concepto_id] = p

        for c in self.conceptos:
            nombre = self.nombre_campo(c.pk)
            self.fields[nombre] = forms.DecimalField(
                required=False, max_digits=14, decimal_places=2,
                min_value=Decimal("0"), label=c.nombre,
                widget=forms.NumberInput(attrs={
                    "step": "0.01", "min": "0", "class": _INPUT, "placeholder": "0,00",
                }),
            )
            pago = self.actuales.get(c.pk)
            if pago is not None:
                self.initial[nombre] = pago.monto

    @staticmethod
    def nombre_campo(concepto_pk):
        return f"concepto_{concepto_pk}"

    def filas(self):
        """(concepto, campo) de cada ítem, para pintar la grilla."""
        return [(c, self[self.nombre_campo(c.pk)]) for c in self.conceptos]

    def guardar(self, usuario):
        """Aplica la grilla. Devuelve (altas, cambios, bajas, bloqueadas).

        `bloqueadas` son los conceptos que se intentó vaciar sin permiso para
        quitar: vaciar el casillero saca el concepto del expediente, así que es
        un borrado y queda reservado al Administrador. Los demás roles pueden
        corregir el monto, pero no dejar a la persona sin ese concepto.
        """
        altas = cambios = bajas = 0
        bloqueadas = []
        puede_quitar = usuario.puede_borrar

        # Filas repetidas de cargas viejas: la grilla es de un ítem por
        # concepto, así que esto es reparar un estado inconsistente y no un
        # borrado que alguien haya pedido.
        for repetido in self.duplicados:
            repetido.activo = False
            repetido.save(update_fields=["activo", "actualizado_en"])

        for c in self.conceptos:
            monto = self.cleaned_data.get(self.nombre_campo(c.pk))
            pago = self.actuales.get(c.pk)

            # Vacío o cero = esta persona no cobra este concepto.
            if monto is None or monto <= 0:
                if pago is not None:
                    if not puede_quitar:
                        bloqueadas.append(c.nombre)
                        continue
                    pago.activo = False
                    pago.save(update_fields=["activo", "actualizado_en"])
                    bajas += 1
                continue

            if pago is None:
                AsignacionPago.objects.create(
                    trabajador=self.trabajador, concepto=c,
                    monto=monto, moneda=c.moneda, creado_por=usuario,
                )
                altas += 1
            elif pago.monto != monto or pago.moneda_id != c.moneda_id:
                pago.monto = monto
                pago.moneda = c.moneda  # la moneda siempre la manda el catálogo
                pago.save(update_fields=["monto", "moneda", "actualizado_en"])
                cambios += 1

        return altas, cambios, bajas, bloqueadas


class BonoExtraForm(forms.ModelForm):
    """Bono puntual que no está en el catálogo: nombre, monto y moneda a mano."""

    # Convive con DocumentoForm en la misma página y ambos tienen 'observaciones':
    # el prefijo evita que se pisen los id/name en el HTML.
    prefix = "extra"

    class Meta:
        model = AsignacionPago
        fields = ["nombre_libre", "monto", "moneda", "observaciones"]
        widgets = {
            "monto": forms.NumberInput(attrs={"step": "0.01", "min": "0", "placeholder": "0,00"}),
            "nombre_libre": forms.TextInput(attrs={"placeholder": "Ej: Bono de puntualidad"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nombre_libre"].required = True
        self.fields["nombre_libre"].label = "Nombre del bono"

        monedas = Moneda.objects.filter(activa=True)
        self.fields["moneda"].queryset = monedas
        self.fields["moneda"].empty_label = None
        if not self.instance.pk and not self.initial.get("moneda"):
            nacional = monedas.filter(es_nacional=True).first() or monedas.first()
            if nacional:
                self.initial["moneda"] = nacional.pk

        for campo in self.fields.values():
            css = _SELECT if isinstance(campo.widget, forms.Select) else _INPUT
            campo.widget.attrs.setdefault("class", css)

    def clean_nombre_libre(self):
        nombre = (self.cleaned_data.get("nombre_libre") or "").strip()
        if not nombre:
            raise forms.ValidationError("Poné un nombre para el bono.")
        return nombre

    def clean_monto(self):
        monto = self.cleaned_data["monto"]
        if monto is not None and monto <= 0:
            raise forms.ValidationError("El monto tiene que ser mayor que cero.")
        return monto


class DatosContratacionForm(forms.ModelForm):
    """Datos de contratación, bancarios y de seguimiento del ingreso.

    Va junto al formulario del trabajador en la misma pantalla: la idea es
    cargar todo una sola vez y que de ahí salgan los documentos.
    """

    prefix = "contrato"

    class Meta:
        model = DatosContratacion
        fields = ["estado_civil", "direccion", "ciudad_nacimiento",
                  "duracion_dias", "fecha_culminacion", "motivo_contratacion",
                  "horario", "ciudad_firma",
                  "banco", "prefijo", "numero_cuenta",
                  "talla_camisa", "talla_pantalon", "talla_zapato",
                  "observaciones", "responsable"]
        widgets = {
            "fecha_culminacion": FechaInput(),
            "duracion_dias": forms.NumberInput(attrs={"min": "1", "placeholder": "Ej: 90"}),
            "horario": forms.TextInput(
                attrs={"placeholder": "Ej: 8:00AM a 5:00PM de lunes a sábado"}),
            "direccion": forms.TextInput(
                attrs={"placeholder": "Calle, edificio, piso, urbanización, ciudad, estado"}),
            "ciudad_nacimiento": forms.TextInput(
                attrs={"placeholder": "Ej: CARACAS, DISTRITO CAPITAL"}),
            "motivo_contratacion": forms.TextInput(
                attrs={"placeholder": "Ej: Temporada Navidad"}),
            "banco": forms.TextInput(attrs={"placeholder": "Ej: Banco de Venezuela"}),
            "prefijo": forms.TextInput(attrs={"placeholder": "0102", "inputmode": "numeric"}),
            "numero_cuenta": forms.TextInput(attrs={"inputmode": "numeric"}),
            "talla_camisa": forms.TextInput(attrs={"placeholder": "Ej: M"}),
            "talla_pantalon": forms.TextInput(attrs={"placeholder": "Ej: 32"}),
            "talla_zapato": forms.TextInput(attrs={"placeholder": "Ej: 41"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            css = _SELECT if isinstance(campo.widget, forms.Select) else _INPUT
            campo.widget.attrs.setdefault("class", css)

    def _solo_digitos(self, nombre):
        valor = (self.cleaned_data.get(nombre) or "").strip()
        if valor and not valor.isdigit():
            raise forms.ValidationError("Solo números, sin espacios ni guiones.")
        return valor

    def clean_prefijo(self):
        return self._solo_digitos("prefijo")

    def clean_numero_cuenta(self):
        return self._solo_digitos("numero_cuenta")

    def _talla(self, nombre):
        """Normaliza la talla: sin espacios sobrantes y en mayúscula.

        Así "m" y "M" no terminan como dos valores distintos al agrupar el
        pedido de dotación.
        """
        return (self.cleaned_data.get(nombre) or "").strip().upper()

    def clean_talla_camisa(self):
        return self._talla("talla_camisa")

    def clean_talla_pantalon(self):
        return self._talla("talla_pantalon")

    def clean_talla_zapato(self):
        return self._talla("talla_zapato")

    def sincronizar_contrato(self, fecha_ingreso):
        """Completa duración o fecha fin a partir de la otra.

        Se llama desde la vista porque la fecha de ingreso vive en el
        formulario del trabajador. Si vienen las dos, manda la fecha: es la
        que se imprime en el contrato.
        """
        if not fecha_ingreso:
            return
        dias = self.cleaned_data.get("duracion_dias")
        fin = self.cleaned_data.get("fecha_culminacion")

        if fin:
            self.instance.duracion_dias = max((fin - fecha_ingreso).days, 0)
        elif dias:
            self.instance.fecha_culminacion = fecha_ingreso + timedelta(days=dias)

    def validar_contra_ingreso(self, fecha_ingreso):
        """La fecha de fin no puede ser anterior a la de ingreso."""
        fin = self.cleaned_data.get("fecha_culminacion")
        if fecha_ingreso and fin and fin < fecha_ingreso:
            self.add_error(
                "fecha_culminacion",
                "La fecha de fin no puede ser anterior a la fecha de ingreso.",
            )
            return False
        return True


class HijoForm(forms.ModelForm):
    """Alta de un hijo en el expediente."""

    # Convive con otros formularios en la misma pantalla (documento, bono):
    # el prefijo evita que se pisen los id/name en el HTML.
    prefix = "hijo"

    class Meta:
        model = Hijo
        fields = ["nombre_completo", "fecha_nacimiento", "documento_identidad",
                  "observaciones"]
        widgets = {
            "fecha_nacimiento": FechaInput(),
            "nombre_completo": forms.TextInput(
                attrs={"placeholder": "Nombre y apellido"}),
            "documento_identidad": forms.TextInput(
                attrs={"placeholder": "Si ya tiene"}),
            "observaciones": forms.TextInput(
                attrs={"placeholder": "Opcional"}),
        }

    def __init__(self, *args, trabajador=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.trabajador = trabajador
        for campo in self.fields.values():
            css = _SELECT if isinstance(campo.widget, forms.Select) else _INPUT
            campo.widget.attrs.setdefault("class", css)

    def clean_nombre_completo(self):
        # Sin esto, "ana perez" y "Ana Perez" pasarían el control de repetidos.
        return " ".join((self.cleaned_data.get("nombre_completo") or "").split()).upper()

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data.get("fecha_nacimiento")
        if fecha and fecha > timezone.localdate():
            raise forms.ValidationError("La fecha de nacimiento no puede ser futura.")
        return fecha

    def clean(self):
        datos = super().clean()
        nombre = datos.get("nombre_completo")
        fecha = datos.get("fecha_nacimiento")
        if self.trabajador and nombre and fecha:
            repetido = Hijo.objects.filter(
                trabajador=self.trabajador, nombre_completo=nombre,
                fecha_nacimiento=fecha,
            ).exclude(pk=self.instance.pk)
            if repetido.exists():
                raise forms.ValidationError(
                    f"{nombre} ya está cargado en este expediente."
                )
        return datos


class FiltroTrabajadorForm(forms.Form):
    """Filtros del listado de expedientes."""

    q = forms.CharField(
        required=False, label="Buscar",
        widget=forms.TextInput(attrs={
            "class": _INPUT, "placeholder": "Nombre, apellido o documento…",
        }),
    )
    sedes = forms.ModelMultipleChoiceField(
        required=False, queryset=Sede.objects.none(), label="Tiendas",
        widget=forms.CheckboxSelectMultiple,
    )
    departamento = forms.ModelChoiceField(
        required=False, queryset=Departamento.objects.filter(activo=True),
        empty_label="Todos los departamentos",
        widget=forms.Select(attrs={"class": _SELECT}),
    )
    estado = forms.ChoiceField(
        required=False,
        choices=[("", "Todos los estados")] + list(Trabajador.Estado.choices),
        widget=forms.Select(attrs={"class": _SELECT}),
    )
    docs = forms.ChoiceField(
        required=False, label="Cantidad de documentos",
        widget=forms.Select(attrs={"class": _SELECT}),
    )

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        self.fields["sedes"].queryset = _tiendas_del_usuario(usuario)
        self._aceptar_sede_vieja()
        self.fields["docs"].choices = (
            [("", "Docs: todos")] + self._opciones_docs())

    def _opciones_docs(self):
        """Las cantidades detectadas entre los expedientes visibles: 0..max.

        Se calcula en cada carga de pantalla: si mañana alguien llega a 7
        documentos, el 7 aparece solo en el desplegable. Sirve sobre todo para
        el otro extremo: ver cuáles expedientes quedaron con 0 documentos.
        """
        maximo = trabajadores_visibles(self.usuario).annotate(
            cant=Count("documentos", filter=Q(documentos__activo=True))
        ).aggregate(maximo=Max("cant"))["maximo"] or 0
        opciones = [(str(n), str(n)) for n in range(maximo + 1)]
        # Un link guardado con una cantidad que ya no existe no puede romper
        # los demás filtros: se acepta y simplemente no saldrá nadie.
        valor = (self.data.get("docs") or "") if hasattr(self.data, "get") else ""
        if valor.isdigit() and (valor, valor) not in opciones:
            opciones.append((valor, valor))
        return opciones

    def _aceptar_sede_vieja(self):
        """Traduce el `?sede=` de una sola tienda al `?sedes=` de ahora.

        Los enlaces guardados y los que ya estén en el historial del navegador
        siguen funcionando en vez de mostrar la lista entera sin filtrar.
        """
        datos = self.data
        if not datos or not hasattr(datos, "getlist"):
            return
        if datos.getlist("sede") and not datos.getlist("sedes"):
            copia = datos.copy()
            copia.setlist("sedes", datos.getlist("sede"))
            self.data = copia

    @property
    def motivo_sin_tiendas(self):
        """Por qué el panel de tiendas está vacío. Cadena vacía si hay tiendas."""
        if self.fields["sedes"].queryset.exists():
            return ""
        return _motivo_sin_tiendas(self.usuario)

    @property
    def tiendas_elegidas(self):
        """Las tiendas marcadas, para pintar el resumen del desplegable."""
        if not self.is_bound:
            return []
        return list(self["sedes"].field.queryset.filter(
            pk__in=[v for v in self["sedes"].value() or [] if v]
        ))

    @property
    def resumen_tiendas(self):
        elegidas = self.tiendas_elegidas
        if not elegidas:
            return "Todas las tiendas"
        if len(elegidas) == 1:
            return elegidas[0].nombre
        return f"{len(elegidas)} tiendas"
