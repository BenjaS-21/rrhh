@echo off
REM ============================================================
REM  GDE - Gestion Digital de Expedientes - Carga de datos maestros
REM  Tiendas con su direccion, unidades organizativas y cargos.
REM
REM  Se puede ejecutar las veces que haga falta: lo que ya existe
REM  se actualiza y lo que falta se crea. NO borra trabajadores,
REM  documentos ni montos de remuneracion.
REM ============================================================
cd /d "%~dp0"
title GDE - Cargar datos maestros

echo.
echo ============================================
echo   CARGA DE DATOS MAESTROS
echo ============================================
echo.
echo   - 49 tiendas con su direccion
echo   - 78 unidades organizativas
echo   - 805 cargos
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

REM Copia de seguridad de la base antes de tocarla.
REM El sello de fecha lo da PowerShell: armarlo con %date% depende del formato
REM regional de Windows y salia vacio.
if exist "db.sqlite3" (
    if not exist "respaldos" mkdir "respaldos"
    for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set SELLO=%%i
)
if exist "db.sqlite3" (
    copy /y "db.sqlite3" "respaldos\db-antes-de-cargar-%SELLO%.sqlite3" >nul
    if errorlevel 1 (
        echo ERROR: no se pudo respaldar la base. Se cancela por seguridad.
        pause
        exit /b 1
    )
    echo Respaldo guardado en: respaldos\db-antes-de-cargar-%SELLO%.sqlite3
    echo.
)

REM Crea las tablas nuevas si hiciera falta.
echo Preparando base de datos...
".venv\Scripts\python.exe" manage.py migrate --noinput
if errorlevel 1 (
    echo.
    echo ERROR al preparar la base de datos. Revisa el mensaje de arriba.
    pause
    exit /b 1
)
echo.

echo Cargando datos maestros...
echo.
".venv\Scripts\python.exe" manage.py seed_damasco
if errorlevel 1 (
    echo.
    echo ERROR al cargar los datos. No se guardo nada: la carga es una sola
    echo transaccion, asi que la base quedo como estaba.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   LISTO
echo ============================================
echo.
echo Revisa los avisos de arriba, si los hay.
echo Para arrancar el sistema: iniciar.bat
echo.
pause
