"""Stable compatibility boundary for classification computation.

The real implementation still lives in the legacy monolith. This module keeps
the public entrypoints explicit so the rest of the package can depend on a
single import path while the internals are being decomposed.
"""

from ..services_classificacions_2 import DEFAULT_SCHEMA as _DEFAULT_SCHEMA
from ..services_classificacions_2 import compute_classificacio as _compute_classificacio


DEFAULT_SCHEMA = _DEFAULT_SCHEMA


def compute_classificacio(*args, **kwargs):
    return _compute_classificacio(*args, **kwargs)

__all__ = ["DEFAULT_SCHEMA", "compute_classificacio"]
