
import os
from pathlib import Path


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'ceeb_web',  # La teva aplicació principal
    'django_celery_results',  # Resultats de Celery
    'alumnat',
    'competicions_trampoli',
    'marbella_informes', # L'app per informes anuals de Marbella
    'designacions',
     # Example apps
]


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
SECRET_KEY = 'django-insecure-4x8z$1@#k2!3v&l^7%9m(0p)q*r&s+t=u'
ROOT_URLCONF = 'ceeb_web.urls'
# filepath: c:\Users\Extra\Desktop\ceeb_web\ceeb_web\settings.py
ALLOWED_HOSTS = ['localhost', '127.0.0.1']


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
            ],
        },
    },
]
DEBUG = True
BASE_DIR = Path(__file__).resolve().parent.parent

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB"),
        "USER": os.getenv("POSTGRES_USER"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
        "HOST": os.getenv("POSTGRES_HOST", "db"),
        "PORT": os.getenv("POSTGRES_PORT", 5432),
    }
}


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

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


DATA_UPLOAD_MAX_NUMBER_FILES = 500

CELERY_BROKER_URL = 'redis://redis:6379/0'  # URL del backend de missatgeria
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'

# Per guardar l'estat de les tasques
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "django-db")

CELERY_TASK_ROUTES = {
    'ceeb_web.tasks.process_certificats_task': {'queue': 'heavy_queue'},  # pesades
    # altres tasques -> 'default'
}

# Evita acaparament de tasques llargues
worker_prefetch_multiplier = 1
task_acks_late = True  # si vols ack al final de la tasca

# Límits de temps útils (ara sí funcionen perquè no uses 'solo')
# Allow longer-running tasks (e.g. calendar processing that can take 15-30 minutes)
# Soft limit: worker will receive a SoftTimeLimitExceeded signal at this time
# Hard limit: task will be force-terminated after this time
task_soft_time_limit = 60 * 60  # 60 minutes
task_time_limit = 60 * 65       # 65 minutes

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


#EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend" # PRODUCTION
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.office365.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True

EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "gmerino@ceeb.cat")      # ex: no-reply@elteudomini.cat
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "Et5!2FD*WacG")

DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER)

