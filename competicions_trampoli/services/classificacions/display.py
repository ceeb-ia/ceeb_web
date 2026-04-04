"""Compatibility boundary for classification display helpers."""

from ..services_classificacions_2 import get_display_columns as _get_display_columns


def get_display_columns(*args, **kwargs):
    return _get_display_columns(*args, **kwargs)

__all__ = ["get_display_columns"]
