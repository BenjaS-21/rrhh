@echo off
REM ============================================================
REM  GDE - Gestion Digital de Expedientes - Arranque (solo ejecuta)
REM  Puerto 6652 -> tunel Cloudflare rrhh.aplicacionesdamasco.com
REM ============================================================
cd /d "%~dp0"
title GDE - Servidor

echo.
echo ============================================
echo   GDE - GESTION DIGITAL DE EXPEDIENTES
echo ============================================
echo.

REM Verifica que el entorno exista, pero NO instala nada.
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: no existe el entorno virtual .venv
    echo Prepara el entorno una sola vez con:
    echo    python -m venv .venv
    echo    .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM Pone la base de datos al dia (crea tablas nuevas). NO instala dependencias.
echo Preparando base de datos...
".venv\Scripts\python.exe" manage.py migrate --noinput
if errorlevel 1 (
    echo.
    echo ERROR al preparar la base de datos. Revisa el mensaje de arriba.
    pause
    exit /b 1
)
echo.

echo Iniciando servidor...
echo.
echo   Local:   http://127.0.0.1:6652/
echo   Publico: https://rrhh.aplicacionesdamasco.com/  (via tunel Cloudflare)
echo   Para DETENER: cerra esta ventana o presiona Ctrl+C.
echo.

start "" http://127.0.0.1:6652/
".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:6652

pause
