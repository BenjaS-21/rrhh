"""
Configuración de Django para GDE — Gestión Digital de Expedientes.

Los valores sensibles se leen desde un archivo .env (ver .env.example).
"""

from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Carga variables de entorno desde .env si existe.
load_dotenv(BASE_DIR / ".env")


def env_bool(nombre: str, por_defecto: bool = False) -> bool:
    return os.getenv(nombre, "1" if por_defecto else "0").strip().lower() in {"1", "true", "yes", "si", "sí"}


def env_list(nombre: str) -> list[str]:
    valor = os.getenv(nombre, "").strip()
    return [x.strip() for x in valor.split(",") if x.strip()]


# ---------------------------------------------------------------------------
# Seguridad básica
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-solo-para-desarrollo-cambiar")

# Por defecto APAGADO. Es a propósito: si alguien copia el proyecto al servidor
# sin `.env`, o se le borra la línea, lo que pasa es que deja de mostrar las
# trazas de error, no que empiece a mostrarlas. Para desarrollar se prende
# escribiendo DJANGO_DEBUG=1 en el .env, que es lo que deja `crear_env.bat`.
DEBUG = env_bool("DJANGO_DEBUG", False)

# Un punto adelante ("`.aplicacionesdamasco.com`") vale para el dominio y para
# todos sus subdominios. Hace falta porque el túnel de Cloudflare arma nombres
# por máquina y por puerto —`6652-laptop.aplicacionesdamasco.com`— y cada equipo
# nuevo generaría un `DisallowedHost` que hay que ir agregando a mano.
DOMINIO_CORPORATIVO = ".aplicacionesdamasco.com"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS") or ["127.0.0.1", "localhost"]
if DOMINIO_CORPORATIVO not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(DOMINIO_CORPORATIVO)

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
# Sin esto, el host queda permitido pero cualquier formulario del subdominio
# falla con "CSRF verification failed", que es más confuso todavía.
_origen_corporativo = f"https://*{DOMINIO_CORPORATIVO}"
if _origen_corporativo not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(_origen_corporativo)

# URL base del sistema (para armar links absolutos de invitación). Ej:
# http://192.168.1.50:8000  o  https://rrhh.empresa.local
SITE_URL = os.getenv("DJANGO_SITE_URL", "http://127.0.0.1:8000")

# En producción (con HTTPS) poné DJANGO_SECURE_COOKIES=1
_secure = env_bool("DJANGO_SECURE_COOKIES", False)
SESSION_COOKIE_SECURE = _secure
CSRF_COOKIE_SECURE = _secure
SESSION_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 60 * 60 * 8  # 8 horas

# Estamos detrás de un proxy/túnel (Cloudflare) que termina el HTTPS y reenvía
# por HTTP a Django. Esta cabecera le dice a Django que la petición original fue
# HTTPS, para que el chequeo de origen de CSRF y request.is_secure() funcionen.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_COOKIES", False)
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 7 if _secure else 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True


# ---------------------------------------------------------------------------
# Aplicaciones
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Apps del proyecto
    "cuentas",
    "expedientes",
    "configuracion",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Después de sesiones y mensajes: necesita poder dejar el aviso en pantalla.
    "config.middleware.LimitarTamanoDeSubida",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.sistema",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Identidad del sistema
# ---------------------------------------------------------------------------
# El nombre vive acá y llega a las plantillas por `config.context_processors`.
# Está en un solo lugar para que no se desincronice entre la pestaña del
# navegador, el pie, el admin de Django y los .bat.
NOMBRE_SISTEMA = "GDE"
NOMBRE_SISTEMA_LARGO = "Gestión Digital de Expedientes"


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            # SQLite deja escribir a uno solo por vez. Sin esto, la segunda
            # persona que guarda en el mismo instante recibe "database is
            # locked" en la cara; con esto espera su turno hasta 20 segundos,
            # que es muchísimo más de lo que tarda cualquier guardado real.
            "timeout": 20,
            # Pide el candado de escritura al abrir la transacción y no a mitad
            # de camino. Evita el caso feo: dos guardados que ya empezaron y
            # uno tiene que abortar cuando iba por la mitad.
            "transaction_mode": "IMMEDIATE",
        },
    }
}
# Nota: para muchos usuarios simultáneos conviene migrar a PostgreSQL.
# Ver instrucciones en el README.


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "cuentas.Usuario"
LOGIN_URL = "cuentas:login"
LOGIN_REDIRECT_URL = "expedientes:trabajador_list"
LOGOUT_REDIRECT_URL = "cuentas:login"

# Cuántos intentos fallidos se toleran antes de frenar, y por cuánto tiempo.
# No es contra alguien que se equivocó de tecla —cinco intentos sobran— sino
# contra probar contraseñas de a miles contra una dirección pública.
LOGIN_INTENTOS_MAX = 5
LOGIN_BLOQUEO_SEGUNDOS = 15 * 60

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ---------------------------------------------------------------------------
# Internacionalización
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "es-ar"
TIME_ZONE = "America/Argentina/Buenos_Aires"
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Archivos estáticos y de medios (documentos subidos)
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []

# Los documentos se guardan FUERA de la web pública. NUNCA se sirven por MEDIA_URL
# directo: siempre pasan por una vista que valida permisos (ver expedientes.views).
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media-privado-no-usar/"

# Cuánto puede pesar un documento. Es el número que ve la persona en pantalla
# y el que rechaza el servidor: si no coinciden, alguien sube 80 MB por la
# conexión de la tienda para que recién al final le digan que no.
DOCUMENTOS_MAX_BYTES = 20 * 1024 * 1024

# Cuánto se admite recibir en total, ya con el sobre del formulario. El margen
# es para los otros campos y los límites de multipart.
SUBIDA_MAX_BYTES = DOCUMENTOS_MAX_BYTES + 5 * 1024 * 1024

# Los datos que NO son archivo (los campos del formulario) siguen acotados.
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# A partir de acá el archivo subido se escribe en un temporal en vez de quedar
# en RAM. Estaba en 25 MB: cada subida se reservaba eso de memoria antes de
# empezar a cifrar, y con varias a la vez el servidor se quedaba sin aire.
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# El escáner manda una foto por hoja; `expedientes.escaner` limita a 30.
DATA_UPLOAD_MAX_NUMBER_FILES = 40

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Las pruebas corren con el transporte fijado a HTTP plano, pase lo que pase en
# el .env de la maquina. Ver config/test_runner.py: sin esto, el suite entero
# depende de como este configurado el equipo donde se ejecuta.
TEST_RUNNER = "config.test_runner.Corredor"


# ---------------------------------------------------------------------------
# Cifrado de documentos en reposo
# ---------------------------------------------------------------------------
# Clave para cifrar los archivos en disco. En producción DEBE venir del .env.
DOCUMENTOS_ENCRYPTION_KEY = os.getenv("DOCUMENTOS_ENCRYPTION_KEY", "")

# Extensiones permitidas para documentos.
DOCUMENTOS_EXTENSIONES_PERMITIDAS = [
    ".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp",
]

# ---------------------------------------------------------------------------
# Plantillas Word de los documentos corporativos
# ---------------------------------------------------------------------------
# Las deja listas el comando: python manage.py preparar_plantillas
PLANTILLAS_DIR = BASE_DIR / "plantillas"

MESSAGE_TAGS = {
    10: "debug", 20: "info", 25: "success", 30: "warning", 40: "danger",
}
