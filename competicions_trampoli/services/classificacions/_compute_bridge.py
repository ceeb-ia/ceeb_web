"""Temporary private bridge for classification compute.

This keeps the public `compute.py` boundary clean while the remaining
implementation is still being extracted from the legacy monolith.
"""

from .engine.schema import DEFAULT_SCHEMA
from .engine.orchestrator import compute_classificacio


__all__ = ["DEFAULT_SCHEMA", "compute_classificacio"]
