from __future__ import absolute_import, unicode_literals
import os
from celery import Celery

# Estableix el mòdul de configuració de Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ceeb_web.settings')

app_celery = Celery('ceeb_web')

# Carrega la configuració des de Django
app_celery.config_from_object('django.conf:settings', namespace='CELERY')

# Descobreix automàticament les tasques dels teus apps
app_celery.autodiscover_tasks()

@app_celery.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')