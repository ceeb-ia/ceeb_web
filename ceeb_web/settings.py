
import importlib.util
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def _env_str(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def _is_placeholder(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return lowered in {
        "",
        "replace-with-strong-secret",
        "replace_me",
        "changeme",
        "change-me",
        "todo",
    }


def _require_prod_setting(name: str, *, placeholder_ok: bool = False) -> str:
    value = _env_str(name)
    if not value or (not placeholder_ok and _is_placeholder(value)):
        raise ImproperlyConfigured(f"{name} is required when APP_ENV=prod")
    return value


def _email_backend_setting() -> str:
    value = _env_str("EMAIL_BACKEND", "console")
    aliases = {
        "console": "django.core.mail.backends.console.EmailBackend",
        "smtp": "django.core.mail.backends.smtp.EmailBackend",
    }
    return aliases.get(value.lower(), value)


HAS_DJANGO_CELERY_RESULTS = importlib.util.find_spec("django_celery_results") is not None

APP_ENV = os.getenv("APP_ENV", "dev")
DEFAULT_PROJECT_APPS = (
    "ceeb_web,competicions_trampoli"
    if APP_ENV == "prod"
    else (
        "ceeb_web,certificats,competicions_trampoli,marbella_informes,designacions,calendaritzacions.django"
        if APP_ENV == "intern"
        else "ceeb_web,alumnat,certificats,competicions_trampoli,marbella_informes,designacions,calendaritzacions.django"
    )
)
PROJECT_APPS = _env_csv("PROJECT_APPS", DEFAULT_PROJECT_APPS)


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
] + PROJECT_APPS

if HAS_DJANGO_CELERY_RESULTS:
    INSTALLED_APPS.append('django_celery_results')


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# filepath: c:\Users\Extra\Desktop\ceeb_web\ceeb_web\settings.py
SECRET_KEY = _env_str("DJANGO_SECRET_KEY")
ROOT_URLCONF = (
    "ceeb_web.urls_prod"
    if APP_ENV == "prod"
    else "ceeb_web.urls_intern" if APP_ENV == "intern" else "ceeb_web.urls"
)
# filepath: c:\Users\Extra\Desktop\ceeb_web\ceeb_web\settings.py
ALLOWED_HOSTS = _env_csv("ALLOWED_HOSTS", "localhost,127.0.0.1")


BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'ceeb_web.context_processors.app_env',
            ],
        },
    },
]
DEBUG = _env_bool("DEBUG", APP_ENV not in {"prod", "intern"})
BASE_DIR = Path(__file__).resolve().parent.parent

POSTGRES_DB = os.getenv("POSTGRES_DB")

if POSTGRES_DB:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": POSTGRES_DB,
            "USER": os.getenv("POSTGRES_USER"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
            "HOST": os.getenv("POSTGRES_HOST", "db"),
            "PORT": os.getenv("POSTGRES_PORT", 5432),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(BASE_DIR / "db.sqlite3"),
        }
    }

if APP_ENV == "prod":
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured("ALLOWED_HOSTS is required when APP_ENV=prod")
    _require_prod_setting("POSTGRES_DB")
    _require_prod_setting("POSTGRES_USER")
    _require_prod_setting("POSTGRES_PASSWORD")


WSGI_APPLICATION = 'ceeb_web.wsgi.application'
ASGI_APPLICATION = 'ceeb_web.asgi.application'

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

MEDIA_URL = os.getenv('MEDIA_URL', '/media/')
MEDIA_ROOT = os.getenv('MEDIA_ROOT', '/data/media')

X_FRAME_OPTIONS = "SAMEORIGIN"

STATIC_VERSION = "dev-1"
STATIC_URL = '/static/'  # URL per accedir als fitxers estàtics
STATICFILES_DIRS = [BASE_DIR / 'static']  # Ruta al directori 'static'
STATIC_ROOT = os.getenv("STATIC_ROOT", "/data/static")


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"


DATA_UPLOAD_MAX_NUMBER_FILES = 500
DATA_UPLOAD_MAX_NUMBER_FILES = int(os.getenv("DATA_UPLOAD_MAX_NUMBER_FILES", str(DATA_UPLOAD_MAX_NUMBER_FILES)))
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("DATA_UPLOAD_MAX_MEMORY_SIZE", str(150 * 1024 * 1024)))
FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("FILE_UPLOAD_MAX_MEMORY_SIZE", str(10 * 1024 * 1024)))
JUDGE_VIDEO_FFPROBE_BIN = os.getenv("JUDGE_VIDEO_FFPROBE_BIN", "ffprobe")
JUDGE_VIDEO_FFPROBE_TIMEOUT_SECONDS = int(os.getenv("JUDGE_VIDEO_FFPROBE_TIMEOUT_SECONDS", "15"))

CSRF_TRUSTED_ORIGINS = _env_csv("CSRF_TRUSTED_ORIGINS", "")
if _env_bool("USE_X_FORWARDED_PROTO", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if APP_ENV == "prod":
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = _env_bool("SECURE_HSTS_PRELOAD", False)

CELERY_BROKER_URL = 'redis://redis:6379/0'  # URL del backend de missatgeria
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'

# Per guardar l'estat de les tasques
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "django-db")

CELERY_TASK_ROUTES = {
    'ceeb_web.tasks.process_certificats_task': {'queue': 'heavy_queue'},  # pesades
    'calendaritzacions.django.tasks.execute_calendarization_run_task': {'queue': 'heavy_queue'},
    # altres tasques -> 'default'
}

CALENDARITZACIONS_ASYNC_BACKEND = os.getenv("CALENDARITZACIONS_ASYNC_BACKEND", "celery")

# Evita acaparament de tasques llargues
CELERY_WORKER_PREFETCH_MULTIPLIER = int(os.getenv("CELERY_WORKER_PREFETCH_MULTIPLIER", "1"))
CELERY_TASK_ACKS_LATE = _env_bool("CELERY_TASK_ACKS_LATE", True)
CELERY_TASK_REJECT_ON_WORKER_LOST = _env_bool("CELERY_TASK_REJECT_ON_WORKER_LOST", False)
CELERY_BROKER_VISIBILITY_TIMEOUT = int(os.getenv("CELERY_BROKER_VISIBILITY_TIMEOUT", str(60 * 60 * 12)))
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": CELERY_BROKER_VISIBILITY_TIMEOUT}
CELERY_RESULT_BACKEND_TRANSPORT_OPTIONS = {"visibility_timeout": CELERY_BROKER_VISIBILITY_TIMEOUT}
CELERY_VISIBILITY_TIMEOUT = CELERY_BROKER_VISIBILITY_TIMEOUT
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = _env_bool("CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP", True)

# Límits de temps útils (ara sí funcionen perquè no uses 'solo')
# Allow longer-running tasks (e.g. calendar processing that can take 15-30 minutes)
# Soft limit: worker will receive a SoftTimeLimitExceeded signal at this time
# Hard limit: task will be force-terminated after this time
CELERY_TASK_SOFT_TIME_LIMIT = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", str(60 * 60)))
CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", str(60 * 65)))

# Logs consola
CELERYD_HIJACK_ROOT_LOGGER = False
CELERYD_LOG_LEVEL = "INFO"
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',  # Mostra tots els missatges d'informació
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}

RAG_URL = os.getenv("RAG_URL", "http://rag:8000/chatbot/")
TIME_ZONE = "Europe/Madrid"
USE_TZ = True


EMAIL_BACKEND = _email_backend_setting()

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.office365.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS", True)

EMAIL_HOST_USER = _env_str("EMAIL_HOST_USER")      # ex: no-reply@elteudomini.cat
EMAIL_HOST_PASSWORD = _env_str("EMAIL_HOST_PASSWORD")

DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER)
