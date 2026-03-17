from django.apps import AppConfig


class CompeticionsTrampoliConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'competicions_trampoli'

    def ready(self):
        from . import signals  # noqa: F401
