"""Formularios de la app de cuentas."""

from datetime import timedelta

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from .models import Departamento, InvitacionRegistro, Usuario, Zona
from .widgets import FechaInput


class RegistroForm(UserCreationForm):
    """Alta de usuario a partir de una invitación tokenizada.

    El rol y la zona NO se piden aquí: vienen fijados por la invitación, así la
    persona no puede elegirse un rol de mayor privilegio.
    """

    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = ("username", "first_name", "last_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Nombre de usuario"
        self.fields["first_name"].label = "Nombre"
        self.fields["last_name"].label = "Apellido"
        self.fields["email"].label = "Email"
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        for campo in self.fields.values():
            campo.widget.attrs.setdefault("class", "input")


class InvitacionForm(forms.ModelForm):
    """Creación de un link de invitación desde la propia app (solo admin)."""

    class Meta:
        model = InvitacionRegistro
        fields = ["rol", "acceso_nacional", "zona", "departamento", "email",
                  "nota", "expira_en"]
        widgets = {
            "expira_en": FechaInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["zona"].queryset = Zona.objects.filter(activa=True)
        self.fields["departamento"].queryset = Departamento.objects.filter(activo=True)
        self.fields["zona"].help_text = (
            "Requerida para RRHH Interior y Solo lectura, salvo que les des "
            "acceso a todas las zonas."
        )
        if not self.instance.pk:
            self.fields["expira_en"].initial = timezone.localdate() + timedelta(days=7)
        for nombre, campo in self.fields.items():
            if isinstance(campo.widget, forms.CheckboxInput):
                continue          # la casilla no lleva la clase de los inputs
            css = "select" if isinstance(campo.widget, forms.Select) else "input"
            campo.widget.attrs.setdefault("class", css)

    def clean(self):
        datos = super().clean()
        rol = datos.get("rol")
        zona = datos.get("zona")
        nacional = datos.get("acceso_nacional")
        if rol == Usuario.Rol.ADMIN:
            # Un admin ya es nacional; no tiene sentido restringirlo a una zona.
            datos["zona"] = None
            datos["acceso_nacional"] = False
            return datos
        if nacional:
            # Con acceso a todo el país la zona sobra, y dejarla puesta haría
            # creer que restringe algo.
            datos["zona"] = None
        elif not zona:
            self.add_error(
                "zona",
                "Elegí una zona, o marcá «acceso a todas las zonas» si esta "
                "persona trabaja con todo el país.",
            )
        return datos
