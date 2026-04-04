"""Compatibility wrapper for inscripcions team series views."""

from .views.inscripcions.team_series import (
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

__all__ = [
    "series_assign",
    "series_create",
    "series_delete",
    "series_delete_empty",
    "series_detail",
    "series_preview",
    "series_rename",
    "series_reorder",
    "series_start_list_export",
    "series_unassign",
    "series_work_sheet_export",
    "series_workspace",
]
