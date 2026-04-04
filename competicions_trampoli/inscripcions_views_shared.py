"""Compatibility facade for legacy shared inscripcions imports."""

from .views.inscripcions.base import (
    InscripcionsImportExcelView,
    InscripcionsListView,
    _normalize_competition_order_tail_flag,
    assign_groups_balanced,
    assign_groups_k,
)
from .services.inscripcions.export import (
    LEGACY_EXCEL_COL_MAP,
    get_available_excel_columns,
    get_excel_export_value,
)
from .services.inscripcions.groups import (
    _persist_group_suggested_names,
    _programmed_groups_emptied_by_move,
    renumber_groups_for_competicio,
    sync_stable_groups_from_legacy,
)
from .services.inscripcions.queries import (
    _attach_base_equip_runtime,
    _message_for_emptied_programmed_groups,
    competicio_has_rotacions,
)
from .services.inscripcions.sorting import (
    _split_custom_sort_tokens,
    arrow_positions,
    clear_inscripcions_sort_state_for_competicio,
    recalcular_ordre_sortida,
    set_competicio_custom_sort_order_values,
    shuffle_ordre_sortida,
    sort_records_by_field_stable,
)

__all__ = [
    "InscripcionsImportExcelView",
    "InscripcionsListView",
    "LEGACY_EXCEL_COL_MAP",
    "_attach_base_equip_runtime",
    "_message_for_emptied_programmed_groups",
    "_normalize_competition_order_tail_flag",
    "_persist_group_suggested_names",
    "_programmed_groups_emptied_by_move",
    "_split_custom_sort_tokens",
    "arrow_positions",
    "assign_groups_balanced",
    "assign_groups_k",
    "clear_inscripcions_sort_state_for_competicio",
    "competicio_has_rotacions",
    "get_available_excel_columns",
    "get_excel_export_value",
    "recalcular_ordre_sortida",
    "renumber_groups_for_competicio",
    "set_competicio_custom_sort_order_values",
    "shuffle_ordre_sortida",
    "sort_records_by_field_stable",
    "sync_stable_groups_from_legacy",
]
