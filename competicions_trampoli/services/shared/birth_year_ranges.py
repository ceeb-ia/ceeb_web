from datetime import date, timedelta
from functools import lru_cache

from django.db.models import Case, CharField, Value, When
from django.utils.dateparse import parse_date


BIRTH_YEAR_RANGE_PARTITION_CODE = "any_naixement_forquilla"
DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG = {
    "ranges": [],
    "sense_data_label": "Sense data",
    "fora_rang_label": "Fora de forquilla",
    "team_rules": {
        "reference_mode": "oldest_member_birthdate",
        "compliance_mode": "strict",
        "max_members_outside_range": 0,
        "missing_birthdate_policy": "outside_range",
    },
}

DEFAULT_BIRTH_YEAR_RANGE_TEAM_RULES = DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG["team_rules"]


def _parse_optional_year(raw):
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _parse_optional_date(raw):
    if isinstance(raw, date):
        return raw
    token = str(raw or "").strip()
    if not token:
        return None
    return parse_date(token)


def _iso_or_none(value):
    return value.isoformat() if isinstance(value, date) else None


def _safe_non_negative_int(raw, default=0):
    try:
        value = int(raw)
    except Exception:
        return max(0, int(default or 0))
    return max(0, value)


def _normalize_birth_year_range_team_rules(raw_rules):
    rules = raw_rules if isinstance(raw_rules, dict) else {}
    reference_mode = str(
        rules.get("reference_mode")
        or DEFAULT_BIRTH_YEAR_RANGE_TEAM_RULES["reference_mode"]
    ).strip() or DEFAULT_BIRTH_YEAR_RANGE_TEAM_RULES["reference_mode"]
    compliance_mode = str(
        rules.get("compliance_mode")
        or DEFAULT_BIRTH_YEAR_RANGE_TEAM_RULES["compliance_mode"]
    ).strip() or DEFAULT_BIRTH_YEAR_RANGE_TEAM_RULES["compliance_mode"]
    missing_birthdate_policy = str(
        rules.get("missing_birthdate_policy")
        or DEFAULT_BIRTH_YEAR_RANGE_TEAM_RULES["missing_birthdate_policy"]
    ).strip() or DEFAULT_BIRTH_YEAR_RANGE_TEAM_RULES["missing_birthdate_policy"]
    return {
        "reference_mode": reference_mode,
        "compliance_mode": compliance_mode,
        "max_members_outside_range": _safe_non_negative_int(
            rules.get("max_members_outside_range"),
            DEFAULT_BIRTH_YEAR_RANGE_TEAM_RULES["max_members_outside_range"],
        ),
        "missing_birthdate_policy": missing_birthdate_policy,
    }


def _legacy_year_to_start_date(year_value):
    year = _parse_optional_year(year_value)
    if year is None:
        return None
    return date(year, 1, 1)


def _legacy_year_to_end_date(year_value):
    year = _parse_optional_year(year_value)
    if year is None:
        return None
    return date(year, 12, 31)


def default_birth_year_range_label(from_date, until_date, idx):
    if isinstance(from_date, date) and isinstance(until_date, date):
        return f"{from_date.isoformat()} a {until_date.isoformat()}"
    if isinstance(from_date, date):
        return f"Des de {from_date.isoformat()}"
    if isinstance(until_date, date):
        return f"Fins {until_date.isoformat()}"
    return f"Forquilla {idx + 1}"


def normalize_birth_year_range_partition_config(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    out = {
        **DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG,
    }
    out["sense_data_label"] = (
        str(cfg.get("sense_data_label") or out["sense_data_label"]).strip()
        or DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG["sense_data_label"]
    )
    out["fora_rang_label"] = (
        str(cfg.get("fora_rang_label") or out["fora_rang_label"]).strip()
        or DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG["fora_rang_label"]
    )
    out["team_rules"] = _normalize_birth_year_range_team_rules(cfg.get("team_rules"))

    ranges_out = []
    for idx, item in enumerate(cfg.get("ranges") or []):
        if not isinstance(item, dict):
            continue
        raw_label = str(item.get("label") or "").strip()
        from_date = _parse_optional_date(item.get("from_date"))
        until_date = _parse_optional_date(item.get("until_date"))
        from_year = _parse_optional_year(item.get("from_year"))
        to_year = _parse_optional_year(item.get("to_year"))

        if from_date is None and from_year is not None:
            from_date = _legacy_year_to_start_date(from_year)
        if until_date is None and to_year is not None:
            until_date = _legacy_year_to_end_date(to_year)

        if raw_label == "" and from_date is None and until_date is None:
            continue

        label = raw_label or default_birth_year_range_label(from_date, until_date, idx)
        ranges_out.append(
            {
                "label": label,
                "from_date": _iso_or_none(from_date),
                "until_date": _iso_or_none(until_date),
                "from_year": from_year,
                "to_year": to_year,
            }
        )
    out["ranges"] = ranges_out
    return out


def normalize_birth_year_range_partition_config_for_inscripcions(raw_cfg):
    cfg = normalize_birth_year_range_partition_config(raw_cfg)
    ranges = []
    for idx, item in enumerate(cfg.get("ranges") or []):
        if not isinstance(item, dict):
            continue
        from_date = _parse_optional_date(item.get("from_date"))
        until_date = _parse_optional_date(item.get("until_date"))
        label = str(item.get("label") or "").strip() or default_birth_year_range_label(from_date, until_date, idx)
        ranges.append(
            {
                "label": label,
                "from_date": _iso_or_none(from_date),
                "until_date": _iso_or_none(until_date),
            }
        )
    return {
        "ranges": ranges,
        "sense_data_label": cfg.get("sense_data_label") or DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG["sense_data_label"],
        "fora_rang_label": cfg.get("fora_rang_label") or DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG["fora_rang_label"],
    }


def validate_birth_year_range_partition_config(raw_cfg, *, require_ranges=True):
    cfg = normalize_birth_year_range_partition_config(raw_cfg)
    errors = []
    ranges = cfg.get("ranges") or []
    if require_ranges and not ranges:
        errors.append("Cal definir almenys una forquilla.")
        return cfg, errors

    seen_labels = {}
    normalized_ranges = []
    for idx, item in enumerate(ranges):
        label = str(item.get("label") or "").strip()
        from_date = _parse_optional_date(item.get("from_date"))
        until_date = _parse_optional_date(item.get("until_date"))

        if from_date is None and until_date is None:
            errors.append(f"Forquilla {idx + 1}: cal indicar data inici, data final o totes dues.")
            continue
        if from_date is not None and until_date is not None and from_date > until_date:
            errors.append(f"Forquilla {idx + 1}: la data inici no pot ser mes gran que la data final.")

        key = " ".join(label.split()).casefold()
        if key:
            owner = seen_labels.get(key)
            if owner is not None:
                errors.append(f"Forquilla {idx + 1}: etiqueta repetida amb la forquilla {owner + 1}.")
            else:
                seen_labels[key] = idx
        normalized_ranges.append((idx, from_date, until_date))

    for pos, (idx_a, from_a, until_a) in enumerate(normalized_ranges):
        for idx_b, from_b, until_b in normalized_ranges[pos + 1 :]:
            start_a = from_a or date.min
            end_a = until_a or date.max
            start_b = from_b or date.min
            end_b = until_b or date.max
            if start_a <= end_b and start_b <= end_a:
                errors.append(
                    f"Hi ha solapament entre les forquilles {idx_a + 1} i {idx_b + 1}."
                )

    team_rules = cfg.get("team_rules") or {}
    if team_rules.get("reference_mode") != DEFAULT_BIRTH_YEAR_RANGE_TEAM_RULES["reference_mode"]:
        errors.append("team_rules.reference_mode ha de ser oldest_member_birthdate.")
    if team_rules.get("compliance_mode") not in {"strict", "allow_outside_n"}:
        errors.append("team_rules.compliance_mode ha de ser strict o allow_outside_n.")
    if team_rules.get("missing_birthdate_policy") != DEFAULT_BIRTH_YEAR_RANGE_TEAM_RULES["missing_birthdate_policy"]:
        errors.append("team_rules.missing_birthdate_policy ha de ser outside_range.")
    if team_rules.get("compliance_mode") == "allow_outside_n":
        raw_limit = team_rules.get("max_members_outside_range")
        try:
            limit = int(raw_limit)
        except Exception:
            errors.append("team_rules.max_members_outside_range ha de ser un enter >= 0.")
        else:
            if limit < 0:
                errors.append("team_rules.max_members_outside_range ha de ser un enter >= 0.")
    return cfg, errors


def birth_year_range_partition_value(inscripcio, raw_cfg, *, empty_if_unconfigured=False):
    cfg = normalize_birth_year_range_partition_config(raw_cfg)
    ranges = cfg.get("ranges") or []
    if empty_if_unconfigured and not ranges:
        return None

    birth_date = getattr(inscripcio, "data_naixement", None)
    if not isinstance(birth_date, date):
        return cfg.get("sense_data_label") or DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG["sense_data_label"]

    for idx, item in enumerate(ranges):
        from_date = _parse_optional_date(item.get("from_date"))
        until_date = _parse_optional_date(item.get("until_date"))
        if from_date is None and until_date is None:
            continue
        if from_date is not None and birth_date < from_date:
            continue
        if until_date is not None and birth_date > until_date:
            continue
        return str(item.get("label") or "").strip() or default_birth_year_range_label(from_date, until_date, idx)

    return cfg.get("fora_rang_label") or DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG["fora_rang_label"]


def birth_year_range_partition_expression(raw_cfg, *, field_name="data_naixement"):
    cfg = normalize_birth_year_range_partition_config(raw_cfg)
    cases = [
        When(**{f"{field_name}__isnull": True}, then=Value(cfg.get("sense_data_label") or DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG["sense_data_label"]))
    ]
    for idx, item in enumerate(cfg.get("ranges") or []):
        from_date = _parse_optional_date(item.get("from_date"))
        until_date = _parse_optional_date(item.get("until_date"))
        if from_date is None and until_date is None:
            continue
        lookup = {}
        if from_date is not None:
            lookup[f"{field_name}__gte"] = from_date
        if until_date is not None:
            lookup[f"{field_name}__lte"] = until_date
        label = str(item.get("label") or "").strip() or default_birth_year_range_label(from_date, until_date, idx)
        cases.append(When(**lookup, then=Value(label)))
    return Case(
        *cases,
        default=Value(cfg.get("fora_rang_label") or DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG["fora_rang_label"]),
        output_field=CharField(),
    )


def _shift_years_safe(base_date, years):
    if not isinstance(base_date, date):
        return None
    try:
        return base_date.replace(year=base_date.year + years)
    except ValueError:
        # 29/02 -> 28/02 en anys no de traspas
        return base_date.replace(month=2, day=28, year=base_date.year + years)


def legacy_team_age_thresholds_to_birth_year_ranges(llindars, ref_date):
    if not isinstance(ref_date, date):
        return []

    thresholds = []
    seen = set()
    for raw in llindars or []:
        try:
            value = int(raw)
        except Exception:
            continue
        if value < 0 or value in seen:
            continue
        seen.add(value)
        thresholds.append(value)
    thresholds.sort()
    if not thresholds:
        return []

    ranges = []
    previous = None
    for threshold in thresholds:
        from_date = _shift_years_safe(ref_date, -(threshold + 1))
        if from_date is not None:
            from_date = from_date + timedelta(days=1)
        until_date = _shift_years_safe(ref_date, -(previous + 1)) if previous is not None else None
        label = f"<={threshold}" if previous is None else (
            f"{previous + 1}-{threshold}" if previous + 1 != threshold else f"{threshold}"
        )
        ranges.append(
            {
                "label": label,
                "from_date": _iso_or_none(from_date),
                "until_date": _iso_or_none(until_date),
            }
        )
        previous = threshold

    ranges.append(
        {
            "label": f">{previous}",
            "from_date": None,
            "until_date": _iso_or_none(_shift_years_safe(ref_date, -(previous + 1))),
        }
    )
    return ranges


def legacy_team_age_partition_to_birth_year_range_config(raw_cfg, ref_date):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    return normalize_birth_year_range_partition_config(
        {
            "ranges": legacy_team_age_thresholds_to_birth_year_ranges(cfg.get("llindars") or [], ref_date),
            "sense_data_label": str(cfg.get("sense_data_label") or "Sense edat").strip() or "Sense edat",
            "fora_rang_label": "Fora de forquilla",
            "team_rules": {
                "reference_mode": "oldest_member_birthdate",
                "compliance_mode": "strict",
                "max_members_outside_range": 0,
                "missing_birthdate_policy": "outside_range",
            },
        }
    )


def normalize_inscripcions_derived_group_config(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    return {
        BIRTH_YEAR_RANGE_PARTITION_CODE: normalize_birth_year_range_partition_config_for_inscripcions(
            cfg.get(BIRTH_YEAR_RANGE_PARTITION_CODE)
        ),
    }


def get_inscripcions_derived_group_config(view_cfg):
    view = view_cfg if isinstance(view_cfg, dict) else {}
    return normalize_inscripcions_derived_group_config(view.get("derived_group_config"))


@lru_cache(maxsize=256)
def _cached_inscripcions_derived_group_config(competicio_id):
    from ...models import Competicio

    if not competicio_id:
        return normalize_inscripcions_derived_group_config({})
    row = (
        Competicio.objects
        .filter(pk=competicio_id)
        .values("inscripcions_view")
        .first()
    )
    view_cfg = row.get("inscripcions_view") if isinstance(row, dict) else {}
    return get_inscripcions_derived_group_config(view_cfg)


def clear_inscripcions_derived_group_config_cache():
    _cached_inscripcions_derived_group_config.cache_clear()


def get_cached_inscripcions_derived_group_config(competicio_id):
    return _cached_inscripcions_derived_group_config(int(competicio_id or 0))
