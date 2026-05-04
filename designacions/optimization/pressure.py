"""Pressure metrics for designation optimization.

This module is intentionally Django-free. Inputs can be instances of the
optimization contracts dataclasses, plain dictionaries, or objects with matching
attributes.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any

try:  # Prefer the shared contracts when they are present in this package.
    from .contracts import BaseSubgroup, TutorCandidate
except ImportError:  # pragma: no cover - contracts may be introduced later.
    BaseSubgroup = Any  # type: ignore
    TutorCandidate = Any  # type: ignore


DEFAULT_CONFIG = {
    "time_bucket_minutes": 60,
    "modality_aliases": {},
    "level_rank": {},
    "isolated_cluster_statuses": {"isolated", "aillat", "outlier", "remote"},
}


def build_pressure_summary(
    base_subgroups: list[BaseSubgroup],
    tutors: list[TutorCandidate],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build local pressure metrics for buckets, vehicles, levels and clusters.

    Pressure is demand divided by viable tutor supply, capped only by using a
    minimum denominator of 1 so bottlenecks remain visible and auditable.
    """

    cfg = _merge_config(config)
    subgroup_rows = [_to_mapping(item) for item in base_subgroups]
    tutor_rows = [_to_mapping(item) for item in tutors]
    tutor_rows = [_normalize_tutor(row, cfg) for row in tutor_rows]

    bucket_demand: dict[str, dict[str, Any]] = {}
    vehicle_demand: dict[str, float] = {}
    level_demand: dict[str, dict[str, float]] = {}
    cluster_demand: dict[str, dict[str, float]] = {}

    for subgroup in subgroup_rows:
        normalized = _normalize_subgroup(subgroup, cfg)
        bucket_key = _bucket_key(normalized)
        demand = normalized["match_count"]

        entry = bucket_demand.setdefault(
            bucket_key,
            {
                "bucket": normalized["bucket"],
                "date": normalized["date"],
                "modality": normalized["modality"],
                "demand": 0.0,
                "subgroup_ids": [],
                "match_ids": [],
            },
        )
        entry["demand"] += demand
        if normalized["id"] is not None:
            entry["subgroup_ids"].append(normalized["id"])
        entry["match_ids"].extend(normalized["match_ids"])

        if _requires_vehicle(normalized, cfg):
            vehicle_demand[bucket_key] = vehicle_demand.get(bucket_key, 0.0) + demand

        levels_for_bucket = level_demand.setdefault(bucket_key, {})
        for level, level_count in normalized["level_demands"].items():
            levels_for_bucket[level] = levels_for_bucket.get(level, 0.0) + level_count

        for cluster_id in normalized["cluster_ids"] or ["unknown"]:
            cluster_key = _cluster_key(normalized, cluster_id)
            cluster_demand.setdefault(cluster_key, {
                "date": normalized["date"],
                "modality": normalized["modality"],
                "bucket": normalized["bucket"],
                "cluster_id": str(cluster_id),
                "demand": 0.0,
            })
            cluster_demand[cluster_key]["demand"] += demand

    bucket_supply = {
        key: _count_supply(entry, tutor_rows, cfg)
        for key, entry in bucket_demand.items()
    }

    pressure_by_hour = []
    pressure_lookup = {}
    for key in sorted(bucket_demand):
        entry = bucket_demand[key]
        supply = bucket_supply[key]["total"]
        pressure = _pressure(entry["demand"], supply)
        row = {
            "key": key,
            "date": entry["date"],
            "modality": entry["modality"],
            "bucket": entry["bucket"],
            "demand": entry["demand"],
            "supply": supply,
            "general_pressure": pressure,
            "subgroup_ids": entry["subgroup_ids"],
            "match_ids": entry["match_ids"],
        }
        pressure_by_hour.append(row)
        pressure_lookup[key] = pressure

    vehicle_pressure_by_hour = []
    vehicle_lookup = {}
    for key in sorted(bucket_demand):
        entry = bucket_demand[key]
        demand = vehicle_demand.get(key, 0.0)
        supply = bucket_supply[key]["vehicle"]
        pressure = _pressure(demand, supply)
        row = {
            "key": key,
            "date": entry["date"],
            "modality": entry["modality"],
            "bucket": entry["bucket"],
            "vehicle_demand": demand,
            "vehicle_supply": supply,
            "vehicle_pressure": pressure,
        }
        vehicle_pressure_by_hour.append(row)
        vehicle_lookup[key] = pressure

    level_pressure_by_hour = []
    level_lookup = {}
    for key in sorted(level_demand):
        entry = bucket_demand[key]
        for level in sorted(level_demand[key]):
            demand = level_demand[key][level]
            supply = _count_level_supply(entry, level, tutor_rows, cfg)
            pressure = _pressure(demand, supply)
            level_key = _join_key(key, level)
            row = {
                "key": level_key,
                "date": entry["date"],
                "modality": entry["modality"],
                "bucket": entry["bucket"],
                "level": level,
                "level_demand": demand,
                "level_supply": supply,
                "level_pressure": pressure,
            }
            level_pressure_by_hour.append(row)
            level_lookup[level_key] = pressure

    pressure_by_cluster = []
    cluster_lookup = {}
    for key in sorted(cluster_demand):
        entry = cluster_demand[key]
        bucket_key = _join_key(entry["date"], entry["modality"], entry["bucket"])
        supply = _count_cluster_supply(entry, tutor_rows, bucket_supply.get(bucket_key, {}), cfg)
        pressure = _pressure(entry["demand"], supply)
        row = {
            "key": key,
            "date": entry["date"],
            "modality": entry["modality"],
            "bucket": entry["bucket"],
            "cluster_id": entry["cluster_id"],
            "demand": entry["demand"],
            "supply": supply,
            "cluster_pressure": pressure,
        }
        pressure_by_cluster.append(row)
        cluster_lookup[key] = pressure

    return {
        "pressure_summary": _summarize_pressures(
            pressure_by_hour,
            vehicle_pressure_by_hour,
            level_pressure_by_hour,
            pressure_by_cluster,
        ),
        "pressure_by_hour": pressure_by_hour,
        "pressure_by_cluster": pressure_by_cluster,
        "vehicle_pressure_by_hour": vehicle_pressure_by_hour,
        "level_pressure_by_hour": level_pressure_by_hour,
        "lookups": {
            "general_pressure": pressure_lookup,
            "vehicle_pressure": vehicle_lookup,
            "level_pressure": level_lookup,
            "cluster_pressure": cluster_lookup,
        },
    }


def bucket_for_subgroup(subgroup: BaseSubgroup, config: dict[str, Any] | None = None) -> dict[str, str]:
    """Return the normalized pressure bucket for a subgroup-like object."""

    normalized = _normalize_subgroup(_to_mapping(subgroup), _merge_config(config))
    return {
        "date": normalized["date"],
        "modality": normalized["modality"],
        "bucket": normalized["bucket"],
        "key": _bucket_key(normalized),
    }


def bucket_for_datetime(
    value: datetime | date | str | None,
    modality: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Build a bucket from a date/datetime and optional modality."""

    cfg = _merge_config(config)
    dt = _parse_datetime(value)
    return {
        "date": _date_key(dt),
        "modality": _normalize_modality(modality, cfg),
        "bucket": _time_bucket(dt, cfg),
        "key": _join_key(_date_key(dt), _normalize_modality(modality, cfg), _time_bucket(dt, cfg)),
    }


def _merge_config(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    if config:
        merged.update(config)
    merged["isolated_cluster_statuses"] = {
        str(item).lower() for item in merged.get("isolated_cluster_statuses", set())
    }
    return merged


def _to_mapping(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    fields = getattr(value, "__dict__", None)
    return dict(fields) if fields is not None else {}


def _normalize_subgroup(row: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    start_dt = _parse_datetime(_first(row, "start_dt", "start", "inici", "hora_inici"))
    match_ids = _as_list(_first(row, "match_ids", "matches", "partit_ids", "partits"))
    cluster_ids = [str(item) for item in _as_list(_first(row, "cluster_ids", "clusters", "cluster_id"))]
    return {
        "id": _first(row, "id", "subgroup_id"),
        "date": _date_key(_first(row, "date", "data", default=start_dt)),
        "modality": _normalize_modality(_first(row, "modality", "modalitat"), cfg),
        "bucket": _time_bucket(start_dt, cfg),
        "match_count": _number(_first(row, "match_count", "num_matches", default=len(match_ids) or 1), 1.0),
        "match_ids": [str(item) for item in match_ids],
        "cluster_ids": cluster_ids,
        "cluster_statuses": [str(item).lower() for item in _as_list(_first(row, "cluster_statuses", "cluster_status"))],
        "level_demands": _normalize_level_demands(
            _first(row, "level_demand", "level", "category", "categoria"),
            _number(_first(row, "match_count", "num_matches", default=len(match_ids) or 1), 1.0),
        ),
        "requires_vehicle": _truthy(_first(row, "requires_vehicle", "vehicle_required", default=False)),
        "vehicle_preferred": _truthy(_first(row, "vehicle_preferred", default=False)),
    }


def _normalize_tutor(row: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _first(row, "id", "tutor_id"),
        "modality": _normalize_modality(_first(row, "modality", "modalitat"), cfg),
        "level": str(_first(row, "level", "nivell", default="unknown")),
        "has_vehicle": _truthy(_first(row, "has_vehicle", "vehicle", "cotxe", default=False)),
        "availability_by_date": _first(row, "availability_by_date", "availability", "disponibilitat", default=None),
        "cluster_ids": [str(item) for item in _as_list(_first(row, "cluster_ids", "clusters", "preferred_cluster_ids"))],
    }


def _bucket_key(normalized: dict[str, Any]) -> str:
    return _join_key(normalized["date"], normalized["modality"], normalized["bucket"])


def _cluster_key(normalized: dict[str, Any], cluster_id: Any) -> str:
    return _join_key(normalized["date"], normalized["modality"], normalized["bucket"], cluster_id)


def _join_key(*parts: Any) -> str:
    return "|".join(str(part) for part in parts)


def _count_supply(bucket: dict[str, Any], tutors: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, int]:
    matching = [
        tutor for tutor in tutors
        if _modality_matches(tutor["modality"], bucket["modality"])
        and _is_available(tutor.get("availability_by_date"), bucket["date"], bucket["bucket"])
    ]
    return {
        "total": len(matching),
        "vehicle": sum(1 for tutor in matching if tutor["has_vehicle"]),
    }


def _count_level_supply(bucket: dict[str, Any], level: str, tutors: list[dict[str, Any]], cfg: dict[str, Any]) -> int:
    return sum(
        1 for tutor in tutors
        if _modality_matches(tutor["modality"], bucket["modality"])
        and _level_acceptable(tutor["level"], level, cfg)
        and _is_available(tutor.get("availability_by_date"), bucket["date"], bucket["bucket"])
    )


def _count_cluster_supply(
    cluster_bucket: dict[str, Any],
    tutors: list[dict[str, Any]],
    bucket_supply: dict[str, Any],
    cfg: dict[str, Any],
) -> int:
    cluster_id = str(cluster_bucket["cluster_id"])
    local = [
        tutor for tutor in tutors
        if cluster_id in tutor["cluster_ids"]
        and _modality_matches(tutor["modality"], cluster_bucket["modality"])
        and _is_available(tutor.get("availability_by_date"), cluster_bucket["date"], cluster_bucket["bucket"])
    ]
    if local:
        return len(local)
    return int(bucket_supply.get("total", 0))


def _is_available(availability_by_date: Any, date_key: str, bucket: str) -> bool:
    if not availability_by_date:
        return True
    if not isinstance(availability_by_date, dict):
        return bool(availability_by_date)

    day_value = _availability_for_date(availability_by_date, date_key)
    if day_value is None:
        return True
    return _availability_value_allows(day_value, bucket)


def _availability_for_date(availability_by_date: dict[Any, Any], date_key: str) -> Any:
    keys: set[Any] = {date_key, _date_without_time(date_key)}
    parsed = _parse_datetime(date_key)
    if isinstance(parsed, datetime):
        keys.add(parsed.date())
    elif isinstance(parsed, date):
        keys.add(parsed)

    for key, value in availability_by_date.items():
        if key in keys or _date_key(key) in keys:
            return value
    return None


def _availability_value_allows(value: Any, bucket: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        if "available" in value:
            return bool(value["available"])
        if bucket in value:
            return bool(value[bucket])
        windows = value.get("windows") or value.get("intervals") or value.get("slots")
        if windows is not None:
            return _any_window_allows(windows, bucket)
        if "start" in value or "end" in value:
            return _window_allows(value, bucket)
        return any(bool(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return _any_window_allows(value, bucket)
    return bool(value)


def _any_window_allows(windows: Any, bucket: str) -> bool:
    if isinstance(windows, str):
        return windows == bucket
    return any(_window_allows(window, bucket) for window in windows)


def _window_allows(window: Any, bucket: str) -> bool:
    if isinstance(window, str):
        return window == bucket
    if isinstance(window, dict):
        start = window.get("start") or window.get("from")
        end = window.get("end") or window.get("to")
    elif isinstance(window, (list, tuple)) and len(window) >= 2:
        start, end = window[0], window[1]
    else:
        return bool(window)

    bucket_minutes = _minutes_from_hhmm(bucket)
    start_minutes = _minutes_from_hhmm(str(start)) if start is not None else 0
    end_minutes = _minutes_from_hhmm(str(end)) if end is not None else 24 * 60
    return start_minutes <= bucket_minutes < end_minutes


def _requires_vehicle(subgroup: dict[str, Any], cfg: dict[str, Any]) -> bool:
    if subgroup["requires_vehicle"] or subgroup["vehicle_preferred"]:
        return True
    if len(set(subgroup["cluster_ids"])) > 1:
        return True
    statuses = set(subgroup["cluster_statuses"])
    return bool(statuses & cfg["isolated_cluster_statuses"])


def _normalize_level_demands(value: Any, default_count: float) -> dict[str, float]:
    if isinstance(value, dict):
        normalized = {
            str(level): _number(count, 0.0)
            for level, count in value.items()
            if level is not None
        }
        return normalized or {"unknown": default_count}
    if value is None:
        return {"unknown": default_count}
    return {str(value): default_count}


def _level_acceptable(tutor_level: str, demand_level: str, cfg: dict[str, Any]) -> bool:
    if demand_level == "unknown" or tutor_level == demand_level:
        return True
    rank = cfg.get("level_rank") or {}
    if tutor_level in rank and demand_level in rank:
        return rank[tutor_level] >= rank[demand_level]
    try:
        return float(tutor_level) >= float(demand_level)
    except (TypeError, ValueError):
        return False


def _pressure(demand: float, supply: int | float) -> float:
    return round(float(demand) / max(float(supply), 1.0), 4)


def _summarize_pressures(
    general: list[dict[str, Any]],
    vehicle: list[dict[str, Any]],
    level: list[dict[str, Any]],
    cluster: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "bucket_count": len(general),
        "max_general_pressure": _max_metric(general, "general_pressure"),
        "max_vehicle_pressure": _max_metric(vehicle, "vehicle_pressure"),
        "max_level_pressure": _max_metric(level, "level_pressure"),
        "max_cluster_pressure": _max_metric(cluster, "cluster_pressure"),
        "high_pressure_buckets": [
            row["key"] for row in general if row["general_pressure"] >= 1.0
        ],
        "high_vehicle_pressure_buckets": [
            row["key"] for row in vehicle if row["vehicle_pressure"] >= 1.0
        ],
        "high_cluster_pressure_buckets": [
            row["key"] for row in cluster if row["cluster_pressure"] >= 1.0
        ],
    }


def _max_metric(rows: list[dict[str, Any]], metric: str) -> float:
    if not rows:
        return 0.0
    return max(float(row.get(metric, 0.0)) for row in rows)


def _first(row: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return default


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "si", "y"}
    return bool(value)


def _normalize_modality(value: Any, cfg: dict[str, Any]) -> str:
    modality = str(value or "unknown").strip().lower()
    return str(cfg.get("modality_aliases", {}).get(modality, modality))


def _modality_matches(tutor_modality: str, bucket_modality: str) -> bool:
    return tutor_modality in {bucket_modality, "any", "unknown"} or bucket_modality == "unknown"


def _parse_datetime(value: Any) -> datetime | date | None:
    if isinstance(value, (datetime, date)):
        return value
    if isinstance(value, str) and value:
        cleaned = value.replace("Z", "+00:00")
        for parser in (datetime.fromisoformat, date.fromisoformat):
            try:
                return parser(cleaned)
            except ValueError:
                continue
    return None


def _date_key(value: Any) -> str:
    parsed = _parse_datetime(value)
    if isinstance(parsed, datetime):
        return parsed.date().isoformat()
    if isinstance(parsed, date):
        return parsed.isoformat()
    if value:
        return _date_without_time(str(value))
    return "unknown"


def _date_without_time(value: str) -> str:
    return value.split("T", 1)[0].split(" ", 1)[0]


def _time_bucket(value: Any, cfg: dict[str, Any]) -> str:
    parsed = _parse_datetime(value)
    if not isinstance(parsed, datetime):
        return "unknown"
    minutes = parsed.hour * 60 + parsed.minute
    bucket_size = max(int(cfg.get("time_bucket_minutes", 60)), 1)
    bucket_minutes = (minutes // bucket_size) * bucket_size
    return _hhmm_from_minutes(bucket_minutes)


def _minutes_from_hhmm(value: str) -> int:
    if "T" in value:
        value = value.rsplit("T", 1)[1]
    if " " in value:
        value = value.rsplit(" ", 1)[1]
    parts = value.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        return 0
    return hour * 60 + minute


def _hhmm_from_minutes(minutes: int) -> str:
    hour = minutes // 60
    minute = minutes % 60
    return f"{hour:02d}:{minute:02d}"
