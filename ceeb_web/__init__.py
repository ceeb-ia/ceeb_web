# This file is intentionally left blank.
try:
    from .celery import app_celery as celery_app
except ImportError:  # pragma: no cover - optional dependency in local/test envs
    celery_app = None

__all__ = ("celery_app",)
