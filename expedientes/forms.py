"""Formularios del sistema de expedientes."""

from django import forms

from cuentas.models import Departamento, Sede
from .models import Trabajador, Documento, TipoDocumento


_INPUT = "input"
_SELECT = "select"


class TrabajadorForm(forms.ModelForm):
    class Meta:
        model = Trabajador
        fields = [
            "documento_identidad", "nombres", "apellidos", "fecha_nacimiento",
            "email", "telefono", "sede", "departamento", "puesto",
            "fecha_ingreso", "estado",
        ]
        widgets = {
            "fecha_nacimiento": forms.DateInput(attrs={"type": "date"}),
            "fecha_ingreso": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        # RRHH Interior solo puede asignar sedes de su zona.
        if usuario is not None and not usuario.es_admin and usuario.zona_id:
            self.fields["sede"].queryset = Sede.objects.filter(
                zona_id=usuario.zona_id, activa=True
            )
        else:
            self.fields["sede"].queryset = Sede.objects.filter(activa=True)
        self.fields["departamento"].queryset = Departamento.objects.filter(activo=True)
        for campo in self.fields.values():
            css = _SELECT if isinstance(campo.widget, forms.Select) else _INPUT
            campo.widget.attrs.setdefault("class", css)

    def clean_sede(self):
        sede = self.cleaned_data["sede"]
        u = self.usuario
        if u is not None and not u.es_admin and u.zona_id and sede.zona_id != u.zona_id:
            raise forms.ValidationError("No podés asignar una sede fuera de tu zona.")
        return sede


class DocumentoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ["tipo", "archivo", "fecha_vencimiento", "observaciones"]
        widgets = {
            "fecha_vencimiento": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tipo"].queryset = TipoDocumento.objects.filter(activo=True)
        for nombre, campo in self.fields.items():
            css = _SELECT if isinstance(campo.widget, forms.Select) else _INPUT
            campo.widget.attrs.setdefault("class", css)

    def clean(self):
        datos = super().clean()
        tipo = datos.get("tipo")
        venc = datos.get("fecha_vencimiento")
        if tipo and tipo.requiere_vencimiento and not venc:
            self.add_error("fecha_vencimiento",
                           f"El tipo '{tipo}' requiere fecha de vencimiento.")
        return datos


class FiltroTrabajadorForm(forms.Form):
    """Filtros del listado de expedientes."""

    q = forms.CharField(
        required=False, label="Buscar",
        widget=forms.TextInput(attrs={
            "class": _INPUT, "placeholder": "Nombre, apellido o documento…",
        }),
    )
    sede = forms.ModelChoiceField(
        required=False, queryset=Sede.objects.none(), empty_label="Todas las tiendas",
        widget=forms.Select(attrs={"class": _SELECT}),
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

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        if usuario is not None and not usuario.es_admin and usuario.zona_id:
            self.fields["sede"].queryset = Sede.objects.filter(
                zona_id=usuario.zona_id, activa=True
            )
        else:
            self.fields["sede"].queryset = Sede.objects.filter(activa=True)
