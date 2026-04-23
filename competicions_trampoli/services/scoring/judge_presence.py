from __future__ import annotations

import copy
from typing import Any


def presence_key(code: str) -> str:
    return f"__presence__{code}"


def is_presence_key(key: str) -> bool:
    return isinstance(key, str) and key.startswith("__presence__")


def is_judge_shaped_field(field_cfg: dict) -> bool:
    if not isinstance(field_cfg, dict):
        return False
    ftype = str(field_cfg.get("type") or "number").strip().lower()
    shape = str(field_cfg.get("shape") or "").strip()
    return (ftype == "list" and shape == "judge") or (
        ftype == "matrix" and shape in {"judge_x_item", "judge_x_element"}
    )


def is_strict_presence_field(field_cfg: dict) -> bool:
    return is_judge_shaped_field(field_cfg) and _judge_count(field_cfg) > 1


def _judge_count(field_cfg: dict) -> int:
    judges_cfg = field_cfg.get("judges") if isinstance(field_cfg.get("judges"), dict) else {}
    try:
        value = int(judges_cfg.get("count") or 1)
    except Exception:
        value = 1
    return max(1, min(10, value))


def _item_count(field_cfg: dict) -> int:
    items_cfg = field_cfg.get("items") if isinstance(field_cfg.get("items"), dict) else {}
    try:
        value = int(items_cfg.get("count") or 0)
    except Exception:
        value = 0
    return max(0, min(50, value))


def _normalize_presence(raw_presence: Any, n_judges: int) -> list[bool]:
    arr = raw_presence if isinstance(raw_presence, list) else []
    out = []
    for idx in range(n_judges):
        out.append(bool(arr[idx]) if idx < len(arr) else False)
    return out


def infer_presence_for_field(raw_field_value: Any, raw_crash_value: Any, n_judges: int) -> list[bool]:
    raw_values = raw_field_value if isinstance(raw_field_value, list) else []
    raw_crash = raw_crash_value if isinstance(raw_crash_value, list) else []
    presence = []
    for idx in range(n_judges):
        has_value = idx < len(raw_values) and raw_values[idx] is not None
        has_crash = idx < len(raw_crash) and raw_crash[idx] is not None
        presence.append(bool(has_value or has_crash))
    return presence


def _normalized_crash_list(raw_value: Any, presence: list[bool], n_judges: int) -> list[Any]:
    raw = raw_value if isinstance(raw_value, list) else []
    out = []
    for idx in range(n_judges):
        if idx < len(raw) and raw[idx] is not None:
            out.append(copy.deepcopy(raw[idx]))
        elif presence[idx]:
            out.append(0)
        else:
            out.append(None)
    return out


def canonicalize_judge_field(inputs: dict, field_cfg: dict) -> dict:
    if not isinstance(inputs, dict) or not is_strict_presence_field(field_cfg):
        return {}

    code = str(field_cfg.get("code") or "")
    if not code:
        return {}

    n_judges = _judge_count(field_cfg)
    n_items = _item_count(field_cfg)
    ftype = str(field_cfg.get("type") or "number").strip().lower()
    pk = presence_key(code)
    ck = f"__crash__{code}"
    crash_cfg = field_cfg.get("crash") if isinstance(field_cfg.get("crash"), dict) else {}

    raw = inputs.get(code)
    raw_crash = inputs.get(ck)
    if pk in inputs:
        presence = _normalize_presence(inputs.get(pk), n_judges)
    else:
        presence = infer_presence_for_field(raw, raw_crash, n_judges)

    raw_values = raw if isinstance(raw, list) else []
    out: dict[str, Any] = {pk: presence}

    if ftype == "list":
        values = []
        for idx in range(n_judges):
            values.append(copy.deepcopy(raw_values[idx]) if idx < len(raw_values) else None)
        out[code] = values
        return out

    values = []
    for idx in range(n_judges):
        if idx >= len(raw_values) or not isinstance(raw_values[idx], list):
            values.append(None)
            continue
        row = raw_values[idx]
        row_out = [copy.deepcopy(row[col]) if col < len(row) else None for col in range(n_items)]
        values.append(row_out)
    out[code] = values
    if crash_cfg.get("enabled"):
        out[ck] = _normalized_crash_list(raw_crash, presence, n_judges)
    return out


def canonicalize_inputs_for_schema(inputs: dict, schema: dict) -> dict:
    source = copy.deepcopy(inputs if isinstance(inputs, dict) else {})
    out = {}
    fields = [field for field in (schema.get("fields") or []) if isinstance(field, dict) and field.get("code")]
    field_by_code = {str(field["code"]): field for field in fields}

    for key, value in source.items():
        key_str = str(key)
        base_code = key_str
        if key_str.startswith("__crash__"):
            base_code = key_str[len("__crash__") :]
        elif key_str.startswith("__presence__"):
            base_code = key_str[len("__presence__") :]
        field = field_by_code.get(base_code)
        if field is None:
            out[key] = value
            continue
        if not is_strict_presence_field(field):
            if not is_presence_key(key_str):
                out[key] = value
            continue

    for code, field in field_by_code.items():
        pk = presence_key(code)
        ck = f"__crash__{code}"
        if not is_strict_presence_field(field):
            continue
        if code not in source and ck not in source and pk not in source:
            continue
        out.update(canonicalize_judge_field(source, field))
    return out


def merge_judge_patch_into_canonical(current_inputs: dict, sanitized_patch: dict, schema: dict) -> dict:
    out = canonicalize_inputs_for_schema(current_inputs or {}, schema or {})
    by_code = {
        str(field.get("code")): field
        for field in (schema.get("fields") or [])
        if isinstance(field, dict) and field.get("code")
    }

    for code, payload in (sanitized_patch or {}).items():
        code = str(code)
        if code.startswith("__crash__"):
            base_code = code[len("__crash__") :]
            field = by_code.get(base_code)
            if not field:
                continue
            if not is_strict_presence_field(field):
                if not is_judge_shaped_field(field) or not isinstance(payload, dict):
                    out[code] = copy.deepcopy(payload)
                continue
            if not is_judge_shaped_field(field):
                out[code] = copy.deepcopy(payload)
                continue
            crash_cfg = field.get("crash") if isinstance(field.get("crash"), dict) else {}
            if str(field.get("type") or "number") != "matrix" or not crash_cfg.get("enabled"):
                continue
            current = canonicalize_judge_field(out, field)
            out.update(current)
            n_judges = _judge_count(field)
            n_items = _item_count(field)
            pk = presence_key(base_code)
            presence = _normalize_presence(out.get(pk), n_judges)
            crash_values = out.get(code) if isinstance(out.get(code), list) else [None] * n_judges
            rows = out.get(base_code) if isinstance(out.get(base_code), list) else [None] * n_judges
            while len(crash_values) < n_judges:
                crash_values.append(None)
            while len(rows) < n_judges:
                rows.append(None)
            if isinstance(payload, dict) and "__set_list__" in payload:
                for idx, value in payload["__set_list__"]:
                    if idx < 0 or idx >= n_judges:
                        continue
                    presence[idx] = True
                    crash_values[idx] = copy.deepcopy(value) if value is not None else 0
                    if not isinstance(rows[idx], list):
                        rows[idx] = [None] * n_items
            out[pk] = presence
            out[code] = crash_values[:n_judges]
            out[base_code] = rows[:n_judges]
            continue

        field = by_code.get(code)
        if not field:
            continue
        ftype = str(field.get("type") or "number").strip().lower()
        if not is_strict_presence_field(field):
            if not is_judge_shaped_field(field) or not isinstance(payload, dict):
                out[code] = copy.deepcopy(payload)
            continue
        if not is_judge_shaped_field(field):
            out[code] = copy.deepcopy(payload)
            continue

        current = canonicalize_judge_field(out, field)
        out.update(current)
        n_judges = _judge_count(field)
        n_items = _item_count(field)
        pk = presence_key(code)
        presence = _normalize_presence(out.get(pk), n_judges)

        if ftype == "list" and isinstance(payload, dict) and "__set_list__" in payload:
            values = out.get(code) if isinstance(out.get(code), list) else [None] * n_judges
            while len(values) < n_judges:
                values.append(None)
            for idx, value in payload["__set_list__"]:
                if idx < 0 or idx >= n_judges:
                    continue
                presence[idx] = True
                values[idx] = copy.deepcopy(value)
            out[pk] = presence
            out[code] = values[:n_judges]
            continue

        if ftype == "matrix" and isinstance(payload, dict) and "__set_matrix__" in payload:
            rows = out.get(code) if isinstance(out.get(code), list) else [None] * n_judges
            while len(rows) < n_judges:
                rows.append(None)
            for row_idx, col_idx, value in payload["__set_matrix__"]:
                if row_idx < 0 or row_idx >= n_judges or col_idx < 0 or col_idx >= n_items:
                    continue
                presence[row_idx] = True
                current_row = rows[row_idx] if isinstance(rows[row_idx], list) else [None] * n_items
                while len(current_row) < n_items:
                    current_row.append(None)
                current_row[col_idx] = copy.deepcopy(value)
                rows[row_idx] = current_row[:n_items]
            out[pk] = presence
            out[code] = rows[:n_judges]
            crash_code = f"__crash__{code}"
            if crash_code in out and isinstance(out[crash_code], list):
                crash_values = out[crash_code]
                while len(crash_values) < n_judges:
                    crash_values.append(None)
                out[crash_code] = crash_values[:n_judges]
            continue

    return out


def build_runtime_inputs_from_canonical(canonical_inputs: dict, schema: dict) -> dict:
    runtime = canonicalize_inputs_for_schema(canonical_inputs or {}, schema or {})
    for field in (schema.get("fields") or []):
        if not isinstance(field, dict) or not field.get("code") or not is_strict_presence_field(field):
            continue
        code = str(field["code"])
        n_judges = _judge_count(field)
        presence = _normalize_presence(runtime.get(presence_key(code)), n_judges)
        values = runtime.get(code)
        if isinstance(values, list):
            padded = values[:n_judges] + [None] * max(0, n_judges - len(values))
            runtime[code] = [padded[idx] if presence[idx] else None for idx in range(n_judges)]
        crash_code = f"__crash__{code}"
        crash_values = runtime.get(crash_code)
        if isinstance(crash_values, list):
            padded_crash = crash_values[:n_judges] + [None] * max(0, n_judges - len(crash_values))
            runtime[crash_code] = [padded_crash[idx] if presence[idx] else None for idx in range(n_judges)]
    return runtime


def persist_inputs_after_compute(canonical_inputs: dict, normalized_inputs: dict, schema: dict) -> dict:
    canonical = canonicalize_inputs_for_schema(canonical_inputs or {}, schema or {})
    normalized = copy.deepcopy(normalized_inputs if isinstance(normalized_inputs, dict) else {})
    out = {}
    judge_codes = set()
    judge_meta_codes = set()

    for field in (schema.get("fields") or []):
        if not isinstance(field, dict) or not field.get("code") or not is_strict_presence_field(field):
            continue
        code = str(field["code"])
        judge_codes.add(code)
        judge_meta_codes.add(presence_key(code))
        judge_meta_codes.add(f"__crash__{code}")

    for key, value in normalized.items():
        if key in judge_codes or key in judge_meta_codes:
            continue
        out[key] = value

    for key, value in canonical.items():
        if key in judge_codes or key in judge_meta_codes:
            out[key] = copy.deepcopy(value)
    return out
