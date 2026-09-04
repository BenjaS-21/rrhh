"""Widgets compartidos por los formularios del proyecto."""

from django import forms


class FechaInput(forms.DateInput):
    """`<input type="date">` que muestra el valor en el formato que el navegador entiende.

    El input nativo de fecha solo lee `AAAA-MM-DD`. Django, en cambio, renderiza
    el valor con el formato del locale (`es-ar` -> `05/03/1990`), así que el
    navegador no lo podía interpretar y mostraba el campo **vacío**: al guardar
    se enviaba vacío y la fecha ya cargada se borraba sin aviso.

    Para leer los datos que llegan no hace falta nada especial: `%Y-%m-%d` ya
    está en los `DATE_INPUT_FORMATS` de `es-ar`.
    """

    input_type = "date"

    def __init__(self, attrs=None, format=None):
        super().__init__(attrs=attrs, format=format or "%Y-%m-%d")
