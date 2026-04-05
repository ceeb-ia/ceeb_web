from django.urls import path

from .base import competition_view
from ..views.inscripcions.base import InscripcionsImportExcelView
from ..views.inscripcions.crud import (
    InscripcioCreateView,
    InscripcioDeleteView,
    InscripcioUpdateView,
)
from ..views.inscripcions.equips import (
    equip_context_create,
    equip_context_delete,
    equip_context_rename,
    equip_context_sources_save,
    equips_assign,
    equips_auto_create,
    equips_create_manual,
    equips_delete,
    equips_delete_all,
    equips_delete_empty,
    equips_preview,
    equips_rename,
    equips_unassign,
    equips_workspace,
)
from ..views.inscripcions.groups import (
    groups_assign,
    groups_create,
    groups_delete,
    groups_delete_all,
    groups_delete_empty,
    groups_detail,
    groups_preview,
    groups_unassign,
    groups_workspace,
    inscripcions_group_competition_order_preview,
    inscripcions_groups_from_sort,
    inscripcions_merge_tabs,
    inscripcions_reorder,
    inscripcions_save_group_competition_order,
)
from ..views.inscripcions.listing import (
    InscripcionsListNewView,
    inscripcions_save_birth_year_range_config,
    inscripcions_save_table_columns as inscripcions_save_table_columns_new,
    inscripcions_set_aparells as inscripcions_set_aparells_new,
    inscripcions_set_group_name as inscripcions_set_group_name_new,
)
from ..views.inscripcions.media import (
    inscripcions_media_delete,
    inscripcions_media_file,
    inscripcions_media_match_apply,
    inscripcions_media_match_preview,
    inscripcions_media_set_primary,
    inscripcions_media_upload,
)
from ..views.inscripcions.sorting import (
    inscripcions_filter_values,
    inscripcions_history_redo,
    inscripcions_history_undo,
    inscripcions_sort_apply,
    inscripcions_sort_clear,
    inscripcions_sort_competition_tail_toggle,
    inscripcions_sort_custom_save,
    inscripcions_sort_custom_values,
    inscripcions_sort_remove,
    inscripcions_sort_undo,
)
from ..views.inscripcions.team_series import (
    series_assign,
    series_create,
    series_delete,
    series_delete_empty,
    series_detail,
    series_preview,
    series_rename,
    series_reorder,
    series_start_list_export,
    series_unassign,
    series_work_sheet_export,
    series_workspace,
)


urlpatterns = [
    path(
        "competicions/<int:pk>/importar/",
        competition_view(InscripcionsImportExcelView.as_view(), "inscripcions.edit"),
        name="import",
    ),
    path(
        "competicions/<int:pk>/inscripcions/",
        competition_view(InscripcionsListNewView.as_view(), "inscripcions.view"),
        name="inscripcions_list",
    ),
    path(
        "competicio/<int:pk>/inscripcions/reorder/",
        competition_view(inscripcions_reorder, "inscripcions.edit"),
        name="inscripcions_reorder",
    ),
    path(
        "competicio/<int:pk>/inscripcions/save-group-competition-order/",
        competition_view(inscripcions_save_group_competition_order, "inscripcions.edit"),
        name="inscripcions_save_group_competition_order",
    ),
    path(
        "competicio/<int:pk>/inscripcions/group-competition-order/preview/",
        competition_view(inscripcions_group_competition_order_preview, "inscripcions.view"),
        name="inscripcions_group_competition_order_preview",
    ),
    path(
        "competicio/<int:pk>/groups/workspace/",
        competition_view(groups_workspace, "inscripcions.view"),
        name="groups_workspace",
    ),
    path(
        "competicio/<int:pk>/groups/detail/",
        competition_view(groups_detail, "inscripcions.view"),
        name="groups_detail",
    ),
    path(
        "competicio/<int:pk>/groups/preview/",
        competition_view(groups_preview, "inscripcions.view"),
        name="groups_preview",
    ),
    path(
        "competicio/<int:pk>/groups/create/",
        competition_view(groups_create, "inscripcions.edit"),
        name="groups_create",
    ),
    path(
        "competicio/<int:pk>/groups/assign/",
        competition_view(groups_assign, "inscripcions.edit"),
        name="groups_assign",
    ),
    path(
        "competicio/<int:pk>/groups/unassign/",
        competition_view(groups_unassign, "inscripcions.edit"),
        name="groups_unassign",
    ),
    path(
        "competicio/<int:pk>/groups/delete/",
        competition_view(groups_delete, "inscripcions.edit"),
        name="groups_delete",
    ),
    path(
        "competicio/<int:pk>/groups/delete-all/",
        competition_view(groups_delete_all, "inscripcions.edit"),
        name="groups_delete_all",
    ),
    path(
        "competicio/<int:pk>/groups/delete-empty/",
        competition_view(groups_delete_empty, "inscripcions.edit"),
        name="groups_delete_empty",
    ),
    path(
        "competicio/<int:pk>/inscripcions/groups/workspace/",
        competition_view(groups_workspace, "inscripcions.view"),
        name="groups_workspace_legacy",
    ),
    path(
        "competicio/<int:pk>/inscripcions/groups/detail/",
        competition_view(groups_detail, "inscripcions.view"),
        name="groups_detail_legacy",
    ),
    path(
        "competicio/<int:pk>/inscripcions/groups/preview/",
        competition_view(groups_preview, "inscripcions.view"),
        name="groups_preview_legacy",
    ),
    path(
        "competicio/<int:pk>/inscripcions/groups/create/",
        competition_view(groups_create, "inscripcions.edit"),
        name="groups_create_legacy",
    ),
    path(
        "competicio/<int:pk>/inscripcions/groups/assign/",
        competition_view(groups_assign, "inscripcions.edit"),
        name="groups_assign_legacy",
    ),
    path(
        "competicio/<int:pk>/inscripcions/groups/unassign/",
        competition_view(groups_unassign, "inscripcions.edit"),
        name="groups_unassign_legacy",
    ),
    path(
        "competicio/<int:pk>/inscripcions/groups/delete/",
        competition_view(groups_delete, "inscripcions.edit"),
        name="groups_delete_legacy",
    ),
    path(
        "competicio/<int:pk>/inscripcions/groups/delete-all/",
        competition_view(groups_delete_all, "inscripcions.edit"),
        name="groups_delete_all_legacy",
    ),
    path(
        "competicio/<int:pk>/inscripcions/groups/delete-empty/",
        competition_view(groups_delete_empty, "inscripcions.edit"),
        name="groups_delete_empty_legacy",
    ),
    path(
        "competicio/<int:pk>/inscripcions/sort-apply/",
        competition_view(inscripcions_sort_apply, "inscripcions.edit"),
        name="inscripcions_sort_apply",
    ),
    path(
        "competicio/<int:pk>/inscripcions/sort-remove/",
        competition_view(inscripcions_sort_remove, "inscripcions.edit"),
        name="inscripcions_sort_remove",
    ),
    path(
        "competicio/<int:pk>/inscripcions/sort-clear/",
        competition_view(inscripcions_sort_clear, "inscripcions.edit"),
        name="inscripcions_sort_clear",
    ),
    path(
        "competicio/<int:pk>/inscripcions/sort-competition-tail/",
        competition_view(inscripcions_sort_competition_tail_toggle, "inscripcions.edit"),
        name="inscripcions_sort_competition_tail_toggle",
    ),
    path(
        "competicio/<int:pk>/inscripcions/filter-values/",
        competition_view(inscripcions_filter_values, "inscripcions.view"),
        name="inscripcions_filter_values",
    ),
    path(
        "competicio/<int:pk>/inscripcions/sort-custom/values/",
        competition_view(inscripcions_sort_custom_values, "inscripcions.edit"),
        name="inscripcions_sort_custom_values",
    ),
    path(
        "competicio/<int:pk>/inscripcions/sort-custom/save/",
        competition_view(inscripcions_sort_custom_save, "inscripcions.edit"),
        name="inscripcions_sort_custom_save",
    ),
    path(
        "competicio/<int:pk>/inscripcions/history/undo/",
        competition_view(inscripcions_history_undo, "inscripcions.edit"),
        name="inscripcions_history_undo",
    ),
    path(
        "competicio/<int:pk>/inscripcions/history/redo/",
        competition_view(inscripcions_history_redo, "inscripcions.edit"),
        name="inscripcions_history_redo",
    ),
    path(
        "competicio/<int:pk>/inscripcions/sort-undo/",
        competition_view(inscripcions_sort_undo, "inscripcions.edit"),
        name="inscripcions_sort_undo",
    ),
    path(
        "competicio/<int:pk>/inscripcions/groups-from-sort/",
        competition_view(inscripcions_groups_from_sort, "inscripcions.edit"),
        name="inscripcions_groups_from_sort",
    ),
    path(
        "competicio/<int:pk>/inscripcions/save-table-columns/",
        competition_view(inscripcions_save_table_columns_new, "inscripcions.edit"),
        name="inscripcions_save_table_columns",
    ),
    path(
        "competicio/<int:pk>/inscripcions/save-birth-year-range-config/",
        competition_view(inscripcions_save_birth_year_range_config, "inscripcions.edit"),
        name="inscripcions_save_birth_year_range_config",
    ),
    path(
        "competicio/<int:pk>/inscripcions/set-group-name/",
        competition_view(inscripcions_set_group_name_new, "inscripcions.edit"),
        name="inscripcions_set_group_name",
    ),
    path(
        "competicio/<int:pk>/inscripcions/set-aparells/",
        competition_view(inscripcions_set_aparells_new, "inscripcions.edit"),
        name="inscripcions_set_aparells",
    ),
    path(
        "competicio/<int:pk>/inscripcions/media/upload/",
        competition_view(inscripcions_media_upload, "inscripcions.edit"),
        name="inscripcions_media_upload",
    ),
    path(
        "competicio/<int:pk>/inscripcions/media/delete/",
        competition_view(inscripcions_media_delete, "inscripcions.edit"),
        name="inscripcions_media_delete",
    ),
    path(
        "competicio/<int:pk>/inscripcions/media/set-primary/",
        competition_view(inscripcions_media_set_primary, "inscripcions.edit"),
        name="inscripcions_media_set_primary",
    ),
    path(
        "competicio/<int:pk>/inscripcions/media/match-preview/",
        competition_view(inscripcions_media_match_preview, "inscripcions.view"),
        name="inscripcions_media_match_preview",
    ),
    path(
        "competicio/<int:pk>/inscripcions/media/match-apply/",
        competition_view(inscripcions_media_match_apply, "inscripcions.edit"),
        name="inscripcions_media_match_apply",
    ),
    path(
        "competicio/<int:pk>/inscripcions/equips/preview/",
        competition_view(equips_preview, "inscripcions.view"),
        name="inscripcions_equips_preview",
    ),
    path(
        "competicio/<int:pk>/inscripcions/equips/workspace/",
        competition_view(equips_workspace, "inscripcions.view"),
        name="inscripcions_equips_workspace",
    ),
    path(
        "competicio/<int:pk>/inscripcions/equips/auto-create/",
        competition_view(equips_auto_create, "inscripcions.edit"),
        name="inscripcions_equips_auto_create",
    ),
    path(
        "competicio/<int:pk>/inscripcions/equips/create/",
        competition_view(equips_create_manual, "inscripcions.edit"),
        name="inscripcions_equips_create_manual",
    ),
    path(
        "competicio/<int:pk>/inscripcions/equips/assign/",
        competition_view(equips_assign, "inscripcions.edit"),
        name="inscripcions_equips_assign",
    ),
    path(
        "competicio/<int:pk>/inscripcions/equips/unassign/",
        competition_view(equips_unassign, "inscripcions.edit"),
        name="inscripcions_equips_unassign",
    ),
    path(
        "competicio/<int:pk>/inscripcions/equips/contexts/create/",
        competition_view(equip_context_create, "inscripcions.edit"),
        name="inscripcions_equip_context_create",
    ),
    path(
        "competicio/<int:pk>/inscripcions/equips/contexts/<slug:context_code>/rename/",
        competition_view(equip_context_rename, "inscripcions.edit"),
        name="inscripcions_equip_context_rename",
    ),
    path(
        "competicio/<int:pk>/inscripcions/equips/contexts/<slug:context_code>/delete/",
        competition_view(equip_context_delete, "inscripcions.edit"),
        name="inscripcions_equip_context_delete",
    ),
    path(
        "competicio/<int:pk>/inscripcions/equips/contexts/sources/save/",
        competition_view(equip_context_sources_save, "inscripcions.edit"),
        name="inscripcions_equip_context_sources_save",
    ),
    path(
        "competicio/<int:pk>/inscripcions/equips/<int:equip_id>/rename/",
        competition_view(equips_rename, "inscripcions.edit"),
        name="inscripcions_equips_rename",
    ),
    path(
        "competicio/<int:pk>/inscripcions/equips/<int:equip_id>/delete/",
        competition_view(equips_delete, "inscripcions.edit"),
        name="inscripcions_equips_delete",
    ),
    path(
        "competicio/<int:pk>/inscripcions/equips/delete-all/",
        competition_view(equips_delete_all, "inscripcions.edit"),
        name="inscripcions_equips_delete_all",
    ),
    path(
        "competicio/<int:pk>/inscripcions/equips/delete-empty/",
        competition_view(equips_delete_empty, "inscripcions.edit"),
        name="inscripcions_equips_delete_empty",
    ),
    path(
        "competicio/<int:pk>/inscripcions/series-equips/workspace/",
        competition_view(series_workspace, "inscripcions.view"),
        name="inscripcions_series_equips_workspace",
    ),
    path(
        "competicio/<int:pk>/inscripcions/series-equips/detail/",
        competition_view(series_detail, "inscripcions.view"),
        name="inscripcions_series_equips_detail",
    ),
    path(
        "competicio/<int:pk>/inscripcions/series-equips/preview/",
        competition_view(series_preview, "inscripcions.view"),
        name="inscripcions_series_equips_preview",
    ),
    path(
        "competicio/<int:pk>/inscripcions/series-equips/create/",
        competition_view(series_create, "inscripcions.edit"),
        name="inscripcions_series_equips_create",
    ),
    path(
        "competicio/<int:pk>/inscripcions/series-equips/assign/",
        competition_view(series_assign, "inscripcions.edit"),
        name="inscripcions_series_equips_assign",
    ),
    path(
        "competicio/<int:pk>/inscripcions/series-equips/unassign/",
        competition_view(series_unassign, "inscripcions.edit"),
        name="inscripcions_series_equips_unassign",
    ),
    path(
        "competicio/<int:pk>/inscripcions/series-equips/delete/",
        competition_view(series_delete, "inscripcions.edit"),
        name="inscripcions_series_equips_delete",
    ),
    path(
        "competicio/<int:pk>/inscripcions/series-equips/delete-empty/",
        competition_view(series_delete_empty, "inscripcions.edit"),
        name="inscripcions_series_equips_delete_empty",
    ),
    path(
        "competicio/<int:pk>/inscripcions/series-equips/rename/",
        competition_view(series_rename, "inscripcions.edit"),
        name="inscripcions_series_equips_rename",
    ),
    path(
        "competicio/<int:pk>/inscripcions/series-equips/reorder/",
        competition_view(series_reorder, "inscripcions.edit"),
        name="inscripcions_series_equips_reorder",
    ),
    path(
        "competicio/<int:pk>/inscripcions/series-equips/start-list.xlsx",
        competition_view(series_start_list_export, "inscripcions.view"),
        name="inscripcions_series_equips_start_list_export",
    ),
    path(
        "competicio/<int:pk>/inscripcions/series-equips/work-sheet.xlsx",
        competition_view(series_work_sheet_export, "inscripcions.view"),
        name="inscripcions_series_equips_work_sheet_export",
    ),
    path(
        "competicio/<int:pk>/inscripcio/<int:ins_id>/editar/",
        competition_view(InscripcioUpdateView.as_view(), "inscripcions.edit"),
        name="inscripcio_edit",
    ),
    path(
        "competicio/<int:pk>/inscripcio/<int:ins_id>/eliminar/",
        competition_view(InscripcioDeleteView.as_view(), "inscripcions.edit"),
        name="inscripcio_delete",
    ),
    path(
        "competicio/<int:pk>/inscripcio/nova/",
        competition_view(InscripcioCreateView.as_view(), "inscripcions.edit"),
        name="inscripcio_add",
    ),
    path(
        "competicio/<int:pk>/inscripcions/merge-tabs/",
        competition_view(inscripcions_merge_tabs, "inscripcions.edit"),
        name="inscripcions_merge_tabs",
    ),
    path(
        "competicio/<int:pk>/inscripcions/media/files/<int:media_id>/",
        competition_view(inscripcions_media_file, "inscripcions.view"),
        name="inscripcions_media_file",
    ),
]
