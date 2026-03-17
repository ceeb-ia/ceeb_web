from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .live_cache import mark_live_dirty
from .models_classificacions import ClassificacioConfig
from .models_scoring import ScoreEntry


def _mark_live_dirty_on_commit(competicio_id):
    if not competicio_id:
        return
    transaction.on_commit(lambda cid=int(competicio_id): mark_live_dirty(cid))


@receiver(post_save, sender=ScoreEntry)
def _scoreentry_saved_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))


@receiver(post_delete, sender=ScoreEntry)
def _scoreentry_deleted_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))


@receiver(post_save, sender=ClassificacioConfig)
def _classificacio_saved_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))


@receiver(post_delete, sender=ClassificacioConfig)
def _classificacio_deleted_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))
