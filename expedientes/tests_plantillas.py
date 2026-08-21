"""Ningún comentario de plantilla termina impreso en la pantalla.

Django solo reconoce `{# … #}` cuando abre y cierra en el mismo renglón. Si el
comentario sigue abajo, deja de ser comentario: se imprime tal cual, con las
llaves y todo, en medio de la página. Ya pasó dos veces —una en Configuración y
otra al pie del expediente— así que en vez de revisar pantalla por pantalla se
revisan todas las plantillas del proyecto de una sola vez.

Para comentarios de varios renglones está `{% comment %}`.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

CARPETA = Path(settings.BASE_DIR) / "templates"


def _abiertos_sin_cerrar(texto):
    """Renglones donde se abre un `{#` que no cierra ahí mismo."""
    sueltos = []
    for numero, renglon in enumerate(texto.splitlines(), start=1):
        for pos in (m.start() for m in re.finditer(r"\{#", renglon)):
            if "#}" not in renglon[pos:]:
                sueltos.append((numero, renglon.strip()))
    return sueltos


class LosComentariosNoSeVen(SimpleTestCase):

    def test_ninguna_plantilla_deja_un_comentario_abierto(self):
        plantillas = sorted(CARPETA.rglob("*.html"))
        self.assertGreater(len(plantillas), 10, "no se encontraron las plantillas")

        for plantilla in plantillas:
            sueltos = _abiertos_sin_cerrar(plantilla.read_text(encoding="utf-8"))
            with self.subTest(plantilla=plantilla.relative_to(CARPETA).as_posix()):
                self.assertEqual(
                    sueltos, [],
                    "un `{#` que no cierra en el mismo renglón se imprime en la "
                    "pantalla; usá `{% comment %}` … `{% endcomment %}`")

    def test_el_revisor_reconoce_uno_roto(self):
        """Testigo: sin esto, el test de arriba pasaría aunque no mirara nada."""
        roto = "<p>hola</p>\n{# esto sigue\n   en el renglón de abajo #}\n"
        self.assertEqual(_abiertos_sin_cerrar(roto), [(2, "{# esto sigue")])

        sano = "{# esto abre y cierra acá #}\n{% comment %}\nlargo\n{% endcomment %}\n"
        self.assertEqual(_abiertos_sin_cerrar(sano), [])
