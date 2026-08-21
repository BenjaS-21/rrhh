"""Utilidad para registrar acciones en la bitácora de auditoría."""

import ipaddress

from .models import RegistroAuditoria


def _direccion_valida(texto):
    """Devuelve el texto si es una IP de verdad; si no, None.

    La auditoría es prueba de quién hizo qué. Guardar lo que venga en una
    cabecera, sin mirarlo, permite escribir cualquier cosa en el registro.
    """
    try:
        return str(ipaddress.ip_address((texto or "").strip()))
    except ValueError:
        return None


def _es_de_confianza(direccion):
    """¿La petición llegó desde la misma máquina o desde la red interna?

    El túnel de Cloudflare corre en el mismo servidor y entrega a Django por
    127.0.0.1, así que solo en ese caso las cabeceras de reenvío las puso el
    túnel y no un desconocido.
    """
    ip = _direccion_valida(direccion)
    if ip is None:
        return False
    objeto = ipaddress.ip_address(ip)
    return objeto.is_loopback or objeto.is_private


def obtener_ip(request):
    """La IP de quien hizo la petición, sin creerle a cualquiera.

    `X-Forwarded-For` la escribe el cliente. Antes se tomaba siempre la primera
    entrada, así que mandando esa cabecera a mano se podía firmar cualquier
    acción con la IP que uno quisiera: la bitácora decía "192.168.1.7 borró el
    expediente" y era mentira.

    Ahora solo se le hace caso cuando la petición llegó desde la propia máquina
    o desde la red interna —o sea, cuando la puso el túnel—. Si llegó de afuera
    directo, vale la dirección real de la conexión y nada más.
    """
    remota = request.META.get("REMOTE_ADDR")
    if not _es_de_confianza(remota):
        return _direccion_valida(remota)

    # Cloudflare pone la IP real acá, ya limpia y sin lista de intermediarios.
    real = _direccion_valida(request.META.get("HTTP_CF_CONNECTING_IP"))
    if real:
        return real

    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    for parte in xff.split(","):
        candidata = _direccion_valida(parte)
        if candidata:
            return candidata

    return _direccion_valida(remota)


def registrar(request, accion, *, entidad="", objeto_id="", descripcion=""):
    """Crea un RegistroAuditoria a partir del request actual."""
    usuario = getattr(request, "user", None)
    if usuario is not None and not usuario.is_authenticated:
        usuario = None
    RegistroAuditoria.objects.create(
        usuario=usuario,
        usuario_texto=(usuario.get_username() if usuario else "anónimo"),
        accion=accion,
        entidad=entidad,
        objeto_id=str(objeto_id) if objeto_id else "",
        descripcion=descripcion[:400],
        ip=obtener_ip(request),
    )
