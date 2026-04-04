"""Compatibility wrapper for inscripcions CRUD views."""

from .views.inscripcions.crud import (
    InscripcioCreateView,
    InscripcioDeleteView,
    InscripcioFormViewMixin,
    InscripcioUpdateView,
)

__all__ = [
    "InscripcioCreateView",
    "InscripcioDeleteView",
    "InscripcioFormViewMixin",
    "InscripcioUpdateView",
]
