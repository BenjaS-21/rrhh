"""Utilidad para registrar acciones en la bitácora de auditoría."""

from .models import RegistroAuditoria


def obtener_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


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
