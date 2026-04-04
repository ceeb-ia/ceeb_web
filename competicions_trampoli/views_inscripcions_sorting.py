"""Compatibility wrapper for inscripcions sorting views."""

from .views.inscripcions.sorting import (
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
    "inscripcions_filter_values",
    "inscripcions_history_redo",
    "inscripcions_history_undo",
    "inscripcions_sort_apply",
    "inscripcions_sort_clear",
    "inscripcions_sort_competition_tail_toggle",
    "inscripcions_sort_custom_save",
    "inscripcions_sort_custom_values",
    "inscripcions_sort_remove",
    "inscripcions_sort_undo",
]
