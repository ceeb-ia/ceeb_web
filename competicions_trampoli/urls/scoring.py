from django.urls import path

from .base import competition_view
from ..views.competition.aparatus import (
    CompeticioAparellCreate,
    CompeticioAparellDeleteView,
    CompeticioAparellUpdate,
    TrampoliAparellList,
)
from ..views.competition.legacy import ConfiguracioCompeticio
from ..views.scoring.media import (
    scoring_judge_video_file,
    scoring_media_context,
    scoring_media_file,
)
from ..views.scoring.legacy import TrampoliNotesHome, trampoli_guardar_nota
from ..views.scoring.notes import ScoringNotesHome
from ..views.scoring.notes_api import notes_manifest, notes_table, notes_warning_validate, notes_warnings
from ..views.scoring.save import scoring_save, scoring_save_partial
from ..views.scoring.schema import ScoringSchemaUpdate
from ..views.scoring.updates import scoring_updates


urlpatterns = [
    path(
        "competicio/<int:pk>/notes/trampoli/",
        competition_view(TrampoliNotesHome.as_view(), "scoring.view"),
        name="trampoli_notes_home",
    ),
    path(
        "competicio/<int:pk>/notes/trampoli/configuracio/",
        competition_view(ConfiguracioCompeticio.as_view(), "scoring.edit"),
        name="trampoli_config",
    ),
    path(
        "competicio/<int:pk>/notes/trampoli/guardar/",
        competition_view(trampoli_guardar_nota, "scoring.edit"),
        name="trampoli_save",
    ),
    path(
        "competicio/<int:pk>/notes/trampoli/aparells/",
        competition_view(TrampoliAparellList.as_view(), "scoring.edit"),
        name="trampoli_aparells_list",
    ),
    path(
        "competicio/<int:pk>/notes/trampoli/aparells/<int:app_id>/editar/",
        competition_view(CompeticioAparellUpdate.as_view(), "scoring.edit"),
        name="trampoli_aparell_edit",
    ),
    path(
        "competicio/<int:pk>/notes/trampoli/aparells/nou/",
        competition_view(CompeticioAparellCreate.as_view(), "scoring.edit"),
        name="trampoli_aparell_create",
    ),
    path(
        "competicio/<int:pk>/notes-v2/",
        competition_view(ScoringNotesHome.as_view(), "scoring.view"),
        name="scoring_notes_home",
    ),
    path(
        "competicio/<int:pk>/scoring/notes/manifest/",
        competition_view(notes_manifest, "scoring.view"),
        name="scoring_notes_manifest",
    ),
    path(
        "competicio/<int:pk>/scoring/notes/table/",
        competition_view(notes_table, "scoring.view"),
        name="scoring_notes_table",
    ),
    path(
        "competicio/<int:pk>/scoring/notes/warnings/",
        competition_view(notes_warnings, "scoring.view"),
        name="scoring_notes_warnings",
    ),
    path(
        "competicio/<int:pk>/scoring/notes/warnings/validate/",
        competition_view(notes_warning_validate, "scoring.edit"),
        name="scoring_notes_warning_validate",
    ),
    path(
        "competicio/<int:pk>/aparell/<int:ap_id>/schema/",
        competition_view(ScoringSchemaUpdate.as_view(), "scoring.edit"),
        name="scoring_schema_update",
    ),
    path(
        "competicio/<int:pk>/aparells/<int:app_id>/eliminar/",
        competition_view(CompeticioAparellDeleteView.as_view(), "scoring.edit"),
        name="competicio_aparell_delete",
    ),
    path(
        "competicio/<int:pk>/scores/save/",
        competition_view(scoring_save, "scoring.edit"),
        name="scoring_save",
    ),
    path(
        "scoring/<int:pk>/save-partial/",
        competition_view(scoring_save_partial, "scoring.edit"),
        name="scoring_save_partial",
    ),
    path(
        "scoring/<int:pk>/updates/",
        competition_view(scoring_updates, "scoring.view"),
        name="scoring_updates",
    ),
    path(
        "scoring/<int:pk>/media/context/",
        competition_view(scoring_media_context, "scoring.view"),
        name="scoring_media_context",
    ),
    path(
        "scoring/<int:pk>/media/files/<int:media_id>/",
        competition_view(scoring_media_file, "scoring.view"),
        name="scoring_media_file",
    ),
    path(
        "scoring/<int:pk>/media/judge-video/<str:video_kind>/<int:video_id>/",
        competition_view(scoring_judge_video_file, "scoring.view"),
        name="scoring_judge_video_file",
    ),
]
