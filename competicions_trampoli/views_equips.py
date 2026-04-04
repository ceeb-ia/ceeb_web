"""Compatibility wrapper for inscripcions equips views."""

from .views.inscripcions.equips import (
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

__all__ = [
    "equip_context_create",
    "equip_context_delete",
    "equip_context_rename",
    "equip_context_sources_save",
    "equips_assign",
    "equips_auto_create",
    "equips_create_manual",
    "equips_delete",
    "equips_delete_all",
    "equips_delete_empty",
    "equips_preview",
    "equips_rename",
    "equips_unassign",
    "equips_workspace",
]
