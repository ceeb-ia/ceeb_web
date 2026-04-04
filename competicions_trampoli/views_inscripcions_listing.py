"""Compatibility wrapper for inscripcions listing views."""

from .views.inscripcions.listing import (
    InscripcionsListNewView,
    get_available_table_columns,
    get_selected_table_columns,
    inscripcions_save_birth_year_range_config,
    inscripcions_save_table_columns,
    inscripcions_set_aparells,
    inscripcions_set_group_name,
)

__all__ = [
    "InscripcionsListNewView",
    "get_available_table_columns",
    "get_selected_table_columns",
    "inscripcions_save_birth_year_range_config",
    "inscripcions_save_table_columns",
    "inscripcions_set_aparells",
    "inscripcions_set_group_name",
]
