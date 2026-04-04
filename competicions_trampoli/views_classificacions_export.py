"""Compatibility wrapper for classificacions export entrypoints."""

from .views.classificacions.export import (
    classificacions_live_export_excel,
    compute_classificacio,
)

__all__ = [
    "classificacions_live_export_excel",
    "compute_classificacio",
]
