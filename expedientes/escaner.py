"""Armado del PDF a partir de las fotos que saca el escáner del teléfono.

El recorte de la hoja y el filtro de escáner se hacen en el teléfono, sobre la
foto, antes de subirla: así viaja una imagen chica en blanco y negro en vez de
una foto de 4 MB, que en la tienda —con la conexión que haya— es la diferencia
entre que funcione y que no.

Acá se hace lo que no se puede confiar al navegador: verificar que lo que llegó
sean imágenes de verdad, acotar el tamaño, y unirlas en un solo PDF.
"""

from io import BytesIO

from PIL import Image, ImageOps

# Un expediente escaneado con el teléfono no tiene 50 hojas; el tope es para que
# una petición rota no consuma la memoria del servidor.
MAX_PAGINAS = 30
MAX_BYTES_POR_PAGINA = 8 * 1024 * 1024
MAX_BYTES_TOTAL = 24 * 1024 * 1024

# 150 ppp sobre el lado largo deja una hoja A4 legible y un archivo liviano.
LADO_MAXIMO = 2000
RESOLUCION = 150

FORMATOS = {"JPEG", "PNG", "WEBP"}


class EscaneoInvalido(Exception):
    """Lo que llegó no sirve para armar un PDF. El mensaje va a la pantalla."""


def armar_pdf(paginas) -> bytes:
    """Une las imágenes recibidas en un único PDF y devuelve sus bytes.

    `paginas` son los archivos subidos, en el orden en que se sacaron las fotos.
    """
    if not paginas:
        raise EscaneoInvalido("No llegó ninguna foto.")
    if len(paginas) > MAX_PAGINAS:
        raise EscaneoInvalido(
            f"Son demasiadas hojas ({len(paginas)}). El máximo es {MAX_PAGINAS}."
        )

    total = sum(getattr(p, "size", 0) for p in paginas)
    if total > MAX_BYTES_TOTAL:
        raise EscaneoInvalido("Las fotos pesan demasiado en conjunto.")

    imagenes = [_abrir(p, numero) for numero, p in enumerate(paginas, start=1)]

    salida = BytesIO()
    imagenes[0].save(
        salida, format="PDF", save_all=True, append_images=imagenes[1:],
        resolution=RESOLUCION,
    )
    return salida.getvalue()


def _abrir(archivo, numero):
    """Valida una foto y la deja lista para el PDF."""
    if getattr(archivo, "size", 0) > MAX_BYTES_POR_PAGINA:
        raise EscaneoInvalido(f"La hoja {numero} pesa demasiado.")

    try:
        imagen = Image.open(archivo)
        imagen.load()
    except Exception:
        # No se filtra el error de Pillow: no le dice nada a quien lo lee y
        # puede exponer detalles del archivo que mandaron.
        raise EscaneoInvalido(f"La hoja {numero} no es una imagen válida.")

    if imagen.format not in FORMATOS:
        raise EscaneoInvalido(
            f"La hoja {numero} está en un formato que no se puede usar "
            f"({imagen.format})."
        )

    # El teléfono guarda la orientación como metadato en vez de rotar los
    # píxeles: sin esto, las hojas sacadas de costado salen acostadas.
    imagen = ImageOps.exif_transpose(imagen)

    if max(imagen.size) > LADO_MAXIMO:
        imagen.thumbnail((LADO_MAXIMO, LADO_MAXIMO), Image.LANCZOS)

    # El PDF no admite transparencia: un PNG con alfa saldría con el fondo negro.
    if imagen.mode in ("RGBA", "LA", "P"):
        fondo = Image.new("RGB", imagen.size, "white")
        imagen = imagen.convert("RGBA")
        fondo.paste(imagen, mask=imagen.split()[-1])
        imagen = fondo
    elif imagen.mode != "RGB":
        imagen = imagen.convert("RGB")

    return imagen
