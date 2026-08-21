"""Generación de los documentos corporativos a partir de las plantillas Word.

Funciona como la correspondencia (mail merge) de Word: las plantillas ya traen
campos `MERGEFIELD` y acá se reemplazan por los datos del trabajador, dejando
el texto fijo. El resultado es un .docx normal, editable.

El relleno se hace sobre el XML del documento, sin dependencias externas:
- `.docx` es un ZIP con `word/document.xml` (+ encabezados y pies).
- Un campo de combinación se arma con varios `<w:r>`:

      begin | instrText " MERGEFIELD Cargo " | separate | resultado | end

  Se conserva el run del resultado (para no perder el formato), se le escribe
  el valor y se eliminan los runs de control, de modo que el .docx generado ya
  no dependa de ningún origen de datos.
"""

import copy
import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = "{%s}" % W

# Partes del .docx que pueden contener campos.
_PARTES = re.compile(r"^word/(document|header\d*|footer\d*)\.xml$")


def normalizar_campo(nombre: str) -> str:
    """'Día_de_ingreso' -> 'dia_de_ingreso'.

    Las plantillas mezclan mayúsculas y acentos para el mismo dato
    (`Mes_de_ingreso` y `mes_de_ingreso`), así que se comparan normalizados.
    """
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", nombre)
        if unicodedata.category(c) != "Mn"
    )
    return sin_tildes.strip().lower()


def _registrar_namespaces(xml: bytes) -> None:
    """Conserva los prefijos originales (w:, mc:, wp14:…) al reescribir.

    Si cambian, atributos como `mc:Ignorable="w14 wp14"` quedan colgados y Word
    se queja al abrir el archivo.
    """
    cabecera = xml[:4000].decode("utf-8", "replace")
    for prefijo, uri in re.findall(r'xmlns:([A-Za-z0-9_]+)\s*=\s*"([^"]+)"', cabecera):
        try:
            ET.register_namespace(prefijo, uri)
        except ValueError:
            pass


def _escribir_valor(run, valor: str) -> None:
    """Deja el run con exactamente `valor` como texto."""
    textos = list(run.iter(_W + "t"))
    if not textos:
        t = ET.SubElement(run, _W + "t")
        textos = [t]
    textos[0].text = valor
    textos[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    for extra in textos[1:]:
        extra.text = ""


def _run_vacio_como(modelo):
    """Un run nuevo que hereda el formato de `modelo`."""
    nuevo = ET.Element(_W + "r")
    rpr = modelo.find(_W + "rPr") if modelo is not None else None
    if rpr is not None:
        nuevo.append(copy.deepcopy(rpr))
    ET.SubElement(nuevo, _W + "t")
    return nuevo


def _rellenar_parrafo(parrafo, valores, faltantes):
    """Reemplaza los campos de combinación de un párrafo. Devuelve cuántos."""
    hijos = list(parrafo)
    a_borrar = []
    reemplazos = 0

    inicio = None          # índice del run con fldChar begin
    nombre = None          # nombre del MERGEFIELD
    separador = None       # índice del run con fldChar separate
    instr = []

    for i, hijo in enumerate(hijos):
        if hijo.tag == _W + "fldSimple":
            campo = re.search(r"MERGEFIELD\s+\"?([^\s\"\\]+)", hijo.get(_W + "instr") or "")
            if not campo:
                continue
            clave = normalizar_campo(campo.group(1))
            if clave not in valores:
                faltantes.add(campo.group(1))
                continue
            interno = hijo.find(_W + "r")
            run = copy.deepcopy(interno) if interno is not None else _run_vacio_como(None)
            _escribir_valor(run, valores[clave])
            parrafo.insert(list(parrafo).index(hijo), run)
            a_borrar.append(hijo)
            reemplazos += 1
            continue

        if hijo.tag != _W + "r":
            continue

        fld = hijo.find(_W + "fldChar")
        if fld is not None:
            tipo = fld.get(_W + "fldCharType")
            if tipo == "begin":
                inicio, nombre, separador, instr = i, None, None, []
            elif tipo == "separate":
                separador = i
            elif tipo == "end" and inicio is not None:
                if nombre:
                    clave = normalizar_campo(nombre)
                    if clave in valores:
                        # Runs del resultado cacheado (entre separate y end).
                        desde = (separador + 1) if separador is not None else (i)
                        resultado = [hijos[j] for j in range(desde, i)
                                     if hijos[j].tag == _W + "r"]
                        if resultado:
                            destino = resultado[0]
                            _escribir_valor(destino, valores[clave])
                            a_borrar.extend(resultado[1:])
                        else:
                            destino = _run_vacio_como(hijos[inicio])
                            _escribir_valor(destino, valores[clave])
                            parrafo.insert(list(parrafo).index(hijos[i]), destino)
                        # Se eliminan los runs de control del campo.
                        for j in range(inicio, i + 1):
                            if hijos[j] is not destino and hijos[j].tag == _W + "r":
                                if hijos[j] not in resultado[1:]:
                                    a_borrar.append(hijos[j])
                        reemplazos += 1
                    else:
                        faltantes.add(nombre)
                inicio, nombre, separador, instr = None, None, None, []
            continue

        it = hijo.find(_W + "instrText")
        if it is not None and it.text:
            instr.append(it.text)
            campo = re.search(r"MERGEFIELD\s+\"?([^\s\"\\]+)", "".join(instr))
            if campo:
                nombre = campo.group(1)

    for elem in a_borrar:
        try:
            parrafo.remove(elem)
        except ValueError:
            pass
    return reemplazos


# El BOM es opcional: varias partes del .docx lo traen y otras no.
_RAIZ = re.compile(
    rb"(?:\xef\xbb\xbf)?\s*(?:<\?xml[^>]*\?>)?\s*(<[A-Za-z0-9_:.-]+(?:\s[^>]*?)?>)", re.S
)


def _completar_raiz(original: bytes, generado: bytes) -> bytes:
    """Devuelve a la etiqueta raíz los xmlns que ElementTree descartó.

    ElementTree solo conserva las declaraciones de namespace que algún elemento
    usa. Eso deja sin declarar los prefijos que menciona `mc:Ignorable` (w15,
    w16se, wp14…) y Word abre el documento avisando que tiene "contenido
    ilegible".

    Se **agregan** las declaraciones que faltan en vez de reemplazar la etiqueta
    entera: ElementTree también declara prefijos propios que el original no
    tenía (los que en el original venían declarados en un hijo), y pisarlos
    dejaría esos prefijos sin ligar.
    """
    m_orig = _RAIZ.match(original)
    m_gen = _RAIZ.match(generado)
    if not (m_orig and m_gen):
        return generado

    tag_orig = m_orig.group(1).decode("utf-8", "replace")
    tag_gen = m_gen.group(1).decode("utf-8", "replace")

    presentes = set(re.findall(r'xmlns:([A-Za-z0-9_]+)=', tag_gen))
    agregar = [
        decl for decl in re.findall(r'xmlns:[A-Za-z0-9_]+="[^"]*"', tag_orig)
        if re.match(r'xmlns:([A-Za-z0-9_]+)=', decl).group(1) not in presentes
    ]
    ignorable = re.search(r'mc:Ignorable="[^"]*"', tag_orig)
    if ignorable and "mc:Ignorable=" not in tag_gen:
        agregar.append(ignorable.group(0))

    if not agregar:
        return generado

    cuerpo = tag_gen[:-1].rstrip()
    cierre = ">"
    if cuerpo.endswith("/"):
        cuerpo, cierre = cuerpo[:-1].rstrip(), "/>"
    nuevo = (cuerpo + " " + " ".join(agregar) + cierre).encode("utf-8")
    return generado[:m_gen.start(1)] + nuevo + generado[m_gen.end(1):]


def _rellenar_xml(xml: bytes, valores, faltantes):
    _registrar_namespaces(xml)
    root = ET.fromstring(xml)
    total = 0
    for parrafo in root.iter(_W + "p"):
        total += _rellenar_parrafo(parrafo, valores, faltantes)

    # Marcadores {{CAMPO}}, para las plantillas que no traían MERGEFIELD.
    # Se insertan siempre dentro de un único run (ver el comando
    # `preparar_plantillas`), así que nunca quedan partidos entre runs.
    for t in root.iter(_W + "t"):
        if t.text and "{{" in t.text:
            t.text = _reemplazar_marcadores(t.text, valores, faltantes)
            total += 1

    salida = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    return _completar_raiz(xml, salida), total


def rellenar_docx(ruta, valores: dict) -> tuple[bytes, set]:
    """Devuelve (bytes del .docx generado, campos de la plantilla sin valor)."""
    claves = {normalizar_campo(k): ("" if v is None else str(v)) for k, v in valores.items()}
    faltantes = set()
    salida = io.BytesIO()

    with zipfile.ZipFile(ruta) as origen:
        with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as destino:
            for item in origen.infolist():
                datos = origen.read(item.filename)
                if _PARTES.match(item.filename):
                    datos, _ = _rellenar_xml(datos, claves, faltantes)
                destino.writestr(item, datos)

    return salida.getvalue(), faltantes


# ---------------------------------------------------------------------------
# RTF
# ---------------------------------------------------------------------------
def _cierre_de_grupo(texto: str, inicio: int) -> int:
    """Índice de la llave que cierra el grupo RTF abierto en `inicio`.

    Se recorre contando llaves y salteando las escapadas (`\\{`, `\\}`), que en
    RTF son texto y no delimitan grupo.
    """
    nivel = 0
    i = inicio
    while i < len(texto):
        c = texto[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            nivel += 1
        elif c == "}":
            nivel -= 1
            if nivel == 0:
                return i
        i += 1
    return -1


def _formato_del_resultado(bloque: str) -> str:
    """Control words del `\\fldrslt`, para que el valor conserve la tipografía."""
    m = re.search(r"\{\\fldrslt\s*\{", bloque)
    if not m:
        return ""
    ini = m.end() - 1
    fin = _cierre_de_grupo(bloque, ini)
    if fin < 0:
        return ""
    contenido = bloque[ini + 1:fin]
    solo_control = re.match(r"((?:\s*\\[a-zA-Z]+-?\d*)*)", contenido)
    return solo_control.group(1) if solo_control else ""


def rellenar_rtf(ruta, valores: dict) -> tuple[bytes, set]:
    """Igual que rellenar_docx pero para plantillas .rtf.

    Un campo en RTF es `{\\field\\fldedit{\\*\\fldinst { … MERGEFIELD X }}
    {\\fldrslt {…}}}`. Se reemplaza el grupo entero por el valor, conservando
    el formato que tenía el resultado.
    """
    claves = {normalizar_campo(k): ("" if v is None else str(v)) for k, v in valores.items()}
    faltantes = set()
    texto = Path(ruta).read_text(encoding="latin-1", errors="replace")

    salida = []
    i = 0
    while True:
        inicio = texto.find("{\\field", i)
        if inicio < 0:
            salida.append(texto[i:])
            break
        fin = _cierre_de_grupo(texto, inicio)
        if fin < 0:
            salida.append(texto[i:])
            break

        bloque = texto[inicio:fin + 1]
        campo = re.search(r"MERGEFIELD\s+\"?([A-Za-z0-9_]+)", bloque)
        clave = normalizar_campo(campo.group(1)) if campo else None

        salida.append(texto[i:inicio])
        if clave is not None and clave in claves:
            formato = _formato_del_resultado(bloque)
            salida.append("{" + formato + " " + _rtf_escapar(claves[clave]) + "}")
        else:
            if campo:
                faltantes.add(campo.group(1))
            salida.append(bloque)
        i = fin + 1

    texto = "".join(salida)
    # Marcadores propios, para los huecos que la plantilla no tenía como campo.
    texto = _reemplazar_marcadores(texto, claves, faltantes, escapar=_rtf_escapar)
    return texto.encode("latin-1", "replace"), faltantes


def _rtf_escapar(valor: str) -> str:
    valor = valor.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
    return "".join(c if ord(c) < 128 else "\\'%02x" % (ord(c) & 0xFF) for c in valor)


# ---------------------------------------------------------------------------
# Marcadores {{CAMPO}} — para plantillas sin MERGEFIELD
# ---------------------------------------------------------------------------
# En .docx el marcador es {{CAMPO}}. En .rtf las llaves delimitan grupos, as\u00ed
# que ah\u00ed se usa @@CAMPO@@ para no romper la estructura del archivo.
_MARCADOR = re.compile(
    r"\{\{\s*([A-Za-z0-9_\u00c0-\u017f]+)\s*\}\}"
    r"|@@\s*([A-Za-z0-9_\u00c0-\u017f]+)\s*@@"
)


def _reemplazar_marcadores(texto, claves, faltantes, escapar=lambda v: v):
    def _sub(m):
        nombre = m.group(1) or m.group(2)
        clave = normalizar_campo(nombre)
        if clave not in claves:
            faltantes.add(nombre)
            return m.group(0)
        return escapar(claves[clave])
    return _MARCADOR.sub(_sub, texto)


# ---------------------------------------------------------------------------
# Catálogo de documentos
# ---------------------------------------------------------------------------
PLANTILLAS = {
    "contrato": {
        "titulo": "Contrato de trabajo",
        "origen": "CONTRATOS.docx",
        "archivo": "contrato_de_trabajo.docx",
    },
    "confidencialidad": {
        "titulo": "Acuerdo de confidencialidad",
        "origen": "Formato de Contrato de Confidencialidad.docx",
        "archivo": "acuerdo_de_confidencialidad.docx",
    },
    "beneficios": {
        "titulo": "Acta de convenio de beneficios no salariales",
        "origen": "17. ACTA CONVENIO BENEFICIOS NO SALARIALES (2).docx",
        "archivo": "acta_beneficios_no_salariales.docx",
    },
    "recibo": {
        "titulo": "Acta de emisión de recibos de pago",
        "origen": "18. ACTAS EMISION DE RECIBO (1).rtf",
        "archivo": "acta_emision_de_recibos.rtf",
    },
    "carta": {
        "titulo": "Carta de aceptación de personal en tienda",
        "origen": "Formato de Carta de Autorización.docx",
        "archivo": "carta_aceptacion_en_tienda.docx",
    },
}


def ruta_plantilla(clave):
    from django.conf import settings
    return Path(settings.PLANTILLAS_DIR) / PLANTILLAS[clave]["archivo"]


def generar(clave, trabajador):
    """Genera un documento. Devuelve (bytes, nombre_de_archivo, faltantes)."""
    meta = PLANTILLAS[clave]
    ruta = ruta_plantilla(clave)
    if not ruta.exists():
        raise FileNotFoundError(
            f"Falta la plantilla '{ruta.name}'. Corré: python manage.py preparar_plantillas"
        )

    valores = contexto_documentos(trabajador)
    if ruta.suffix.lower() == ".rtf":
        datos, faltantes = rellenar_rtf(ruta, valores)
    else:
        datos, faltantes = rellenar_docx(ruta, valores)

    persona = f"{trabajador.apellidos} {trabajador.nombres}".strip()
    seguro = re.sub(r"[^\w\s-]", "", persona).strip().replace(" ", "_") or "trabajador"
    nombre = f"{meta['titulo']} - {seguro}{ruta.suffix.lower()}"
    return datos, nombre, faltantes


# ---------------------------------------------------------------------------
# Datos que se vuelcan en los documentos
# ---------------------------------------------------------------------------
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _partes_fecha(fecha, prefijo):
    if not fecha:
        return {f"dia_de_{prefijo}": "", f"mes_de_{prefijo}": "", f"ano_de_{prefijo}": ""}
    return {
        f"dia_de_{prefijo}": str(fecha.day),
        f"mes_de_{prefijo}": MESES[fecha.month - 1],
        f"ano_de_{prefijo}": str(fecha.year),
    }


def _edad(nacimiento, referencia):
    if not nacimiento:
        return ""
    años = referencia.year - nacimiento.year
    if (referencia.month, referencia.day) < (nacimiento.month, nacimiento.day):
        años -= 1
    return str(años)


def contexto_documentos(trabajador) -> dict:
    """Arma el diccionario campo -> valor para las plantillas.

    Las claves se comparan normalizadas (sin tildes, en minúscula), así que
    cubren las variantes que usan los Word: `Cédula`/`Columna1`,
    `Mes_de_ingreso`/`mes_de_ingreso`, etc.
    """
    from django.utils import timezone

    hoy = timezone.localdate()
    datos = getattr(trabajador, "contratacion", None)
    sede = trabajador.sede
    nombre_completo = f"{trabajador.apellidos} {trabajador.nombres}".strip()

    valores = {
        # Identificación
        "APELLIDO_Y_NOMBRE": nombre_completo,
        "Nombres_y_apellidos": nombre_completo,
        "Columna2": nombre_completo,
        "Cedula": trabajador.cedula_completa,
        "Columna1": trabajador.cedula_completa,
        "Cargo": trabajador.cargo_nombre,
        # Tienda
        "Tienda": sede.nombre if sede else "",
        "Direccion_de_tienda": (sede.direccion if sede else "") or "",
        # Firma
        "Ciudad_de_firma": (datos.ciudad_firma if datos else "") or "",
        "Edad": _edad(trabajador.fecha_nacimiento, hoy),
        # Datos de contratación (pueden no estar cargados todavía)
        "Estado_civil": (datos.estado_civil if datos else "") or "",
        "Direccion": (datos.direccion if datos else "") or "",
        "Ciudad_de_nacimiento": (datos.ciudad_nacimiento if datos else "") or "",
        "Horario": (datos.horario if datos else "") or "",
        "Motivo_de_contratacion": (datos.motivo_contratacion if datos else "") or "",
        "Salario_texto": salario_en_letras(trabajador),
        # Dotación: hoy ninguna plantilla las combina, pero quedan disponibles
        # por si se les agrega el campo a un Word más adelante.
        "Cantidad_de_hijos": str(trabajador.cantidad_hijos),
        "Talla_de_camisa": (datos.talla_camisa if datos else "") or "",
        "Talla_de_pantalon": (datos.talla_pantalon if datos else "") or "",
        "Talla_de_zapato": (datos.talla_zapato if datos else "") or "",
    }
    valores.update(_partes_fecha(trabajador.fecha_nacimiento, "nacimiento"))
    valores.update(_partes_fecha(trabajador.fecha_ingreso, "ingreso"))
    valores.update(_partes_fecha(datos.fecha_culminacion if datos else None, "culminacion"))
    return valores


def campos_incompletos(trabajador) -> list:
    """Campos que van a salir en blanco si se genera ahora."""
    # Cada etiqueta dice dónde se completa: los campos no se cargan todos en la
    # misma pantalla y el aviso tiene que poder accionarse.
    etiquetas = {
        "cargo": "Cargo (ficha del trabajador)",
        "dia_de_nacimiento": "Fecha de nacimiento (ficha del trabajador)",
        "dia_de_ingreso": "Fecha de ingreso (ficha del trabajador)",
        "estado_civil": "Estado civil (datos de contratación)",
        "direccion": "Dirección de habitación (datos de contratación)",
        "ciudad_de_nacimiento": "Ciudad de nacimiento (datos de contratación)",
        "horario": "Horario de trabajo (datos de contratación)",
        "motivo_de_contratacion": "Motivo de contratación (datos de contratación)",
        "ciudad_de_firma": "Ciudad de firma (datos de contratación)",
        "dia_de_culminacion": "Fecha de culminación (datos de contratación)",
        "direccion_de_tienda": "Dirección de la tienda (Configuración → Tiendas)",
        "salario_texto": "Salario (sección Remuneración)",
    }
    contexto = {normalizar_campo(k): v for k, v in contexto_documentos(trabajador).items()}
    vistos, faltan = set(), []
    for clave, etiqueta in etiquetas.items():
        if not str(contexto.get(clave, "")).strip() and etiqueta not in vistos:
            vistos.add(etiqueta)
            faltan.append(etiqueta)
    return faltan


# ---------------------------------------------------------------------------
# Monto en letras (para la cláusula de salario del contrato)
# ---------------------------------------------------------------------------
_UNIDADES = [
    "", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE",
    "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISÉIS", "DIECISIETE",
    "DIECIOCHO", "DIECINUEVE", "VEINTE", "VEINTIUNO", "VEINTIDÓS", "VEINTITRÉS",
    "VEINTICUATRO", "VEINTICINCO", "VEINTISÉIS", "VEINTISIETE", "VEINTIOCHO",
    "VEINTINUEVE",
]
_DECENAS = ["", "", "", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA",
            "OCHENTA", "NOVENTA"]
_CENTENAS = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS",
             "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]

# código ISO -> (singular, plural, fracción, símbolo)
_NOMBRES_MONEDA = {
    "VES": ("BOLÍVAR", "BOLÍVARES", "CÉNTIMOS", "Bs."),
    "USD": ("DÓLAR", "DÓLARES", "CENTAVOS", "$"),
    "EUR": ("EURO", "EUROS", "CÉNTIMOS", "€"),
}


def _hasta_999(n: int) -> str:
    if n == 0:
        return ""
    if n == 100:
        return "CIEN"
    partes = []
    centenas, resto = divmod(n, 100)
    if centenas:
        partes.append(_CENTENAS[centenas])
    if resto:
        if resto < 30:
            partes.append(_UNIDADES[resto])
        else:
            decenas, unidades = divmod(resto, 10)
            partes.append(_DECENAS[decenas] + (" Y " + _UNIDADES[unidades] if unidades else ""))
    return " ".join(partes)


def numero_a_letras(n: int) -> str:
    n = int(n)
    if n == 0:
        return "CERO"
    if n < 0:
        return "MENOS " + numero_a_letras(-n)

    partes = []
    millones, resto = divmod(n, 1_000_000)
    if millones:
        partes.append("UN MILLÓN" if millones == 1
                      else _hasta_999(millones) + " MILLONES")
    miles, unidades = divmod(resto, 1000)
    if miles:
        partes.append("MIL" if miles == 1 else _hasta_999(miles) + " MIL")
    if unidades:
        partes.append(_hasta_999(unidades))
    return " ".join(partes)


def monto_en_letras(monto, codigo_moneda="VES") -> str:
    """130 -> 'CIENTO TREINTA BOLÍVARES CON 00/100 CÉNTIMOS (Bs.130,00)'."""
    from decimal import Decimal

    monto = Decimal(monto)
    entero = int(monto)
    centimos = int((monto - entero) * 100)

    # Apócope delante del nombre de la moneda: UN BOLÍVAR, VEINTIÚN BOLÍVARES.
    letras = numero_a_letras(entero)
    if letras.endswith("VEINTIUNO"):
        letras = letras[:-len("VEINTIUNO")] + "VEINTIÚN"
    elif letras.endswith("UNO"):
        letras = letras[:-3] + "UN"

    singular, plural, fraccion, simbolo = _NOMBRES_MONEDA.get(
        codigo_moneda, (codigo_moneda, codigo_moneda, "CÉNTIMOS", codigo_moneda)
    )
    nombre = singular if entero == 1 else plural
    miles, _, dec = f"{monto:,.2f}".partition(".")
    formateado = miles.replace(",", ".") + "," + dec
    return f"{letras} {nombre} CON {centimos:02d}/100 {fraccion} ({simbolo}{formateado})"


def salario_en_letras(trabajador) -> str:
    """Toma el sueldo de la Remuneración del expediente y lo pasa a letras.

    Se suman los conceptos de clase 'Sueldo' que estén vigentes; si hay en
    varias monedas se prioriza la nacional, que es la que usa el contrato.
    """
    from .models import ConceptoPago

    sueldos = [
        p for p in trabajador.pagos.filter(activo=True).select_related("concepto", "moneda")
        if p.concepto_id and p.concepto.clase == ConceptoPago.Clase.SUELDO
    ]
    if not sueldos:
        return ""

    nacionales = [p for p in sueldos if p.moneda.es_nacional]
    elegidos = nacionales or sueldos
    moneda = elegidos[0].moneda
    total = sum(p.monto for p in elegidos if p.moneda_id == moneda.pk)
    return monto_en_letras(total, moneda.codigo)
