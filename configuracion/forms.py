"""Formularios de los catálogos administrables."""

from django import forms

from cuentas.models import Area, Cargo, Departamento, Sede, Zona
from expedientes.models import ConceptoPago, Moneda, TipoDocumento

from .models import Preferencias


class _BaseForm(forms.ModelForm):
    """Aplica estilos Damasco a todos los campos."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            if isinstance(campo.widget, forms.CheckboxInput):
                continue
            css = "select" if isinstance(campo.widget, forms.Select) else "input"
            campo.widget.attrs.setdefault("class", css)


class DepartamentoForm(_BaseForm):
    class Meta:
        model = Departamento
        fields = ["nombre", "descripcion", "activo"]


class AreaForm(_BaseForm):
    class Meta:
        model = Area
        fields = ["nombre", "departamento", "descripcion", "activo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["departamento"].queryset = Departamento.objects.filter(activo=True)


class CargoForm(_BaseForm):
    """Un cargo vive dentro de una unidad organizativa.

    El mismo nombre se repite a propósito en varias unidades (ALMACENISTA está
    en casi todas), así que lo único que no se admite es repetirlo DENTRO de la
    misma unidad; de eso se encarga la restricción del modelo, y acá se traduce
    a un mensaje que se entienda.
    """

    class Meta:
        model = Cargo
        fields = ["nombre", "departamento", "activo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["departamento"].queryset = Departamento.objects.filter(activo=True)
        self.fields["departamento"].label = "Unidad organizativa"

    def clean_nombre(self):
        # El catálogo real viene todo en mayúsculas: si se carga a mano en
        # minúscula queda un duplicado que la restricción no llega a ver.
        return (self.cleaned_data["nombre"] or "").strip().upper()

    def validate_unique(self):
        """Se reemplaza la verificación de Django para poder decir cuál cambiar.

        La suya sale arriba de todo y dice «Ya existe un/a Cargo con este/a
        Nombre y Unidad organizativa», que no señala ningún campo. La de acá
        cuelga del nombre, que es el que hay que corregir. La restricción de la
        base sigue estando: esto es el mensaje, no la garantía.
        """
        nombre = self.cleaned_data.get("nombre")
        unidad = self.cleaned_data.get("departamento")
        if not nombre or not unidad:
            return
        otros = Cargo.objects.filter(nombre=nombre, departamento=unidad)
        if self.instance.pk:
            otros = otros.exclude(pk=self.instance.pk)
        if otros.exists():
            self.add_error("nombre", f"{unidad} ya tiene un cargo con ese nombre.")


class ZonaForm(_BaseForm):
    class Meta:
        model = Zona
        fields = ["nombre", "descripcion", "activa"]


class SedeForm(_BaseForm):
    class Meta:
        model = Sede
        fields = ["nombre", "zona", "ciudad", "direccion", "es_central", "activa"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["zona"].queryset = Zona.objects.filter(activa=True)


class TipoDocumentoForm(_BaseForm):
    class Meta:
        model = TipoDocumento
        fields = ["nombre", "descripcion", "obligatorio",
                  "requiere_vencimiento", "activo", "orden"]


class MonedaForm(_BaseForm):
    class Meta:
        model = Moneda
        fields = ["codigo", "nombre", "simbolo", "es_nacional", "activa", "orden"]

    def clean_codigo(self):
        return self.cleaned_data["codigo"].strip().upper()


class ConceptoPagoForm(_BaseForm):
    class Meta:
        model = ConceptoPago
        fields = ["nombre", "descripcion", "clase", "moneda", "activo", "orden"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["moneda"].queryset = Moneda.objects.filter(activa=True)
        self.fields["moneda"].empty_label = None


class PreferenciasForm(_BaseForm):
    """Opciones globales. No es un catálogo: es una sola fila."""

    class Meta:
        model = Preferencias
        fields = ["restringir_por_zona", "dias_para_eliminar_marcados"]

    def clean_dias_para_eliminar_marcados(self):
        """Dejarlo en blanco es decir «sin plazo», o sea 0.

        La columna no admite nulos, así que sin esto un campo vacío revienta al
        guardar en vez de significar lo evidente.
        """
        return self.cleaned_data.get("dias_para_eliminar_marcados") or 0
