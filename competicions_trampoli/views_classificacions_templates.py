"""Compatibility wrapper for classificacions competition-template entrypoints."""

from .views.classificacions.templates import (
    classificacio_template_apply,
    classificacio_template_list,
    classificacio_template_save,
    classificacio_template_validate,
)

__all__ = [
    "classificacio_template_apply",
    "classificacio_template_list",
    "classificacio_template_save",
    "classificacio_template_validate",
]
