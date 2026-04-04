"""Compatibility wrapper for inscripcions group views."""

from .views.inscripcions.groups import (
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

__all__ = [
    "groups_assign",
    "groups_create",
    "groups_delete",
    "groups_delete_all",
    "groups_delete_empty",
    "groups_detail",
    "groups_preview",
    "groups_unassign",
    "groups_workspace",
    "inscripcions_group_competition_order_preview",
    "inscripcions_groups_from_sort",
    "inscripcions_merge_tabs",
    "inscripcions_reorder",
    "inscripcions_save_group_competition_order",
]
