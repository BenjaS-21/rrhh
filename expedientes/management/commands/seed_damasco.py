"""Carga los datos maestros de Damasco: tiendas, unidades organizativas y cargos.

Uso:
    python manage.py seed_damasco            (carga / actualiza)
    python manage.py seed_damasco --limpiar  (además desactiva lo que sobra)

Es idempotente: se puede correr las veces que haga falta. Lo que ya existe se
actualiza (la dirección de una tienda, por ejemplo) y lo que falta se crea.
NUNCA borra trabajadores, documentos ni montos de remuneración.

Con `--limpiar` desactiva —no borra— las tiendas, unidades y cargos que están
en el sistema pero no en las planillas. Se desactivan en vez de borrarse porque
puede haber trabajadores apuntando a ellos.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from cuentas.models import Cargo, Departamento, Sede, Zona

from ._datos_damasco import (
    ALIAS_DE_ESTADO, NO_SON_TIENDA, ORGANIGRAMA, SEDE_CENTRAL, TIENDAS,
)


class Command(BaseCommand):
    help = "Carga tiendas, unidades organizativas y cargos de Damasco."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limpiar", action="store_true",
            help="Desactiva las tiendas, unidades y cargos que no estén en las "
                 "planillas. No borra nada.",
        )

    @transaction.atomic
    def handle(self, *args, **opciones):
        resumen = {}
        resumen.update(self._cargar_tiendas())
        resumen.update(self._cargar_organigrama())
        if opciones["limpiar"]:
            resumen.update(self._desactivar_sobrantes())

        self._informar(resumen)

    # --- Tiendas ------------------------------------------------------------
    def _cargar_tiendas(self):
        self.stdout.write("Cargando estados y tiendas…")
        zonas, sedes_nuevas, sedes_actualizadas = {}, 0, 0

        for estado_crudo, nombre, direccion in TIENDAS:
            estado = ALIAS_DE_ESTADO.get(estado_crudo, estado_crudo)
            zona = zonas.get(estado)
            if zona is None:
                zona, _ = Zona.objects.get_or_create(
                    nombre=estado, defaults={"descripcion": "Estado de Venezuela."},
                )
                if not zona.activa:
                    zona.activa = True
                    zona.save(update_fields=["activa"])
                zonas[estado] = zona

            sede, creada = Sede.objects.get_or_create(
                nombre=nombre, zona=zona,
                defaults={
                    "direccion": direccion,
                    "es_central": nombre == SEDE_CENTRAL,
                    "activa": True,
                },
            )
            if creada:
                sedes_nuevas += 1
                continue

            # Ya existía: se actualiza la dirección, que es lo que va al contrato.
            cambios = []
            if sede.direccion != direccion:
                sede.direccion = direccion
                cambios.append("direccion")
            if not sede.activa:
                sede.activa = True
                cambios.append("activa")
            if sede.es_central != (nombre == SEDE_CENTRAL):
                sede.es_central = nombre == SEDE_CENTRAL
                cambios.append("es_central")
            if cambios:
                sede.save(update_fields=cambios)
                sedes_actualizadas += 1

        return {
            "zonas": len(zonas),
            "sedes_nuevas": sedes_nuevas,
            "sedes_actualizadas": sedes_actualizadas,
        }

    # --- Unidades organizativas y cargos ------------------------------------
    def _cargar_organigrama(self):
        self.stdout.write("Cargando unidades organizativas y cargos…")
        unidades_nuevas = cargos_nuevos = cargos_reactivados = 0

        for unidad, cargos in ORGANIGRAMA.items():
            depto, creada = Departamento.objects.get_or_create(nombre=unidad)
            if creada:
                unidades_nuevas += 1
            elif not depto.activo:
                depto.activo = True
                depto.save(update_fields=["activo"])

            existentes = {c.nombre: c for c in depto.cargos.all()}
            for nombre in cargos:
                cargo = existentes.get(nombre)
                if cargo is None:
                    Cargo.objects.create(nombre=nombre, departamento=depto)
                    cargos_nuevos += 1
                elif not cargo.activo:
                    cargo.activo = True
                    cargo.save(update_fields=["activo"])
                    cargos_reactivados += 1

        return {
            "unidades": len(ORGANIGRAMA),
            "unidades_nuevas": unidades_nuevas,
            "cargos_nuevos": cargos_nuevos,
            "cargos_reactivados": cargos_reactivados,
        }

    # --- Limpieza opcional ---------------------------------------------------
    def _desactivar_sobrantes(self):
        """Apaga lo que no está en las planillas. No borra: puede tener gente."""
        self.stdout.write("Desactivando lo que no está en las planillas…")

        de_planilla = {(ALIAS_DE_ESTADO.get(e, e), n) for e, n, _ in TIENDAS}
        sedes = 0
        for sede in Sede.objects.filter(activa=True).select_related("zona"):
            if (sede.zona.nombre, sede.nombre) not in de_planilla:
                sede.activa = False
                sede.save(update_fields=["activa"])
                sedes += 1

        unidades = cargos = 0
        for depto in Departamento.objects.filter(activo=True).prefetch_related("cargos"):
            esperados = ORGANIGRAMA.get(depto.nombre)
            if esperados is None:
                depto.activo = False
                depto.save(update_fields=["activo"])
                unidades += 1
                continue
            for cargo in depto.cargos.filter(activo=True):
                if cargo.nombre not in esperados:
                    cargo.activo = False
                    cargo.save(update_fields=["activo"])
                    cargos += 1

        return {"sedes_desactivadas": sedes, "unidades_desactivadas": unidades,
                "cargos_desactivados": cargos}

    # --- Salida --------------------------------------------------------------
    def _informar(self, r):
        ok = self.style.SUCCESS
        self.stdout.write("")
        self.stdout.write(ok("Listo."))
        self.stdout.write(
            f"  Estados (zonas):        {r['zonas']}\n"
            f"  Tiendas nuevas:         {r['sedes_nuevas']}\n"
            f"  Tiendas actualizadas:   {r['sedes_actualizadas']}\n"
            f"  Unidades organizativas: {r['unidades']} "
            f"({r['unidades_nuevas']} nuevas)\n"
            f"  Cargos nuevos:          {r['cargos_nuevos']}\n"
            f"  Cargos reactivados:     {r['cargos_reactivados']}"
        )
        if "sedes_desactivadas" in r:
            self.stdout.write(
                f"  Desactivados: {r['sedes_desactivadas']} tiendas, "
                f"{r['unidades_desactivadas']} unidades, "
                f"{r['cargos_desactivados']} cargos"
            )

        self._advertencias()

    def _advertencias(self):
        """Cosas de las planillas que conviene que RRHH revise."""
        avisos = []

        if ALIAS_DE_ESTADO:
            pares = ", ".join(f"'{a}' -> '{b}'" for a, b in ALIAS_DE_ESTADO.items())
            avisos.append(
                f"Estados escritos de dos formas, unificados: {pares}. "
                "Si fueran zonas distintas, avisá y las separo."
            )

        # Las dos planillas nombran las tiendas distinto. No se cruzan solas y
        # NO se adivina la equivalencia: decidirla es de RRHH, no del sistema.
        # Esto no bloquea nada (tienda y unidad son campos independientes), pero
        # obliga a saber de memoria que la tienda "MARACAY" es la unidad
        # "TIENDA DAMASCO MARACAY I".
        unidades_tienda = {
            u[len("TIENDA DAMASCO "):] for u in ORGANIGRAMA
            if u.startswith("TIENDA DAMASCO ")
        }
        nombres_tienda = {n for _, n, _ in TIENDAS if n not in NO_SON_TIENDA}

        solo_direcciones = sorted(nombres_tienda - unidades_tienda)
        solo_cargos = sorted(unidades_tienda - nombres_tienda)

        if solo_direcciones or solo_cargos:
            avisos.append(
                f"Las dos planillas usan nombres distintos: {len(solo_direcciones)} "
                f"tiendas de la lista de direcciones no tienen una unidad con el "
                f"mismo nombre, y {len(solo_cargos)} unidades de tienda no tienen "
                "una tienda con el mismo nombre. Varias parecen la misma "
                "(MUEBLERIA/CATIA MUEBLERIA, SABANA GARANDE/SABANA GRANDE, "
                "MARACAY/MARACAY I, SAN MARTIN 1/SAN MARTIN I). No las uní por "
                "mi cuenta: decidí vos la equivalencia y te unifico las listas."
            )
            avisos.append(f"  Solo en direcciones: {', '.join(solo_direcciones)}")
            avisos.append(f"  Solo en cargos:     {', '.join(solo_cargos)}")

        # Erratas evidentes en el nombre de la tienda, que es lo que se imprime
        # en el contrato. Se cargan tal cual vinieron; corregirlas es decisión
        # de RRHH porque son sus nombres oficiales.
        sospechosas = [n for _, n, _ in TIENDAS if n in {"SABANA GARANDE", "MERIDAD"}]
        if sospechosas:
            avisos.append(
                f"Nombres que parecen erratas y quedaron tal cual: "
                f"{', '.join(sospechosas)}. Salen así en los contratos."
            )

        if not avisos:
            return
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Para revisar:"))
        for a in avisos:
            prefijo = "  " if a.startswith("  ") else "  - "
            self.stdout.write(self.style.WARNING(f"{prefijo}{a.strip()}"))
