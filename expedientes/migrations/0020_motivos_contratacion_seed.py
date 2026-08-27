"""Semilla del catálogo de motivos de contratación.

Son las temporadas que la base de datos de ingresos (el Excel de Gestión
Humana) usa en su columna «Motivo de contratación»: cada valor combinado que
aparece ahí ("Temporada Red Friday, Temporada Black Friday, ...") se arma con
estas doce. En orden de calendario, como el Excel las lista.
"""

from django.db import migrations


TEMPORADAS = [
    "Temporada Inventario Anual",
    "Temporada de Carnaval",
    "Temporada de Semana Santa",
    "Temporada Día del Trabajador",
    "Temporada Día de las Madres",
    "Temporada Día del Padre",
    "Temporada Día del Niño",
    "Temporada Felices Vacaciones",
    "Temporada Feliz Regreso a Clases",
    "Temporada Red Friday",
    "Temporada Black Friday",
    "Temporada Decembrina",
]


def sembrar(apps, schema_editor):
    MotivoContratacion = apps.get_model("expedientes", "MotivoContratacion")
    for orden, nombre in enumerate(TEMPORADAS, start=1):
        MotivoContratacion.objects.get_or_create(
            nombre=nombre, defaults={"orden": orden})


def arrancar(apps, schema_editor):
    MotivoContratacion = apps.get_model("expedientes", "MotivoContratacion")
    MotivoContratacion.objects.filter(nombre__in=TEMPORADAS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("expedientes", "0019_motivocontratacion"),
    ]

    operations = [
        migrations.RunPython(sembrar, arrancar),
    ]
