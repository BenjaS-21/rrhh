"""Deja el sistema limpio: conserva SOLO los usuarios administradores, borra el
resto de los datos y crea los departamentos base.

Uso:
    python manage.py resetear_datos            (pide confirmación)
    python manage.py resetear_datos --force    (sin preguntar)

Se CONSERVA:
    - Los usuarios administradores (superusuarios o rol ADMIN).

Se BORRA:
    - Trabajadores y sus documentos.
    - Invitaciones de registro.
    - Áreas, Tiendas (sedes), Zonas.
    - Tipos de documento.
    - Registros de auditoría.
    - Usuarios NO administradores.
    - Departamentos existentes (se recrean los de la lista de abajo).

Se CREA:
    - Los departamentos definidos en DEPARTAMENTOS.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from cuentas.models import Area, Departamento, Sede, Zona, InvitacionRegistro
from expedientes.models import Documento, RegistroAuditoria, TipoDocumento, Trabajador

Usuario = get_user_model()

# --- Editá esta lista con los departamentos que quieras crear ---------------
DEPARTAMENTOS = [
    "Recursos Humanos",
    "Administración",
    "Ventas",
    "Sistemas",
    "Logística",
    "Finanzas",
    "Marketing",
]


class Command(BaseCommand):
    help = ("Conserva solo los usuarios administradores, borra el resto de los "
            "datos y crea los departamentos base.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="No pedir confirmación (útil desde un .bat).",
        )

    def handle(self, *args, **options):
        admins = Usuario.objects.filter(Q(is_superuser=True) | Q(rol=Usuario.Rol.ADMIN))
        if not admins.exists():
            self.stderr.write(self.style.ERROR(
                "No hay ningún usuario administrador. Abortado para no dejarte sin acceso."
            ))
            return

        self.stdout.write(self.style.WARNING(
            "\nESTO BORRARÁ: trabajadores, documentos, invitaciones, áreas, tiendas, "
            "zonas, tipos de documento, auditoría y usuarios NO administradores.\n"
        ))
        self.stdout.write("Se conservarán estos administradores:")
        for a in admins:
            self.stdout.write(f"   - {a.username} ({a.get_rol_display()})")
        self.stdout.write("")

        if not options["force"]:
            resp = input("Escribí 'SI' (mayúsculas) para continuar: ")
            if resp.strip() != "SI":
                self.stdout.write(self.style.NOTICE("Cancelado. No se borró nada."))
                return

        admin_ids = list(admins.values_list("id", flat=True))

        with transaction.atomic():
            # Orden por dependencias (primero lo que apunta a otros).
            n_docs = Documento.objects.all().delete()[0]
            n_trab = Trabajador.objects.all().delete()[0]
            n_aud = RegistroAuditoria.objects.all().delete()[0]
            n_inv = InvitacionRegistro.objects.all().delete()[0]
            # Usuarios no administradores (antes de borrar zonas, que están PROTEGIDAS).
            n_users = Usuario.objects.exclude(id__in=admin_ids).delete()[0]
            # A los admins que queden les quitamos zona/departamento para poder borrarlos.
            Usuario.objects.filter(id__in=admin_ids).update(zona=None, departamento=None)
            n_area = Area.objects.all().delete()[0]
            n_sede = Sede.objects.all().delete()[0]
            n_zona = Zona.objects.all().delete()[0]
            n_tipo = TipoDocumento.objects.all().delete()[0]
            n_dep = Departamento.objects.all().delete()[0]

            # Crear los departamentos.
            creados = 0
            for nombre in DEPARTAMENTOS:
                _, nuevo = Departamento.objects.get_or_create(nombre=nombre)
                creados += 1 if nuevo else 0

        self.stdout.write(self.style.SUCCESS("\n¡Listo! Resumen:"))
        self.stdout.write(f"   Borrados -> documentos: {n_docs}, trabajadores: {n_trab}, "
                          f"invitaciones: {n_inv}, áreas: {n_area}, tiendas: {n_sede}, "
                          f"zonas: {n_zona}, tipos doc: {n_tipo}, auditoría: {n_aud}, "
                          f"usuarios no admin: {n_users}, departamentos previos: {n_dep}")
        self.stdout.write(f"   Departamentos creados: {creados}")
        self.stdout.write(f"   Administradores conservados: {len(admin_ids)}")
