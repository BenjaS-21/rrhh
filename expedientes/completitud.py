"""Qué tan completo está un trabajador para la nómina en Excel.

La lista de datos vive acá y no en la vista ni en la plantilla porque la usan
dos cosas que tienen que decir lo mismo: el semáforo de la pantalla y las
columnas del archivo. Si cada una tuviera su propia lista, el semáforo diría
«completo» y el Excel saldría con celdas vacías igual.
"""

from dataclasses import dataclass


def _de_contratacion(campo):
    """Los datos de contratación viven en otra tabla y pueden no existir."""
    def leer(trabajador):
        datos = getattr(trabajador, "contratacion", None)
        return getattr(datos, campo, "") if datos else ""
    return leer


# Cada dato, con el nombre que ve la persona y dónde se corrige.
#
# Quedan afuera a propósito:
#   - C.I., apellidos y nombres: no pueden estar vacíos, no hay nada que avisar.
#   - Hijos: cero hijos es una respuesta, no un dato faltante.
#   - Los conceptos de pago: nadie cobra todos. Un monto vacío quiere decir
#     "esta persona no cobra esto", así que contarlo como falta marcaría en
#     rojo a media nómina sin que haya nada que completar.
DATOS_BASE = [
    ("Cargo", lambda t: t.puesto_id),
    ("Departamento", lambda t: t.departamento_id),
    ("Fecha de ingreso", lambda t: t.fecha_ingreso),
    ("Talla de camisa", _de_contratacion("talla_camisa")),
    ("Talla de pantalón", _de_contratacion("talla_pantalon")),
    ("Talla de zapato", _de_contratacion("talla_zapato")),
]

# Solo cuentan para quien puede ver los datos de pago. Para Solo lectura esas
# columnas ni salen en el Excel: marcarle que "faltan" sería pedirle que
# complete algo que no puede ni mirar.
DATOS_DE_PAGO = [
    ("Banco", _de_contratacion("banco")),
    ("Prefijo del banco", _de_contratacion("prefijo")),
    ("Número de cuenta", _de_contratacion("numero_cuenta")),
]


@dataclass(frozen=True)
class Completitud:
    porcentaje: int
    faltan: tuple

    @property
    def nivel(self):
        """Verde / amarillo / rojo, que es lo que se ve de un vistazo."""
        if self.porcentaje >= 100:
            return "completo"
        if self.porcentaje > 0:
            return "parcial"
        return "vacio"

    @property
    def detalle(self):
        if not self.faltan:
            return "Listo para exportar: no falta ningún dato."
        return "Falta cargar: " + ", ".join(self.faltan) + "."


def datos_revisados(con_pagos):
    return DATOS_BASE + DATOS_DE_PAGO if con_pagos else list(DATOS_BASE)


def completitud(trabajador, con_pagos):
    """Cuánto de lo que va al Excel está cargado, y qué falta."""
    revisar = datos_revisados(con_pagos)
    faltan = tuple(etiqueta for etiqueta, leer in revisar if not leer(trabajador))
    completos = len(revisar) - len(faltan)
    return Completitud(
        porcentaje=round(completos / len(revisar) * 100) if revisar else 100,
        faltan=faltan,
    )
