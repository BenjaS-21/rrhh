@echo off
REM ============================================================
REM  GDE - Gestion Digital de Expedientes - Migrar la base
REM
REM  Pone la estructura de la base al dia: crea las columnas y las
REM  tablas nuevas que trae el codigo, y corre las migraciones de
REM  datos (por ejemplo, la que marca un cargo general por nombre).
REM
REM  Se puede ejecutar las veces que haga falta: lo que ya se aplico
REM  no se vuelve a aplicar. NO borra expedientes ni documentos.
REM
REM  iniciar.bat ya hace esto al arrancar. Esto sirve para migrar
REM  SIN levantar el servidor: se ve el detalle en pantalla y, si algo
REM  sale mal, queda el respaldo de antes.
REM ============================================================
cd /d "%~dp0"
title GDE - Migrar la base

echo.
echo ============================================
echo   MIGRAR LA BASE DE DATOS
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: no existe el entorno virtual .venv
    echo Prepara el entorno una sola vez con:
    echo    python -m venv .venv
    echo    .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM Que va a correr, ANTES de tocar nada. Si esta lista sale vacia, la base ya
REM estaba al dia y no hay nada que hacer.
echo Migraciones pendientes:
echo.
".venv\Scripts\python.exe" manage.py migrate --plan
if errorlevel 1 (
    echo.
    echo ERROR: no se pudo leer el estado de la base. Revisa el mensaje de arriba.
    echo No se toco nada.
    pause
    exit /b 1
)
echo.

REM Copia de seguridad antes de cambiar la estructura. Una migracion de datos
REM reescribe filas, y volver atras no siempre es posible: el respaldo es la
REM unica salida real si algo queda mal.
REM El sello de fecha lo da PowerShell: armarlo con %date% depende del formato
REM regional de Windows y salia vacio.
if exist "db.sqlite3" (
    if not exist "respaldos" mkdir "respaldos"
    for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set SELLO=%%i
)
if exist "db.sqlite3" (
    copy /y "db.sqlite3" "respaldos\db-antes-de-migrar-%SELLO%.sqlite3" >nul
    if errorlevel 1 (
        echo ERROR: no se pudo respaldar la base. Se cancela por seguridad.
        pause
        exit /b 1
    )
    echo Respaldo guardado en: respaldos\db-antes-de-migrar-%SELLO%.sqlite3
    echo.
)

echo Migrando...
echo.
".venv\Scripts\python.exe" manage.py migrate --noinput
if errorlevel 1 (
    echo.
    echo ERROR al migrar. Revisa el mensaje de arriba.
    echo.
    echo La base quedo como la dejo la ultima migracion que si entro. Para
    echo volver al estado anterior, reemplaza db.sqlite3 por el respaldo de
    echo arriba con el servidor APAGADO.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   BASE AL DIA
echo ============================================
echo.
echo Ojo: migrar pone al dia la BASE, no el resto.
echo.
echo   - Si el codigo nuevo trae dependencias nuevas, falta:
echo       .venv\Scripts\python.exe -m pip install -r requirements.txt
echo   - Si cambiaron los documentos corporativos, falta:
echo       .venv\Scripts\python.exe manage.py preparar_plantillas
echo.
echo Para arrancar el sistema: iniciar.bat
echo.
pause
