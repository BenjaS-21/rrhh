"""Deja las 5 plantillas listas para la generación automática, en `plantillas/`.

Tres de los archivos ya traían los campos de combinación de Word y se copian
tal cual. Los otros dos tenían huecos con guiones bajos (`______`) en vez de
campos, así que acá se les insertan marcadores `{{CAMPO}}` en el lugar exacto.

Es idempotente: se puede volver a correr después de cambiar los originales.

Uso:
    python manage.py preparar_plantillas
    python manage.py preparar_plantillas --origen "C:\\ruta\\a\\los\\word"
"""

import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from expedientes.documentos import PLANTILLAS, _completar_raiz

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class Command(BaseCommand):
    help = "Copia y prepara las plantillas Word en la carpeta plantillas/."

    def add_arguments(self, parser):
        parser.add_argument(
            "--origen", default=None,
            help="Carpeta donde están los Word originales (por defecto, la raíz del proyecto).",
        )

    def handle(self, *args, **options):
        origen = Path(options["origen"] or settings.BASE_DIR)
        destino = Path(settings.PLANTILLAS_DIR)
        destino.mkdir(parents=True, exist_ok=True)

        for clave, meta in PLANTILLAS.items():
            archivo = self._buscar(origen, meta["origen"])
            if archivo is None:
                self.stderr.write(self.style.ERROR(
                    f"  {clave}: no encontré '{meta['origen']}' en {origen}"
                ))
                continue

            salida = destino / meta["archivo"]
            preparador = getattr(self, f"_preparar_{clave}", None)
            if preparador is None:
                shutil.copyfile(archivo, salida)
                self.stdout.write(f"  {clave}: copiada tal cual ({archivo.name})")
            else:
                cambios = preparador(archivo, salida)
                self.stdout.write(self.style.SUCCESS(
                    f"  {clave}: preparada con {cambios} marcador/es ({archivo.name})"
                ))

        self.stdout.write(self.style.SUCCESS(f"\nPlantillas listas en {destino}"))

    @staticmethod
    def _buscar(carpeta, nombre):
        """Busca el archivo tolerando acentos y numeración del nombre."""
        exacto = carpeta / nombre
        if exacto.exists():
            return exacto
        clave = re.sub(r"[^a-z0-9]", "", nombre.lower())[:14]
        for p in carpeta.iterdir():
            if p.suffix.lower() not in (".docx", ".rtf"):
                continue
            if re.sub(r"[^a-z0-9]", "", p.name.lower()).startswith(clave):
                return p
        return None

    @staticmethod
    def _abrir_docx(origen):
        """Devuelve (partes del zip, root de document.xml) con los prefijos ok."""
        with zipfile.ZipFile(origen) as z:
            partes = {n: z.read(n) for n in z.namelist()}
        xml = partes["word/document.xml"]
        for prefijo, uri in re.findall(
                r'xmlns:([A-Za-z0-9_]+)\s*=\s*"([^"]+)"',
                xml[:4000].decode("utf-8", "replace")):
            try:
                ET.register_namespace(prefijo, uri)
            except ValueError:
                pass
        return partes, ET.fromstring(xml)

    @staticmethod
    def _guardar_docx(partes, root, salida):
        # Se restaura la etiqueta raíz original: ElementTree descarta los xmlns
        # que ningún elemento usa y eso rompe mc:Ignorable (ver documentos.py).
        nuevo = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
        partes["word/document.xml"] = _completar_raiz(partes["word/document.xml"], nuevo)
        with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
            for nombre, datos in partes.items():
                z.writestr(nombre, datos)

    # -- Contrato: el salario estaba escrito fijo, no era un campo -----------
    def _preparar_contrato(self, origen, salida):
        partes, root = self._abrir_docx(origen)
        cambios = 0
        # "CIENTO TREINTA BOLÍVARES CON 00/100 CÉNTIMOS (Bs.130,00)" -> marcador,
        # para que el monto salga de la Remuneración del expediente.
        patron = re.compile(r"[A-ZÁÉÍÓÚÑ ]*BOL[IÍ]VARES\s+CON\s+\d+/100\s+C[EÉ]NTIMOS"
                            r"\s*\(Bs\.[\d.,]+\)", re.IGNORECASE)
        for t in root.iter(W + "t"):
            if t.text and patron.search(t.text):
                t.text = patron.sub("{{SALARIO_TEXTO}}", t.text)
                cambios += 1
        self._guardar_docx(partes, root, salida)
        return cambios

    # -- Acta de beneficios: tenía huecos "______" en vez de campos ----------
    def _preparar_beneficios(self, origen, salida):
        partes, root = self._abrir_docx(origen)
        cambios = 0
        pendientes = ["{{APELLIDO_Y_NOMBRE}}", "{{CARGO}}"]
        for t in root.iter(W + "t"):
            texto = t.text or ""

            # Hueco de guiones bajos -> marcador (el primero es el nombre,
            # el segundo el cargo; el resto se limpia).
            if re.fullmatch(r"\s*_{6,}\s*", texto):
                t.text = pendientes.pop(0) if pendientes else ""
                cambios += 1
                continue
            if "_" * 6 in texto:
                marcador = pendientes.pop(0) if pendientes else ""
                t.text = re.sub(r"_{6,}", marcador, texto, count=1)
                t.text = re.sub(r"_{6,}", "", t.text)
                cambios += 1
                continue

            # "...identidad número V-, quien..." -> le falta el número.
            if "V-," in texto and "identidad" in texto:
                t.text = texto.replace("V-,", "V-{{CEDULA}},")
                cambios += 1

        self._guardar_docx(partes, root, salida)
        return cambios

    # -- Acta de emisión de recibos: es RTF y le falta la cédula -------------
    def _preparar_recibo(self, origen, salida):
        """Los huecos largos de guiones bajos, en orden de aparición:

        1. el renglón que quedaba al lado del campo del nombre  -> se elimina
        2. el de la cédula                                      -> marcador

        Los demás (más cortos) son el bloque de firma y la fecha, y se dejan
        en blanco a propósito para completarlos a mano al firmar.

        No se puede buscar por el texto que los rodea porque en RTF esa frase
        queda partida en varios grupos; por eso se ubican por orden y largo.
        En RTF las llaves delimitan grupos, así que el marcador es @@CAMPO@@.
        """
        texto = origen.read_text(encoding="latin-1", errors="replace")
        pendientes = ["", "@@CEDULA@@"]
        cambios = 0

        def _sub(m):
            nonlocal cambios
            if not pendientes:
                return m.group(0)
            cambios += 1
            return pendientes.pop(0)

        texto = re.sub(r"_{20,}", _sub, texto)
        salida.write_text(texto, encoding="latin-1", errors="replace")
        return cambios
