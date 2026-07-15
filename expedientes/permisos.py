"""
Lógica central de permisos por rol y zona geográfica.

Regla de oro: TODA consulta de trabajadores/documentos se filtra con
`trabajadores_visibles(user)`. Nunca se expone un queryset sin filtrar.
"""

from django.core.exceptions import PermissionDenied

from .models import Trabajador


def trabajadores_visibles(user):
    """Queryset de trabajadores que el usuario tiene permitido ver.

    - Admin / superuser: todos (alcance nacional).
    - RRHH Interior / Solo lectura: solo los de su zona asignada.
    - Sin zona asignada (y no admin): ninguno.
    """
    qs = Trabajador.objects.select_related("sede", "sede__zona")
    if user.es_admin:
        return qs
    if user.zona_id:
        return qs.filter(sede__zona_id=user.zona_id)
    return qs.none()


def puede_ver_trabajador(user, trabajador) -> bool:
    if user.es_admin:
        return True
    return bool(user.zona_id) and trabajador.sede.zona_id == user.zona_id


def exigir_ver_trabajador(user, trabajador):
    if not puede_ver_trabajador(user, trabajador):
        raise PermissionDenied("No tenés permiso para ver este expediente.")


def exigir_editar_trabajador(user, trabajador):
    """Puede editar/subir si puede ver Y tiene rol de edición."""
    exigir_ver_trabajador(user, trabajador)
    if not user.puede_editar:
        raise PermissionDenied("Tu rol es de solo lectura.")


def exigir_borrar(user):
    if not user.puede_borrar:
        raise PermissionDenied("Solo el Administrador puede enviar a papelera o restaurar.")
