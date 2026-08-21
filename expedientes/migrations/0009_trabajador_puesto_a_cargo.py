"""El cargo del trabajador pasa de texto libre a una entrada del catálogo.

No se hace un AlterField directo de CharField a ForeignKey: eso intentaría
interpretar el texto como un id y dejaría a todos los trabajadores sin cargo.
Se hace en cuatro pasos, conservando lo que ya estaba escrito a mano.
"""

from django.db import migrations, models
import django.db.models.deletion

# Los cargos escritos a mano no tienen unidad organizativa. En vez de perderlos
# o inventarles una, se agrupan acá para que RRHH los reubique.
UNIDAD_HUERFANA = "SIN UNIDAD ASIGNADA"


def texto_a_catalogo(apps, schema_editor):
    Trabajador = apps.get_model("expedientes", "Trabajador")
    Departamento = apps.get_model("cuentas", "Departamento")
    Cargo = apps.get_model("cuentas", "Cargo")

    pendientes = Trabajador.objects.exclude(puesto_texto="").exclude(
        puesto_texto__isnull=True
    )
    if not pendientes.exists():
        return

    huerfana = None
    for t in pendientes:
        nombre = (t.puesto_texto or "").strip()
        if not nombre:
            continue
        # Si ya existe ese cargo en la unidad del trabajador, se reusa.
        cargo = None
        if t.departamento_id:
            cargo = Cargo.objects.filter(
                nombre=nombre, departamento_id=t.departamento_id
            ).first()
        if cargo is None:
            if huerfana is None:
                huerfana, _ = Departamento.objects.get_or_create(
                    nombre=UNIDAD_HUERFANA,
                    defaults={"descripcion": "Cargos que venían escritos a mano."},
                )
            destino = t.departamento_id or huerfana.pk
            cargo, _ = Cargo.objects.get_or_create(
                nombre=nombre, departamento_id=destino
            )
        t.puesto = cargo
        t.save(update_fields=["puesto"])


def catalogo_a_texto(apps, schema_editor):
    Trabajador = apps.get_model("expedientes", "Trabajador")
    for t in Trabajador.objects.exclude(puesto__isnull=True).select_related("puesto"):
        t.puesto_texto = t.puesto.nombre[:120]
        t.save(update_fields=["puesto_texto"])


class Migration(migrations.Migration):

    dependencies = [
        ("cuentas", "0005_cargo"),
        ("expedientes", "0008_datoscontratacion_talla_camisa_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="trabajador", old_name="puesto", new_name="puesto_texto",
        ),
        migrations.AddField(
            model_name="trabajador",
            name="puesto",
            field=models.ForeignKey(
                blank=True, null=True,
                help_text="Se elige de los cargos de la unidad organizativa.",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="trabajadores", to="cuentas.cargo",
                verbose_name="cargo",
            ),
        ),
        migrations.RunPython(texto_a_catalogo, catalogo_a_texto),
        migrations.RemoveField(model_name="trabajador", name="puesto_texto"),
    ]
