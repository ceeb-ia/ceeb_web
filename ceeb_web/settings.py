
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
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / "db.sqlite3",
    }
}


WSGI_APPLICATION = 'ceeb_web.wsgi.application'
ASGI_APPLICATION = 'ceeb_web.asgi.application'

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')


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
task_soft_time_limit = 60 * 25
task_time_limit = 60 * 30

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