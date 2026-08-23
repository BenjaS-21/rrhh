"""Borra los "CARACAS" que puso el valor por omision, no una persona.

`ciudad_firma` venia con `default="CARACAS"`, asi que TODO expediente nacia
diciendo Caracas se firmara donde se firmara. Ahora el campo vacio significa
"la ciudad de la tienda", que es lo que corresponde casi siempre; los valores
heredados taparian esa cadena y seguirian imprimiendo Caracas.

Se limpia solo lo que coincide exactamente con el viejo valor por omision. Si
alguien escribio otra ciudad a mano, se respeta.

Al reves no se puede desandar: no hay forma de distinguir el que se escribio a
proposito del que puso el sistema. Por eso el reverso no hace nada, en vez de
volver a poner CARACAS en expedientes donde nadie lo eligio.
"""

from django.db import migrations

HEREDADO = "CARACAS"


def limpiar(apps, schema_editor):
    Datos = apps.get_model("expedientes", "DatosContratacion")
    Datos.objects.filter(ciudad_firma=HEREDADO).update(ciudad_firma="")


def no_se_desanda(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("expedientes", "0014_ciudad_de_la_tienda"),
    ]

    operations = [
        migrations.RunPython(limpiar, no_se_desanda),
    ]
