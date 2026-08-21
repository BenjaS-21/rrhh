"""Etiqueta `estatico`: como `static`, pero con la versión del archivo pegada.

Sin esto, el navegador se queda con la hoja de estilos vieja después de cada
cambio y hay que pedirle a cada usuario que apriete Ctrl+F5. Un cambio de CSS
que el navegador no vuelve a pedir se ve idéntico a un cambio que no se hizo.

La versión sale de la fecha de modificación del archivo: cambia sola cuando el
archivo cambia, y no cambia cuando no. No se cachea en memoria a propósito —un
`stat` por pantalla no se nota, y guardarlo traería de vuelta el problema que
esto viene a resolver, solo que del lado del servidor.
"""

import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def estatico(ruta):
    url = static(ruta)
    version = _version(ruta)
    return f"{url}?v={version}" if version else url


def _version(ruta):
    """Fecha de modificación en segundos, o cadena vacía si no se encuentra.

    Que falte la versión es preferible a que la pantalla no cargue.
    """
    absoluta = finders.find(ruta)
    if not absoluta:
        return ""
    try:
        return str(int(os.path.getmtime(absoluta)))
    except OSError:
        return ""
