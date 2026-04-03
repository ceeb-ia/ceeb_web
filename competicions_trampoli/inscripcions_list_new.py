"""Compatibility facade for the extracted inscripcions backend.

The real runtime implementation now lives in the dedicated
`views_inscripcions_*` modules plus `inscripcions_views_shared`.
"""

from .inscripcions_views_shared import InscripcionsListView
from .views_inscripcions_groups import (
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
)
from .views_inscripcions_listing import (
    InscripcionsListNewView,
    get_available_table_columns,
    get_selected_table_columns,
    inscripcions_save_birth_year_range_config,
    inscripcions_save_table_columns,
    inscripcions_set_aparells,
    inscripcions_set_group_name,
)
from .views_inscripcions_media import (
    _get_media_matching_config,
    _serialize_media_item,
    inscripcions_media_delete,
    inscripcions_media_match_apply,
    inscripcions_media_match_preview,
    inscripcions_media_set_primary,
    inscripcions_media_upload,
)

__all__ = [
    "InscripcionsListNewView",
    "InscripcionsListView",
    "_get_media_matching_config",
    "_serialize_media_item",
    "get_available_table_columns",
    "get_selected_table_columns",
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
    "inscripcions_media_delete",
    "inscripcions_media_match_apply",
    "inscripcions_media_match_preview",
    "inscripcions_media_set_primary",
    "inscripcions_media_upload",
    "inscripcions_save_birth_year_range_config",
    "inscripcions_save_table_columns",
    "inscripcions_set_aparells",
    "inscripcions_set_group_name",
]
