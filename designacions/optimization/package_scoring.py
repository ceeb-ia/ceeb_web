from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable

from designacions.services.assignment_feasibility import has_vehicle, normalize_text_key

from .levels import (
    LEVEL_FIT_EXCEPTIONAL,
    LEVEL_FIT_FORBIDDEN,
    LEVEL_FIT_UNSCORABLE,
    level_distance_cost,
    level_fit,
    normalized_tutor_position,
)

try:
    from .contracts import AssignmentCandidate as ContractAssignmentCandidate
except ImportError:  # pragma: no cover - contracts are optional during rollout.
    ContractAssignmentCandidate = None


@dataclass(frozen=True)
class LocalAssignmentCandidate:
    tutor_id: Any
    package_id: Any
    match_ids: tuple[Any, ...]
    is_viable: bool
    blocking_reasons: tuple[str, ...] = field(default_factory=tuple)
    warning_codes: tuple[str, ...] = field(default_factory=tuple)
    cost: float = 0.0
    score_breakdown: dict[str, Any] = field(default_factory=dict)


AssignmentCandidate = ContractAssignmentCandidate or LocalAssignmentCandidate

TUTOR_LEVEL_ORDER = ("NIVELLA1", "NIVELLB1", "NIVELLC1", "NIVELLD1", "D")
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


def build_assignment_candidates(packages, tutors, pressure_summary=None, config=None):
    """Build explainable tutor-package assignment candidates.

    Inputs may be dataclasses, plain objects, or dictionaries. This keeps the
    scoring layer usable before the rest of the optimization contracts are
    fully wired into the Django flow.
    """
    pressure_summary = pressure_summary or {}
    config = config or {}

    candidates = []
    for package in packages or []:
        for tutor in tutors or []:
            candidates.append(_score_candidate(package, tutor, pressure_summary, config))
    return candidates


def _score_candidate(package, tutor, pressure_summary, config):
    package_id = _value(package, "id", "package_id")
    tutor_id = _value(tutor, "id", "tutor_id", "code")
    match_ids = tuple(_list_value(package, "match_ids"))
    blocking_reasons = []
    warning_codes = list(_list_value(package, "warning_codes"))

    package_modality = _text(_value(package, "modality"))
    tutor_modality = _text(_value(tutor, "modality"))
    if package_modality and tutor_modality and package_modality != tutor_modality:
        blocking_reasons.append("modality_mismatch")

    if not _availability_covers_package(tutor, package, config):
        blocking_reasons.append("outside_availability_window")
    elif not _availability_respects_buffer_package(tutor, package, config):
        warning_codes.append("availability_end_buffer_warning")

    tutor_has_vehicle = _tutor_has_vehicle(tutor)
    requires_vehicle = bool(_value(package, "requires_vehicle", default=False))
    vehicle_preferred = bool(_value(package, "vehicle_preferred", default=False))
    if requires_vehicle and not tutor_has_vehicle:
        blocking_reasons.append("vehicle_required")
    elif vehicle_preferred and not tutor_has_vehicle:
        warning_codes.append("vehicle_preferred_without_vehicle")

    level_cost, level_label, level_block = _level_cost(tutor, package, config)
    if level_block:
        blocking_reasons.append("level_forbidden")

    match_count = len(match_ids)
    classification_cost = _float_value(package, "classification_pressure", default=0.0) * _cfg(
        config, "classification_weight", 1.0
    )
    base_difficulty_cost = _float_value(package, "base_difficulty_score", default=0.0) * _cfg(
        config, "base_difficulty_weight", 1.0
    )
    mobility_cost = _mobility_cost(package, warning_codes, requires_vehicle)
    vehicle_cost = _vehicle_cost(package, tutor_has_vehicle, pressure_summary, config)
    classification_fit_cost = _classification_fit_cost(package, tutor, config)
    pressure_relief_reward = _pressure_relief_reward(package, pressure_summary, config)
    warning_cost = len(set(warning_codes)) * _cfg(config, "warning_cost", 15.0)
    coverage_reward = match_count * _cfg(config, "coverage_reward", 1000.0)

    raw_cost = (
        level_cost
        + classification_cost
        + base_difficulty_cost
        + mobility_cost
        + vehicle_cost
        + classification_fit_cost
        + warning_cost
        - pressure_relief_reward
    )
    cost = max(0.0, raw_cost)

    blocking_reasons = _dedupe(blocking_reasons)
    warning_codes = _dedupe(warning_codes)
    is_viable = not blocking_reasons
    if not is_viable:
        cost += _cfg(config, "inviable_candidate_penalty", 1000000.0)

    return AssignmentCandidate(
        tutor_id=tutor_id,
        package_id=package_id,
        match_ids=match_ids,
        is_viable=is_viable,
        blocking_reasons=tuple(blocking_reasons),
        warning_codes=tuple(warning_codes),
        cost=float(cost),
        score_breakdown={
            "coverage_reward": -coverage_reward,
            "match_count": match_count,
            "level_cost": float(level_cost),
            "level_fit": level_label,
            "level_exceptional": level_label == LEVEL_FIT_EXCEPTIONAL,
            "classification_cost": float(classification_cost),
            "base_difficulty_cost": float(base_difficulty_cost),
            "mobility_cost": float(mobility_cost),
            "vehicle_cost": float(vehicle_cost),
            "classification_fit_cost": float(classification_fit_cost),
            "classification_importance": float(_value(package, "classification_importance", default=0.0) or 0.0),
            "weighted_coverage_value": float(
                _value(package, "weighted_coverage_value", default=len(match_ids)) or len(match_ids)
            ),
            "pressure_relief_reward": float(-pressure_relief_reward),
            "warning_cost": float(warning_cost),
            "raw_cost_before_viability": float(raw_cost),
            "requires_vehicle": requires_vehicle,
            "vehicle_preferred": vehicle_preferred,
            "tutor_has_vehicle": tutor_has_vehicle,
        },
    )


def _availability_covers_package(tutor, package, config):
    return _availability_package_window_check(tutor, package, config, use_buffer=False)


def _availability_respects_buffer_package(tutor, package, config):
    return _availability_package_window_check(tutor, package, config, use_buffer=True)


def _availability_package_window_check(tutor, package, config, *, use_buffer: bool):
    availability_by_date = _value(tutor, "availability_by_date", default=None)
    if not availability_by_date:
        return bool(_cfg(config, "assume_available_when_missing", False))

    package_date = _date_value(_value(package, "date"))
    start_dt = _datetime_value(_value(package, "start_dt", "start_datetime", "start"))
    end_dt = _datetime_value(_value(package, "end_dt", "end_datetime", "end")) or start_dt
    if package_date is None or start_dt is None or end_dt is None:
        return False

    windows = _availability_windows(availability_by_date, package_date)
    if not windows:
        return False

    return any(
        _window_covers(start_dt, end_dt, window_start, window_end, config, use_buffer=use_buffer)
        for window_start, window_end in windows
    )


def _window_covers(start_dt: datetime, end_dt: datetime, start: time, end: time, config, *, use_buffer: bool = False) -> bool:
    buffer_min = int(_cfg(config, "availability_end_buffer_min", 60) or 0) if use_buffer else 0
    window_start = datetime.combine(start_dt.date(), start)
    window_end = datetime.combine(start_dt.date(), end) - timedelta(minutes=buffer_min)
    return window_start <= start_dt and end_dt <= window_end


def _availability_windows(availability_by_date, package_date):
    raw = None
    if isinstance(availability_by_date, dict):
        raw = availability_by_date.get(package_date) or availability_by_date.get(str(package_date))
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    if isinstance(raw, tuple) and len(raw) == 2:
        raw = [raw]

    windows = []
    for item in raw if isinstance(raw, list) else [raw]:
        if isinstance(item, dict):
            start = _time_value(item.get("start") or item.get("Hora Inici") or item.get("hora_inici"))
            end = _time_value(item.get("end") or item.get("Hora Fi") or item.get("hora_fi"))
        elif isinstance(item, tuple) and len(item) == 2:
            start = _time_value(item[0])
            end = _time_value(item[1])
        else:
            continue
        if start is not None and end is not None:
            windows.append((start, end))
    return windows


def _level_cost(tutor, package, config):
    tutor_level = _value(tutor, "level", "nivell")
    demand_level = _value(package, "level_demand", "level", "categoria")
    fit = level_fit(
        tutor_level,
        demand_level,
        {
            **dict(config or {}),
            "classification_importance": _float_value(package, "classification_importance", default=0.0),
        },
    )
    if fit == LEVEL_FIT_UNSCORABLE:
        if bool(_cfg(config, "block_unscorable_level", False)):
            return _cfg(config, "unscorable_level_penalty", 1000000.0), fit, True
        return _cfg(config, "unscorable_level_cost", 0.0), fit, False

    cost = level_distance_cost(tutor_level, demand_level, _cfg(config, "level_distance_weight", 1000.0))
    if fit == LEVEL_FIT_EXCEPTIONAL:
        cost += _cfg(config, "exceptional_level_penalty", 3000.0)
    if fit == LEVEL_FIT_FORBIDDEN:
        return cost + _cfg(config, "forbidden_level_penalty", 1000000.0), fit, True
    return cost, fit, False


def _ordered_position(value, order):
    text = normalize_text_key(value)
    if not text:
        return None
    normalized_order = [normalize_text_key(item) for item in order]
    if text in normalized_order:
        index = normalized_order.index(text)
        return index / max(len(normalized_order) - 1, 1)
    for index, token in sorted(enumerate(normalized_order), key=lambda item: len(item[1]), reverse=True):
        if token and token in text:
            return index / max(len(normalized_order) - 1, 1)
    return None


def _mobility_cost(package, warning_codes, requires_vehicle):
    cost = 0.0
    if requires_vehicle:
        cost += 40.0
    for code in set(warning_codes):
        if code == "cross_cluster_with_vehicle_warning":
            cost += 25.0
        elif code == "same_cluster_pitch_change_warning":
            cost += 10.0
        elif "outlier" in code or "missing_cluster" in code:
            cost += 35.0
        else:
            cost += 5.0
    return cost


def _classification_fit_cost(package, tutor, config):
    importance = _float_value(package, "classification_importance", default=0.0)
    if importance <= 0:
        return 0.0
    tutor_position = normalized_tutor_position(_value(tutor, "level", "nivell"))
    if tutor_position is None:
        return importance * _cfg(config, "classification_missing_level_cost", 150.0)
    return importance * tutor_position * _cfg(config, "classification_fit_weight", 500.0)


def _vehicle_cost(package, tutor_has_vehicle, pressure_summary, config):
    if not tutor_has_vehicle:
        return 0.0
    if bool(_value(package, "requires_vehicle", default=False)):
        return 0.0
    if not _vehicle_pressure_active(pressure_summary):
        return 0.0
    if bool(_value(package, "vehicle_preferred", default=False)):
        return _cfg(config, "vehicle_preferred_vehicle_cost", 20.0)
    return _cfg(config, "vehicle_easy_segment_penalty", 250.0)


def _pressure_relief_reward(package, pressure_summary, config):
    explicit = _float_value(package, "pressure_relief_score", default=None)
    if explicit is not None:
        return explicit * _cfg(config, "pressure_relief_weight", 50.0)
    date_key = str(_value(package, "date", default=""))
    by_date = pressure_summary.get("pressure_by_date", {}) if isinstance(pressure_summary, dict) else {}
    try:
        return float(by_date.get(date_key, 0.0)) * len(_list_value(package, "match_ids")) * _cfg(
            config, "pressure_relief_weight", 50.0
        )
    except (TypeError, ValueError):
        return 0.0


def _vehicle_pressure_active(pressure_summary):
    if not isinstance(pressure_summary, dict):
        return False
    if pressure_summary.get("vehicle_pressure"):
        return True
    try:
        return float(pressure_summary.get("vehicle_pressure_score", 0.0)) > 0
    except (TypeError, ValueError):
        return False


def _tutor_has_vehicle(tutor):
    explicit = _value(tutor, "has_vehicle", default=None)
    if explicit is not None:
        return bool(explicit)
    transport = _value(tutor, "transport", "Mitja de Transport", default="")
    if not transport and isinstance(tutor, dict):
        for key, value in tutor.items():
            if normalize_text_key(key) in {"mitja de transport", "transport"}:
                transport = value
                break
    return has_vehicle(transport)


def _value(obj, *names, default=None):
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _list_value(obj, *names):
    value = _value(obj, *names, default=())
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def _float_value(obj, *names, default=0.0):
    value = _value(obj, *names, default=default)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _cfg(config, name, default):
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)


def _text(value):
    return normalize_text_key(value)


def _date_value(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None


def _datetime_value(value):
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    raw = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _time_value(value):
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    if isinstance(value, time):
        return value.replace(microsecond=0)
    if value is None:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(str(value), fmt).time()
        except ValueError:
            continue
    return None


def _dedupe(values):
    result = []
    seen = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
