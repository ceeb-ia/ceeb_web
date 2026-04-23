"""Small ORM-facing helpers extracted from legacy classificacions code."""

from django.db import models


def is_relational_field(model_cls, field_name: str) -> bool:
    try:
        field = model_cls._meta.get_field(field_name)
        return isinstance(field, (models.ForeignKey, models.OneToOneField))
    except Exception:
        return False


def filter_in(qs, model_cls, field_name: str, ids: list):
    if not ids:
        return qs
    if is_relational_field(model_cls, field_name):
        return qs.filter(**{f"{field_name}_id__in": ids})
    return qs.filter(**{f"{field_name}__in": ids})


def display_value(instance, field_name: str) -> str:
    value = getattr(instance, field_name, None)
    if value is None:
        return ""
    if hasattr(value, "_meta"):
        return getattr(value, "nom", None) or str(value)
    return str(value)


__all__ = [
    "display_value",
    "filter_in",
    "is_relational_field",
]
