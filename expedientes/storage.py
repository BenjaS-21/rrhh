"""
Almacenamiento cifrado de documentos en reposo.

Los archivos se cifran con Fernet (AES-128 en modo CBC + HMAC) antes de
escribirse a disco y se descifran al leerlos. Así, aunque alguien acceda al
sistema de archivos del servidor, los documentos no son legibles sin la clave
(DOCUMENTOS_ENCRYPTION_KEY del .env).

Los archivos NUNCA se sirven directamente por el servidor web: siempre pasan
por una vista de descarga que valida permisos y descifra en memoria.

**Se cifra por pedazos.** Fernet trabaja sobre bytes en memoria y no tiene modo
de flujo: cifrar un archivo entero de una vez pedía casi siete veces su tamaño
en RAM (medido: 100 MB de archivo -> 670 MB de pico). Con dos personas subiendo
al mismo tiempo, el servidor se quedaba sin memoria y dejaba de responder. Acá
el archivo se parte en bloques de 1 MB, cada bloque se cifra por su cuenta y se
escribe, así que el pico no depende del tamaño del archivo.

Los archivos guardados con el formato viejo —un único token Fernet— se siguen
leyendo igual: lo dice el encabezado. No hay nada que migrar.
"""

import struct

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from cryptography.fernet import Fernet

# Marca al principio del archivo. Los guardados antes no la tienen: un token
# Fernet siempre empieza con "gAAAAA", así que los dos formatos se distinguen
# sin ambigüedad.
CABECERA = b"GDE1\n"

# Bloque de texto claro. Cifrado ocupa ~1,4 MB; el pico de memoria son unos
# pocos de estos, pese un archivo 1 MB o 500.
BLOQUE = 1024 * 1024

# Cuánto puede medir un bloque cifrado. Es un tope de cordura para no reservar
# memoria a lo loco si el archivo está dañado o alguien lo tocó a mano.
MAX_BLOQUE_CIFRADO = 8 * 1024 * 1024


def _get_fernet() -> Fernet:
    clave = getattr(settings, "DOCUMENTOS_ENCRYPTION_KEY", "") or ""
    if not clave:
        raise RuntimeError(
            "DOCUMENTOS_ENCRYPTION_KEY no está configurada. Generá una clave con:\n"
            '  python -c "import base64,os; '
            'print(base64.urlsafe_b64encode(os.urandom(32)).decode())"\n'
            "y ponéla en el archivo .env."
        )
    return Fernet(clave.encode() if isinstance(clave, str) else clave)


class ArchivoCifrado:
    """Lo que se le pasa a `FileSystemStorage._save`: se lee de a pedazos.

    Django escribe el archivo llamando a `chunks()`, así que el cifrado ocurre
    a medida que se escribe y nunca hay más de un bloque en memoria.
    """

    def __init__(self, origen):
        self.origen = origen
        self.name = getattr(origen, "name", "")

    def chunks(self, chunk_size=None):
        fernet = _get_fernet()
        yield CABECERA
        for pedazo in self.origen.chunks(BLOQUE):
            token = fernet.encrypt(pedazo)
            yield struct.pack(">I", len(token))
            yield token

    def read(self, size=None):
        # Django no la usa cuando hay `chunks()`, pero `File` la promete.
        return b"".join(self.chunks())

    # `FileSystemStorage` mira estos dos para decidir cómo escribir.
    def multiple_chunks(self, chunk_size=None):
        return True

    @property
    def size(self):
        return getattr(self.origen, "size", 0)


class AlmacenamientoCifrado(FileSystemStorage):
    """FileSystemStorage que cifra el contenido al guardar y descifra al abrir."""

    def _save(self, name, content):
        try:
            content.seek(0)
        except (AttributeError, OSError, ValueError):
            pass
        return super()._save(name, ArchivoCifrado(content))

    def _open(self, name, mode="rb"):
        from django.core.files.base import ContentFile
        return ContentFile(self.leer_descifrado(name), name=name)

    def leer_descifrado(self, name) -> bytes:
        """Los bytes descifrados, todos juntos.

        Sigue existiendo para lo que necesita el archivo completo (armar un
        PDF, una prueba). Para mandarlo al navegador está `pedazos_descifrados`,
        que no lo junta.
        """
        return b"".join(self.pedazos_descifrados(name))

    def pedazos_descifrados(self, name):
        """Va devolviendo el contenido descifrado de a bloques.

        Es lo que consume la vista de descarga: el archivo sale hacia el
        navegador mientras se descifra, sin quedar entero en memoria.
        """
        fernet = _get_fernet()
        archivo = super()._open(name, "rb")
        try:
            marca = archivo.read(len(CABECERA))
            if marca != CABECERA:
                # Formato viejo: el archivo entero es un solo token Fernet.
                yield fernet.decrypt(marca + archivo.read())
                return
            while True:
                medida = archivo.read(4)
                if not medida:
                    return
                if len(medida) != 4:
                    raise ValueError(
                        f"El documento '{name}' está cortado: le falta el final.")
                (largo,) = struct.unpack(">I", medida)
                if largo == 0 or largo > MAX_BLOQUE_CIFRADO:
                    raise ValueError(f"El documento '{name}' está dañado.")
                token = archivo.read(largo)
                if len(token) != largo:
                    raise ValueError(
                        f"El documento '{name}' está cortado: le falta el final.")
                yield fernet.decrypt(token)
        finally:
            archivo.close()


# Instancia única usada por el campo FileField del modelo Documento.
almacenamiento_documentos = AlmacenamientoCifrado()
