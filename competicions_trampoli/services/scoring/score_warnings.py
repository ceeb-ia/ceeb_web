from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable

from .judge_presence import is_judge_shaped_field, presence_key


WARNING_SEVERITY = "warning"


def generate_score_warnings(
    schema: dict[str, Any] | None,
    score_or_inputs: dict[str, Any] | None,
    subject: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """
    Return non-blocking warnings for one subject in one scoring context.

    The function is intentionally pure and accepts plain dictionaries so it can
    be reused by table endpoints, aggregate warning endpoints, or client parity
    tests without depending on Django models.
    """

    schema = schema if isinstance(schema, dict) else {}
    inputs = _extract_inputs(score_or_inputs)
    subject = subject if isinstance(subject, dict) else {}
    context = context if isinstance(context, dict) else {}

    subject_kind = str(subject.get("subject_kind") or subject.get("kind") or "inscripcio")
    subject_id = subject.get("subject_id", subject.get("id"))
    comp_aparell_id = context.get("comp_aparell_id")
    exercici = context.get("exercici")

    warnings: list[dict[str, Any]] = []
    for field in _iter_fields(schema):
        code = str(field.get("code") or "").strip()
        if not code:
            continue
        field_value = inputs.get(code)
        for point in _iter_field_points(field, field_value):
            value = point["value"]
            if _is_blank(value):
                continue
            numeric = _to_decimal(value)
            if numeric is None:
                continue
            expected = _range_expected(field)
            minimum = expected.get("min")
            maximum = expected.get("max")
            if minimum is not None and numeric < minimum:
                warnings.append(
                    _warning(
                        code="range_low",
                        message=_range_message(code, point, value, "es menor que el minim", minimum),
                        subject_kind=subject_kind,
                        subject_id=subject_id,
                        comp_aparell_id=comp_aparell_id,
                        exercici=exercici,
                        field_code=code,
                        judge=point.get("judge"),
                        item=point.get("item"),
                        value=value,
                        expected=_json_expected(expected),
                    )
                )
            if maximum is not None and numeric > maximum:
                warnings.append(
                    _warning(
                        code="range_high",
                        message=_range_message(code, point, value, "supera el maxim", maximum),
                        subject_kind=subject_kind,
                        subject_id=subject_id,
                        comp_aparell_id=comp_aparell_id,
                        exercici=exercici,
                        field_code=code,
                        judge=point.get("judge"),
                        item=point.get("item"),
                        value=value,
                        expected=_json_expected(expected),
                    )
                )
            decimals = _decimal_limit(field)
            if decimals is not None and _decimal_places(value) > decimals:
                warnings.append(
                    _warning(
                        code="decimal_precision",
                        message=_point_label(code, point) + f" te mes de {decimals} decimals",
                        subject_kind=subject_kind,
                        subject_id=subject_id,
                        comp_aparell_id=comp_aparell_id,
                        exercici=exercici,
                        field_code=code,
                        judge=point.get("judge"),
                        item=point.get("item"),
                        value=value,
                        expected={"decimals": decimals},
                    )
                )

        warnings.extend(
            _judge_presence_warnings(
                field=field,
                inputs=inputs,
                subject_kind=subject_kind,
                subject_id=subject_id,
                comp_aparell_id=comp_aparell_id,
                exercici=exercici,
            )
        )
        warnings.extend(
            _crash_warnings(
                field=field,
                inputs=inputs,
                subject_kind=subject_kind,
                subject_id=subject_id,
                comp_aparell_id=comp_aparell_id,
                exercici=exercici,
            )
        )
        warnings.extend(
            _zero_pattern_warnings(
                field=field,
                inputs=inputs,
                subject_kind=subject_kind,
                subject_id=subject_id,
                comp_aparell_id=comp_aparell_id,
                exercici=exercici,
            )
        )

    for idx, warning in enumerate(warnings):
        warning["id"] = _warning_id(warning, idx)
    return warnings


def generate_score_warnings_for_subjects(
    schema: dict[str, Any] | None,
    scores_by_subject: dict[Any, Any] | None,
    subjects: Iterable[dict[str, Any]] | None,
    context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    scores_by_subject = scores_by_subject if isinstance(scores_by_subject, dict) else {}
    for subject in subjects or []:
        if not isinstance(subject, dict):
            continue
        subject_id = subject.get("subject_id", subject.get("id"))
        score = scores_by_subject.get(subject_id) or scores_by_subject.get(str(subject_id)) or {}
        warnings.extend(generate_score_warnings(schema, score, subject, context))
    return warnings


def _extract_inputs(score_or_inputs: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(score_or_inputs, dict):
        return {}
    inputs = score_or_inputs.get("inputs")
    if isinstance(inputs, dict):
        return inputs
    return score_or_inputs


def _iter_fields(schema: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for field in schema.get("fields") or []:
        if isinstance(field, dict):
            yield field


def _iter_field_points(field: dict[str, Any], raw_value: Any) -> Iterable[dict[str, Any]]:
    ftype = str(field.get("type") or "number").strip().lower()
    shape = str(field.get("shape") or "").strip()
    if ftype == "matrix" or shape in {"judge_x_item", "judge_x_element"}:
        rows = raw_value if isinstance(raw_value, list) else []
        n_judges = _judge_count(field)
        n_items = _item_count(field)
        for judge_idx in range(n_judges):
            row = rows[judge_idx] if judge_idx < len(rows) and isinstance(rows[judge_idx], list) else []
            for item_idx in range(n_items):
                yield {
                    "judge": judge_idx + 1,
                    "item": item_idx + 1,
                    "value": row[item_idx] if item_idx < len(row) else None,
                }
        return
    if ftype == "list" or shape == "judge":
        values = raw_value if isinstance(raw_value, list) else []
        for judge_idx in range(_judge_count(field)):
            yield {
                "judge": judge_idx + 1,
                "item": None,
                "value": values[judge_idx] if judge_idx < len(values) else None,
            }
        return
    yield {"judge": None, "item": None, "value": raw_value}


def _judge_presence_warnings(
    *,
    field: dict[str, Any],
    inputs: dict[str, Any],
    subject_kind: str,
    subject_id: Any,
    comp_aparell_id: Any,
    exercici: Any,
) -> list[dict[str, Any]]:
    if not is_judge_shaped_field(field):
        return []
    code = str(field.get("code") or "").strip()
    if not code:
        return []
    presence = inputs.get(presence_key(code))
    if not isinstance(presence, list):
        return []
    warnings: list[dict[str, Any]] = []
    values = inputs.get(code) if isinstance(inputs.get(code), list) else []
    ftype = str(field.get("type") or "number").strip().lower()
    n_judges = _judge_count(field)
    n_items = _item_count(field)
    crash_cfg = field.get("crash") if isinstance(field.get("crash"), dict) else {}
    crash_values = inputs.get(f"__crash__{code}") if isinstance(inputs.get(f"__crash__{code}"), list) else []
    allow_implicit_zero = _field_accepts_implicit_zero(field)
    for judge_idx in range(n_judges):
        is_present = bool(presence[judge_idx]) if judge_idx < len(presence) else False
        if ftype == "matrix":
            row = values[judge_idx] if judge_idx < len(values) and isinstance(values[judge_idx], list) else []
            row_has_value = any(not _is_blank(v) for v in row)
            if is_present:
                required_items = n_items
                if crash_cfg.get("enabled"):
                    crash_at = _positive_int(crash_values[judge_idx] if judge_idx < len(crash_values) else None)
                    if crash_at is not None and crash_at > 0:
                        required_items = max(0, min(n_items, crash_at - 1))
                for item_idx in range(required_items):
                    value = row[item_idx] if item_idx < len(row) else None
                    if _is_blank(value) and not allow_implicit_zero:
                        warnings.append(
                            _presence_warning(
                                "missing_counting_judge",
                                f"{_point_label(code, {'judge': judge_idx + 1, 'item': item_idx + 1})} no te valor tot i tenir el jutge present",
                                subject_kind,
                                subject_id,
                                comp_aparell_id,
                                exercici,
                                code,
                                judge_idx + 1,
                                item_idx + 1,
                                value,
                                {"presence": True},
                            )
                        )
            elif row_has_value:
                warnings.append(
                    _presence_warning(
                        "value_without_presence",
                        f"{code} J{judge_idx + 1} te valor amb el jutge absent",
                        subject_kind,
                        subject_id,
                        comp_aparell_id,
                        exercici,
                        code,
                        judge_idx + 1,
                        None,
                        row,
                        {"presence": False},
                    )
            )
            continue
        value = values[judge_idx] if judge_idx < len(values) else None
        if is_present and _is_blank(value) and not allow_implicit_zero:
            warnings.append(
                _presence_warning(
                    "missing_counting_judge",
                    f"{code} J{judge_idx + 1} no te valor tot i tenir el jutge present",
                    subject_kind,
                    subject_id,
                    comp_aparell_id,
                    exercici,
                    code,
                    judge_idx + 1,
                    None,
                    value,
                    {"presence": True},
                )
            )
        elif not is_present and not _is_blank(value):
            warnings.append(
                _presence_warning(
                    "value_without_presence",
                    f"{code} J{judge_idx + 1} te valor amb el jutge absent",
                    subject_kind,
                    subject_id,
                    comp_aparell_id,
                    exercici,
                    code,
                    judge_idx + 1,
                    None,
                    value,
                    {"presence": False},
                )
            )
    return warnings


def _crash_warnings(
    *,
    field: dict[str, Any],
    inputs: dict[str, Any],
    subject_kind: str,
    subject_id: Any,
    comp_aparell_id: Any,
    exercici: Any,
) -> list[dict[str, Any]]:
    code = str(field.get("code") or "").strip()
    crash_cfg = field.get("crash") if isinstance(field.get("crash"), dict) else {}
    if not code or str(field.get("type") or "").strip().lower() != "matrix" or not crash_cfg.get("enabled"):
        return []
    rows = inputs.get(code) if isinstance(inputs.get(code), list) else []
    crash_values = inputs.get(f"__crash__{code}") if isinstance(inputs.get(f"__crash__{code}"), list) else []
    warnings: list[dict[str, Any]] = []
    n_judges = _judge_count(field)
    n_items = _item_count(field)
    for judge_idx in range(n_judges):
        crash_at = _positive_int(crash_values[judge_idx] if judge_idx < len(crash_values) else None)
        if crash_at is None or crash_at <= 0:
            continue
        row = rows[judge_idx] if judge_idx < len(rows) and isinstance(rows[judge_idx], list) else []
        first_blocked_idx = max(0, min(n_items, crash_at - 1))
        for item_idx in range(first_blocked_idx, n_items):
            value = row[item_idx] if item_idx < len(row) else None
            if _is_blank(value):
                continue
            warnings.append(
                _warning(
                    code="crash_inconsistent",
                    message=f"{_point_label(code, {'judge': judge_idx + 1, 'item': item_idx + 1})} te valor posterior al crash",
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    comp_aparell_id=comp_aparell_id,
                    exercici=exercici,
                    field_code=code,
                    judge=judge_idx + 1,
                    item=item_idx + 1,
                    value=value,
                    expected={"crash_at": crash_at, "empty_from_item": first_blocked_idx + 1},
                )
            )
    return warnings


def _zero_pattern_warnings(
    *,
    field: dict[str, Any],
    inputs: dict[str, Any],
    subject_kind: str,
    subject_id: Any,
    comp_aparell_id: Any,
    exercici: Any,
) -> list[dict[str, Any]]:
    code = str(field.get("code") or "").strip()
    if not code or str(field.get("type") or "").strip().lower() != "matrix":
        return []
    if not _field_accepts_implicit_zero(field):
        return []
    n_items = _item_count(field)
    if n_items < 3:
        return []
    rows = inputs.get(code) if isinstance(inputs.get(code), list) else []
    presence = inputs.get(presence_key(code))
    crash_cfg = field.get("crash") if isinstance(field.get("crash"), dict) else {}
    crash_values = inputs.get(f"__crash__{code}") if isinstance(inputs.get(f"__crash__{code}"), list) else []
    warnings: list[dict[str, Any]] = []
    for judge_idx in range(_judge_count(field)):
        if isinstance(presence, list) and not (bool(presence[judge_idx]) if judge_idx < len(presence) else False):
            continue
        row = rows[judge_idx] if judge_idx < len(rows) and isinstance(rows[judge_idx], list) else []
        if not row and not isinstance(presence, list):
            continue
        required_items = n_items
        if crash_cfg.get("enabled"):
            crash_at = _positive_int(crash_values[judge_idx] if judge_idx < len(crash_values) else None)
            if crash_at is not None and crash_at > 0:
                required_items = max(0, min(n_items, crash_at - 1))
        if required_items < 3:
            continue
        zero_count = 0
        for item_idx in range(required_items):
            value = row[item_idx] if item_idx < len(row) else None
            numeric = _to_decimal(value)
            if numeric == 0 or _is_blank(value):
                zero_count += 1
        ratio = zero_count / required_items if required_items else 0
        if zero_count == required_items or (zero_count >= 3 and ratio >= 0.8):
            warnings.append(
                _warning(
                    code="zero_pattern",
                    message=f"{code} J{judge_idx + 1} te {zero_count}/{required_items} valors a 0",
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    comp_aparell_id=comp_aparell_id,
                    exercici=exercici,
                    field_code=code,
                    judge=judge_idx + 1,
                    item=None,
                    value={"zero_count": zero_count, "count": required_items},
                    expected={"zero_ratio_below": 0.8},
                )
            )
    return warnings


def _presence_warning(
    code: str,
    message: str,
    subject_kind: str,
    subject_id: Any,
    comp_aparell_id: Any,
    exercici: Any,
    field_code: str,
    judge: int | None,
    item: int | None,
    value: Any,
    expected: dict[str, Any],
) -> dict[str, Any]:
    return _warning(
        code=code,
        message=message,
        subject_kind=subject_kind,
        subject_id=subject_id,
        comp_aparell_id=comp_aparell_id,
        exercici=exercici,
        field_code=field_code,
        judge=judge,
        item=item,
        value=value,
        expected=expected,
    )


def _warning(
    *,
    code: str,
    message: str,
    subject_kind: str,
    subject_id: Any,
    comp_aparell_id: Any,
    exercici: Any,
    field_code: str,
    judge: int | None,
    item: int | None,
    value: Any,
    expected: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": "",
        "severity": WARNING_SEVERITY,
        "code": code,
        "message": message,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "comp_aparell_id": comp_aparell_id,
        "exercici": exercici,
        "field_code": field_code,
        "judge": judge,
        "item": item,
        "value": _json_value(value),
        "expected": expected,
    }


def _warning_id(warning: dict[str, Any], index: int) -> str:
    parts = [
        warning.get("code"),
        warning.get("subject_kind"),
        warning.get("subject_id"),
        warning.get("comp_aparell_id"),
        warning.get("exercici"),
        warning.get("field_code"),
        warning.get("judge") if warning.get("judge") is not None else "-",
        warning.get("item") if warning.get("item") is not None else "-",
    ]
    base = ":".join(str(part) for part in parts)
    return f"{base}:{index}"


def _range_expected(field: dict[str, Any]) -> dict[str, Decimal | None]:
    return {"min": _to_decimal(field.get("min")), "max": _to_decimal(field.get("max"))}


def _field_accepts_implicit_zero(field: dict[str, Any]) -> bool:
    expected = _range_expected(field)
    minimum = expected.get("min")
    maximum = expected.get("max")
    if minimum is not None and minimum > 0:
        return False
    if maximum is not None and maximum < 0:
        return False
    return minimum is not None or maximum is not None


def _json_expected(expected: dict[str, Decimal | None]) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in expected.items() if value is not None}


def _range_message(code: str, point: dict[str, Any], value: Any, text: str, expected: Decimal) -> str:
    return f"{_point_label(code, point)} {text} {_json_value(expected)}"


def _point_label(code: str, point: dict[str, Any]) -> str:
    parts = [code]
    if point.get("judge") is not None:
        parts.append(f"J{point['judge']}")
    if point.get("item") is not None:
        parts.append(f"S{point['item']}")
    return " ".join(parts)


def _decimal_limit(field: dict[str, Any]) -> int | None:
    if "decimals" not in field:
        return None
    try:
        value = int(field.get("decimals"))
    except (TypeError, ValueError):
        return None
    return max(0, value)


def _decimal_places(value: Any) -> int:
    if isinstance(value, bool) or _is_blank(value):
        return 0
    try:
        decimal = Decimal(str(value).strip())
    except Exception:
        return 0
    exponent = decimal.as_tuple().exponent
    return abs(exponent) if exponent < 0 else 0


def _to_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or _is_blank(value):
        return None
    try:
        return Decimal(str(value).strip())
    except Exception:
        return None


def _positive_int(value: Any) -> int | None:
    decimal = _to_decimal(value)
    if decimal is None:
        return None
    try:
        return int(decimal)
    except Exception:
        return None


def _judge_count(field: dict[str, Any]) -> int:
    judges_cfg = field.get("judges") if isinstance(field.get("judges"), dict) else {}
    try:
        value = int(judges_cfg.get("count") or 1)
    except Exception:
        value = 1
    return max(1, min(10, value))


def _item_count(field: dict[str, Any]) -> int:
    items_cfg = field.get("items") if isinstance(field.get("items"), dict) else {}
    try:
        value = int(items_cfg.get("count") or 0)
    except Exception:
        value = 0
    return max(0, min(50, value))


def _is_blank(value: Any) -> bool:
    return value is None or value == ""


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value
