import json
from datetime import date
from types import SimpleNamespace

from ...shared.birth_year_ranges import (
    DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG,
    birth_year_range_partition_value,
)
from ..partitions import (
    BIRTH_YEAR_RANGE_PARTITION_CODE,
    normalize_birth_year_range_partition_config,
    normalize_particions_v2_entries,
)


_MISSING = object()


def _inscripcio_value_for_partition(ins, field_code: str):
    code = str(field_code or "").strip()
    if not code:
        return None

    extra = getattr(ins, "extra", None) or {}
    if isinstance(extra, dict) and code.startswith("excel__"):
        if code in extra:
            return extra.get(code)
        legacy_code = code[len("excel__") :]
        if legacy_code in extra:
            return extra.get(legacy_code)

    value = getattr(ins, code, _MISSING)
    if value is not _MISSING:
        return value

    if isinstance(extra, dict):
        if code in extra:
            return extra.get(code)
        if code.startswith("excel__"):
            legacy_code = code[len("excel__") :]
            if legacy_code in extra:
                return extra.get(legacy_code)
    return None


def _birth_year_range_partition_value(ins, particions_config: dict):
    cfg = normalize_birth_year_range_partition_config(
        (particions_config or {}).get(BIRTH_YEAR_RANGE_PARTITION_CODE)
    )
    return birth_year_range_partition_value(ins, cfg)


def _birth_year_range_partition_value_for_team(member_rows, particions_config: dict):
    cfg = normalize_birth_year_range_partition_config(
        (particions_config or {}).get(BIRTH_YEAR_RANGE_PARTITION_CODE)
    )
    team_rules = cfg.get("team_rules") or {}
    sense_label = (
        cfg.get("sense_data_label")
        or DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG["sense_data_label"]
    )
    outside_label = (
        cfg.get("fora_rang_label")
        or DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG["fora_rang_label"]
    )

    members = [item[0] for item in (member_rows or []) if isinstance(item, (list, tuple)) and item]
    birth_dates = [
        getattr(member, "data_naixement", None)
        for member in members
        if isinstance(getattr(member, "data_naixement", None), date)
    ]
    if not birth_dates:
        return sense_label

    oldest_birth_date = min(birth_dates)
    candidate_label = birth_year_range_partition_value(
        SimpleNamespace(data_naixement=oldest_birth_date),
        cfg,
    )
    if candidate_label in {sense_label, outside_label}:
        return candidate_label

    outside_count = 0
    for member in members:
        birth_date = getattr(member, "data_naixement", None)
        if not isinstance(birth_date, date):
            outside_count += 1
            continue
        member_label = birth_year_range_partition_value(
            SimpleNamespace(data_naixement=birth_date),
            cfg,
        )
        if member_label != candidate_label:
            outside_count += 1

    compliance_mode = str(team_rules.get("compliance_mode") or "strict").strip().lower()
    if compliance_mode == "allow_outside_n":
        limit = max(0, int(team_rules.get("max_members_outside_range") or 0))
        return candidate_label if outside_count <= limit else outside_label
    return candidate_label if outside_count == 0 else outside_label


def _split_particio_custom_values(raw):
    if isinstance(raw, list):
        out = []
        for item in raw:
            value = str(item or "").strip()
            if value:
                out.append(value)
        return out
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return []


def _partition_value_display(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "_meta"):
        return getattr(value, "nom", None) or str(value)
    if isinstance(value, (list, dict)):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(value)
    return str(value)


def _normalize_partition_token(value: str) -> str:
    txt = str(value or "")
    txt = " ".join(txt.split()).strip()
    return txt.casefold()


def _normalize_partition_parent_values(raw):
    if isinstance(raw, list):
        values = [str(item or "").strip() for item in raw]
    elif isinstance(raw, str):
        values = [item.strip() for item in raw.split(",")]
    else:
        values = []

    out = []
    seen = set()
    for value in values:
        if not value:
            continue
        key = _normalize_partition_token(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _build_particions_custom_index(raw_cfg):
    out = {}
    if not isinstance(raw_cfg, dict):
        return out

    for field_code, cfg in raw_cfg.items():
        code = str(field_code or "").strip()
        if not code or not isinstance(cfg, dict):
            continue

        mode = str(cfg.get("mode") or "raw").strip().lower()
        fallback_label = str(cfg.get("fallback_label") or "").strip()
        value_map = {}

        for idx, group in enumerate(cfg.get("grups") or []):
            if not isinstance(group, dict):
                continue
            group_label = (
                str(group.get("label") or group.get("key") or f"Grup {idx + 1}").strip()
                or f"Grup {idx + 1}"
            )
            for raw_value in _split_particio_custom_values(group.get("values")):
                norm = _normalize_partition_token(raw_value)
                if norm and norm not in value_map:
                    value_map[norm] = group_label

        out[code] = {
            "mode": "custom" if mode == "custom" else "raw",
            "fallback_label": fallback_label,
            "value_map": value_map,
        }
    return out


def _resolve_partition_display(field_code: str, raw_display: str, custom_idx: dict) -> str:
    cfg = (custom_idx or {}).get(field_code) or {}
    if (cfg.get("mode") or "raw") != "custom":
        return raw_display

    mapped = (cfg.get("value_map") or {}).get(_normalize_partition_token(raw_display))
    if mapped is not None:
        return mapped

    fallback = str(cfg.get("fallback_label") or "").strip()
    if fallback:
        return fallback
    return raw_display


def _partition_raw_value(ins, field_code: str, particions_config=None):
    code = str(field_code or "").strip()
    if code == BIRTH_YEAR_RANGE_PARTITION_CODE:
        return _birth_year_range_partition_value(ins, particions_config or {})
    return _inscripcio_value_for_partition(ins, code)


def _partition_key_from_entries(
    ins,
    entries: list,
    particions_custom_index=None,
    particions_config=None,
):
    part_entries = normalize_particions_v2_entries(entries)
    if not part_entries:
        return "global"

    parts = []
    parent_resolved = None
    for idx, entry in enumerate(part_entries):
        code = str((entry or {}).get("code") or "").strip()
        if not code:
            continue

        if idx > 0:
            if parent_resolved is None:
                break
            apply_mode = str((entry or {}).get("apply_mode") or "all").strip().lower()
            if apply_mode == "some_parents":
                allowed = {
                    _normalize_partition_token(value)
                    for value in _normalize_partition_parent_values(
                        (entry or {}).get("parent_values")
                    )
                }
                if not allowed or _normalize_partition_token(parent_resolved) not in allowed:
                    parent_resolved = None
                    break

        raw_value = _partition_raw_value(ins, code, particions_config=particions_config)
        display_value = _partition_value_display(raw_value)
        resolved = _resolve_partition_display(code, display_value, particions_custom_index or {})
        parts.append(f"{code}:{resolved}")
        parent_resolved = resolved

    return "|".join(parts) if parts else "global"


def _partition_key_from_entries_for_team(
    member_rows,
    entries: list,
    particions_custom_index=None,
    particions_config=None,
):
    part_entries = normalize_particions_v2_entries(entries)
    if not part_entries:
        return "global"

    ref_member = None
    for item in member_rows or []:
        if isinstance(item, (list, tuple)) and item:
            ref_member = item[0]
            break

    parts = []
    parent_resolved = None
    for idx, entry in enumerate(part_entries):
        code = str((entry or {}).get("code") or "").strip()
        if not code:
            continue

        if idx > 0:
            if parent_resolved is None:
                break
            apply_mode = str((entry or {}).get("apply_mode") or "all").strip().lower()
            if apply_mode == "some_parents":
                allowed = {
                    _normalize_partition_token(value)
                    for value in _normalize_partition_parent_values(
                        (entry or {}).get("parent_values")
                    )
                }
                if not allowed or _normalize_partition_token(parent_resolved) not in allowed:
                    parent_resolved = None
                    break

        if code == BIRTH_YEAR_RANGE_PARTITION_CODE:
            raw_value = _birth_year_range_partition_value_for_team(
                member_rows,
                particions_config or {},
            )
        elif ref_member is not None:
            raw_value = _partition_raw_value(ref_member, code, particions_config=particions_config)
        else:
            raw_value = None

        display_value = _partition_value_display(raw_value)
        resolved = _resolve_partition_display(code, display_value, particions_custom_index or {})
        parts.append(f"{code}:{resolved}")
        parent_resolved = resolved

    return "|".join(parts) if parts else "global"


def _years_old(birth_date, ref_date):
    if not isinstance(birth_date, date) or not isinstance(ref_date, date):
        return None
    years = ref_date.year - birth_date.year
    before_birthday = (ref_date.month, ref_date.day) < (birth_date.month, birth_date.day)
    return years - 1 if before_birthday else years


def _bucket_edat(age_max, llindars, sense_data_label):
    if age_max is None:
        label = str(sense_data_label or "Sense edat").strip() or "Sense edat"
        return f"edat:{label}"

    ordered = sorted(set(int(value) for value in (llindars or [])))
    if not ordered:
        return f"edat:{age_max}"

    for threshold in ordered:
        if age_max <= threshold:
            return f"edat:<={threshold}"
    return f"edat:>{ordered[-1]}"


def _resolve_particio_equip(manual_key, age_key, combine):
    if combine:
        if manual_key or age_key:
            return f"{manual_key or 'manual:(cap)'}|{age_key or 'edat:(cap)'}"
        return "global"
    if manual_key:
        return manual_key
    if age_key:
        return age_key
    return "global"


__all__ = [
    "_birth_year_range_partition_value",
    "_birth_year_range_partition_value_for_team",
    "_build_particions_custom_index",
    "_bucket_edat",
    "_inscripcio_value_for_partition",
    "_partition_key_from_entries",
    "_partition_key_from_entries_for_team",
    "_resolve_partition_display",
    "_resolve_particio_equip",
    "_years_old",
]
