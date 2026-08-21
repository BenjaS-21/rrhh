"""Datos que toda plantilla necesita tener a mano."""

from django.conf import settings


def sistema(request):
    """Nombre del sistema, corto y largo.

    Las plantillas usan `{{ sistema }}` en las pestañas y `{{ sistema_largo }}`
    donde hay lugar para el nombre completo.
    """
    return {
        "sistema": settings.NOMBRE_SISTEMA,
        "sistema_largo": settings.NOMBRE_SISTEMA_LARGO,
    }
