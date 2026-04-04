"""Compatibility wrapper for inscripcions media views."""

from .views.inscripcions.media import (
    _get_media_matching_config,
    _serialize_media_item,
    inscripcions_media_delete,
    inscripcions_media_file,
    inscripcions_media_match_apply,
    inscripcions_media_match_preview,
    inscripcions_media_set_primary,
    inscripcions_media_upload,
)

__all__ = [
    "_get_media_matching_config",
    "_serialize_media_item",
    "inscripcions_media_delete",
    "inscripcions_media_file",
    "inscripcions_media_match_apply",
    "inscripcions_media_match_preview",
    "inscripcions_media_set_primary",
    "inscripcions_media_upload",
]
