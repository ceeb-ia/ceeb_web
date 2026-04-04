"""Compatibility wrapper for classificacions global-template entrypoints."""

from .views.classificacions.global_templates import (
    ClassificacioTemplateGlobalBuilder,
    ClassificacioTemplateGlobalDeleteView,
    ClassificacioTemplateGlobalList,
    classificacio_template_global_save,
)

__all__ = [
    "ClassificacioTemplateGlobalBuilder",
    "ClassificacioTemplateGlobalDeleteView",
    "ClassificacioTemplateGlobalList",
    "classificacio_template_global_save",
]
