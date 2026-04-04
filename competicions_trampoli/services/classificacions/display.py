"""Stable public boundary for classification display helpers."""

from ._display_bridge import get_display_columns as _get_display_columns


def get_display_columns(*args, **kwargs):
    return _get_display_columns(*args, **kwargs)

__all__ = ["get_display_columns"]
