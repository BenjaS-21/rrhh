"""El barrido de los documentos marcados para eliminar.

Quien sube un archivo es quien se da cuenta en el momento de que subió el que
no era. Pero borrar es del Administrador, así que hasta ahora el documento
equivocado se quedaba en el expediente hasta que alguien más lo mirara. Ahora
se marca, y la marca aparece en una lista en Configuración.

De esa lista salen por dos caminos: alguien aprieta «Eliminar», o se cumple el
plazo que puso el Administrador y se van solos.

Dos decisiones que conviene tener a la vista:

**Se van a la papelera, no se destruyen.** Un barrido por tiempo que borrara de
verdad sería un borrado sin nadie mirando: si alguien marca mal y nadie
revisa la lista a tiempo, el archivo no vuelve. A la papelera vuelve.

**Sin plazo no se barre nada.** El valor de fábrica es 0, y entonces la lista
es una bandeja de pendientes que espera a una persona. Poner un plazo es una
decisión del Administrador, no algo que empiece a pasar solo.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from configuracion.models import Preferencias

from .models import Documento, RegistroAuditoria


def pendientes():
    """Los documentos marcados que todavía están en el expediente.

    Los que ya fueron a la papelera quedan afuera: la lista es de cosas por
    resolver, y uno ya resuelto que siguiera apareciendo se volvería a
    «eliminar» una y otra vez.
    """
    return (Documento.objects
            .filter(marcado_en__isnull=False, activo=True)
            .select_related("trabajador", "trabajador__sede", "tipo",
                            "marcado_por")
            .order_by("marcado_en"))


def vencidos(ahora=None):
    """Los pendientes a los que ya se les cumplió el plazo."""
    dias = Preferencias.obtener().dias_para_eliminar_marcados
    if not dias:
        return Documento.objects.none()
    limite = (ahora or timezone.now()) - timedelta(days=dias)
    return pendientes().filter(marcado_en__lte=limite)


def barrer(ahora=None) -> int:
    """Manda a la papelera los que vencieron. Devuelve cuántos.

    Se llama sola cada vez que se abre la lista de pendientes, y también desde
    `manage.py purgar_marcados` para el arranque del servidor. Que corra de más
    no hace daño: la segunda pasada no encuentra nada porque los de la primera
    ya no están activos.
    """
    documentos = list(vencidos(ahora))
    if not documentos:
        return 0

    with transaction.atomic():
        for doc in documentos:
            doc.activo = False
            doc.save(update_fields=["activo"])
            # Queda asentado a nombre del sistema y no de quien abrió la
            # pantalla: no lo borró esa persona, se cumplió un plazo.
            RegistroAuditoria.objects.create(
                usuario=None,
                usuario_texto="sistema",
                accion=RegistroAuditoria.Accion.BORRAR,
                entidad="Documento",
                objeto_id=str(doc.pk),
                descripcion=(
                    f"Papelera automática: '{doc.tipo}' de {doc.trabajador}, "
                    f"marcado por {_quien(doc)} el "
                    f"{timezone.localtime(doc.marcado_en):%d/%m/%Y}"
                )[:400],
                ip=None,
            )
    return len(documentos)


def _quien(doc):
    if not doc.marcado_por:
        return "un usuario dado de baja"
    return doc.marcado_por.get_full_name() or doc.marcado_por.get_username()
