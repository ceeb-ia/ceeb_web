from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time
from inspect import signature
from itertools import combinations
from typing import Any, Iterable

from designacions.services.assignment_feasibility import normalize_text_key

from .classification import package_classification_importance, weighted_coverage
from .levels import (
    LEVEL_FIT_ACCEPTABLE,
    LEVEL_FIT_EXCEPTIONAL,
    LEVEL_FIT_FORBIDDEN,
    LEVEL_FIT_IDEAL,
    LEVEL_FIT_UNSCORABLE,
    hardest_match_level,
    level_fit,
)


try:
    from .levels import level_fit as classify_level_fit
except Exception:  # pragma: no cover - levels.py is optional during rollout.
    classify_level_fit = None


try:
    from .contracts import PackageCandidate as ContractPackageCandidate
except Exception:  # pragma: no cover - contracts.py is optional during rollout.
    ContractPackageCandidate = None


@dataclass(frozen=True)
class LocalPackageCandidate:
    id: str
    kind: str
    subgroup_ids: list[str]
    match_ids: list[str]
    date: date | str | None
    modality: str
    start_dt: datetime | Any | None
    end_dt: datetime | Any | None
    requires_vehicle: bool = False
    vehicle_preferred: bool = False
    warning_codes: list[str] = field(default_factory=list)
    pressure_relief_score: float = 0.0
    base_difficulty_score: float = 0.0
    coverage_value: float = 0.0
    route_score: float = 0.0
    cluster_ids: list[str | None] = field(default_factory=list)
    cluster_statuses: list[str | None] = field(default_factory=list)
    venues: list[str] = field(default_factory=list)
    component_ids: list[str] = field(default_factory=list)
    level_demand: Any = None
    classification_pressure: float = 0.0
    classification_importance: float = 0.0
    weighted_coverage_value: float = 0.0
    level_fit_summary: dict[str, int] = field(default_factory=dict)
    eligible_tutor_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PackageCandidate = ContractPackageCandidate or LocalPackageCandidate


TRANSPORT_FIELDS = (
    "Mitja de Transport",
    "Mitjà de Transport",
    "MitjÃ\xa0 de Transport",
    "MitjÃƒÂ\xa0 de Transport",
    "transport",
)

MATCH_LEVEL_ORDER = (
    "SÈNIOR",
    "JÚNIOR",
    "JUVENIL",
    "CADET",
    "INFANTIL",
    "PREINFANTIL",
    "ALEVÍ",
    "BENJAMÍ",
    "PREBENJAMÍ",
    "MENUT",
    "INFANTIL MIXT",
    "ALEVÍ MIXT",
    "BENJAMÍ MIXT",
    "PREBENJAMÍ MIXT",
    "MENUT MIXT",
)

TUTOR_LEVEL_ORDER = ("NIVELLA1", "NIVELLB1", "NIVELLC1", "NIVELLD1", "D")
LEVEL_FIT_LABELS = ("ideal", "acceptable", "exceptional", "forbidden", "unscorable")


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row.get(key, default)
    except AttributeError:
        return getattr(row, key, default)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(value != value)
    except Exception:
        return False


def _clean_text(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip()


def _dedupe(values: Iterable[Any]) -> list[Any]:
    out = []
    seen = set()
    for value in values:
        key = repr(value)
        if key not in seen:
            out.append(value)
            seen.add(key)
    return out


def _parse_date(value: Any) -> date | str | None:
    if _is_missing(value) or _clean_text(value).lower() in {"", "nat"}:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date") and not isinstance(value, str):
        try:
            return value.date()
        except Exception:
            pass
    raw = _clean_text(value)
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return raw


def _parse_time(value: Any) -> time | None:
    if _is_missing(value) or _clean_text(value) in {"", "-", "NaT"}:
        return None
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    if isinstance(value, time):
        return value.replace(microsecond=0)
    raw = _clean_text(value)
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


def _as_datetime(value: Any) -> datetime | Any | None:
    if _is_missing(value):
        return None
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime()
        except Exception:
            return value
    return value


def _row_datetime(row: Any) -> datetime | Any | None:
    value = _row_get(row, "__match_datetime")
    parsed = _as_datetime(value)
    if parsed is not None:
        return parsed
    parsed_date = _parse_date(_row_get(row, "Data"))
    parsed_time = _parse_time(_row_get(row, "Hora"))
    if isinstance(parsed_date, date) and parsed_time is not None:
        return datetime.combine(parsed_date, parsed_time)
    return None


def _candidate(payload: dict[str, Any]) -> Any:
    if ContractPackageCandidate is None:
        return LocalPackageCandidate(**payload)
    accepted = set(signature(ContractPackageCandidate).parameters)
    return ContractPackageCandidate(**{key: value for key, value in payload.items() if key in accepted})


def _obj_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _clusters_need_vehicle(cluster_ids: Iterable[Any]) -> bool:
    cleaned = {cluster for cluster in cluster_ids if cluster is not None and _clean_text(cluster)}
    return len(cleaned) > 1


def _has_unreliable_cluster(cluster_ids: Iterable[Any], statuses: Iterable[Any]) -> bool:
    if any(cluster is None or not _clean_text(cluster) for cluster in cluster_ids):
        return True
    normalized_statuses = {_clean_text(status).lower() for status in statuses if _clean_text(status)}
    return bool(normalized_statuses.intersection({"outlier", "missing_geocode", "pending", "not_found"}))


def _warning_codes(cluster_ids: list[Any], statuses: list[Any], *, requires_vehicle: bool) -> list[str]:
    warnings = []
    normalized_statuses = {_clean_text(status).lower() for status in statuses if _clean_text(status)}
    if "outlier" in normalized_statuses:
        warnings.append("outlier_mobility_warning")
    elif _has_unreliable_cluster(cluster_ids, statuses):
        warnings.append("missing_cluster_mobility_warning")
    if requires_vehicle:
        warnings.append("cross_cluster_with_vehicle_warning")
    return _dedupe(warnings)


def _level_demand_from_rows(rows: list[Any]) -> Any:
    return hardest_match_level([_row_get(row, "Categoria", _row_get(row, "Nivell")) for row in rows])


def _hardest_level(left: Any, right: Any) -> Any:
    return hardest_match_level([_obj_get(left, "level_demand"), _obj_get(right, "level_demand")])


def _base_payload(base: Any, *, candidate_id: str, kind: str, match_ids: list[str] | None = None) -> dict[str, Any]:
    selected_match_ids = list(match_ids if match_ids is not None else _obj_get(base, "match_ids", []))
    cluster_ids = list(_obj_get(base, "cluster_ids", []) or [])
    statuses = list(_obj_get(base, "cluster_statuses", []) or [])
    requires_vehicle = _clusters_need_vehicle(cluster_ids)
    vehicle_preferred = _has_unreliable_cluster(cluster_ids, statuses)
    return {
        "id": candidate_id,
        "kind": kind,
        "subgroup_ids": [_obj_get(base, "id", "")],
        "match_ids": selected_match_ids,
        "date": _obj_get(base, "date"),
        "modality": _obj_get(base, "modality", ""),
        "start_dt": _as_datetime(_obj_get(base, "start_dt")),
        "end_dt": _as_datetime(_obj_get(base, "end_dt")),
        "requires_vehicle": requires_vehicle,
        "vehicle_preferred": vehicle_preferred,
        "warning_codes": _warning_codes(cluster_ids, statuses, requires_vehicle=requires_vehicle),
        "pressure_relief_score": 0.0,
        "base_difficulty_score": 0.0,
        "coverage_value": float(len(selected_match_ids)),
        "route_score": float(len(selected_match_ids)),
        "cluster_ids": cluster_ids,
        "cluster_statuses": statuses,
        "venues": list(_obj_get(base, "venues", []) or []),
        "component_ids": [],
        "level_demand": _obj_get(base, "level_demand"),
        "classification_pressure": _obj_get(base, "classification_pressure", 0.0),
        "classification_importance": float(_obj_get(base, "classification_importance", 0.0) or 0.0),
        "weighted_coverage_value": float(
            _obj_get(base, "weighted_coverage_value", 0.0)
            or weighted_coverage(len(selected_match_ids), float(_obj_get(base, "classification_importance", 0.0) or 0.0))
        ),
    }


def _split_base_by_indices(base: Any, indexes: list[int], *, candidate_id: str, kind: str) -> Any:
    match_ids = list(_obj_get(base, "match_ids", []) or [])
    cluster_ids = list(_obj_get(base, "cluster_ids", []) or [])
    statuses = list(_obj_get(base, "cluster_statuses", []) or [])
    rows = list(_obj_get(base, "rows", []) or [])
    selected_rows = [rows[index] for index in indexes if index < len(rows)]
    selected_datetimes = [dt for dt in (_row_datetime(row) for row in selected_rows) if dt is not None]
    payload = _base_payload(
        base,
        candidate_id=candidate_id,
        kind=kind,
        match_ids=[match_ids[index] for index in indexes if index < len(match_ids)],
    )
    payload["cluster_ids"] = [cluster_ids[index] for index in indexes if index < len(cluster_ids)]
    payload["cluster_statuses"] = [statuses[index] for index in indexes if index < len(statuses)]
    if selected_datetimes:
        payload["start_dt"] = min(selected_datetimes)
        payload["end_dt"] = max(selected_datetimes)
    if selected_rows:
        payload["venues"] = _dedupe(
            _clean_text(_row_get(row, "Pista joc", _row_get(row, "venue")))
            for row in selected_rows
            if _clean_text(_row_get(row, "Pista joc", _row_get(row, "venue")))
        )
        payload["level_demand"] = _level_demand_from_rows(selected_rows)
        payload["classification_importance"] = package_classification_importance(selected_rows, _row_get)
        payload["weighted_coverage_value"] = weighted_coverage(
            len(payload["match_ids"]),
            payload["classification_importance"],
        )
    payload["requires_vehicle"] = _clusters_need_vehicle(payload["cluster_ids"])
    payload["vehicle_preferred"] = _has_unreliable_cluster(payload["cluster_ids"], payload["cluster_statuses"])
    payload["warning_codes"] = _warning_codes(payload["cluster_ids"], payload["cluster_statuses"], requires_vehicle=payload["requires_vehicle"])
    return _candidate(payload)


def _split_variants(base: Any, config: dict[str, Any]) -> list[Any]:
    match_ids = list(_obj_get(base, "match_ids", []) or [])
    if len(match_ids) <= 1:
        return []
    max_split_size = int(config.get("max_split_subgroup_size", 3))
    max_variants = int(config.get("max_split_variants_per_subgroup", 4))
    if len(match_ids) > max_split_size or max_variants <= 0:
        return []

    variants = []
    base_id = _obj_get(base, "id", "base")
    for index in range(len(match_ids)):
        variants.append(_split_base_by_indices(base, [index], candidate_id=f"{base_id}:single:{index + 1}", kind="single_match"))

    for start in range(len(match_ids)):
        for end in range(start + 2, len(match_ids) + 1):
            if start == 0 and end == len(match_ids):
                continue
            variants.append(
                _split_base_by_indices(
                    base,
                    list(range(start, end)),
                    candidate_id=f"{base_id}:split:{start + 1}-{end}",
                    kind="contiguous_split",
                )
            )
            if len(variants) >= len(match_ids) + max_variants:
                return variants
    return variants[: len(match_ids) + max_variants]


def _pressure_lookup(pressure_summary: Any, key: str, default: float = 0.0) -> float:
    if not isinstance(pressure_summary, dict):
        return default
    value = pressure_summary.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _score_candidate(candidate: Any, pressure_summary: Any, tutors: list[Any] | None = None, config: dict[str, Any] | None = None) -> Any:
    pressure_bonus = _pressure_lookup(pressure_summary, "general_pressure", 0.0)
    vehicle_bonus = _pressure_lookup(pressure_summary, "vehicle_pressure", 0.0)
    relief = float(len(_obj_get(candidate, "match_ids", []) or [])) + pressure_bonus
    if _obj_get(candidate, "requires_vehicle", False):
        relief += vehicle_bonus + 1.0
    relief += float(_obj_get(candidate, "classification_importance", 0.0) or 0.0) * _pressure_lookup(
        pressure_summary,
        "classification_route_weight",
        0.5,
    )
    difficulty = 0.0
    if _obj_get(candidate, "requires_vehicle", False):
        difficulty += 2.0
    if _obj_get(candidate, "vehicle_preferred", False):
        difficulty += 1.0
    difficulty += len(_obj_get(candidate, "warning_codes", []) or []) * 0.25
    route_score = relief - difficulty
    try:
        scored = replace(
            candidate,
            pressure_relief_score=relief,
            base_difficulty_score=difficulty,
            route_score=route_score,
        )
    except TypeError:
        scored = candidate
    if tutors is None:
        return scored
    return _with_level_metadata(
        scored,
        tutors,
        allow_exceptional=bool((config or {}).get("allow_exceptional_routes", False)),
        config=config,
    )


def _transport_value(tutor: Any) -> str:
    for field_name in TRANSPORT_FIELDS:
        value = _row_get(tutor, field_name)
        if _clean_text(value):
            return _clean_text(value)
    return ""


def _has_vehicle(tutor: Any) -> bool:
    normalized = _transport_value(tutor).lower()
    return any(token in normalized for token in ("cotxe", "coche", "moto", "bicicleta", "bici", "patinet", "furgoneta"))


def _iter_tutors(tutors: Any) -> list[Any]:
    if tutors is None:
        return []
    if hasattr(tutors, "iterrows"):
        return [row for _, row in tutors.iterrows()]
    return list(tutors)


def _tutor_matches_day_modality(tutor: Any, candidate: Any) -> bool:
    tutor_modality = _clean_text(_row_get(tutor, "Modalitat", _row_get(tutor, "modality"))).lower()
    candidate_modality = _clean_text(_obj_get(candidate, "modality")).lower()
    if tutor_modality and candidate_modality and tutor_modality != candidate_modality:
        return False
    tutor_date = _parse_date(_row_get(tutor, "Data", _row_get(tutor, "date")))
    candidate_date = _parse_date(_obj_get(candidate, "date"))
    return tutor_date is None or candidate_date is None or tutor_date == candidate_date


def _availability_covers(tutor: Any, candidate: Any) -> bool:
    if not _tutor_matches_day_modality(tutor, candidate):
        return False
    start_dt = _as_datetime(_obj_get(candidate, "start_dt"))
    end_dt = _as_datetime(_obj_get(candidate, "end_dt"))
    if start_dt is None or end_dt is None or not isinstance(start_dt, datetime) or not isinstance(end_dt, datetime):
        return True
    availability_by_date = _row_get(tutor, "availability_by_date")
    if isinstance(availability_by_date, dict):
        day_key = start_dt.date().isoformat()
        raw_windows = availability_by_date.get(day_key) or availability_by_date.get(start_dt.date())
        if raw_windows is not None:
            windows = raw_windows if isinstance(raw_windows, list) else [raw_windows]
            for window in windows:
                if isinstance(window, dict):
                    start_value = window.get("start") or window.get("Hora Inici")
                    end_value = window.get("end") or window.get("Hora Fi")
                elif isinstance(window, tuple) and len(window) >= 2:
                    start_value, end_value = window[0], window[1]
                else:
                    continue
                start_time = _parse_time(start_value)
                end_time = _parse_time(end_value)
                if start_time is not None and end_time is not None and start_time <= start_dt.time() and end_dt.time() <= end_time:
                    return True
            return False
    start_time = _parse_time(_row_get(tutor, "Hora Inici"))
    end_time = _parse_time(_row_get(tutor, "Hora Fi"))
    if start_time is None or end_time is None:
        return True
    availability_date = _parse_date(_row_get(tutor, "Data"))
    if isinstance(availability_date, date) and start_dt.date() != availability_date:
        return False
    return start_time <= start_dt.time() and end_dt.time() <= end_time


def _has_viable_tutor(candidate: Any, tutors: list[Any]) -> bool:
    if not tutors:
        return True
    for tutor in tutors:
        if _tutor_can_cover_candidate(tutor, candidate):
            return True
    return False


def _tutor_can_cover_candidate(tutor: Any, candidate: Any) -> bool:
    if _obj_get(candidate, "requires_vehicle", False) and not _has_vehicle(tutor):
        return False
    return _availability_covers(tutor, candidate)


def _level_label(value: Any) -> str:
    if isinstance(value, str):
        label = value
    elif isinstance(value, dict):
        label = value.get("label", "")
    else:
        label = getattr(value, "label", "")
    normalized = _clean_text(label).lower()
    return normalized if normalized in LEVEL_FIT_LABELS else "unscorable"


def _ordered_position(value: Any, order: Iterable[str]) -> float | None:
    text = normalize_text_key(value)
    if not text:
        return None
    normalized_order = [normalize_text_key(item) for item in order]
    if text in normalized_order:
        return normalized_order.index(text) / max(len(normalized_order) - 1, 1)
    for index, token in sorted(enumerate(normalized_order), key=lambda item: len(item[1]), reverse=True):
        if token and token in text:
            return index / max(len(normalized_order) - 1, 1)
    return None


def _tutor_level(tutor: Any) -> Any:
    return _row_get(tutor, "level", _row_get(tutor, "nivell", _row_get(tutor, "Nivell")))


def _candidate_level_demand(candidate: Any) -> Any:
    return _obj_get(candidate, "level_demand", _obj_get(candidate, "level"))


def _fallback_level_fit_label(tutor: Any, candidate: Any) -> str:
    tutor_position = _ordered_position(_tutor_level(tutor), TUTOR_LEVEL_ORDER)
    demand_position = _ordered_position(_candidate_level_demand(candidate), MATCH_LEVEL_ORDER)
    if tutor_position is None or demand_position is None:
        return "unscorable"
    under_level_gap = tutor_position - demand_position
    if under_level_gap <= 0.08:
        return "ideal"
    if under_level_gap <= 0.22:
        return "acceptable"
    if under_level_gap <= 0.42:
        return "exceptional"
    return "forbidden"


def _candidate_level_fit_label(tutor: Any, candidate: Any, config: dict[str, Any] | None = None) -> str:
    if classify_level_fit is None:
        return _fallback_level_fit_label(tutor, candidate)
    level_config = dict(config or {})
    level_config.setdefault(
        "classification_importance",
        float(_obj_get(candidate, "classification_importance", 0.0) or 0.0),
    )
    tutor_level = _tutor_level(tutor)
    match_level = _candidate_level_demand(candidate)
    try:
        return _level_label(classify_level_fit(tutor_level, match_level, level_config))
    except TypeError:
        pass
    try:
        return _level_label(classify_level_fit(tutor_level, match_level))
    except TypeError:
        pass
    for args in ((tutor, candidate), (candidate, tutor)):
        try:
            return _level_label(classify_level_fit(*args))
        except TypeError:
            continue
    try:
        return _level_label(classify_level_fit(tutor=tutor, package=candidate))
    except TypeError:
        return "unscorable"


def _level_fit_summary(candidate: Any, tutors: list[Any], config: dict[str, Any] | None = None) -> dict[str, int]:
    summary = {label: 0 for label in LEVEL_FIT_LABELS}
    if not tutors:
        return summary
    for tutor in tutors:
        if not _tutor_can_cover_candidate(tutor, candidate):
            continue
        summary[_candidate_level_fit_label(tutor, candidate, config)] += 1
    return summary


def _ideal_acceptable_count(summary: dict[str, int]) -> int:
    return int(summary.get("ideal", 0)) + int(summary.get("acceptable", 0))


def _eligible_count(summary: dict[str, int], *, allow_exceptional: bool = False) -> int:
    count = _ideal_acceptable_count(summary)
    if allow_exceptional:
        count += int(summary.get("exceptional", 0))
    return count


def _route_has_allowed_level_fit(route: Any, config: dict[str, Any], summary: dict[str, int] | None = None) -> bool:
    summary = summary or _obj_get(route, "level_fit_summary", {}) or {}
    if _ideal_acceptable_count(summary) > 0:
        return True
    return bool(config.get("allow_exceptional_routes", False)) and int(summary.get("exceptional", 0)) > 0


def _route_retention_key(route: Any, summary: dict[str, int] | None = None) -> tuple[float, float, float, float]:
    summary = summary or _obj_get(route, "level_fit_summary", {}) or {}
    return (
        float(_ideal_acceptable_count(summary)),
        float(_obj_get(route, "weighted_coverage_value", 0.0) or 0.0),
        float(_obj_get(route, "classification_importance", 0.0) or 0.0),
        float(_obj_get(route, "route_score", 0.0) or 0.0),
    )


def _with_level_metadata(
    candidate: Any,
    tutors: list[Any],
    *,
    allow_exceptional: bool = False,
    config: dict[str, Any] | None = None,
) -> Any:
    summary = _level_fit_summary(candidate, tutors, config)
    eligible_tutor_count = _eligible_count(summary, allow_exceptional=allow_exceptional)
    try:
        return replace(
            candidate,
            level_fit_summary=summary,
            eligible_tutor_count=eligible_tutor_count,
        )
    except TypeError:
        return candidate


def _gap_minutes(left: Any, right: Any) -> float | None:
    left_end = _as_datetime(_obj_get(left, "end_dt"))
    right_start = _as_datetime(_obj_get(right, "start_dt"))
    if not isinstance(left_end, datetime) or not isinstance(right_start, datetime):
        return None
    return (right_start - left_end).total_seconds() / 60.0


def _required_gap(left: Any, right: Any, config: dict[str, Any], requires_vehicle: bool) -> int:
    left_venues = set(_obj_get(left, "venues", []) or [])
    right_venues = set(_obj_get(right, "venues", []) or [])
    same_pitch = bool(left_venues and right_venues and left_venues.intersection(right_venues))
    if same_pitch:
        return int(config.get("gap_same_pitch_min", 90))
    if requires_vehicle:
        return int(config.get("gap_diff_cluster_min", 150))
    return int(config.get("gap_diff_pitch_min", 120))


def _can_route(left: Any, right: Any, config: dict[str, Any]) -> bool:
    if _obj_get(left, "date") != _obj_get(right, "date"):
        return False
    if _clean_text(_obj_get(left, "modality")).lower() != _clean_text(_obj_get(right, "modality")).lower():
        return False
    if set(_obj_get(left, "match_ids", []) or []).intersection(_obj_get(right, "match_ids", []) or []):
        return False
    minutes = _gap_minutes(left, right)
    if minutes is None or minutes < 0:
        return False
    cluster_ids = list(_obj_get(left, "cluster_ids", []) or []) + list(_obj_get(right, "cluster_ids", []) or [])
    return minutes >= _required_gap(left, right, config, _clusters_need_vehicle(cluster_ids))


def _merge_route(left: Any, right: Any, pressure_summary: Any, tutors: list[Any] | None = None, config: dict[str, Any] | None = None) -> Any:
    cluster_ids = list(_obj_get(left, "cluster_ids", []) or []) + list(_obj_get(right, "cluster_ids", []) or [])
    statuses = list(_obj_get(left, "cluster_statuses", []) or []) + list(_obj_get(right, "cluster_statuses", []) or [])
    requires_vehicle = _clusters_need_vehicle(cluster_ids)
    vehicle_preferred = _has_unreliable_cluster(cluster_ids, statuses)
    component_ids = [_obj_get(left, "id"), _obj_get(right, "id")]
    kind = "merged_route"
    if _obj_get(left, "kind") != "base" or _obj_get(right, "kind") != "base":
        kind = "split_merged_route"
    classification_importance = max(
        float(_obj_get(left, "classification_importance", 0.0) or 0.0),
        float(_obj_get(right, "classification_importance", 0.0) or 0.0),
    )
    match_count = len(_obj_get(left, "match_ids", []) or []) + len(_obj_get(right, "match_ids", []) or [])
    payload = {
        "id": "route:" + "+".join(component_ids),
        "kind": kind,
        "subgroup_ids": _dedupe(list(_obj_get(left, "subgroup_ids", []) or []) + list(_obj_get(right, "subgroup_ids", []) or [])),
        "match_ids": list(_obj_get(left, "match_ids", []) or []) + list(_obj_get(right, "match_ids", []) or []),
        "date": _obj_get(left, "date"),
        "modality": _obj_get(left, "modality", ""),
        "start_dt": _obj_get(left, "start_dt"),
        "end_dt": _obj_get(right, "end_dt"),
        "requires_vehicle": requires_vehicle,
        "vehicle_preferred": vehicle_preferred,
        "warning_codes": _warning_codes(cluster_ids, statuses, requires_vehicle=requires_vehicle),
        "pressure_relief_score": 0.0,
        "base_difficulty_score": 0.0,
        "coverage_value": float(match_count),
        "route_score": 0.0,
        "cluster_ids": cluster_ids,
        "cluster_statuses": statuses,
        "venues": _dedupe(list(_obj_get(left, "venues", []) or []) + list(_obj_get(right, "venues", []) or [])),
        "component_ids": component_ids,
        "level_demand": _hardest_level(left, right),
        "classification_pressure": float(_obj_get(left, "classification_pressure", 0.0) or 0.0)
        + float(_obj_get(right, "classification_pressure", 0.0) or 0.0),
        "classification_importance": classification_importance,
        "weighted_coverage_value": weighted_coverage(match_count, classification_importance),
    }
    return _score_candidate(_candidate(payload), pressure_summary, tutors, config)


def _route_budget(candidates: list[Any], tutors: list[Any], config: dict[str, Any]) -> dict[tuple[Any, str], int]:
    groups = {(candidate.date, candidate.modality) for candidate in candidates if hasattr(candidate, "date")}
    budgets = {}
    factor = int(config.get("route_candidate_factor", 2))
    buffer = int(config.get("route_candidate_buffer", 3))
    for key_date, key_modality in groups:
        probe = type("Probe", (), {"date": key_date, "modality": key_modality})()
        vehicle_capable = sum(1 for tutor in tutors if _has_vehicle(tutor) and _tutor_matches_day_modality(tutor, probe))
        budgets[(key_date, key_modality)] = max(vehicle_capable * factor, vehicle_capable + buffer, 1)
    return budgets


def generate_package_candidates(
    base_subgroups: Iterable[Any],
    tutors: Any = None,
    pressure_summary: Any = None,
    config: dict[str, Any] | None = None,
) -> list[Any]:
    config = dict(config or {})
    tutor_rows = _iter_tutors(tutors)
    candidates = []
    seen_ids = set()

    for base in base_subgroups or []:
        base_candidate = _score_candidate(
            _candidate(_base_payload(base, candidate_id=f"pkg:{_obj_get(base, 'id')}", kind="base")),
            pressure_summary,
            tutor_rows,
            config,
        )
        if _has_viable_tutor(base_candidate, tutor_rows):
            candidates.append(base_candidate)
            seen_ids.add(_obj_get(base_candidate, "id"))
        for variant in _split_variants(base, config):
            variant = _score_candidate(variant, pressure_summary, tutor_rows, config)
            if _obj_get(variant, "id") not in seen_ids and _has_viable_tutor(variant, tutor_rows):
                candidates.append(variant)
                seen_ids.add(_obj_get(variant, "id"))

    ordered = sorted(
        candidates,
        key=lambda item: (
            _clean_text(_obj_get(item, "date")),
            _obj_get(item, "start_dt") or datetime.max,
            _obj_get(item, "id"),
        ),
    )
    route_candidates_by_group: dict[tuple[Any, str], list[tuple[Any, dict[str, int]]]] = {}
    for left, right in combinations(ordered, 2):
        if not _can_route(left, right, config):
            continue
        route = _merge_route(left, right, pressure_summary, tutor_rows, config)
        if not _has_viable_tutor(route, tutor_rows):
            continue
        route_level_summary = _obj_get(route, "level_fit_summary", {}) or _level_fit_summary(route, tutor_rows, config)
        if not _route_has_allowed_level_fit(route, config, route_level_summary):
            continue
        route_candidates_by_group.setdefault((_obj_get(route, "date"), _obj_get(route, "modality")), []).append((route, route_level_summary))

    budgets = _route_budget(candidates, tutor_rows, config)
    for key, route_candidates in route_candidates_by_group.items():
        route_candidates.sort(key=lambda item: _route_retention_key(item[0], item[1]), reverse=True)
        for route, _summary in route_candidates[: budgets.get(key, 1)]:
            if _obj_get(route, "id") not in seen_ids:
                candidates.append(route)
                seen_ids.add(_obj_get(route, "id"))

    return candidates


__all__ = ["PackageCandidate", "generate_package_candidates"]
