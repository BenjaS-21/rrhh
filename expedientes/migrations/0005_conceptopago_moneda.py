"""Cada concepto de pago pasa a tener su moneda (Bs, $, €).

A los conceptos que ya existían se les asigna la moneda nacional, que es la
suposición más segura; se puede corregir desde Configuración → Conceptos de pago.
"""

import django.db.models.deletion
from django.db import migrations, models


def asignar_moneda(apps, schema_editor):
    Moneda = apps.get_model("expedientes", "Moneda")
    ConceptoPago = apps.get_model("expedientes", "ConceptoPago")

    nacional = Moneda.objects.filter(es_nacional=True).first() or Moneda.objects.first()
    if nacional is None:
        # Sin monedas cargadas no hay conceptos posibles; nada que migrar.
        return
    ConceptoPago.objects.filter(moneda__isnull=True).update(moneda=nacional)


class Migration(migrations.Migration):

    dependencies = [
        ("expedientes", "0004_monedas_iniciales"),
    ]

    operations = [
        # 1) Se agrega admitiendo nulos, para no romper las filas existentes.
        migrations.AddField(
            model_name="conceptopago",
            name="moneda",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="conceptos",
                to="expedientes.moneda",
            ),
        ),
        # 2) Se completan las filas viejas.
        migrations.RunPython(asignar_moneda, migrations.RunPython.noop),
        # 3) Ya con datos, pasa a ser obligatoria.
        migrations.AlterField(
            model_name="conceptopago",
            name="moneda",
            field=models.ForeignKey(
                help_text="Moneda en la que se paga este concepto. Se propone sola al "
                          "cargarlo en un expediente y ahí se puede cambiar si hace falta.",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="conceptos",
                to="expedientes.moneda",
            ),
        ),
    ]
