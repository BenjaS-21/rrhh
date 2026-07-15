"""
Almacenamiento cifrado de documentos en reposo.

Los archivos se cifran con Fernet (AES-128 en modo CBC + HMAC) antes de
escribirse a disco y se descifran al leerlos. Así, aunque alguien acceda al
sistema de archivos del servidor, los documentos no son legibles sin la clave
(DOCUMENTOS_ENCRYPTION_KEY del .env).

Los archivos NUNCA se sirven directamente por el servidor web: siempre pasan
por una vista de descarga que valida permisos y descifra en memoria.
"""

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from cryptography.fernet import Fernet


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


class AlmacenamientoCifrado(FileSystemStorage):
    """FileSystemStorage que cifra el contenido al guardar y descifra al abrir."""

    def _save(self, name, content):
        datos = content.read()
        cifrado = _get_fernet().encrypt(datos)
        return super()._save(name, ContentFile(cifrado))

    def _open(self, name, mode="rb"):
        archivo = super()._open(name, "rb")
        try:
            descifrado = _get_fernet().decrypt(archivo.read())
        finally:
            archivo.close()
        return ContentFile(descifrado, name=name)

    def leer_descifrado(self, name) -> bytes:
        """Devuelve los bytes descifrados de un archivo. Uso en la vista de descarga."""
        archivo = super()._open(name, "rb")
        try:
            return _get_fernet().decrypt(archivo.read())
        finally:
            archivo.close()


# Instancia única usada por el campo FileField del modelo Documento.
almacenamiento_documentos = AlmacenamientoCifrado()
