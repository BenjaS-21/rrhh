"""
Lógica central de permisos por rol y zona geográfica.

Regla de oro: TODA consulta de trabajadores/documentos se filtra con
`trabajadores_visibles(user)`. Nunca se expone un queryset sin filtrar.
"""

from django.core.exceptions import PermissionDenied

from configuracion.models import Preferencias

from .models import Trabajador


def ve_todo_el_pais(user) -> bool:
    """¿Este usuario alcanza todas las zonas?

    De fábrica, todos: el sistema no restringe por zona salvo que se prenda
    «Restringir cada usuario a su zona» en Configuración → Opciones del
    sistema. Con esa opción prendida, alcanzan todo el país el Administrador y
    quien tenga «acceso a todas las zonas».

    Lo que esto decide es qué VE cada uno. Lo que puede HACER no cambia: borrar
    sigue siendo solo del Administrador.
    """
    if user.alcance_nacional:
        return True
    if not Preferencias.obtener().restringir_por_zona:
        return True
    return False


def trabajadores_visibles(user):
    """Queryset de trabajadores que el usuario tiene permitido ver.

    De fábrica: todos, para todos. La restricción por zona existe pero viene
    apagada (ver `ve_todo_el_pais`); prendida, cada uno ve solo los de su zona.

    Tiene que devolver siempre lo mismo que `_tiendas_del_usuario` deja elegir:
    si no, alguien podría dar de alta a una persona en una tienda y después no
    encontrarla nunca más.
    """
    qs = Trabajador.objects.select_related("sede", "sede__zona")
    if ve_todo_el_pais(user):
        return qs
    if user.zona_id:
        return qs.filter(sede__zona_id=user.zona_id)
    return qs.none()


def puede_ver_trabajador(user, trabajador) -> bool:
    if ve_todo_el_pais(user):
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
        raise PermissionDenied("Solo el Administrador puede borrar.")


def exigir_borrar_del_expediente(user, trabajador):
    """Quitar algo de un expediente: solo el Administrador, y de un expediente
    que además tenga permitido ver.

    Existe como una sola función para que no se pueda olvidar ninguna de las dos
    mitades: chequear solo el rol dejaría a un administrador… bueno, es
    nacional; pero chequear solo la zona dejaría borrar a RRHH Interior.
    Los demás roles ven, agregan y editan, pero no quitan.
    """
    exigir_ver_trabajador(user, trabajador)
    exigir_borrar(user)


def puede_gestionar_pagos(user, trabajador) -> bool:
    """¿Puede ver y cargar la remuneración de este trabajador?

    Los montos son dato sensible: los ve el Administrador (alcance nacional) y
    RRHH Interior dentro de su zona. Solo lectura NO accede.
    """
    return user.puede_editar and puede_ver_trabajador(user, trabajador)


def exigir_gestionar_pagos(user, trabajador):
    if not puede_gestionar_pagos(user, trabajador):
        raise PermissionDenied("No tenés permiso para ver la remuneración de este expediente.")
