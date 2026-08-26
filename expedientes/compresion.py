"""Compresión de documentos que pesan más que DOCUMENTOS_MAX_BYTES.

Es la mitad servidor del botón "Comprimir aquí y subir" de la pantalla de carga
(la otra mitad está en `static/js/subida.js`, que comprime las imágenes en el
propio navegador y solo manda los PDF acá).

Un PDF no se puede descomprimir y rearmar igual de chico con Pillow: hay que
VOLVER A DIBUJAR cada página, y eso es lo que hace PyMuPDF. El resultado es un
PDF de imágenes, como el que arma el escáner del teléfono: para documentos
escaneados —que es lo que se sube— se lee igual y pesa una fracción.

Se trabaja de a una página por vez: el pico de memoria es una página renderizada
(unos pocos MB), nunca el documento entero.
"""

from io import BytesIO
import os

import pymupdf
from django.conf import settings
from PIL import Image, ImageOps

# Una hoja A4 a 2500 px de lado largo se lee sin esfuerzo y queda liviana.
LADO_MAXIMO_IMAGEN = 2500

# De más legible a más chico. El primero que deje el archivo por debajo del
# tope es el que se usa; lo normal es que alcance con el primero.
_INTENTOS_PDF = [
    {"ppp": 150, "calidad": 75},
    {"ppp": 130, "calidad": 60},
    {"ppp": 110, "calidad": 45},
]
_CALIDADES_IMAGEN = [85, 70, 55]


class NoSePudoComprimir(Exception):
    """El archivo no es válido o ni comprimido entra en el tope.

    El mensaje está pensado para mostrarse en pantalla tal cual.
    """


def _tope() -> int:
    return settings.DOCUMENTOS_MAX_BYTES


def comprimir_imagen(datos: bytes) -> bytes:
    """Re-codifica una imagen como JPEG por debajo del tope. Devuelve los bytes."""
    try:
        imagen = Image.open(BytesIO(datos))
        imagen.load()
    except Image.DecompressionBombError:
        raise NoSePudoComprimir(
            "La imagen es demasiado grande para procesarla en el servidor."
        )
    except Exception:
        raise NoSePudoComprimir("El archivo no es una imagen válida.")

    imagen = ImageOps.exif_transpose(imagen)
    if max(imagen.size) > LADO_MAXIMO_IMAGEN:
        imagen.thumbnail((LADO_MAXIMO_IMAGEN, LADO_MAXIMO_IMAGEN), Image.LANCZOS)

    # El JPEG no admite transparencia: se aplana sobre fondo blanco, que es lo
    # que espera ver quien imprime el documento.
    if imagen.mode in ("RGBA", "LA", "P"):
        fondo = Image.new("RGB", imagen.size, "white")
        imagen = imagen.convert("RGBA")
        fondo.paste(imagen, mask=imagen.split()[-1])
        imagen = fondo
    elif imagen.mode != "RGB":
        imagen = imagen.convert("RGB")

    resultado = None
    for calidad in _CALIDADES_IMAGEN:
        salida = BytesIO()
        imagen.save(salida, format="JPEG", quality=calidad, optimize=True)
        resultado = salida.getvalue()
        if len(resultado) <= _tope():
            return resultado
    # Última carta: achicar de verdad la imagen, no solo la calidad.
    while max(imagen.size) > 1200:
        imagen.thumbnail((int(imagen.size[0] * 0.7), int(imagen.size[1] * 0.7)),
                         Image.LANCZOS)
        salida = BytesIO()
        imagen.save(salida, format="JPEG", quality=_CALIDADES_IMAGEN[-1],
                    optimize=True)
        resultado = salida.getvalue()
        if len(resultado) <= _tope():
            return resultado
    raise NoSePudoComprimir(
        "Ni comprimida entra en el máximo permitido. Subila partida en dos."
    )


def _render_pagina_jpeg(pagina, ppp: int, calidad: int) -> bytes:
    """Dibuja la página como foto JPEG. Una sola en memoria por vez."""
    pix = pagina.get_pixmap(dpi=ppp)
    try:
        imagen = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        salida = BytesIO()
        imagen.save(salida, format="JPEG", quality=calidad, optimize=True)
        return salida.getvalue()
    finally:
        pix = None


def _rearmar_pdf(origen, ppp: int, calidad: int) -> bytes:
    """El documento entero rearmado con cada página como imagen JPEG."""
    salida = pymupdf.open()
    try:
        for pagina in origen:
            jpeg = _render_pagina_jpeg(pagina, ppp, calidad)
            # Mismas dimensiones de la página original: el PDF que sale tiene
            # el mismo tamaño de hoja, solo que con la página como foto.
            nueva = salida.new_page(width=pagina.rect.width,
                                    height=pagina.rect.height)
            nueva.insert_image(nueva.rect, stream=jpeg)
        buffer = BytesIO()
        salida.save(buffer, garbage=4, deflate=True)
        return buffer.getvalue()
    finally:
        salida.close()


def comprimir_pdf(fuente) -> bytes:
    """Reconstruye un PDF pesado como PDF de imágenes por debajo del tope.

    `fuente` son los bytes del PDF o la ruta del temporal en disco: con los
    archivos grandes se prefiere la ruta para no tener el PDF entero en RAM
    mientras se rearman las páginas.
    """
    try:
        if isinstance(fuente, (str, os.PathLike)):
            origen = pymupdf.open(fuente)
        else:
            origen = pymupdf.open(stream=fuente, filetype="pdf")
    except Exception:
        raise NoSePudoComprimir("El archivo no es un PDF válido.")
    try:
        if origen.page_count == 0:
            raise NoSePudoComprimir("El PDF no tiene ninguna página.")

        for intento in _INTENTOS_PDF:
            resultado = _rearmar_pdf(origen, intento["ppp"], intento["calidad"])
            if len(resultado) <= _tope():
                return resultado
        raise NoSePudoComprimir(
            "Ni comprimido entra en el máximo permitido. Subilo partido en dos "
            "documentos."
        )
    finally:
        origen.close()
