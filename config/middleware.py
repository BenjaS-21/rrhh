"""Cortes que conviene hacer antes de que la petición llegue a una vista."""

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


def _texto_mb(n):
    return f"{n / 1024 / 1024:.0f} MB"


class LimitarTamanoDeSubida:
    """Rechaza una subida demasiado grande sin llegar a guardarla.

    Django decide qué hacer con un archivo subido —RAM o temporal en disco—
    recién cuando alguien toca `request.FILES`, o sea dentro de la vista. Para
    entonces ya lo recibió entero. Con archivos de cientos de megas eso solo
    era memoria y disco gastados en algo que igual se iba a rechazar, y con dos
    subidas a la vez el servidor se quedaba sin aire y dejaba de responder.

    Acá se mira nada más el `Content-Length`, que viaja en el encabezado, así
    que la respuesta sale antes de leer un solo byte del cuerpo.

    Es la red de seguridad, no el aviso: el aviso lo da el navegador antes de
    empezar a subir (`subida.js`), que es donde de verdad se le ahorra el rato
    a la persona.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tope = getattr(settings, "SUBIDA_MAX_BYTES", 0)
        if tope and request.method in ("POST", "PUT", "PATCH"):
            try:
                largo = int(request.META.get("CONTENT_LENGTH") or 0)
            except (TypeError, ValueError):
                largo = 0
            if largo > tope:
                return self._negar(request, largo, tope)
        return self.get_response(request)

    def _negar(self, request, largo, tope):
        maximo = getattr(settings, "DOCUMENTOS_MAX_BYTES", tope)
        detalle = (f"Lo que mandaste pesa {_texto_mb(largo)} y el máximo por "
                   f"documento es {_texto_mb(maximo)}.")

        # El escáner y todo lo que va por HTMX esperan una respuesta, no una
        # página nueva: si se les manda un redirect, el error no se ve.
        espera_json = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or request.headers.get("HX-Request")
            or "application/json" in request.headers.get("Accept", "")
        )
        if espera_json:
            return JsonResponse({"ok": False, "error": detalle}, status=413)

        messages.error(request, f"No se subió el documento. {detalle}")
        # Se vuelve a la pantalla de donde salió, pero solo si es de este mismo
        # sistema: el `Referer` lo escribe quien manda la petición, así que
        # seguirlo a ciegas sería un salto a donde le convenga a un tercero.
        destino = request.headers.get("Referer") or "/"
        if not url_has_allowed_host_and_scheme(
                destino, allowed_hosts={request.get_host()},
                require_https=request.is_secure()):
            destino = "/"
        return redirect(destino)
