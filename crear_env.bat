@echo off
REM ============================================================
REM  GDE - Gestion Digital de Expedientes - Crear el archivo .env
REM
REM  El .env guarda las claves del sistema. Se genera una sola vez
REM  por instalacion y NO se sube al repositorio.
REM
REM  IMPORTANTE: con DOCUMENTOS_ENCRYPTION_KEY se cifran los
REM  documentos en disco. Si esa clave cambia, los documentos ya
REM  subidos NO se pueden volver a leer. Por eso este script nunca
REM  pisa un .env que ya exista: como maximo le agrega lo que falte.
REM ============================================================
setlocal
cd /d "%~dp0"
title GDE - Crear .env

echo.
echo ============================================
echo   GDE - CREAR ARCHIVO .env
echo ============================================
echo.

REM Alcanza con Python a secas: las claves se arman con la libreria
REM estandar, asi que esto funciona aunque el entorno no este armado todavia.
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -c "import secrets" >nul 2>&1
if errorlevel 1 goto sin_python

if exist ".env" goto ya_existe
goto crear


:sin_python
echo ERROR: no se encontro Python en esta maquina.
echo.
echo Instalalo desde https://www.python.org/downloads/ y volve a ejecutar
echo este archivo. No hace falta preparar el entorno .venv todavia.
echo.
pause
exit /b 1


REM ------------------------------------------------------------
REM  Ya hay un .env: no se toca, solo se revisa que este completo.
REM ------------------------------------------------------------
:ya_existe
echo Ya existe un archivo .env en esta carpeta. NO se va a reemplazar.
echo.
echo   Adentro esta la clave con la que se cifran los documentos.
echo   Reemplazarla dejaria ilegible todo lo que ya se subio.
echo.
echo Revisando que no falte nada...
echo.

set "FALTA_SECRETO=0"
findstr /b /r /c:"^DJANGO_SECRET_KEY=..*" ".env" >nul 2>&1
if errorlevel 1 set "FALTA_SECRETO=1"

set "FALTA_CIFRADO=0"
findstr /b /r /c:"^DOCUMENTOS_ENCRYPTION_KEY=..*" ".env" >nul 2>&1
if errorlevel 1 set "FALTA_CIFRADO=1"

if "%FALTA_SECRETO%"=="1" echo   FALTA: DJANGO_SECRET_KEY  - sin esto Django no arranca.
if "%FALTA_CIFRADO%"=="1" echo   FALTA: DOCUMENTOS_ENCRYPTION_KEY  - sin esto no se pueden subir documentos.

if "%FALTA_SECRETO%"=="1" goto ofrecer
if "%FALTA_CIFRADO%"=="1" goto ofrecer

echo   Las dos claves estan cargadas. No hay nada que hacer.
echo.
echo Para arrancar el sistema: iniciar.bat
echo.
pause
exit /b 0


:ofrecer
echo.
echo Se pueden agregar las que faltan sin tocar el resto del archivo.
echo Antes se guarda una copia del .env actual.
echo.
set "RESP="
set /p "RESP=Agregar las claves que faltan? Escribi SI y Enter: "
if /i not "%RESP%"=="SI" goto cancelado

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "SELLO=%%i"
if not exist "respaldos" mkdir "respaldos"
copy /y ".env" "respaldos\env-antes-de-completar-%SELLO%.txt" >nul
if errorlevel 1 goto sin_respaldo
echo.
echo Copia guardada en: respaldos\env-antes-de-completar-%SELLO%.txt

if "%FALTA_SECRETO%"=="0" goto sin_secreto
for /f "delims=" %%i in ('%PY% -c "import secrets;print(secrets.token_urlsafe(64))"') do set "SECRETO=%%i"
>>".env" echo.
>>".env" echo # Clave de firma de Django. Agregada por crear_env.bat.
>>".env" echo DJANGO_SECRET_KEY=%SECRETO%
echo   Agregada: DJANGO_SECRET_KEY
:sin_secreto

if "%FALTA_CIFRADO%"=="0" goto sin_cifrado
for /f "delims=" %%i in ('%PY% -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"') do set "CIFRADO=%%i"
>>".env" echo.
>>".env" echo # Clave de cifrado de los documentos. Agregada por crear_env.bat.
>>".env" echo # Si se cambia, los documentos ya subidos no se pueden volver a leer.
>>".env" echo DOCUMENTOS_ENCRYPTION_KEY=%CIFRADO%
echo   Agregada: DOCUMENTOS_ENCRYPTION_KEY
:sin_cifrado

echo.
echo ============================================
echo   LISTO
echo ============================================
echo.
goto guardar_copia


:cancelado
echo.
echo No se cambio nada.
echo.
pause
exit /b 0


:sin_respaldo
echo.
echo ERROR: no se pudo guardar la copia del .env. Se cancela por seguridad.
echo.
pause
exit /b 1


REM ------------------------------------------------------------
REM  No hay .env: se crea de cero.
REM ------------------------------------------------------------
:crear
echo Generando las claves...

for /f "delims=" %%i in ('%PY% -c "import secrets;print(secrets.token_urlsafe(64))"') do set "SECRETO=%%i"
for /f "delims=" %%i in ('%PY% -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"') do set "CIFRADO=%%i"

if not defined SECRETO goto sin_claves
if not defined CIFRADO goto sin_claves

REM El primer echo lleva un solo signo mayor: crea el archivo. Los demas
REM llevan dos: van agregando renglones abajo.
>".env" echo # Configuracion de GDE - Gestion Digital de Expedientes.
>>".env" echo # Lo genero crear_env.bat. NO se sube al repositorio.
>>".env" echo.
>>".env" echo # Clave de firma de Django. Si se cambia, se cierran todas las sesiones.
>>".env" echo DJANGO_SECRET_KEY=%SECRETO%
>>".env" echo.
>>".env" echo # 1 = desarrollo, muestra los errores en pantalla. 0 = produccion.
>>".env" echo DJANGO_DEBUG=1
>>".env" echo.
>>".env" echo # Dominios permitidos, separados por coma.
>>".env" echo # aplicacionesdamasco.com y sus subdominios ya vienen permitidos
>>".env" echo # desde settings.py: no hace falta agregarlos aca.
>>".env" echo DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
>>".env" echo.
>>".env" echo # Origenes de confianza para los formularios cuando se usa HTTPS.
>>".env" echo DJANGO_CSRF_TRUSTED_ORIGINS=
>>".env" echo.
>>".env" echo # Con esta direccion se arman los links de invitacion. Tiene que ser una
>>".env" echo # que le sirva a quien recibe la invitacion, no solo a esta maquina.
>>".env" echo DJANGO_SITE_URL=https://rrhh.aplicacionesdamasco.com
>>".env" echo.
>>".env" echo # ATENCION: con esta clave se cifran los documentos en disco.
>>".env" echo # Si se pierde o se cambia, los documentos ya subidos quedan ilegibles.
>>".env" echo DOCUMENTOS_ENCRYPTION_KEY=%CIFRADO%
>>".env" echo.
>>".env" echo # Pone 1 en el servidor con HTTPS para forzar cookies seguras.
>>".env" echo DJANGO_SECURE_COOKIES=0

if not exist ".env" goto no_se_escribio

echo.
echo ============================================
echo   LISTO - se creo el archivo .env
echo ============================================
echo.
goto guardar_copia


:guardar_copia
echo GUARDA UNA COPIA DEL ARCHIVO .env EN UN LUGAR SEGURO.
echo.
echo   Con la clave DOCUMENTOS_ENCRYPTION_KEY se cifran los documentos.
echo   Si se pierde el .env, los documentos guardados no se pueden recuperar:
echo   ni nosotros ni nadie puede volver a leerlos sin esa clave.
echo.
echo Revisa el archivo antes de arrancar, sobre todo DJANGO_SITE_URL.
echo Para abrirlo:  notepad .env
echo.
echo Para arrancar el sistema: iniciar.bat
echo.
pause
exit /b 0


:sin_claves
echo.
echo ERROR: no se pudieron generar las claves. No se escribio nada.
echo.
pause
exit /b 1


:no_se_escribio
echo.
echo ERROR: no se pudo escribir el archivo .env en esta carpeta.
echo Fijate que la carpeta no sea de solo lectura.
echo.
pause
exit /b 1
