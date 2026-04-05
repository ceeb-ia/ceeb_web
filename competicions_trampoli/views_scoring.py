"""Legacy compatibility facade for scoring views."""

from .views.scoring.media import (
    scoring_judge_video_file,
    scoring_media_context,
    scoring_media_file,
)
from .views.scoring.notes import ScoringNotesHome
from .views.scoring.save import scoring_save, scoring_save_partial
from .views.scoring.schema import ScoringSchemaUpdate
from .views.scoring.updates import SCORING_UPDATES_LIMIT, scoring_updates

__all__ = [
    "SCORING_UPDATES_LIMIT",
    "ScoringNotesHome",
    "ScoringSchemaUpdate",
    "scoring_judge_video_file",
    "scoring_media_context",
    "scoring_media_file",
    "scoring_save",
    "scoring_save_partial",
    "scoring_updates",
]
