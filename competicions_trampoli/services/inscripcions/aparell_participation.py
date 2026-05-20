from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime
from typing import Any, Iterable

from django.db import transaction
from django.utils import timezone

from ...models import Inscripcio
from ...models.competicio import CompeticioAparell, InscripcioAparellExclusio
from .queries import COLUMN_FILTER_EMPTY_TOKEN, get_available_column_filter_fields, get_inscripcio_value


MODE_ALL = "all"
MODE_INCLUDE_MATCHING = "include_matching"
MODE_EXCLUDE_MATCHING = "exclude_matching"
VALID_MODES = {MODE_ALL, MODE_INCLUDE_MATCHING, MODE_EXCLUDE_MATCHING}

OP_IS_ANY = "is_any"
OP_IS_NOT_ANY = "is_not_any"
OP_CONTAINS = "contains"
OP_NOT_CONTAINS = "not_contains"
OP_EMPTY = "empty"
OP_NOT_EMPTY = "not_empty"
VALID_OPERATORS = {OP_IS_ANY, OP_IS_NOT_ANY, OP_CONTAINS, OP_NOT_CONTAINS, OP_EMPTY, OP_NOT_EMPTY}


def participation_operator_choices() -> list[dict[str, str]]:
    return [
        {"code": OP_IS_ANY, "label": "es un d'aquests valors"},
        {"code": OP_IS_NOT_ANY, "label": "no es cap d'aquests valors"},
        {"code": OP_CONTAINS, "label": "conte"},
        {"code": OP_NOT_CONTAINS, "label": "no conte"},
        {"code": OP_EMPTY, "label": "es buit"},
        {"code": OP_NOT_EMPTY, "label": "no es buit"},
    ]


def participation_mode_choices() -> list[dict[str, str]]:
    return [
        {"code": MODE_ALL, "label": "Totes les inscripcions competeixen"},
        {"code": MODE_INCLUDE_MATCHING, "label": "Nomes competeixen les que compleixen el filtre"},
        {"code": MODE_EXCLUDE_MATCHING, "label": "No competeixen les que compleixen el filtre"},
    ]


def available_participation_fields(competicio) -> list[dict[str, str]]:
    return [
        field
        for field in get_available_column_filter_fields(competicio)
        if field.get("code") not in {"__aparells__", "__media__", "__actions__"}
    ]


def _normalize_scalar(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _compare_key(value: Any) -> str:
    return _normalize_scalar(value).casefold()


def _split_values(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple, set)):
        values = []
        for item in raw:
            values.extend(_split_values(item))
        return values
    text = str(raw or "").replace("\r", "\n")
    chunks = []
    for line in text.split("\n"):
        chunks.extend(line.split(","))
    out = []
    seen = set()
    for chunk in chunks:
        value = chunk.strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def normalize_participation_config(raw: dict[str, Any] | None, *, allowed_field_codes: Iterable[str] | None = None) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    mode = str(data.get("mode") or MODE_ALL).strip()
    if mode not in VALID_MODES:
        mode = MODE_ALL

    allowed = {str(code) for code in allowed_field_codes or [] if str(code or "").strip()}
    filters_in = data.get("filters") if isinstance(data.get("filters"), list) else []
    filters = []
    for item in filters_in:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        if not field or (allowed and field not in allowed):
            continue
        operator = str(item.get("operator") or OP_IS_ANY).strip()
        if operator not in VALID_OPERATORS:
            operator = OP_IS_ANY
        values = _split_values(item.get("values") or item.get("value") or "")
        if operator not in {OP_EMPTY, OP_NOT_EMPTY} and not values:
            continue
        filters.append({"field": field, "operator": operator, "values": values})

    if mode == MODE_ALL:
        filters = []
    return {"mode": mode, "filters": filters}


def parse_participation_config_from_post(post, *, allowed_field_codes: Iterable[str] | None = None) -> dict[str, Any]:
    fields = post.getlist("filter_field")
    operators = post.getlist("filter_operator")
    values = post.getlist("filter_values")
    filters = []
    max_len = max(len(fields), len(operators), len(values), 0)
    for index in range(max_len):
        filters.append(
            {
                "field": fields[index] if index < len(fields) else "",
                "operator": operators[index] if index < len(operators) else OP_IS_ANY,
                "values": values[index] if index < len(values) else "",
            }
        )
    return normalize_participation_config(
        {"mode": post.get("participation_mode") or MODE_ALL, "filters": filters},
        allowed_field_codes=allowed_field_codes,
    )


def config_has_required_filters(config: dict[str, Any]) -> bool:
    return config.get("mode") == MODE_ALL or bool(config.get("filters"))


def _filter_matches(inscripcio: Inscripcio, rule: dict[str, Any]) -> bool:
    value = get_inscripcio_value(inscripcio, rule.get("field") or "")
    value_text = _normalize_scalar(value)
    value_key = value_text.casefold()
    operator = rule.get("operator")
    wanted = ["" if item == COLUMN_FILTER_EMPTY_TOKEN else _compare_key(item) for item in rule.get("values") or []]
    if operator == OP_EMPTY:
        return value_text == ""
    if operator == OP_NOT_EMPTY:
        return value_text != ""
    if operator == OP_IS_NOT_ANY:
        return value_key not in wanted
    if operator == OP_CONTAINS:
        return any(item and item in value_key for item in wanted)
    if operator == OP_NOT_CONTAINS:
        return not any(item and item in value_key for item in wanted)
    return value_key in wanted


def inscripcio_matches_participation_filters(inscripcio: Inscripcio, filters: list[dict[str, Any]]) -> bool:
    if not filters:
        return False
    return all(_filter_matches(inscripcio, rule) for rule in filters)


def participation_preview(competicio, comp_aparell: CompeticioAparell, config: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_participation_config(
        config,
        allowed_field_codes=[field["code"] for field in available_participation_fields(competicio)],
    )
    rows = list(Inscripcio.objects.filter(competicio=competicio).order_by("ordre_competicio", "ordre_sortida", "id"))
    mode = normalized.get("mode")
    filters = normalized.get("filters") or []
    included_ids = []
    excluded_ids = []
    for row in rows:
        matches = inscripcio_matches_participation_filters(row, filters)
        if mode == MODE_ALL:
            include = True
        elif mode == MODE_INCLUDE_MATCHING:
            include = matches
        else:
            include = not matches
        if include:
            included_ids.append(int(row.id))
        else:
            excluded_ids.append(int(row.id))

    current_excluded_ids = set(
        InscripcioAparellExclusio.objects.filter(comp_aparell=comp_aparell).values_list("inscripcio_id", flat=True)
    )
    return {
        "config": normalized,
        "total": len(rows),
        "included_count": len(included_ids),
        "excluded_count": len(excluded_ids),
        "included_ids": included_ids,
        "excluded_ids": excluded_ids,
        "current_excluded_count": len(current_excluded_ids),
        "will_add_exclusions_count": len(set(excluded_ids) - current_excluded_ids),
        "will_remove_exclusions_count": len(current_excluded_ids - set(excluded_ids)),
    }


def apply_participation_config(competicio, comp_aparell: CompeticioAparell, config: dict[str, Any]) -> dict[str, Any]:
    preview = participation_preview(competicio, comp_aparell, config)
    now = timezone.now()
    stored_config = {
        **preview["config"],
        "last_applied_at": now.isoformat(),
        "last_summary": {
            "total": preview["total"],
            "included_count": preview["included_count"],
            "excluded_count": preview["excluded_count"],
        },
    }
    excluded_ids = preview["excluded_ids"]
    with transaction.atomic():
        InscripcioAparellExclusio.objects.filter(comp_aparell=comp_aparell).delete()
        if excluded_ids:
            InscripcioAparellExclusio.objects.bulk_create(
                [
                    InscripcioAparellExclusio(
                        inscripcio_id=inscripcio_id,
                        comp_aparell=comp_aparell,
                        motiu="Regla de participacio",
                    )
                    for inscripcio_id in excluded_ids
                ]
            )
        comp_aparell.participation_config = stored_config
        comp_aparell.save(update_fields=["participation_config"])
    preview["config"] = stored_config
    return preview


def field_value_options(competicio, fields: list[dict[str, Any]], *, limit_per_field: int = 80) -> dict[str, list[dict[str, Any]]]:
    rows = list(Inscripcio.objects.filter(competicio=competicio).order_by("ordre_competicio", "ordre_sortida", "id"))
    out = {}
    for field in fields:
        code = field.get("code")
        if not code:
            continue
        values = OrderedDict()
        empty_count = 0
        for row in rows:
            value = get_inscripcio_value(row, code)
            text = _normalize_scalar(value)
            if text == "":
                empty_count += 1
                continue
            key = text.casefold()
            item = values.get(key)
            if item is None:
                item = {"value": text, "label": text, "count": 0}
                values[key] = item
            item["count"] += 1
        items = list(values.values())
        items.sort(key=lambda item: item["label"].casefold())
        if empty_count:
            items.append({"value": COLUMN_FILTER_EMPTY_TOKEN, "label": "(Sense valor)", "count": empty_count})
        out[code] = items[:limit_per_field]
    return out
