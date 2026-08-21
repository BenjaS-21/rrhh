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


class SelectCargo(forms.Select):
    """Select de cargos que marca a qué unidad organizativa pertenece cada uno.

    El `data-unidad` de cada opción lo usa el script del formulario para dejar
    a la vista solo los cargos de la unidad elegida. Se resuelve en el
    navegador y no con una consulta al servidor: son pocos cientos de opciones
    y así el filtrado es inmediato y funciona aunque la conexión falle.
    """

    def create_option(self, name, value, label, selected, index, subindex=None,
                      attrs=None):
        opcion = super().create_option(name, value, label, selected, index,
                                       subindex=subindex, attrs=attrs)
        cargo = getattr(value, "instance", None)
        if cargo is not None:
            opcion["attrs"]["data-unidad"] = cargo.departamento_id
        return opcion
