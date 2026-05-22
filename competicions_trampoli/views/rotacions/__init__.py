"""Canonical HTTP entrypoints for the rotacions domain."""

from .assignments import rotacions_save
from .estacions import estacio_delete, estacio_descans_create, estacions_reorder
from .export import (
    franges_export_excel,
    rotacions_export_logo_clear,
    rotacions_export_logo_upload,
    rotacions_export_meta_save,
)
from .franges import (
    franges_auto_create,
    franja_create,
    franja_delete,
    franja_insert_after,
    franges_reorder,
    franges_reorder_visual,
    franja_order_mode_set,
    franja_update_inline,
    rotacions_franja_note_save,
    rotacions_franges_bulk_clear,
    rotacions_franges_bulk_delete,
    rotacions_franges_bulk_duplicate,
    rotacions_franges_bulk_duration,
    rotacions_franges_bulk_shift,
    rotacions_franges_bulk_update,
    rotacions_clear_all,
    rotacions_extrapolar,
    rotacions_validate_program,
)
from .planner import rotacions_out_of_program_visibility_save, rotacions_planner

__all__ = [
    "estacio_delete",
    "estacio_descans_create",
    "estacions_reorder",
    "franges_auto_create",
    "franges_export_excel",
    "franja_create",
    "franja_delete",
    "franja_insert_after",
    "franges_reorder",
    "franges_reorder_visual",
    "franja_order_mode_set",
    "franja_update_inline",
    "rotacions_franja_note_save",
    "rotacions_franges_bulk_clear",
    "rotacions_franges_bulk_delete",
    "rotacions_franges_bulk_duplicate",
    "rotacions_franges_bulk_duration",
    "rotacions_franges_bulk_shift",
    "rotacions_franges_bulk_update",
    "rotacions_clear_all",
    "rotacions_extrapolar",
    "rotacions_validate_program",
    "rotacions_export_logo_clear",
    "rotacions_export_logo_upload",
    "rotacions_export_meta_save",
    "rotacions_out_of_program_visibility_save",
    "rotacions_planner",
    "rotacions_save",
]
