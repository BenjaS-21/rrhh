"""Rellena un formulario que solo existe en PDF, escribiendo sobre él.

La lista de verificación del expediente (COR-FRM-GEH-005) no vino en Word como
el resto de los formatos: es un PDF plano, sin campos de formulario adentro.
Así que no se puede hacer correspondencia como en `documentos.py`; hay que
DIBUJAR el texto encima, en el lugar exacto.

Y solo una parte del formulario se rellena. Las 29 casillas ☐ SI ☐ NO ☐ N/A
quedan **vacías a propósito**: la lista se imprime y se va tildando a mano,
documento por documento, mientras se arma la carpeta. Lo que sí se completa es
el recuadro «SOLO PARA USO DE GESTIÓN HUMANA» del pie, que son datos que el
sistema ya tiene y que hoy alguien copia a mano de la ficha.

## Por qué no hay coordenadas escritas en el código

Sería lo más corto: mirar el PDF una vez, anotar los ocho pares (x, y) y
escribirlos. Pero el formato lo revisa Gestión Humana —este ya dice «Versión:
01» y «Fecha de Revisión: Julio 2026»—, y con coordenadas fijas la próxima
versión imprimiría el sueldo encima de otra cosa, sin que nada avise.

Acá se busca cada dato por su ETIQUETA («Sueldo:», «Cargo:»…) y se escribe
dentro de la celda que la contiene, deduciendo la celda de las líneas de la
tabla. Si el formulario se mueve, el texto se mueve con él. Y si una etiqueta
cambia de nombre, el campo sale en blanco y se avisa —el mismo camino que un
campo sin cargar—, en vez de escribir en el lugar equivocado.
"""

from io import BytesIO

import pymupdf

# Etiqueta impresa en el formulario -> campo del contexto de documentos.
#
# «Complemento» va cortado: en el PDF el texto «Complemento Alimentación:»
# quedó partido en dos líneas y la búsqueda no encuentra la frase entera.
CAMPOS = [
    ("Fecha de Ingreso:", "Fecha_de_ingreso"),
    ("Sueldo:", "Sueldo"),
    ("Bono de Alimentación:", "Bono_de_alimentacion"),
    ("Complemento", "Complemento_alimentacion"),
    ("Apellidos y Nombre(s):", "APELLIDO_Y_NOMBRE"),
    ("C.I.", "Cedula"),
    ("Cargo:", "Cargo"),
    ("Dependencia:", "Dependencia"),
]

# Dónde empieza el recuadro que se rellena. La búsqueda se acota ahí abajo por
# precaución, no por un choque que exista hoy: en esta versión del formulario
# cada etiqueta aparece una sola vez en toda la hoja. Pero varias son cortas
# —«Complemento», «C.I.», «Cargo:»— y arriba hay 29 renglones de texto libre
# que Gestión Humana puede reescribir; si mañana uno dice «Cargo:», el dato
# iría a parar a la lista de casillas. Hay una prueba que vigila que sigan
# siendo únicas, así que esto es el cinturón y aquella los tiradores.
ENCABEZADO_DEL_RECUADRO = "SOLO PARA USO"

# Las firmas NO se dibujan: se firman a mano, como las casillas se tildan a
# mano. Están nombradas para que quede dicho que es una decisión, no un olvido.
SE_FIRMAN_A_MANO = ("Firma Analista Responsable:", "Firma Gerencia")

TAMANOS = (9, 8, 7, 6)   # se prueba de mayor a menor hasta que entre
FUENTE = "helv"          # incrustada en todo lector: no depende de la máquina
SANGRIA = 4              # el valor arranca apenas corrido de la etiqueta


class FormularioCambio(Exception):
    """El PDF ya no tiene la estructura que este módulo sabe rellenar."""


def _lineas(pagina):
    """Las líneas de la hoja, cada una con el tramo que ocupa.

    El tramo no es un detalle: una vertical solo delimita las celdas de SU
    fila. En esta hoja hay catorce verticales —las del recuadro y las de la
    tabla de las 29 casillas, arriba—, y quedarse con «la primera que está a
    la derecha» agarra casi siempre una que no viene al caso: el sueldo se
    cortaría contra la columna del ☐ SI, y el cargo contra el borde de la
    fila de arriba. Con el tramo, cada etiqueta encuentra su propia celda.
    """
    verticales, horizontales = [], []
    for dibujo in pagina.get_drawings():
        r = dibujo["rect"]
        if r.width < 2 and r.height > 3:
            verticales.append((r.x0, r.y0, r.y1))
        elif r.height < 2 and r.width > 3:
            horizontales.append((r.y0, r.x0, r.x1))
    return verticales, horizontales


def _celda(etiqueta, verticales, horizontales):
    """El hueco libre de la celda: debajo de la etiqueta, hasta el borde.

    El valor va en el renglón de abajo y no al lado, porque «Fecha de
    Ingreso:» ocupa casi toda su celda a lo ancho y no dejaría lugar. Abajo
    entra siempre, y las cuatro celdas quedan parejas.
    """
    derecha = min(
        (x for x, y0, y1 in verticales
         if x > etiqueta.x1 and y0 <= etiqueta.y0 and y1 >= etiqueta.y1),
        default=None)
    abajo = min(
        (y for y, x0, x1 in horizontales
         if y > etiqueta.y1 and x0 <= etiqueta.x0 and x1 >= etiqueta.x1),
        default=None)
    if derecha is None or abajo is None:
        return None
    return pymupdf.Rect(etiqueta.x0 + SANGRIA, etiqueta.y1 + 1,
                        derecha - SANGRIA, abajo - 2)


def _escribir(pagina, hueco, texto):
    """Escribe achicando la letra si hace falta. Devuelve si entró."""
    for tamano in TAMANOS:
        if pagina.insert_textbox(hueco, texto, fontsize=tamano,
                                 fontname=FUENTE, align=0) >= 0:
            return True
    # Ni en 6 puntos: se recorta antes que pisar la celda de al lado. Un dato
    # a medias es visible; uno encimado se lee como el del campo vecino.
    recortado = texto[:40].rstrip() + "…"
    return pagina.insert_textbox(hueco, recortado, fontsize=TAMANOS[-1],
                                 fontname=FUENTE, align=0) >= 0


def rellenar_pdf(ruta, valores):
    """Devuelve (bytes del PDF, campos que quedaron en blanco).

    Misma forma que `rellenar_docx`: lo que no se pudo completar se informa,
    no se inventa. Las casillas de verificación no se tocan.
    """
    documento = pymupdf.open(ruta)
    pagina = documento[0]

    recuadro = pagina.search_for(ENCABEZADO_DEL_RECUADRO)
    if not recuadro:
        raise FormularioCambio(
            f"El formulario ya no tiene el recuadro «{ENCABEZADO_DEL_RECUADRO}». "
            "Hay que revisar expedientes/formulario_pdf.py contra la versión nueva."
        )
    desde = recuadro[0].y0

    verticales, horizontales = _lineas(pagina)
    faltantes = set()
    for etiqueta, campo in CAMPOS:
        valor = str(valores.get(campo, "") or "").strip()
        # Solo las de adentro del recuadro: la etiqueta de la carpeta se
        # menciona también en las Observaciones, más arriba.
        hallazgos = [r for r in pagina.search_for(etiqueta) if r.y0 > desde]
        hueco = _celda(hallazgos[0], verticales, horizontales) if hallazgos else None
        if not valor or hueco is None:
            faltantes.add(campo)
            continue
        if not _escribir(pagina, hueco, valor):
            faltantes.add(campo)

    salida = BytesIO()
    documento.save(salida, garbage=3, deflate=True)
    documento.close()
    return salida.getvalue(), faltantes
