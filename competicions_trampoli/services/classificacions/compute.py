"""Stable public boundary for classification computation."""

from ._compute_bridge import DEFAULT_SCHEMA as _DEFAULT_SCHEMA
from ._compute_bridge import compute_classificacio as _compute_classificacio


DEFAULT_SCHEMA = _DEFAULT_SCHEMA


def compute_classificacio(*args, **kwargs):
    return _compute_classificacio(*args, **kwargs)

__all__ = ["DEFAULT_SCHEMA", "compute_classificacio"]
