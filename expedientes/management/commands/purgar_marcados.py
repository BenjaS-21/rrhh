"""Manda a la papelera los documentos marcados a los que se les cumplio el plazo.

La lista de pendientes en Configuracion ya barre sola cada vez que se abre,
pero eso depende de que alguien la abra. Este comando corre en el arranque del
servidor (`iniciar.bat`) para que el plazo se cumpla aunque nadie entre.

Uso:
    python manage.py purgar_marcados
"""

from django.core.management.base import BaseCommand

from expedientes.purga import barrer


class Command(BaseCommand):
    help = "Manda a la papelera los documentos marcados con el plazo cumplido."

    def handle(self, *args, **options):
        cuantos = barrer()
        if not cuantos:
            self.stdout.write("No habia documentos marcados con el plazo cumplido.")
            return
        self.stdout.write(self.style.SUCCESS(
            f"{cuantos} documento/s marcado/s pasaron a la papelera."))
