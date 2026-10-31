"""
Configuración PRINCIPAL del proyecto (la que usa Render en producción).

No lleva claves escritas: all viene de variables de entorno (Render > Environment).
Variables mínimas: SECRET_KEY y DATABASE_URL. El resto está explicado en DEPLOY.md.

Tu PC usa `settings_dev.py`, que fija sus propios valores y reutiliza este archivo:
    python manage.py runserver --settings=config.settings_dev     (es el valor por defecto de manage.py)

Para operar la base de PRODUCCIÓN desde tu PC: guarda las variables en `.env.production` (fuera de git) y ejecuta
    python manage.py createsuperuser --settings=config.settings
"""

import os
import sys
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
_local_prod_file = BASE_DIR / ".env.production"
if _local_prod_file.exists():  # solo existe en tu PC; en Render las variables ya están en el entorno
    environ.Env.read_env(_local_prod_file)

DEBUG = env.bool("DEBUG", default=False)

SECRET_KEY = env("SECRET_KEY", default="")
if not SECRET_KEY:
    raise ImproperlyConfigured("Falta la variable de entorno SECRET_KEY.")

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"] if DEBUG else [])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
_render_host = env("RENDER_EXTERNAL_HOSTNAME", default="")  # Render lo inyecta solo
if _render_host:
    ALLOWED_HOSTS.append(_render_host)
    CSRF_TRUSTED_ORIGINS.append(f"https://{_render_host}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "raffles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

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

# --- Base de datos: DATABASE_URL = la cadena de conexión de Neon (postgresql://usuario:clave@host/db?sslmode=require) ---
try:
    DATABASES = {"default": env.db("DATABASE_URL")}
except ImproperlyConfigured as exc:
    raise ImproperlyConfigured("Falta la variable de entorno DATABASE_URL (la de Neon).") from exc
DATABASES["default"]["CONN_MAX_AGE"] = 600
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True  # compatible con el pool de Neon
if not DEBUG:
    DATABASES["default"].setdefault("OPTIONS", {})["sslmode"] = "require"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internacionalización (Chile) ---
LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True

# --- Estáticos (WhiteNoise) y media ---
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # Con huella en el nombre solo en producción (en local no hay `collectstatic` previo).
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Imágenes: Render gratis borra el disco, así que en producción se guardan en Cloudinary.
CLOUDINARY_URL = env("CLOUDINARY_URL", default="")
if CLOUDINARY_URL:
    INSTALLED_APPS += ["cloudinary", "cloudinary_storage"]
    STORAGES["default"] = {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- DRF + límites de uso (evitan que un script acapare los números) ---
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_RATES": {"reserve": "10/min", "proof": "10/min"},
    "NUM_PROXIES": 0 if DEBUG else 1,  # en Render hay 1 proxy delante de la app
}

# --- Reglas de negocio por defecto (luego se editan en Admin > Configuración del sitio) ---
TICKET_RESERVATION_MINUTES = 30

# --- Correo: TODOS los correos salen de rifaschile93634@gmail.com ---
# Render gratis BLOQUEA el SMTP (puertos 25/465/587), así que allí el envío va por la API de Brevo (HTTPS)
# con BREVO_API_KEY. Sin esa clave se usa Gmail por SMTP (sirve desde tu PC o en un plan de Render de pago).
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_TIMEOUT = 10
EMAIL_HOST_USER = "chilerifas93634@gmail.com"
DEFAULT_FROM_EMAIL = "Rifas Chile <chilerifas93634@gmail.com>"
BREVO_API_KEY = env("BREVO_API_KEY", default="")
ANYMAIL = {"BREVO_API_KEY": BREVO_API_KEY}
if BREVO_API_KEY:
    EMAIL_BACKEND = "anymail.backends.brevo.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="").replace(" ", "")

# --- Seguridad en producción ---
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # sin esto, bucle de redirecciones en Render
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 7

# --- Protección: desde tu PC, avisa si estás sobre una base REMOTA (producción) y bloquea comandos destructivos ---
_db_host = DATABASES["default"].get("HOST", "")
if (
    os.path.basename(sys.argv[0]) == "manage.py"
    and not os.environ.get("RENDER")
    and _db_host not in ("", "localhost", "127.0.0.1", "::1")
):
    _cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if _cmd in ("test", "flush", "sqlflush", "reset_db"):
        raise ImproperlyConfigured(
            f"'{_cmd}' está bloqueado: apuntas a una base REMOTA ({_db_host}). Podría borrar datos de producción."
        )
    print(f"\n⚠️  CONECTADO A LA BASE REMOTA (PRODUCCIÓN): {_db_host}\n", file=sys.stderr)
