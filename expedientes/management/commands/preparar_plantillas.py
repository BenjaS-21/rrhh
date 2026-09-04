"""Deja las plantillas Word listas para la generación automática, en `plantillas/`.

Algunos archivos ya traían los campos de combinación de Word y se copian tal
cual. Otros tenían huecos con guiones bajos (`______`) en vez de campos, o
datos de una persona real escritos a mano, así que acá se les insertan
marcadores `{{CAMPO}}` en el lugar exacto.

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

from expedientes.documentos import (MESES, PLANTILLAS, _completar_raiz,
                                    normalizar_campo)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Cédula del representante legal de la empresa. Está escrita en las plantillas
# (no es un campo: no depende del trabajador) y venía sin la letra.
CEDULA_DEL_EMPLEADOR = "17158865"

# Los nombres con que las plantillas llaman al campo de la cédula del
# trabajador. Ya viene con su letra ("V-26045681", "E-84512233").
CAMPOS_DE_CEDULA = ("cedula", "columna1")


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
            archivo, descartados = self._buscar(origen, meta["origen"])
            if archivo is None:
                self.stderr.write(self.style.ERROR(
                    f"  {clave}: no encontré '{meta['origen']}' en {origen}"
                ))
                continue
            if descartados:
                self.stderr.write(self.style.WARNING(
                    f"  {clave}: hay más de un original que sirve. Uso "
                    f"'{archivo.name}' y dejo afuera "
                    + ", ".join(f"'{d.name}'" for d in descartados)
                    + ". Si el bueno es uno de ésos, borrá el otro y volvé a "
                      "correr esto."
                ))

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
        """Busca el original tolerando acentos y numeración del nombre.

        Devuelve `(elegido, descartados)`.

        La búsqueda es por prefijo porque Gestión Humana manda las revisiones
        con el nombre cambiado: la misma lista de verificación llegó una vez
        como «... 20072026.pdf» y otra como «... 20072026 AGOSTO.pdf».

        El precio de esa tolerancia es que si la revisión queda AL LADO de la
        vieja en la carpeta, el nombre exacto gana y la nueva se ignora sin
        decir una palabra. Un formulario legal desactualizado que sale igual de
        bien es peor que uno que falla: por eso los descartados se devuelven y
        quien prepara las plantillas se entera y decide.
        """
        clave = re.sub(r"[^a-z0-9]", "", nombre.lower())[:14]
        candidatos = []
        for p in sorted(carpeta.iterdir()):
            # El .pdf es la lista de verificación, que no vino en Word.
            if p.suffix.lower() not in (".docx", ".rtf", ".pdf"):
                continue
            if re.sub(r"[^a-z0-9]", "", p.name.lower()).startswith(clave):
                candidatos.append(p)
        if not candidatos:
            return None, []
        exacto = carpeta / nombre
        elegido = exacto if exacto in candidatos else candidatos[0]
        return elegido, [p for p in candidatos if p != elegido]

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
        cambios += self._separar_domicilio_legal(root)
        cambios += self._no_partir_las_firmas(root)
        cambios += self._cedula_del_empleador(root)
        cambios += self._una_sola_letra_en_la_cedula(root)
        cambios += self._fecha_del_cierre_del_contrato(root)
        self._guardar_docx(partes, root, salida)
        return cambios

    # -- La cédula del representante legal lleva su letra -------------------
    @staticmethod
    def _cedula_del_empleador(root):
        """Le pone la «V-» a la cédula del representante legal de la empresa.

        Reporte: «en el número de cédula del jefe falta la V-». La del
        trabajador sale del expediente y ya viene con la letra; la del
        empleador está escrita en la plantilla y venía pelada, así que el
        mismo contrato mostraba una con letra y la otra sin, una al lado de la
        otra en el bloque de firmas.

        Cuidado con la trampa: en el mismo párrafo del cuerpo está el RIF de
        la empresa, «V-17158865-7», que ya tiene su letra y su dígito
        verificador. Un reemplazo a lo bruto lo dejaría en «V-V-17158865-7».
        De ahí el `(?<!V-)`.

        El acuerdo de confidencialidad ya la trae bien («Nro. V-17.158.865») y
        no se toca: el paso es idempotente.
        """
        pelada = re.compile(r"(?<!V-)(?<!\d)" + CEDULA_DEL_EMPLEADOR)
        # "Nro.17158865" venía sin el espacio, y con la letra delante se lee
        # peor todavía: "Nro.V-17158865". A veces el "Nro." está en el mismo
        # run que el número y a veces en el anterior; se cubren los dos.
        sin_espacio = re.compile("Nro[.](?=" + CEDULA_DEL_EMPLEADOR + ")")
        cambios = 0
        for parrafo in root.iter(W + "p"):
            anterior = None
            for t in parrafo.iter(W + "t"):
                texto = t.text or ""
                if CEDULA_DEL_EMPLEADOR in texto and pelada.search(texto):
                    texto = sin_espacio.sub("Nro. ", texto)
                    t.text = pelada.sub("V-" + CEDULA_DEL_EMPLEADOR, texto)
                    if anterior is not None and (anterior.text or "").endswith("Nro."):
                        anterior.text += " "
                    cambios += 1
                if t.text:
                    anterior = t
        return cambios

    # -- La cédula del trabajador ya trae su letra --------------------------
    @staticmethod
    def _una_sola_letra_en_la_cedula(root):
        """Saca la «V-» que las plantillas traen escrita antes del campo Cédula.

        `Cedula` sale de `cedula_completa`, que ya devuelve «V-26045681» con su
        letra: vive en un solo lugar justamente para que no se arme distinta en
        cada documento. Pero dos plantillas traían además una «V-» escrita a
        mano delante del campo, así que el documento decía «V-V-26045681».

        No lo reportó nadie: apareció al escribir la prueba de la cédula del
        empleador. El contrato corporativo ya tenía este arreglo hecho a
        medida; acá se generaliza, porque el acta de beneficios y el acuerdo de
        confidencialidad lo traían igual y nadie lo había visto.

        Y hay un caso peor que el doble: el tipo de documento es configurable
        (V, E, J, P, G). Con la «V-» escrita en la plantilla, un extranjero
        salía «V-E-12345678» —una cédula que no es la suya—.

        Vienen de dos formas: pegada al marcador en el mismo run
        («número V-{{CEDULA}}») o en dos runs sueltos, «V» y «-», justo antes
        del campo de combinación.
        """
        cambios = 0

        # Forma 1: "V-{{CEDULA}}" en el mismo run.
        pegada = re.compile(r"[VvEeJjPpGg]\s*[-–]\s*(?=\{\{CEDULA\}\})")
        for t in root.iter(W + "t"):
            if t.text and "{{CEDULA}}" in t.text and pegada.search(t.text):
                t.text = pegada.sub("", t.text)
                cambios += 1

        # Forma 2: runs sueltos antes de un MERGEFIELD de cédula.
        for parrafo in root.iter(W + "p"):
            runs = parrafo.findall(W + "r")
            for numero, run in enumerate(runs):
                instruccion = "".join(i.text or "" for i in run.iter(W + "instrText"))
                if not instruccion:
                    continue
                campo = normalizar_campo(instruccion.replace("MERGEFIELD", ""))
                if campo not in CAMPOS_DE_CEDULA:
                    continue
                cambios += Command._borrar_letra_previa(runs[:numero])
        return cambios

    @staticmethod
    def _borrar_letra_previa(anteriores):
        """Borra un «V-» final repartido en los runs que vienen antes.

        Se recorre de atrás para adelante porque Word parte el texto donde
        quiere: acá la letra y el guion quedaron en dos runs distintos.
        """
        textos = [t for r in anteriores for t in r.iter(W + "t")
                  if t.text is not None]
        completo = "".join(t.text for t in textos)
        sobra = re.search(r"[VvEeJjPpGg]\s*[-–]\s*$", completo)
        if not sobra:
            return 0
        cuantos = len(completo) - sobra.start()
        for t in reversed(textos):
            if cuantos <= 0:
                break
            largo = len(t.text)
            if largo <= cuantos:
                t.text = ""
                cuantos -= largo
            else:
                t.text = t.text[:largo - cuantos]
                cuantos = 0
        return 1

    # -- El bloque de firmas no se puede cortar por la mitad ----------------
    @staticmethod
    def _no_partir_las_firmas(root):
        """Que la cédula no quede en otra página que la raya para firmar.

        Reporte: el contrato salía con una página final que tenía SOLO los dos
        números de cédula, sueltos en blanco, lejos de los nombres y de las
        rayas. Word puede cortar una tabla entre dos filas, y la tabla de
        firmas son exactamente tres: las etiquetas, los nombres y las cédulas.
        Cuando el texto de las cláusulas llegaba justo al pie de la página, el
        corte caía entre los nombres y las cédulas.

        No es cosmético: un contrato que se firma es una hoja donde la cédula
        identifica a quien firma arriba. Separadas, la última página parece un
        anexo y la firmada parece incompleta.

        Se marca cada fila como indivisible y se le pide a las de arriba que se
        queden con la de abajo. Si el bloque no entra al pie, pasa entero a la
        página siguiente, que es lo que se quiere.
        """
        cambios = 0
        for tabla in root.iter(W + "tbl"):
            texto = "".join(t.text or "" for t in tabla.iter(W + "t"))
            if "EMPLEADOR" not in texto:
                continue
            filas = tabla.findall(W + "tr")
            for numero, fila in enumerate(filas):
                cambios += Command._fila_indivisible(fila)
                # La última no arrastra a nadie: es el final del bloque.
                if numero < len(filas) - 1:
                    for parrafo in fila.iter(W + "p"):
                        cambios += Command._pegado_al_siguiente(parrafo)
        return cambios

    @staticmethod
    def _fila_indivisible(fila):
        """`w:cantSplit`. Va antes de `w:trHeight`: el orden del esquema."""
        trpr = fila.find(W + "trPr")
        if trpr is None:
            trpr = ET.Element(W + "trPr")
            fila.insert(0, trpr)
        if trpr.find(W + "cantSplit") is not None:
            return 0
        trpr.insert(0, ET.Element(W + "cantSplit"))
        return 1

    @staticmethod
    def _pegado_al_siguiente(parrafo):
        """`w:keepNext`. Va después de `w:pStyle` y antes del resto."""
        ppr = parrafo.find(W + "pPr")
        if ppr is None:
            ppr = ET.Element(W + "pPr")
            parrafo.insert(0, ppr)
        if ppr.find(W + "keepNext") is not None:
            return 0
        estilo = ppr.find(W + "pStyle")
        donde = list(ppr).index(estilo) + 1 if estilo is not None else 0
        ppr.insert(donde, ET.Element(W + "keepNext"))
        return 1

    # -- Acuerdo de confidencialidad: misma ciudad fija que la carta ---------
    def _preparar_confidencialidad(self, origen, salida):
        """Cambia el "En Caracas," del cierre por la ciudad que corresponda.

        Mismo caso que la carta: la fecha era campo y la ciudad no. Importa que
        sea la misma que en el contrato, porque se firman juntos: dos papeles
        del mismo dia con dos ciudades distintas se leen como un error.

        Acá la clausula de jurisdiccion tambien dice Caracas, pero vive dentro
        de un parrafo de texto corrido y no se toca: se busca solo el "Caracas"
        que es un pedazo suelto detras de un "En ".
        """
        partes, root = self._abrir_docx(origen)
        cambios = 0
        anterior = None
        for t in root.iter(W + "t"):
            if (t.text and t.text.strip() == "Caracas"
                    and anterior is not None
                    and (anterior.text or "").rstrip().endswith("En")):
                t.text = "{{CIUDAD_DE_FIRMA}}"
                cambios += 1
            if t.text:
                anterior = t
        cambios += self._fecha_del_acuerdo(root)
        cambios += self._cedula_del_empleador(root)
        cambios += self._una_sola_letra_en_la_cedula(root)
        self._guardar_docx(partes, root, salida)
        return cambios

    # -- Fechas que quedaron escritas a mano en los Word ---------------------
    @staticmethod
    def _dia_y_mes(textos, desde, dia, mes):
        """Cambia por marcadores el dia y el mes escritos a mano tras `desde`.

        Word parte el texto en pedazos por cualquier motivo -un cambio de
        formato invisible, una correccion vieja-, asi que el "11" puede venir
        como dos pedazos de un caracter. Se juntan todos los que sean digitos
        seguidos: el primero se lleva el marcador y los demas se vacian.
        """
        cambios = 0
        i = desde + 1
        primero = True
        while i < len(textos):
            crudo = textos[i].text or ""
            texto = crudo.strip()
            if texto.isdigit():
                textos[i].text = dia if primero else ""
                primero = False
                cambios += 1
            elif texto.lower() in MESES:
                # El espacio de adelante lo puso el Word y hace falta.
                textos[i].text = (" " if crudo.startswith(" ") else "") + mes
                return cambios + 1
            elif texto and not primero and texto != "de":
                break      # ya paso la fecha
            i += 1
        return cambios

    def _fechas_del_corporativo(self, root):
        """La clausula Cuarta del contrato corporativo tenia la fecha fija.

        "El presente contrato entrara en vigencia el 11 de agosto de 2026 y
        concluira el 11 de noviembre de 2026": el dia y el mes de las dos
        fechas estaban escritos a mano. Solo los anios eran campos, asi que el
        contrato cambiaba de anio pero no de dia ni de mes, y salia siempre con
        las fechas de la persona que sirvio de ejemplo. El contrato de trabajo
        normal si tiene los campos; por eso pasaba solo aca.

        Ademas el anio del final apuntaba al de ingreso: un contrato que empieza
        en noviembre y termina en enero decia que terminaba el anio anterior.
        """
        cambios = 0
        for parrafo in root.iter(W + "p"):
            textos = list(parrafo.iter(W + "t"))
            entero = "".join(t.text or "" for t in textos)
            if "entrará en vigencia el" not in entero:
                continue

            for k, t in enumerate(textos):
                if (t.text or "").endswith("vigencia el "):
                    cambios += self._dia_y_mes(
                        textos, k, "{{DIA_DE_INGRESO}}", "{{MES_DE_INGRESO}}")
                elif (t.text or "").strip() == "concluirá el":
                    cambios += self._dia_y_mes(
                        textos, k, "{{DIA_DE_CULMINACION}}",
                        "{{MES_DE_CULMINACION}}")

            cambios += self._anio_del_cierre(parrafo)
            break
        return cambios

    @staticmethod
    def _anio_del_cierre(parrafo):
        """El segundo anio de la clausula Cuarta es el del final, no el del
        comienzo.

        Los dos anios apuntaban al mismo campo, el de ingreso. Un contrato que
        empieza en agosto de 2026 y termina en enero de 2027 salia diciendo que
        concluia el 15 de enero de 2026: cinco meses ANTES de firmarse. Un
        contrato vencido el dia que se firma no obliga a nada.
        """
        anios = [i for i in parrafo.iter(W + "instrText")
                 if i.text and "o_de_ingreso" in i.text]
        if len(anios) != 2:
            # Ya esta arreglado (queda uno solo) o la clausula cambio de forma.
            return 0
        anios[1].text = anios[1].text.replace(
            "Año_de_ingreso", "Año_de_culminación").replace(
            "año_de_ingreso", "Año_de_culminación")
        return 1

    def _fecha_del_cierre_del_contrato(self, root):
        """Lo mismo, en el contrato de trabajo: ahi solo falla el anio.

        Ese Word ya trae el dia y el mes como campos —por eso el arreglo de
        `_fechas_del_corporativo` no hacia falta aca y no se aplico—, pero el
        anio del final apuntaba al de ingreso igual que en el otro. El error
        quedo suelto en este durante todo ese tiempo.
        """
        for parrafo in root.iter(W + "p"):
            entero = "".join(t.text or "" for t in parrafo.iter(W + "t"))
            if "entrará en vigencia el" not in entero:
                continue
            return self._anio_del_cierre(parrafo)
        return 0

    def _fecha_del_acuerdo(self, root):
        """La clausula Primera del acuerdo de confidencialidad, igual.

        "La Empresa ha suscrito en fecha 16 de <mes> de <anio>": el mes y el
        anio eran campos y el dia no, asi que el acuerdo decia siempre 16.
        """
        cambios = 0
        for parrafo in root.iter(W + "p"):
            textos = list(parrafo.iter(W + "t"))
            if "ha suscrito en fecha" not in "".join(t.text or "" for t in textos):
                continue
            for k, t in enumerate(textos):
                if (t.text or "").endswith("ha suscrito en fecha "):
                    siguiente = textos[k + 1] if k + 1 < len(textos) else None
                    if siguiente is not None and (siguiente.text or "").strip().isdigit():
                        siguiente.text = "{{DIA_DE_INGRESO}}"
                        cambios += 1
                    break
            break
        return cambios

    # -- Jurisdiccion vs. lugar de firma -------------------------------------
    @staticmethod
    def _separar_domicilio_legal(root):
        """El "domicilio especial" del contrato no es un lugar.

        En el Word, la clausula de jurisdiccion -"eligen expresamente como
        domicilio especial a la ciudad de X, a la Jurisdiccion de cuyos
        Tribunales declaran someterse"- y el lugar de firma -"se hacen dos
        ejemplares... en la ciudad de X"- usan EL MISMO campo, y estan en el
        mismo parrafo. Mientras ese campo valia CARACAS para todo el mundo no
        se notaba; al hacer que el lugar siga a la tienda, la jurisdiccion se
        iba con el: un contrato de Guatire pasaba a someterse a los tribunales
        de Guatire sin que nadie lo hubiera decidido.

        Son dos cosas distintas y se separan: la primera aparicion del parrafo
        es la jurisdiccion y pasa a `Domicilio_legal`, que no cambia nunca; la
        segunda es donde se firma y sigue siendo `Ciudad_de_firma`.
        """
        cambios = 0
        for parrafo in root.iter(W + "p"):
            texto = "".join(t.text or "" for t in parrafo.iter(W + "t"))
            if "domicilio especial" not in texto:
                continue
            for instr in parrafo.iter(W + "instrText"):
                if instr.text and "Ciudad_de_firma" in instr.text:
                    instr.text = instr.text.replace(
                        "Ciudad_de_firma", "Domicilio_legal")
                    cambios += 1
                    break          # solo la primera: la segunda es la firma
        return cambios

    # -- Carta de autorizacion: la ciudad estaba escrita fija ----------------
    def _preparar_carta(self, origen, salida):
        """Cambia el "Caracas," del encabezado por la ciudad que corresponda.

        La fecha del encabezado si era un campo; la ciudad no. Asi que TODAS
        las autorizaciones de ingreso decian Caracas, incluso la de alguien que
        entra al CENDIS de Guatire. Lo raro es que el documento se dirige al
        gerente de esa tienda, que lee una ciudad que no es la suya.

        Solo se toca el encabezado. Mas abajo no hay ninguna otra ciudad en
        este formato, pero en los contratos si las hay -"domicilio especial a
        la ciudad de CARACAS, a la Jurisdiccion de cuyos Tribunales"- y esas
        son una eleccion legal, no un lugar: no se tocan nunca.
        """
        partes, root = self._abrir_docx(origen)
        cambios = 0
        for t in root.iter(W + "t"):
            if t.text and re.fullmatch(r"\s*Caracas,\s*", t.text):
                t.text = "{{CIUDAD_DE_FIRMA}}, "
                cambios += 1
        self._guardar_docx(partes, root, salida)
        return cambios

    # -- Contrato corporativo: el recuadro de arriba traía datos de una persona
    #    real escritos a mano, en vez de campos --------------------------------
    def _preparar_corporativo(self, origen, salida):
        """Saca los datos de la persona de ejemplo del recuadro de encabezado.

        El Word llega con los campos de combinación puestos en el cuerpo, pero
        el recuadro del principio —el que resume el trabajador— estaba escrito
        a mano con los datos de quien sirvió de ejemplo: nombre completo,
        cédula y cargo. Sin esto, cada contrato que se genere lleva arriba a
        esa persona y abajo a la que corresponde. Es un dato personal de
        alguien que no tiene nada que ver, repartido en el contrato de todos.

        Se reemplaza por marcadores para que el recuadro se llene igual que el
        resto del documento.
        """
        partes, root = self._abrir_docx(origen)
        cambios = 0

        directos = {
            "RAMON ALFREDO CASTILLO SANCHEZ": "{{NOMBRES_Y_APELLIDOS}}",
            "CHIEF OF TECHNOLOGY (CTO)": "{{CARGO}}",
            # `Cedula` ya viene con la letra adelante ("V-30719983"), asi que
            # el "V-" suelto que la precedia se borra mas abajo.
            "19.692.045": "{{CEDULA}}",
        }

        anterior = None
        for t in root.iter(W + "t"):
            texto = (t.text or "").strip()

            # El cierre dice "en la ciudad de X a los N de MES de ANO". El mes
            # y el ano son campos; el dia quedo escrito a mano. Resultado: todo
            # contrato corporativo se firmaba "a los 11", con el mes correcto.
            # El contrato de trabajo si trae el campo, por eso solo pasa aca.
            if (anterior is not None and (anterior.text or "").endswith("a los ")
                    and texto.isdigit()):
                t.text = "{{DIA_DE_INGRESO}}"
                cambios += 1
                anterior = t
                continue

            if texto in directos:
                # El "V-" vive en su propio run, justo antes del numero. Hay
                # tres "V-" en el documento y solo dos son de esta cedula: por
                # eso se mira el de al lado y no todos.
                if texto == "19.692.045" and anterior is not None                         and (anterior.text or "").strip() == "V-":
                    anterior.text = ""
                t.text = directos[texto]
                cambios += 1

            if t.text:
                anterior = t

        cambios += self._separar_domicilio_legal(root)
        cambios += self._fechas_del_corporativo(root)
        cambios += self._no_partir_las_firmas(root)
        cambios += self._cedula_del_empleador(root)
        cambios += self._una_sola_letra_en_la_cedula(root)
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

        cambios += self._cedula_del_empleador(root)
        cambios += self._una_sola_letra_en_la_cedula(root)
        self._guardar_docx(partes, root, salida)
        return cambios

    # -- Acta de emisión de recibos: es RTF y le falta la cédula -------------
    def _preparar_recibo(self, origen, salida):
        """Los huecos largos de guiones bajos, en orden de aparición:

        1. el renglón que quedaba al lado del campo del nombre  -> se elimina
        2. el de la cédula                                      -> marcador

        Los del bloque de firma se dejan en blanco a propósito: se completan a
        mano al firmar. Los de la FECHA no: ver `_cierre_del_recibo`.

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
        texto, mas = self._cierre_del_recibo(texto)
        salida.write_text(texto, encoding="latin-1", errors="replace")
        return cambios + mas

    @staticmethod
    def _cierre_del_recibo(texto):
        """El renglón de cierre: "En ____ a los ___ días del mes de ___ de ___".

        Dos cosas mal, las dos del Word original.

        Donde va la ciudad hay un `MERGEFIELD Horario`. No es un descuido
        inofensivo: el acta salía firmada "En ROTATIVO", que es el turno del
        trabajador. Se cambia por la ciudad, la misma que usan el contrato y la
        carta.

        Y la fecha eran tres huecos en blanco para completar a mano. El sistema
        conoce la fecha de ingreso y la imprime en todos los demás documentos;
        dejarla a mano acá solo en este obliga a buscarla y copiarla, que es
        justo lo que el expediente viene a evitar.

        Se ubican los huecos a partir del campo, no por orden en el archivo: es
        el único `Horario` del acta, así que el ancla no se corre si mañana
        alguien agrega otro hueco más arriba.
        """
        marca = "MERGEFIELD Horario"
        if marca not in texto:
            return texto, 0
        texto = texto.replace(marca, "MERGEFIELD Ciudad_de_firma", 1)

        desde = texto.index("MERGEFIELD Ciudad_de_firma")
        # El primero es la línea sobre la que se escribía la ciudad a mano:
        # ahora la ciudad la pone el sistema, así que sobra.
        pendientes = ["", "@@DIA_DE_INGRESO@@", "@@MES_DE_INGRESO@@",
                      "@@ANO_DE_INGRESO@@"]
        cambios = 1

        def _sub(m):
            nonlocal cambios
            if not pendientes:
                return m.group(0)
            cambios += 1
            return pendientes.pop(0)

        cabeza, cola = texto[:desde], texto[desde:]
        cola = re.sub(r"_{3,}", _sub, cola)
        return cabeza + cola, cambios
