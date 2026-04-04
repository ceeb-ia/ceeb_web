"""Compatibility facade for legacy inscripcions imports.

This package re-exports stable entrypoints from the extracted inscripcions
modules. Runtime routes no longer depend on the old top-level `views.py` file.
"""

from .inscripcions.base import InscripcionsImportExcelView, InscripcionsListView
from ..services.inscripcions.groups import renumber_groups_for_competicio
from ..services.inscripcions.history import (
    apply_inscripcions_history_snapshot,
    capture_inscripcions_history_snapshot,
)
from ..services.inscripcions.queries import (
    COLUMN_FILTER_EMPTY_TOKEN,
    _build_inscripcions_filtered_qs,
    _resolve_group_creation_buckets,
    build_inscripcions_sort_context_key,
    get_competicio_custom_sort_rank_map,
)
from ..services.inscripcions.sorting import (
    _split_custom_sort_tokens,
    sort_records_by_field_stable,
)
from .inscripcions.groups import (
    inscripcions_groups_from_sort,
    inscripcions_merge_tabs,
    inscripcions_reorder,
    inscripcions_save_group_competition_order,
)
from .inscripcions.media import inscripcions_media_file
from .inscripcions.sorting import (
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

__all__ = [
    "COLUMN_FILTER_EMPTY_TOKEN",
    "InscripcionsImportExcelView",
    "InscripcionsListView",
    "_build_inscripcions_filtered_qs",
    "_resolve_group_creation_buckets",
    "_split_custom_sort_tokens",
    "apply_inscripcions_history_snapshot",
    "build_inscripcions_sort_context_key",
    "capture_inscripcions_history_snapshot",
    "get_competicio_custom_sort_rank_map",
    "inscripcions_filter_values",
    "inscripcions_groups_from_sort",
    "inscripcions_history_redo",
    "inscripcions_history_undo",
    "inscripcions_media_file",
    "inscripcions_merge_tabs",
    "inscripcions_reorder",
    "inscripcions_save_group_competition_order",
    "inscripcions_sort_apply",
    "inscripcions_sort_clear",
    "inscripcions_sort_competition_tail_toggle",
    "inscripcions_sort_custom_save",
    "inscripcions_sort_custom_values",
    "inscripcions_sort_remove",
    "inscripcions_sort_undo",
    "renumber_groups_for_competicio",
    "sort_records_by_field_stable",
]
