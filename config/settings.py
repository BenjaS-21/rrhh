"""
Configuración de Django para el Sistema de Expedientes de RRHH.

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

DEBUG = env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS") or ["127.0.0.1", "localhost"]

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
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

# Límite de tamaño de carga por archivo (25 MB) antes de tocar disco.
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Cifrado de documentos en reposo
# ---------------------------------------------------------------------------
# Clave para cifrar los archivos en disco. En producción DEBE venir del .env.
DOCUMENTOS_ENCRYPTION_KEY = os.getenv("DOCUMENTOS_ENCRYPTION_KEY", "")

# Extensiones permitidas para documentos.
DOCUMENTOS_EXTENSIONES_PERMITIDAS = [
    ".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp",
]

MESSAGE_TAGS = {
    10: "debug", 20: "info", 25: "success", 30: "warning", 40: "danger",
}
