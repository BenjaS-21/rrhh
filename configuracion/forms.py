"""Formularios de los catálogos administrables."""

from django import forms

from cuentas.models import Area, Departamento, Sede, Zona
from expedientes.models import TipoDocumento


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


class ZonaForm(_BaseForm):
    class Meta:
        model = Zona
        fields = ["nombre", "descripcion", "activa"]


class SedeForm(_BaseForm):
    class Meta:
        model = Sede
        fields = ["nombre", "zona", "direccion", "es_central", "activa"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["zona"].queryset = Zona.objects.filter(activa=True)


class TipoDocumentoForm(_BaseForm):
    class Meta:
        model = TipoDocumento
        fields = ["nombre", "descripcion", "obligatorio",
                  "requiere_vencimiento", "activo", "orden"]
