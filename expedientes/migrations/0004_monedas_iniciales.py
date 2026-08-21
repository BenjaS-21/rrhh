"""Carga las monedas base y un concepto de pago inicial.

Se pueden editar, desactivar o ampliar desde Configuración → Monedas /
Conceptos de pago. La reversión solo borra los que no estén en uso.
"""

from django.db import migrations

# codigo, nombre, símbolo, es_nacional, orden
MONEDAS = [
    ("VES", "Bolívar", "Bs", True, 10),
    ("USD", "Dólar", "$", False, 20),
    ("EUR", "Euro", "€", False, 30),
]

CONCEPTOS = [
    ("Sueldo base", "SUELDO", 10),
]


def cargar(apps, schema_editor):
    Moneda = apps.get_model("expedientes", "Moneda")
    ConceptoPago = apps.get_model("expedientes", "ConceptoPago")

    for codigo, nombre, simbolo, nacional, orden in MONEDAS:
        Moneda.objects.get_or_create(
            codigo=codigo,
            defaults={
                "nombre": nombre, "simbolo": simbolo,
                "es_nacional": nacional, "orden": orden,
            },
        )

    for nombre, clase, orden in CONCEPTOS:
        ConceptoPago.objects.get_or_create(
            nombre=nombre, defaults={"clase": clase, "orden": orden},
        )


def revertir(apps, schema_editor):
    Moneda = apps.get_model("expedientes", "Moneda")
    ConceptoPago = apps.get_model("expedientes", "ConceptoPago")

    # Solo se borra lo que nadie esté usando, para no perder datos cargados.
    Moneda.objects.filter(
        codigo__in=[m[0] for m in MONEDAS], asignaciones__isnull=True
    ).delete()
    ConceptoPago.objects.filter(
        nombre__in=[c[0] for c in CONCEPTOS], asignaciones__isnull=True
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("expedientes", "0003_conceptopago_moneda_asignacionpago"),
    ]

    operations = [
        migrations.RunPython(cargar, revertir),
    ]
