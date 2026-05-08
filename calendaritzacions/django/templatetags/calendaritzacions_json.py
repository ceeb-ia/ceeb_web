"""Small template filters for calendaritzacions templates."""

from __future__ import annotations

import json
from pathlib import Path

from django import template


register = template.Library()


@register.filter
def json_pretty(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    except TypeError:
        return str(value)


@register.filter
def dict_get(value, key):
    if isinstance(value, dict):
        return value.get(key)
    return None


@register.filter
def audit_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " · ".join(audit_cell(item) for item in value if item not in (None, ""))
    if isinstance(value, tuple):
        return " · ".join(audit_cell(item) for item in value if item not in (None, ""))
    if isinstance(value, dict):
        return " | ".join(f"{key}: {audit_cell(item)}" for key, item in value.items())
    return str(value)


@register.filter
def basename(value) -> str:
    if not value:
        return ""
    return Path(str(value)).name
