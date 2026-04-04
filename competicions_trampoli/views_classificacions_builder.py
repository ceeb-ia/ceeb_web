"""Compatibility wrapper for classificacions builder entrypoints."""

from .views.classificacions.builder import (
    ClassificacionsHome,
    classificacio_delete,
    classificacio_preview,
    classificacio_reorder,
    classificacio_save,
    compute_classificacio,
)

__all__ = [
    "ClassificacionsHome",
    "classificacio_delete",
    "classificacio_preview",
    "classificacio_reorder",
    "classificacio_save",
    "compute_classificacio",
]
