"""Los tipos de cédula que se usan en Venezuela, cargados de entrada.

Un catálogo vacío obliga a que alguien entre al admin antes de poder registrar
al primer trabajador. Estos cinco son los del país; el resto se agrega o se
desactiva desde el admin de Django.

Al revés se borran solo los que no esté usando nadie: si alguien ya cargó un
expediente con uno de estos, desandar la migración no puede llevárselo puesto.
"""

from django.db import migrations

TIPOS = [
    ("V", "Venezolano", 10),
    ("E", "Extranjero", 20),
    ("J", "Jurídico (RIF)", 30),
    ("P", "Pasaporte", 40),
    ("G", "Gubernamental", 50),
]


def cargar(apps, schema_editor):
    Tipo = apps.get_model("cuentas", "TipoDocumentoIdentidad")
    for codigo, nombre, orden in TIPOS:
        Tipo.objects.get_or_create(
            codigo=codigo, defaults={"nombre": nombre, "orden": orden})


def descargar(apps, schema_editor):
    Tipo = apps.get_model("cuentas", "TipoDocumentoIdentidad")
    Tipo.objects.filter(
        codigo__in=[c for c, _, _ in TIPOS], trabajadores__isnull=True
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cuentas", "0008_tipo_de_cedula"),
        # El borrado mira `trabajadores`, así que el campo tiene que existir.
        ("expedientes", "0012_tipo_de_cedula"),
    ]

    operations = [
        migrations.RunPython(cargar, descargar),
    ]
