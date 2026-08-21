"""Carga datos de demostración: zonas, sedes, tipos, usuarios y trabajadores.

Uso:
    python manage.py seed_demo

Crea usuarios de ejemplo (contraseña: Demo1234) para probar cada rol:
    admin_nacional   -> Administrador (acceso nacional)
    rrhh_norte       -> RRHH Interior, zona Norte
    lectura_sur      -> Solo lectura, zona Sur
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from cuentas.models import (
    Area, Cargo, Departamento, InvitacionRegistro, Sede, Zona,
)
from expedientes.models import TipoDocumento, Trabajador

Usuario = get_user_model()

TIPOS = [
    ("Documento de identidad", True, False, 10),
    ("Contrato de trabajo", True, False, 20),
    ("Constancia de CUIL", True, False, 30),
    ("Título / certificado de estudios", False, False, 40),
    ("Carnet de salud", True, True, 50),
    ("Certificado de antecedentes", False, True, 60),
    ("Alta temprana (AFIP)", False, False, 70),
    ("Otros", False, False, 100),
]

ZONAS = {
    "Central": ["Sede Central (Buenos Aires)"],
    "Norte": ["Salta", "Jujuy", "Tucumán"],
    "Sur": ["Neuquén", "Bariloche"],
}

TRABAJADORES = [
    ("30111222", "María", "Gómez", "Sede Central (Buenos Aires)", "Analista de RRHH", "Recursos Humanos"),
    ("28999888", "Juan", "Pérez", "Salta", "Vendedor", "Ventas"),
    ("31222333", "Lucía", "Fernández", "Tucumán", "Cajera", "Administración"),
    ("27888777", "Carlos", "Rodríguez", "Neuquén", "Supervisor", "Ventas"),
    ("33444555", "Ana", "Martínez", "Bariloche", "Administrativa", "Administración"),
]


class Command(BaseCommand):
    help = "Carga datos de demostración para probar el sistema."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Creando tipos de documento…")
        for nombre, obligatorio, vence, orden in TIPOS:
            TipoDocumento.objects.get_or_create(
                nombre=nombre,
                defaults={"obligatorio": obligatorio, "requiere_vencimiento": vence, "orden": orden},
            )

        self.stdout.write("Creando zonas y sedes…")
        sedes = {}
        for zona_nombre, lista_sedes in ZONAS.items():
            zona, _ = Zona.objects.get_or_create(nombre=zona_nombre)
            for sede_nombre in lista_sedes:
                sede, _ = Sede.objects.get_or_create(
                    nombre=sede_nombre, zona=zona,
                    defaults={"es_central": "Central" in sede_nombre},
                )
                sedes[sede_nombre] = sede

        self.stdout.write("Creando departamentos y áreas…")
        deptos = {}
        for nombre in ["Recursos Humanos", "Administración", "Ventas", "Sistemas"]:
            deptos[nombre], _ = Departamento.objects.get_or_create(nombre=nombre)

        areas_por_depto = {
            "Ventas": ["Piso de venta", "Caja", "Depósito"],
            "Recursos Humanos": ["Selección", "Liquidación de sueldos"],
            "Administración": ["Contaduría", "Compras"],
        }
        for depto_nombre, areas in areas_por_depto.items():
            for area_nombre in areas:
                Area.objects.get_or_create(nombre=area_nombre, departamento=deptos[depto_nombre])

        self.stdout.write("Creando usuarios de ejemplo…")
        zona_norte = Zona.objects.get(nombre="Norte")
        zona_sur = Zona.objects.get(nombre="Sur")
        rrhh = deptos["Recursos Humanos"]

        self._crear_usuario("admin_nacional", "Admin", "Nacional",
                            Usuario.Rol.ADMIN, None, rrhh, staff=True)
        self._crear_usuario("rrhh_norte", "RRHH", "Norte",
                            Usuario.Rol.RRHH_INTERIOR, zona_norte, rrhh)
        self._crear_usuario("lectura_sur", "Consulta", "Sur",
                            Usuario.Rol.SOLO_LECTURA, zona_sur, deptos["Administración"])

        self.stdout.write("Creando trabajadores…")
        for doc, nombres, apellidos, sede_nombre, puesto, depto in TRABAJADORES:
            # El cargo dejó de ser texto libre: se crea en el catálogo, dentro
            # de la unidad organizativa de la persona.
            unidad = deptos[depto]
            cargo, _ = Cargo.objects.get_or_create(nombre=puesto, departamento=unidad)
            trab, _ = Trabajador.objects.get_or_create(
                documento_identidad=doc,
                defaults={
                    "nombres": nombres, "apellidos": apellidos,
                    "sede": sedes[sede_nombre], "puesto": cargo,
                },
            )
            trab.departamento = unidad
            trab.save(update_fields=["departamento"])

        self.stdout.write("Creando invitaciones de ejemplo…")
        admin = Usuario.objects.filter(rol=Usuario.Rol.ADMIN).first()
        # Sin invitación de ADMIN a propósito. Estos links son válidos: quien
        # abra el que corresponde se crea una cuenta con ese rol, sin que nadie
        # lo apruebe. Una de administrador nacional, dejada abierta en un
        # servidor de verdad porque alguien corrió este comando de más, es una
        # llave maestra tirada en la puerta. Si hace falta probar el rol, se
        # genera desde Invitaciones y se anula después.
        ejemplos_inv = [
            (Usuario.Rol.RRHH_INTERIOR, zona_norte, "RRHH nuevo — zona Norte"),
            (Usuario.Rol.SOLO_LECTURA, zona_sur, "Consulta — zona Sur"),
        ]
        for rol, zona, nota in ejemplos_inv:
            InvitacionRegistro.objects.get_or_create(
                nota=nota, defaults={"rol": rol, "zona": zona, "creada_por": admin},
            )

        self.stdout.write(self.style.SUCCESS(
            "\n¡Datos demo cargados!\n"
            "Usuarios (contraseña: Demo1234):\n"
            "  admin_nacional  · Administrador (nacional)\n"
            "  rrhh_norte      · RRHH Interior, zona Norte\n"
            "  lectura_sur     · Solo lectura, zona Sur\n"
        ))

    def _crear_usuario(self, username, nombre, apellido, rol, zona, departamento=None, staff=False):
        usuario, creado = Usuario.objects.get_or_create(
            username=username,
            defaults={"first_name": nombre, "last_name": apellido},
        )
        # Idempotente: mantiene rol/zona/departamento al día en cada corrida.
        usuario.rol = rol
        usuario.zona = zona
        usuario.departamento = departamento
        usuario.is_staff = staff
        if creado:
            usuario.set_password("Demo1234")
        usuario.save()
