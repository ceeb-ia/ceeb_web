from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import EquipContext, InscripcioEquipAssignacio, InscripcioMedia
from .live_cache import mark_live_dirty
from .models.classificacions import ClassificacioConfig
from .models.scoring import (
    ScoreEntry,
    ScoreEntryVideo,
    SerieEquip,
    SerieEquipItem,
    TeamScoreEntry,
    TeamScoreEntryVideo,
)


def _mark_live_dirty_on_commit(competicio_id):
    if not competicio_id:
        return
    transaction.on_commit(lambda cid=int(competicio_id): mark_live_dirty(cid))


def _delete_file_on_commit(file_field):
    if not file_field:
        return
    storage = getattr(file_field, "storage", None)
    name = str(getattr(file_field, "name", "") or "").strip()
    if storage is None or not name:
        return
    transaction.on_commit(lambda s=storage, n=name: s.delete(n))


@receiver(post_save, sender=ScoreEntry)
def _scoreentry_saved_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))


@receiver(post_delete, sender=ScoreEntry)
def _scoreentry_deleted_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))


@receiver(post_save, sender=TeamScoreEntry)
def _teamscoreentry_saved_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))


@receiver(post_delete, sender=TeamScoreEntry)
def _teamscoreentry_deleted_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))


@receiver(post_save, sender=ClassificacioConfig)
def _classificacio_saved_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))


@receiver(post_delete, sender=ClassificacioConfig)
def _classificacio_deleted_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))


@receiver(post_save, sender=EquipContext)
def _equip_context_saved_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))


@receiver(post_delete, sender=EquipContext)
def _equip_context_deleted_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))


@receiver(post_save, sender=InscripcioEquipAssignacio)
def _equip_assignacio_saved_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))


@receiver(post_delete, sender=InscripcioEquipAssignacio)
def _equip_assignacio_deleted_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))


@receiver(post_save, sender=SerieEquip)
def _serie_equip_saved_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))


@receiver(post_delete, sender=SerieEquip)
def _serie_equip_deleted_mark_live_dirty(sender, instance, **kwargs):
    _mark_live_dirty_on_commit(getattr(instance, "competicio_id", None))


@receiver(post_save, sender=SerieEquipItem)
def _serie_equip_item_saved_mark_live_dirty(sender, instance, **kwargs):
    competicio_id = getattr(getattr(instance, "serie", None), "competicio_id", None)
    _mark_live_dirty_on_commit(competicio_id)


@receiver(post_delete, sender=SerieEquipItem)
def _serie_equip_item_deleted_mark_live_dirty(sender, instance, **kwargs):
    competicio_id = getattr(getattr(instance, "serie", None), "competicio_id", None)
    _mark_live_dirty_on_commit(competicio_id)


@receiver(post_delete, sender=InscripcioMedia)
def _inscripcio_media_deleted_cleanup_file(sender, instance, **kwargs):
    _delete_file_on_commit(getattr(instance, "fitxer", None))


@receiver(post_delete, sender=ScoreEntryVideo)
def _score_video_deleted_cleanup_file(sender, instance, **kwargs):
    _delete_file_on_commit(getattr(instance, "video_file", None))


@receiver(post_delete, sender=TeamScoreEntryVideo)
def _team_score_video_deleted_cleanup_file(sender, instance, **kwargs):
    _delete_file_on_commit(getattr(instance, "video_file", None))
