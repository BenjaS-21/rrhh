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

REM Barre los documentos marcados para eliminar a los que se les cumplio el
REM plazo que puso el Administrador. La lista de Configuracion tambien barre
REM sola al abrirse, pero eso depende de que alguien la abra. Si esto falla no
REM se frena el arranque: es limpieza, no algo que impida trabajar.
".venv\Scripts\python.exe" manage.py purgar_marcados
echo.

echo Iniciando servidor...
echo.
echo   Publico: https://rrhh.aplicacionesdamasco.com/  (via tunel Cloudflare)
echo   Para DETENER: cerra esta ventana o presiona Ctrl+C.
echo.
echo   Nota: con DJANGO_SECURE_COOKIES=1 el sistema exige HTTPS, asi que
echo   http://127.0.0.1:6652/ redirige y no abre. Se entra por el tunel.
echo   Para revisar algo en local, pone DJANGO_SECURE_COOKIES=0 un rato.
echo.

start "" https://rrhh.aplicacionesdamasco.com/
REM --insecure NO es una opcion insegura: le dice al servidor que siga
REM entregando los archivos de /static/ aunque DJANGO_DEBUG este en 0. Sin
REM esto el sitio abre sin CSS ni JavaScript, y apagar DEBUG en el servidor
REM -que es lo que evita mostrar las trazas de error a cualquiera- deja de
REM ser posible. Es el mismo modo de entrega que se venia usando.
".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:6652 --insecure

pause
