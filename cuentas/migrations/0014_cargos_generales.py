"""Un cargo general por nombre; los duplicados por tienda quedan particulares.

Los cargos nacieron por unidad organizativa (ALMACENISTA existe en decenas de
tiendas) y el desplegable del expediente los ofrecía todos: 800+ opciones con
el mismo nombre repetido. Desde acá, el desplegable ofrece solo los generales:
una fila por nombre.

La regla: por cada nombre, queda general la fila con más trabajadores
asignados (es la que mejor representa el dato) y, a igualdad, la más vieja.
Las demás quedan con `es_general=False`: SIGUEN EXISTIENDO, sus trabajadores
no se tocan y se pueden reactivar a mano desde Configuración. No se borra ni
se repunta nada.
"""

from django.db import migrations
from django.db.models import Count


def marcar_generales(apps, schema_editor):
    Cargo = apps.get_model("cuentas", "Cargo")
    por_nombre = {}
    for c in (Cargo.objects
              .annotate(cuantos=Count("trabajadores"))
              .order_by("nombre", "-cuantos", "pk")):
        if c.nombre not in por_nombre:
            por_nombre[c.nombre] = c.pk      # el primero: más usado, luego más viejo
    generales = set(por_nombre.values())
    Cargo.objects.exclude(pk__in=generales).update(es_general=False)


def nada(apps, schema_editor):
    # Volver atrás es simplemente marcar todo como general de nuevo.
    apps.get_model("cuentas", "Cargo").objects.update(es_general=True)


class Migration(migrations.Migration):

    dependencies = [
        ("cuentas", "0013_cargo_es_general"),
    ]

    operations = [
        migrations.RunPython(marcar_generales, nada),
    ]
