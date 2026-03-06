from django.contrib.auth.decorators import login_required
from django.urls import path

from competicions_trampoli import views, views_judge_admin, views_rotacions, views_scoring

from .access import require_competicio_capability
from .inscripcions_list_new import (
    InscripcionsListNewView,
    inscripcions_save_table_columns as inscripcions_save_table_columns_new,
    inscripcions_set_aparells as inscripcions_set_aparells_new,
    inscripcions_set_group_name as inscripcions_set_group_name_new,
)
from .views import CompeticioCreateView, CompeticioDeleteView, CompeticioHomeView, CompeticioListView, InscripcionsImportExcelView
from .views_classificacions import (
    ClassificacionsHome,
    ClassificacionsLive,
    ClassificacionsLoopLive,
    PublicClassificacionsLive,
    PublicClassificacionsLoopLive,
    classificacio_template_apply,
    classificacio_template_list,
    classificacio_template_save,
    classificacio_template_validate,
    classificacio_delete,
    classificacio_preview,
    classificacio_reorder,
    classificacio_save,
    classificacions_live_export_excel,
    classificacions_live_data,
    public_classificacions_live_data,
)
from .views_equips import (
    equips_assign,
    equips_auto_create,
    equips_create_manual,
    equips_delete,
    equips_delete_all,
    equips_preview,
    equips_rename,
    equips_unassign,
)
from .views_scoring import ScoringNotesHome, ScoringSchemaUpdate, scoring_save
from .views_trampoli import (
    AparellCreate,
    AparellList,
    AparellUpdate,
    CompeticioAparellCreate,
    CompeticioAparellDeleteView,
    CompeticioAparellUpdate,
    ConfiguracioCompeticio,
    TrampoliAparellList,
    TrampoliNotesHome,
    trampoli_guardar_nota,
)
from . import views_judge


def competition_view(view, capability, competicio_kwarg="pk"):
    return login_required(
        require_competicio_capability(capability, competicio_kwarg=competicio_kwarg)(view)
    )


def authenticated_view(view):
    return login_required(view)


urlpatterns = [
    path("trampoli/aparells/", authenticated_view(AparellList.as_view()), name="aparells_list"),
    path("trampoli/aparells/nou/", authenticated_view(AparellCreate.as_view()), name="aparell_create"),
    path("trampoli/aparells/<int:pk>/editar/", authenticated_view(AparellUpdate.as_view()), name="aparell_update"),
    path("trampoli/aparells/<int:pk>/puntuacio/", authenticated_view(ScoringSchemaUpdate.as_view()), name="aparell_scoring_schema_update"),

    path("competicions/nova/", authenticated_view(CompeticioCreateView.as_view()), name="create"),
    path("competicions/created/", authenticated_view(CompeticioListView.as_view()), name="created"),
    path("competicions/", authenticated_view(CompeticioHomeView.as_view()), name="competicions_home"),

    path("competicions/<int:pk>/importar/", competition_view(InscripcionsImportExcelView.as_view(), "inscripcions.edit"), name="import"),
    path("competicions/<int:pk>/inscripcions/", competition_view(InscripcionsListNewView.as_view(), "inscripcions.view"), name="inscripcions_list"),
    path("competicions/<int:pk>/delete/", competition_view(CompeticioDeleteView.as_view(), "competition.delete"), name="delete"),

    path("competicio/<int:pk>/inscripcions/reorder/", competition_view(views.inscripcions_reorder, "inscripcions.edit"), name="inscripcions_reorder"),
    path("competicio/<int:pk>/inscripcions/sort-apply/", competition_view(views.inscripcions_sort_apply, "inscripcions.edit"), name="inscripcions_sort_apply"),
    path("competicio/<int:pk>/inscripcions/sort-remove/", competition_view(views.inscripcions_sort_remove, "inscripcions.edit"), name="inscripcions_sort_remove"),
    path("competicio/<int:pk>/inscripcions/sort-clear/", competition_view(views.inscripcions_sort_clear, "inscripcions.edit"), name="inscripcions_sort_clear"),
    path("competicio/<int:pk>/inscripcions/sort-custom/values/", competition_view(views.inscripcions_sort_custom_values, "inscripcions.edit"), name="inscripcions_sort_custom_values"),
    path("competicio/<int:pk>/inscripcions/sort-custom/save/", competition_view(views.inscripcions_sort_custom_save, "inscripcions.edit"), name="inscripcions_sort_custom_save"),
    path("competicio/<int:pk>/inscripcions/sort-undo/", competition_view(views.inscripcions_sort_undo, "inscripcions.edit"), name="inscripcions_sort_undo"),
    path("competicio/<int:pk>/inscripcions/groups-from-sort/", competition_view(views.inscripcions_groups_from_sort, "inscripcions.edit"), name="inscripcions_groups_from_sort"),
    path("competicio/<int:pk>/inscripcions/save-table-columns/", competition_view(inscripcions_save_table_columns_new, "inscripcions.edit"), name="inscripcions_save_table_columns"),
    path("competicio/<int:pk>/inscripcions/set-group-name/", competition_view(inscripcions_set_group_name_new, "inscripcions.edit"), name="inscripcions_set_group_name"),
    path("competicio/<int:pk>/inscripcions/set-aparells/", competition_view(inscripcions_set_aparells_new, "inscripcions.edit"), name="inscripcions_set_aparells"),
    path("competicio/<int:pk>/inscripcions/equips/preview/", competition_view(equips_preview, "inscripcions.view"), name="inscripcions_equips_preview"),
    path("competicio/<int:pk>/inscripcions/equips/auto-create/", competition_view(equips_auto_create, "inscripcions.edit"), name="inscripcions_equips_auto_create"),
    path("competicio/<int:pk>/inscripcions/equips/create/", competition_view(equips_create_manual, "inscripcions.edit"), name="inscripcions_equips_create_manual"),
    path("competicio/<int:pk>/inscripcions/equips/assign/", competition_view(equips_assign, "inscripcions.edit"), name="inscripcions_equips_assign"),
    path("competicio/<int:pk>/inscripcions/equips/unassign/", competition_view(equips_unassign, "inscripcions.edit"), name="inscripcions_equips_unassign"),
    path("competicio/<int:pk>/inscripcions/equips/<int:equip_id>/rename/", competition_view(equips_rename, "inscripcions.edit"), name="inscripcions_equips_rename"),
    path("competicio/<int:pk>/inscripcions/equips/<int:equip_id>/delete/", competition_view(equips_delete, "inscripcions.edit"), name="inscripcions_equips_delete"),
    path("competicio/<int:pk>/inscripcions/equips/delete-all/", competition_view(equips_delete_all, "inscripcions.edit"), name="inscripcions_equips_delete_all"),
    path("competicio/<int:pk>/inscripcio/<int:ins_id>/editar/", competition_view(views.InscripcioUpdateView.as_view(), "inscripcions.edit"), name="inscripcio_edit"),
    path("competicio/<int:pk>/inscripcio/<int:ins_id>/eliminar/", competition_view(views.InscripcioDeleteView.as_view(), "inscripcions.edit"), name="inscripcio_delete"),
    path("competicio/<int:pk>/inscripcio/nova/", competition_view(views.InscripcioCreateView.as_view(), "inscripcions.edit"), name="inscripcio_add"),
    path("competicio/<int:pk>/inscripcions/merge-tabs/", competition_view(views.inscripcions_merge_tabs, "inscripcions.edit"), name="inscripcions_merge_tabs"),

    path("competicio/<int:pk>/notes/", competition_view(views.notes_home_router, "competition.view"), name="notes_home"),
    path("competicio/<int:pk>/notes/trampoli/", competition_view(TrampoliNotesHome.as_view(), "scoring.view"), name="trampoli_notes_home"),
    path("competicio/<int:pk>/notes/trampoli/configuracio/", competition_view(ConfiguracioCompeticio.as_view(), "scoring.edit"), name="trampoli_config"),
    path("competicio/<int:pk>/notes/trampoli/guardar/", competition_view(trampoli_guardar_nota, "scoring.edit"), name="trampoli_save"),
    path("competicio/<int:pk>/notes/trampoli/aparells/", competition_view(TrampoliAparellList.as_view(), "scoring.edit"), name="trampoli_aparells_list"),
    path("competicio/<int:pk>/notes/trampoli/aparells/<int:app_id>/editar/", competition_view(CompeticioAparellUpdate.as_view(), "scoring.edit"), name="trampoli_aparell_edit"),
    path("competicio/<int:pk>/notes/trampoli/aparells/nou/", competition_view(CompeticioAparellCreate.as_view(), "scoring.edit"), name="trampoli_aparell_create"),
    path("competicio/<int:pk>/notes-v2/", competition_view(ScoringNotesHome.as_view(), "scoring.view"), name="scoring_notes_home"),
    path("competicio/<int:pk>/aparell/<int:ap_id>/schema/", competition_view(ScoringSchemaUpdate.as_view(), "scoring.edit"), name="scoring_schema_update"),
    path("competicio/<int:pk>/aparells/<int:app_id>/eliminar/", competition_view(CompeticioAparellDeleteView.as_view(), "scoring.edit"), name="competicio_aparell_delete"),
    path("competicio/<int:pk>/scores/save/", competition_view(scoring_save, "scoring.edit"), name="scoring_save"),
    path("scoring/<int:pk>/save-partial/", competition_view(views_scoring.scoring_save_partial, "scoring.edit"), name="scoring_save_partial"),
    path("scoring/<int:pk>/updates/", competition_view(views_scoring.scoring_updates, "scoring.view"), name="scoring_updates"),

    path("competicio/<int:pk>/rotacions/", competition_view(views_rotacions.rotacions_planner, "rotacions.view"), name="rotacions_planner"),
    path("competicio/<int:pk>/rotacions/save/", competition_view(views_rotacions.rotacions_save, "rotacions.edit"), name="rotacions_save"),
    path("competicio/<int:pk>/rotacions/franges/auto/", competition_view(views_rotacions.franges_auto_create, "rotacions.edit"), name="rotacions_franges_auto_create"),
    path("competicio/<int:pk>/rotacions/franja/create/", competition_view(views_rotacions.franja_create, "rotacions.edit"), name="rotacions_franja_create"),
    path("competicio/<int:pk>/rotacions/franja/<int:franja_id>/delete/", competition_view(views_rotacions.franja_delete, "rotacions.edit"), name="rotacions_franja_delete"),
    path("competicio/<int:pk>/rotacions/estacio/descans/create/", competition_view(views_rotacions.estacio_descans_create, "rotacions.edit"), name="rotacions_estacio_descans_create"),
    path("competicio/<int:pk>/rotacions/estacio/<int:estacio_id>/delete/", competition_view(views_rotacions.estacio_delete, "rotacions.edit"), name="rotacions_estacio_delete"),
    path("competicio/<int:pk>/rotacions/franja/<int:franja_id>/extrapolar/", competition_view(views_rotacions.rotacions_extrapolar, "rotacions.edit"), name="rotacions_extrapolar"),
    path("competicio/<int:pk>/rotacions/estacions/reorder/", competition_view(views_rotacions.estacions_reorder, "rotacions.edit"), name="rotacions_estacions_reorder"),
    path("competicio/<int:pk>/rotacions/clear_all/", competition_view(views_rotacions.rotacions_clear_all, "rotacions.edit"), name="rotacions_clear_all"),
    path("competicio/<int:pk>/rotacions/franges/<int:franja_id>/insert_after/", competition_view(views_rotacions.franja_insert_after, "rotacions.edit"), name="rotacions_franja_insert_after"),
    path("competicio/<int:pk>/rotacions/franges/<int:franja_id>/update_inline/", competition_view(views_rotacions.franja_update_inline, "rotacions.edit"), name="rotacions_franja_update_inline"),
    path("competicio/<int:pk>/rotacions/franges/<int:franja_id>/order_mode/", competition_view(views_rotacions.franja_order_mode_set, "rotacions.edit"), name="rotacions_franja_order_mode_set"),
    path("competicio/<int:pk>/rotacions/export-meta/save/", competition_view(views_rotacions.rotacions_export_meta_save, "rotacions.edit"), name="rotacions_export_meta_save"),
    path("competicio/<int:pk>/rotacions/export-meta/logo/upload/", competition_view(views_rotacions.rotacions_export_logo_upload, "rotacions.edit"), name="rotacions_export_logo_upload"),
    path("competicio/<int:pk>/rotacions/export-meta/logo/clear/", competition_view(views_rotacions.rotacions_export_logo_clear, "rotacions.edit"), name="rotacions_export_logo_clear"),
    path("competicio/<int:pk>/rotacions/franges/export_excel/", competition_view(views_rotacions.franges_export_excel, "rotacions.view"), name="rotacions_franges_export_excel"),

    path("competicio/<int:pk>/classificacions/", competition_view(ClassificacionsHome.as_view(), "classificacions.view"), name="classificacions_home"),
    path("competicio/<int:pk>/classificacions/save/", competition_view(classificacio_save, "classificacions.edit"), name="classificacio_save"),
    path("competicio/<int:pk>/classificacions/delete/<int:cid>/", competition_view(classificacio_delete, "classificacions.edit"), name="classificacio_delete"),
    path("competicio/<int:pk>/classificacions/reorder/", competition_view(classificacio_reorder, "classificacions.edit"), name="classificacio_reorder"),
    path("competicio/<int:pk>/classificacions/preview/<int:cid>/", competition_view(classificacio_preview, "classificacions.view"), name="classificacio_preview"),
    path("competicio/<int:pk>/classificacions/templates/", competition_view(classificacio_template_list, "classificacions.view"), name="classificacio_template_list"),
    path("competicio/<int:pk>/classificacions/templates/save/", competition_view(classificacio_template_save, "classificacions.edit"), name="classificacio_template_save"),
    path("competicio/<int:pk>/classificacions/templates/validate/", competition_view(classificacio_template_validate, "classificacions.edit"), name="classificacio_template_validate"),
    path("competicio/<int:pk>/classificacions/templates/apply/", competition_view(classificacio_template_apply, "classificacions.edit"), name="classificacio_template_apply"),
    path("scoring/<int:competicio_id>/judges-qr/", competition_view(views_judge_admin.judges_qr_home, "judge_tokens.manage", competicio_kwarg="competicio_id"), name="judges_qr_home"),
    path("scoring/<int:competicio_id>/judges-qr/print/", competition_view(views_judge_admin.judges_qr_print, "judge_tokens.manage", competicio_kwarg="competicio_id"), name="judges_qr_print"),
    path("scoring/<int:competicio_id>/public-live-qr/", competition_view(views_judge_admin.public_live_qr_home, "public_live.manage", competicio_kwarg="competicio_id"), name="public_live_qr_home"),
    path("scoring/<int:competicio_id>/public-live-qr/print/", competition_view(views_judge_admin.public_live_qr_print, "public_live.manage", competicio_kwarg="competicio_id"), name="public_live_qr_print"),

    # Aquestes rutes continuen obertes per disseny: jutges i public live funcionen amb token.
    path("competicio/<int:pk>/classificacions/live/", competition_view(ClassificacionsLive.as_view(), "classificacions.view"), name="classificacions_live"),
    path("competicio/<int:pk>/classificacions/loop/", competition_view(ClassificacionsLoopLive.as_view(), "classificacions.view"), name="classificacions_loop_live"),
    path("competicio/<int:pk>/classificacions/live/data/", competition_view(classificacions_live_data, "classificacions.view"), name="classificacions_live_data"),
    path("competicio/<int:pk>/classificacions/live/export.xlsx/", competition_view(classificacions_live_export_excel, "classificacions.view"), name="classificacions_live_export_excel"),
    path("judge/<uuid:token>/", views_judge.judge_portal, name="judge_portal"),
    path("judge/<uuid:token>/qr.png", views_judge.judge_qr_png, name="judge_qr_png"),
    path("judge/<uuid:token>/api/save/", views_judge.judge_save_partial, name="judge_save_partial"),
    path("judge/<uuid:token>/api/updates/", views_judge.judge_updates, name="judge_updates"),
    path("judge/<uuid:token>/api/video/status/", views_judge.judge_video_status, name="judge_video_status"),
    path("judge/<uuid:token>/api/video/upload/", views_judge.judge_video_upload, name="judge_video_upload"),
    path("judge/<uuid:token>/api/video/delete/", views_judge.judge_video_delete, name="judge_video_delete"),
    path("public/live/<uuid:token>/", PublicClassificacionsLive.as_view(), name="public_live_portal"),
    path("public/live/<uuid:token>/loop/", PublicClassificacionsLoopLive.as_view(), name="public_live_loop"),
    path("public/live/<uuid:token>/data/", public_classificacions_live_data, name="public_live_classificacions_data"),
    path("public/live/<uuid:token>/qr.png", views_judge.public_live_qr_png, name="public_live_qr_png"),
]
