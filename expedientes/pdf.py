"""Conversión de los documentos generados a PDF.

Se apoya en el Word que ya está instalado en la máquina donde corre el sistema
y se lo maneja por COM desde PowerShell. Se eligió así por dos razones:

- **Fidelidad exacta.** El PDF sale idéntico al Word: mismos saltos de página,
  misma tipografía, mismo encabezado. Cualquier conversor propio tendría que
  reinterpretar el .docx y el resultado no coincidiría con lo que firma la gente.
- **Sin dependencias nuevas.** No hace falta instalar LibreOffice ni paquetes de
  Python: se usa lo que ya está.

A cambio, esto **solo funciona en Windows con Word instalado**. Si el sistema se
mudara a un servidor Linux habría que cambiar el motor (LibreOffice en modo
headless sería el reemplazo natural); por eso todo el acceso pasa por
`hay_conversor()` y `convertir_a_pdf()`, y la interfaz esconde los botones de PDF
cuando no se puede.

Word abre una instancia propia y `Quit()` cierra solo esa: está verificado que
no toca los documentos que el usuario tenga abiertos. Por eso **nunca** se matan
procesos WINWORD por las suyas, que sí destruiría trabajo sin guardar.
"""

import logging
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Word no admite que lo manejen dos conversiones a la vez: se serializan.
_CANDADO = threading.Lock()

# Una conversión tarda menos de un segundo; el margen es por si Word arranca
# frío o aparece un diálogo inesperado.
_ESPERA_MAXIMA = 120

# Cuánto vale la respuesta de `hay_conversor()` antes de volver a preguntar.
_VIGENCIA_CACHE = 300
_CACHE_CANDADO = threading.Lock()
_cache = {"valor": False, "hasta": 0.0}

# 17 = wdFormatPDF.
_SCRIPT = r"""
param([string]$Origen, [string]$Destino)
$ErrorActionPreference = "Stop"
$word = $null
$doc = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    # ReadOnly y sin confirmar conversiones: no debe modificar el origen ni
    # quedarse esperando que alguien apriete un boton.
    $doc = $word.Documents.Open($Origen, [ref]$false, [ref]$true)
    $doc.SaveAs([ref]$Destino, [ref]17)
    exit 0
} catch {
    Write-Error $_.Exception.Message
    exit 1
} finally {
    if ($doc -ne $null) { try { $doc.Close([ref]0) } catch {} }
    # Quit cierra unicamente esta instancia, no el Word del usuario.
    if ($word -ne $null) { try { $word.Quit() } catch {} }
}
"""


class ConversionNoDisponible(Exception):
    """No se pudo convertir a PDF en esta máquina."""


def _powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


def hay_conversor() -> bool:
    """¿Esta máquina puede generar PDF?

    La respuesta se guarda unos minutos porque averiguarlo cuesta medio segundo
    (hay que levantar PowerShell) y esto se pregunta cada vez que alguien abre
    un expediente. Con la caché corta, instalar Word se nota solo, sin reiniciar
    el servidor, pero sin pagar el costo en cada pantalla.
    """
    ahora = time.monotonic()
    with _CACHE_CANDADO:
        if _cache["hasta"] > ahora:
            return _cache["valor"]

    valor = _averiguar_conversor()
    with _CACHE_CANDADO:
        _cache["valor"] = valor
        _cache["hasta"] = time.monotonic() + _VIGENCIA_CACHE
    return valor


def olvidar_conversor() -> None:
    """Descarta la respuesta guardada. Para los tests y para forzar un rechequeo."""
    with _CACHE_CANDADO:
        _cache["hasta"] = 0.0


def _averiguar_conversor() -> bool:
    if _powershell() is None:
        return False
    try:
        r = subprocess.run(
            [_powershell(), "-NoProfile", "-NonInteractive", "-Command",
             "if (Get-Command -Name Word.Application -ErrorAction SilentlyContinue) "
             "{ exit 0 }; "
             "if (Test-Path 'HKLM:\\SOFTWARE\\Classes\\Word.Application') { exit 0 }; "
             "if (Test-Path 'HKCR:\\Word.Application') { exit 0 }; exit 1"],
            capture_output=True, timeout=20,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def convertir_a_pdf(datos: bytes, nombre: str) -> bytes:
    """Convierte un .docx o .rtf ya generado a PDF y devuelve sus bytes.

    `nombre` solo aporta la extensión: Word decide cómo abrir el archivo según
    ella, así que un .rtf tiene que llegar como .rtf.
    """
    consola = _powershell()
    if consola is None:
        raise ConversionNoDisponible(
            "No se encontró PowerShell: la conversión a PDF solo funciona en Windows."
        )

    sufijo = Path(nombre).suffix.lower() or ".docx"
    with tempfile.TemporaryDirectory(prefix="rrhh-pdf-") as carpeta:
        base = Path(carpeta)
        # Nombre neutro: el del documento trae acentos y guiones que complican
        # el pasaje por la línea de comandos, y acá no se ve.
        origen = base / f"documento{sufijo}"
        destino = base / "documento.pdf"
        guion = base / "convertir.ps1"
        origen.write_bytes(datos)
        guion.write_text(_SCRIPT, encoding="utf-8")

        with _CANDADO:
            try:
                r = subprocess.run(
                    [consola, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                     "Bypass", "-File", str(guion),
                     "-Origen", str(origen), "-Destino", str(destino)],
                    capture_output=True, timeout=_ESPERA_MAXIMA,
                )
            except subprocess.TimeoutExpired:
                logger.warning("La conversión a PDF de %s superó los %ss",
                               nombre, _ESPERA_MAXIMA)
                raise ConversionNoDisponible(
                    "Word tardó demasiado en convertir el documento. "
                    "Descargalo en Word y guardalo como PDF desde ahí."
                ) from None
            except OSError as e:
                raise ConversionNoDisponible(f"No se pudo ejecutar Word: {e}") from e

        if r.returncode != 0 or not destino.exists():
            detalle = (r.stderr or b"").decode("utf-8", "replace").strip()
            logger.warning("Word no pudo convertir %s: %s", nombre, detalle)
            raise ConversionNoDisponible(
                "Word no pudo convertir este documento a PDF. "
                "Descargalo en Word y guardalo como PDF desde ahí."
            )
        return destino.read_bytes()


def nombre_pdf(nombre: str) -> str:
    """'Contrato - PEREZ.docx' -> 'Contrato - PEREZ.pdf'."""
    return str(Path(nombre).with_suffix(".pdf"))
