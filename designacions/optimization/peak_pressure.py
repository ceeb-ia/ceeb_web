"""Pure peak-pressure helpers for phase route generation.

The helpers in this module are intentionally Django-free and do not mutate
state. Inputs may be optimization dataclasses, dictionaries, pandas rows, or
small objects exposing matching attributes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, time
from typing import Any, Iterable, Mapping


DEFAULT_CONFIG: dict[str, Any] = {
    "peak_time_bucket_minutes": 60,
    "peak_anchor_selection": "local",
    "peak_local_window_minutes": 60,
    "peak_anchor_top_n": 8,
    "peak_anchor_min_pressure": 0.0,
    "peak_anchor_fragment_limit": 12,
    "peak_pressure_classification_weight": 0.35,
    "peak_pressure_vehicle_shortage_weight": 0.75,
    "peak_pressure_existing_route_weight": 0.15,
    "peak_pressure_existing_match_weight": 0.04,
    "assume_available_when_missing": True,
    "assume_available_when_time_missing": True,
}


@dataclass(frozen=True)
class TimeBucket:
    key: str
    date: str
    modality: str
    bucket_start: str
    bucket_end: str
    fragment_ids: tuple[str, ...]
    match_ids: tuple[str, ...]
    demand: float
    weighted_demand: float
    classification_importance: float
    requires_vehicle_count: int
    start_dt: datetime | None = None
    end_dt: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PhaseBucketPressure:
    bucket: TimeBucket
    eligible_tutor_count: int
    available_tutor_count: int
    effective_tutor_supply: float
    vehicle_tutor_count: int
    busy_tutor_count: int
    existing_route_count: int
    existing_match_count: int
    demand_pressure: float
    vehicle_pressure: float
    load_pressure: float
    pressure_score: float

    @property
    def key(self) -> str:
        return self.bucket.key

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["key"] = self.key
        return payload


@dataclass(frozen=True)
class PeakAnchor:
    key: str
    date: str
    modality: str
    bucket_start: str
    bucket_end: str
    pressure_score: float
    demand: float
    effective_tutor_supply: float
    fragment_ids: tuple[str, ...]
    match_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    pressure: PhaseBucketPressure

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["pressure"] = self.pressure.to_dict()
        return payload


def compute_time_buckets(
    pending_fragments: Iterable[Any],
    config: Mapping[str, Any] | None = None,
) -> list[TimeBucket]:
    """Group pending fragments into time buckets by date and modality."""

    cfg = _merge_config(config)
    grouped: dict[str, dict[str, Any]] = {}

    for fragment in pending_fragments or []:
        normalized = _normalize_fragment(fragment, cfg)
        if not normalized["match_ids"]:
            continue
        key = _bucket_key(normalized["date"], normalized["modality"], normalized["bucket_start"])
        entry = grouped.setdefault(
            key,
            {
                "key": key,
                "date": normalized["date"],
                "modality": normalized["modality"],
                "bucket_start": normalized["bucket_start"],
                "bucket_end": normalized["bucket_end"],
                "fragment_ids": [],
                "match_ids": [],
                "demand": 0.0,
                "weighted_demand": 0.0,
                "classification_importance": 0.0,
                "requires_vehicle_count": 0,
                "starts": [],
                "ends": [],
            },
        )
        entry["fragment_ids"].append(normalized["id"])
        entry["match_ids"].extend(normalized["match_ids"])
        entry["demand"] += normalized["demand"]
        entry["weighted_demand"] += normalized["weighted_demand"]
        entry["classification_importance"] = max(
            entry["classification_importance"], normalized["classification_importance"]
        )
        entry["requires_vehicle_count"] += 1 if normalized["requires_vehicle"] else 0
        if normalized["start_dt"] is not None:
            entry["starts"].append(normalized["start_dt"])
        if normalized["end_dt"] is not None:
            entry["ends"].append(normalized["end_dt"])

    buckets = [
        TimeBucket(
            key=entry["key"],
            date=entry["date"],
            modality=entry["modality"],
            bucket_start=entry["bucket_start"],
            bucket_end=entry["bucket_end"],
            fragment_ids=tuple(_dedupe(entry["fragment_ids"])),
            match_ids=tuple(_dedupe(entry["match_ids"])),
            demand=float(entry["demand"]),
            weighted_demand=float(entry["weighted_demand"] or entry["demand"]),
            classification_importance=float(entry["classification_importance"]),
            requires_vehicle_count=int(entry["requires_vehicle_count"]),
            start_dt=min(entry["starts"]) if entry["starts"] else None,
            end_dt=max(entry["ends"]) if entry["ends"] else None,
        )
        for entry in grouped.values()
    ]
    return sorted(buckets, key=lambda bucket: (bucket.date, bucket.modality, bucket.bucket_start, bucket.key))


def estimate_phase_bucket_pressure(
    pending_fragments: Iterable[Any],
    eligible_tutors: Iterable[Any],
    state: Any = None,
    config: Mapping[str, Any] | None = None,
) -> list[PhaseBucketPressure]:
    """Estimate route-generation pressure for each pending phase bucket."""

    cfg = _merge_config(config)
    assigned_match_ids = set(_normalize_ids(_value(state, "assigned_match_ids", default=[])))
    fragments = [
        fragment
        for fragment in pending_fragments or []
        if not (set(_fragment_match_ids(fragment)) & assigned_match_ids)
    ]
    buckets = compute_time_buckets(fragments, cfg)
    tutors = [_normalize_tutor(tutor) for tutor in eligible_tutors or []]

    pressures: list[PhaseBucketPressure] = []
    for bucket in buckets:
        matching = [tutor for tutor in tutors if _modality_matches(tutor["modality"], bucket.modality)]
        available = [
            tutor
            for tutor in matching
            if _availability_covers_bucket(tutor["availability_by_date"], bucket, cfg)
        ]
        route_load = _bucket_route_load(state, bucket)
        busy_ids = route_load["busy_tutor_ids"]
        available_not_busy = [tutor for tutor in available if tutor["id"] not in busy_ids]
        vehicle_count = sum(1 for tutor in available_not_busy if tutor["has_vehicle"])

        load_units = (
            route_load["route_count"] * float(cfg["peak_pressure_existing_route_weight"])
            + route_load["match_count"] * float(cfg["peak_pressure_existing_match_weight"])
        )
        effective_supply = max(float(len(available_not_busy)) - load_units, 0.0)
        demand_pressure = _pressure(bucket.weighted_demand, effective_supply)
        vehicle_pressure = _pressure(bucket.requires_vehicle_count, vehicle_count)
        if bucket.requires_vehicle_count <= 0:
            vehicle_pressure = 0.0
        load_pressure = _pressure(float(route_load["match_count"]), max(len(matching), 1))
        score = (
            demand_pressure
            + vehicle_pressure * float(cfg["peak_pressure_vehicle_shortage_weight"])
            + load_pressure
            + bucket.classification_importance * float(cfg["peak_pressure_classification_weight"])
        )
        pressures.append(
            PhaseBucketPressure(
                bucket=bucket,
                eligible_tutor_count=len(matching),
                available_tutor_count=len(available),
                effective_tutor_supply=round(effective_supply, 4),
                vehicle_tutor_count=vehicle_count,
                busy_tutor_count=len(busy_ids),
                existing_route_count=int(route_load["route_count"]),
                existing_match_count=int(route_load["match_count"]),
                demand_pressure=round(demand_pressure, 4),
                vehicle_pressure=round(vehicle_pressure, 4),
                load_pressure=round(load_pressure, 4),
                pressure_score=round(score, 4),
            )
        )

    return sorted(pressures, key=_pressure_rank)


def select_top_peak_anchors(
    pressures: Iterable[PhaseBucketPressure],
    top_n: int | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[PeakAnchor]:
    """Select highest-pressure buckets as route-generation anchors."""

    cfg = _merge_config(config)
    limit = int(top_n if top_n is not None else cfg["peak_anchor_top_n"])
    min_pressure = float(cfg["peak_anchor_min_pressure"])
    fragment_limit = int(cfg["peak_anchor_fragment_limit"])

    anchors: list[PeakAnchor] = []
    for pressure in sorted(list(pressures or []), key=_pressure_rank):
        if limit > 0 and len(anchors) >= limit:
            break
        if pressure.pressure_score < min_pressure:
            continue
        bucket = pressure.bucket
        reasons = _anchor_reason_codes(pressure)
        anchors.append(
            PeakAnchor(
                key=bucket.key,
                date=bucket.date,
                modality=bucket.modality,
                bucket_start=bucket.bucket_start,
                bucket_end=bucket.bucket_end,
                pressure_score=pressure.pressure_score,
                demand=bucket.demand,
                effective_tutor_supply=pressure.effective_tutor_supply,
                fragment_ids=tuple(bucket.fragment_ids[:fragment_limit]),
                match_ids=bucket.match_ids,
                reason_codes=tuple(reasons),
                pressure=pressure,
            )
        )
    return anchors


def build_peak_anchors(
    pending_fragments: Iterable[Any],
    eligible_tutors: Iterable[Any],
    state: Any = None,
    config: Mapping[str, Any] | None = None,
    top_n: int | None = None,
) -> list[PeakAnchor]:
    """Convenience wrapper for pressure estimation plus anchor selection."""

    cfg = _merge_config(config)
    if str(cfg.get("peak_anchor_selection", "local")).strip().lower() not in {"bucket", "buckets"}:
        pressures = estimate_phase_local_pressure(pending_fragments, eligible_tutors, state, cfg)
        return select_top_peak_anchors(pressures, top_n=top_n, config=cfg)
    pressures = estimate_phase_bucket_pressure(pending_fragments, eligible_tutors, state, config)
    return select_top_peak_anchors(pressures, top_n=top_n, config=config)


def estimate_phase_local_pressure(
    pending_fragments: Iterable[Any],
    eligible_tutors: Iterable[Any],
    state: Any = None,
    config: Mapping[str, Any] | None = None,
) -> list[PhaseBucketPressure]:
    """Estimate pressure around exact fragment times using a sliding local window.

    The return type intentionally reuses PhaseBucketPressure/TimeBucket so the
    downstream route generation and diagnostics contracts stay stable. The
    bucket key is the exact local anchor time, not a rounded fixed-width bucket.
    """

    cfg = _merge_config(config)
    assigned_match_ids = set(_normalize_ids(_value(state, "assigned_match_ids", default=[])))
    fragments = [
        _normalize_fragment(fragment, cfg)
        for fragment in pending_fragments or []
        if not (set(_fragment_match_ids(fragment)) & assigned_match_ids)
    ]
    fragments = [fragment for fragment in fragments if fragment["match_ids"]]
    tutors = [_normalize_tutor(tutor) for tutor in eligible_tutors or []]
    radius = max(int(cfg.get("peak_local_window_radius_minutes") or int(cfg.get("peak_local_window_minutes", 60) or 60) / 2), 1)

    centers: dict[tuple[str, str, datetime], list[dict[str, Any]]] = {}
    for fragment in fragments:
        start_dt = fragment["start_dt"]
        if start_dt is None:
            continue
        centers.setdefault((fragment["date"], fragment["modality"], start_dt), []).append(fragment)

    pressures: list[PhaseBucketPressure] = []
    for (date_key, modality, center_dt), center_fragments in centers.items():
        local_fragments = [
            fragment
            for fragment in fragments
            if fragment["date"] == date_key
            and fragment["modality"] == modality
            and _minutes_apart(center_dt, fragment["start_dt"]) <= radius
        ]
        if not local_fragments:
            continue
        bucket = _local_bucket(date_key, modality, center_dt, local_fragments)
        pressures.append(_pressure_for_bucket(bucket, tutors, state, cfg))

    return sorted(pressures, key=_pressure_rank)


def _local_bucket(
    date_key: str,
    modality: str,
    center_dt: datetime,
    fragments: list[dict[str, Any]],
) -> TimeBucket:
    starts = [fragment["start_dt"] for fragment in fragments if fragment["start_dt"] is not None]
    ends = [fragment["end_dt"] for fragment in fragments if fragment["end_dt"] is not None]
    center_minutes = center_dt.hour * 60 + center_dt.minute
    radius = max(
        int(max(abs((center_dt - start).total_seconds()) / 60.0 for start in starts) if starts else 0),
        1,
    )
    window_start = _hhmm(center_minutes - radius)
    window_end = _hhmm(center_minutes + radius + 1)
    ordered = sorted(
        fragments,
        key=lambda fragment: (
            -float(fragment["classification_importance"] or 0.0),
            -float(fragment["weighted_demand"] or fragment["demand"] or 0.0),
            abs((center_dt - fragment["start_dt"]).total_seconds()) if fragment["start_dt"] else 0.0,
            fragment["id"],
        ),
    )
    return TimeBucket(
        key=_bucket_key(date_key, modality, _hhmm(center_minutes)),
        date=date_key,
        modality=modality,
        bucket_start=window_start,
        bucket_end=window_end,
        fragment_ids=tuple(_dedupe(fragment["id"] for fragment in ordered)),
        match_ids=tuple(_dedupe(match_id for fragment in ordered for match_id in fragment["match_ids"])),
        demand=float(sum(float(fragment["demand"] or 0.0) for fragment in fragments)),
        weighted_demand=float(sum(float(fragment["weighted_demand"] or fragment["demand"] or 0.0) for fragment in fragments)),
        classification_importance=max(float(fragment["classification_importance"] or 0.0) for fragment in fragments),
        requires_vehicle_count=sum(1 for fragment in fragments if fragment["requires_vehicle"]),
        start_dt=min(starts) if starts else center_dt,
        end_dt=max(ends) if ends else center_dt,
    )


def _pressure_for_bucket(
    bucket: TimeBucket,
    tutors: list[dict[str, Any]],
    state: Any,
    cfg: Mapping[str, Any],
) -> PhaseBucketPressure:
    matching = [tutor for tutor in tutors if _modality_matches(tutor["modality"], bucket.modality)]
    available = [
        tutor
        for tutor in matching
        if _availability_covers_bucket(tutor["availability_by_date"], bucket, cfg)
    ]
    route_load = _bucket_route_load(state, bucket)
    busy_ids = route_load["busy_tutor_ids"]
    available_not_busy = [tutor for tutor in available if tutor["id"] not in busy_ids]
    vehicle_count = sum(1 for tutor in available_not_busy if tutor["has_vehicle"])

    load_units = (
        route_load["route_count"] * float(cfg["peak_pressure_existing_route_weight"])
        + route_load["match_count"] * float(cfg["peak_pressure_existing_match_weight"])
    )
    effective_supply = max(float(len(available_not_busy)) - load_units, 0.0)
    demand_pressure = _pressure(bucket.weighted_demand, effective_supply)
    vehicle_pressure = _pressure(bucket.requires_vehicle_count, vehicle_count)
    if bucket.requires_vehicle_count <= 0:
        vehicle_pressure = 0.0
    load_pressure = _pressure(float(route_load["match_count"]), max(len(matching), 1))
    score = (
        demand_pressure
        + vehicle_pressure * float(cfg["peak_pressure_vehicle_shortage_weight"])
        + load_pressure
        + bucket.classification_importance * float(cfg["peak_pressure_classification_weight"])
    )
    return PhaseBucketPressure(
        bucket=bucket,
        eligible_tutor_count=len(matching),
        available_tutor_count=len(available),
        effective_tutor_supply=round(effective_supply, 4),
        vehicle_tutor_count=vehicle_count,
        busy_tutor_count=len(busy_ids),
        existing_route_count=int(route_load["route_count"]),
        existing_match_count=int(route_load["match_count"]),
        demand_pressure=round(demand_pressure, 4),
        vehicle_pressure=round(vehicle_pressure, 4),
        load_pressure=round(load_pressure, 4),
        pressure_score=round(score, 4),
    )


def bucket_key_for_fragment(fragment: Any, config: Mapping[str, Any] | None = None) -> str:
    """Return the date/modality/time key used by peak-pressure helpers."""

    normalized = _normalize_fragment(fragment, _merge_config(config))
    return _bucket_key(normalized["date"], normalized["modality"], normalized["bucket_start"])


def _merge_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if config:
        cfg.update(dict(config))
    cfg["peak_time_bucket_minutes"] = max(int(cfg.get("peak_time_bucket_minutes", 60) or 60), 1)
    return cfg


def _normalize_fragment(fragment: Any, cfg: Mapping[str, Any]) -> dict[str, Any]:
    start_dt = _datetime_value(_value(fragment, "start_dt", "start_datetime", "start", "inici", "__match_datetime"))
    end_dt = _datetime_value(_value(fragment, "end_dt", "end_datetime", "end", "fi", "__match_datetime")) or start_dt
    match_ids = _fragment_match_ids(fragment)
    demand = _float_value(fragment, "match_count", default=float(len(match_ids) or 1))
    weighted = _float_value(fragment, "weighted_coverage_value", default=demand)
    cluster_ids = _list_value(fragment, "cluster_ids", "clusters", "cluster_id", "cluster")
    cluster_statuses = [_clean_key(value) for value in _list_value(fragment, "cluster_statuses", "cluster_status")]
    return {
        "id": _clean_text(_value(fragment, "id", "fragment_id", default="-".join(match_ids) or "fragment")),
        "date": _date_key(_value(fragment, "date", "Data", "data", default=start_dt)),
        "modality": _clean_key(_value(fragment, "modality", "Modalitat", "modalitat", default="")),
        "bucket_start": _bucket_start(start_dt, cfg),
        "bucket_end": _bucket_end(start_dt, cfg),
        "start_dt": start_dt,
        "end_dt": end_dt,
        "match_ids": match_ids,
        "demand": demand,
        "weighted_demand": weighted or demand,
        "classification_importance": _float_value(fragment, "classification_importance", default=0.0),
        "requires_vehicle": _truthy(_value(fragment, "requires_vehicle", "vehicle_required", default=False))
        or _clusters_need_vehicle(cluster_ids)
        or bool(set(cluster_statuses) & {"outlier", "missing_geocode", "pending", "not_found"}),
    }


def _normalize_tutor(tutor: Any) -> dict[str, Any]:
    transport = _value(tutor, "transport", "Mitja de Transport", "Mitja de transport", default="")
    explicit_vehicle = _value(tutor, "has_vehicle", "vehicle", "cotxe", default=None)
    return {
        "id": _clean_text(_value(tutor, "id", "tutor_id", "persona_id", "code", "codi", default="")),
        "modality": _clean_key(_value(tutor, "modality", "Modalitat", "modalitat", default="")),
        "has_vehicle": _truthy(explicit_vehicle) if explicit_vehicle is not None else _transport_has_vehicle(transport),
        "availability_by_date": _value(tutor, "availability_by_date", "availability", default=None),
    }


def _bucket_route_load(state: Any, bucket: TimeBucket) -> dict[str, Any]:
    assignments = _value(state, "assignments_by_tutor_day", default={}) or {}
    if not isinstance(assignments, Mapping):
        return {"busy_tutor_ids": set(), "route_count": 0, "match_count": 0}

    busy_tutor_ids: set[str] = set()
    route_count = 0
    match_count = 0
    for key, route_state in assignments.items():
        tutor_id, date_key = _route_state_identity(key, route_state)
        if date_key != bucket.date:
            continue
        route_count += _int_value(route_state, "route_count", default=1)
        match_ids = _normalize_ids(_value(route_state, "assigned_match_ids", "match_ids", default=[]))
        match_count += len(match_ids) or _int_value(route_state, "match_count", default=0)
        if _route_overlaps_bucket(route_state, bucket):
            busy_tutor_ids.add(tutor_id)
    return {"busy_tutor_ids": busy_tutor_ids, "route_count": route_count, "match_count": match_count}


def _route_state_identity(key: Any, route_state: Any) -> tuple[str, str]:
    if isinstance(key, tuple) and len(key) >= 2:
        return _clean_text(key[0]), _date_key(key[1])
    tutor_id = _clean_text(_value(route_state, "tutor_id", default=""))
    date_key = _date_key(_value(route_state, "date", default=""))
    if (not tutor_id or not date_key) and isinstance(key, str):
        separator = "|" if "|" in key else ":"
        parts = key.split(separator, 1)
        if len(parts) == 2:
            tutor_id = tutor_id or _clean_text(parts[0])
            date_key = date_key or _date_key(parts[1])
    return tutor_id, date_key


def _route_overlaps_bucket(route_state: Any, bucket: TimeBucket) -> bool:
    route_start = _datetime_value(_value(route_state, "route_start_dt", "start_dt", "start", default=None))
    route_end = _datetime_value(_value(route_state, "route_end_dt", "end_dt", "end", default=None)) or route_start
    if route_start is None or route_end is None or bucket.start_dt is None:
        return False
    bucket_start = _combine_date_time(bucket.date, bucket.bucket_start)
    bucket_end = _combine_date_time(bucket.date, bucket.bucket_end)
    if bucket_start is None or bucket_end is None:
        return False
    return route_start < bucket_end and bucket_start < route_end


def _availability_covers_bucket(availability_by_date: Any, bucket: TimeBucket, cfg: Mapping[str, Any]) -> bool:
    if not availability_by_date:
        return bool(cfg.get("assume_available_when_missing", True))
    if bucket.start_dt is None:
        return bool(cfg.get("assume_available_when_time_missing", True))
    if not isinstance(availability_by_date, Mapping):
        return bool(availability_by_date)

    day_value = _availability_for_date(availability_by_date, bucket.date)
    if day_value is None:
        return bool(cfg.get("assume_available_when_missing", True))
    if isinstance(day_value, bool):
        return day_value
    if isinstance(day_value, Mapping):
        if "available" in day_value and not bool(day_value["available"]):
            return False
        windows = day_value.get("windows") or day_value.get("intervals") or day_value.get("slots")
        if windows is None and ("start" in day_value or "end" in day_value or "Hora Inici" in day_value):
            windows = [day_value]
        if windows is None:
            return any(bool(value) for value in day_value.values())
        return _any_window_overlaps(windows, bucket)
    if isinstance(day_value, (list, tuple, set)):
        return _any_window_overlaps(day_value, bucket)
    return bool(day_value)


def _availability_for_date(availability_by_date: Mapping[Any, Any], date_key: str) -> Any:
    for key, value in availability_by_date.items():
        if _date_key(key) == date_key:
            return value
    return None


def _any_window_overlaps(windows: Any, bucket: TimeBucket) -> bool:
    if isinstance(windows, str):
        return windows == bucket.bucket_start
    return any(_window_overlaps(window, bucket) for window in windows or [])


def _window_overlaps(window: Any, bucket: TimeBucket) -> bool:
    if isinstance(window, str):
        return window == bucket.bucket_start
    if isinstance(window, Mapping):
        start = _time_value(window.get("start") or window.get("from") or window.get("Hora Inici"))
        end = _time_value(window.get("end") or window.get("to") or window.get("Hora Fi"))
    elif isinstance(window, tuple) and len(window) >= 2:
        start = _time_value(window[0])
        end = _time_value(window[1])
    else:
        return bool(window)
    if start is None or end is None:
        return False
    bucket_start = _time_value(bucket.bucket_start)
    bucket_end = _time_value(bucket.bucket_end)
    if bucket_start is None or bucket_end is None:
        return False
    return start < bucket_end and bucket_start < end


def _anchor_reason_codes(pressure: PhaseBucketPressure) -> list[str]:
    reasons = ["high_bucket_pressure"]
    if pressure.vehicle_pressure >= 1.0:
        reasons.append("vehicle_shortage")
    if pressure.busy_tutor_count:
        reasons.append("overlaps_existing_routes")
    if pressure.bucket.classification_importance:
        reasons.append("classification_pressure")
    if pressure.available_tutor_count == 0:
        reasons.append("no_available_tutors")
    return reasons


def _pressure_rank(pressure: PhaseBucketPressure) -> tuple[Any, ...]:
    bucket = pressure.bucket
    return (
        -pressure.pressure_score,
        -pressure.demand_pressure,
        -bucket.weighted_demand,
        bucket.date,
        bucket.bucket_start,
        bucket.modality,
        bucket.key,
    )


def _fragment_match_ids(fragment: Any) -> list[str]:
    return _normalize_ids(_value(fragment, "match_ids", "new_match_ids", "partit_ids", "match_id", "partit_id", default=[]))


def _bucket_key(date_key: str, modality: str, bucket_start: str) -> str:
    return "|".join((date_key, modality or "unknown", bucket_start))


def _bucket_start(value: datetime | None, cfg: Mapping[str, Any]) -> str:
    if value is None:
        return "unknown"
    minutes = value.hour * 60 + value.minute
    bucket_size = int(cfg["peak_time_bucket_minutes"])
    return _hhmm((minutes // bucket_size) * bucket_size)


def _bucket_end(value: datetime | None, cfg: Mapping[str, Any]) -> str:
    if value is None:
        return "unknown"
    start_minutes = _minutes_from_hhmm(_bucket_start(value, cfg))
    return _hhmm(start_minutes + int(cfg["peak_time_bucket_minutes"]))


def _combine_date_time(date_key: str, hhmm: str) -> datetime | None:
    parsed_date = _date_value(date_key)
    parsed_time = _time_value(hhmm)
    if parsed_date is None or parsed_time is None:
        return None
    return datetime.combine(parsed_date, parsed_time)


def _date_key(value: Any) -> str:
    parsed = _datetime_value(value)
    if isinstance(parsed, datetime):
        return parsed.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return "unknown"
    text = str(value).strip()
    return text.split("T", 1)[0].split(" ", 1)[0] if text else "unknown"


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        try:
            parsed = value.to_pydatetime()
            return parsed if isinstance(parsed, datetime) else None
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _time_value(value: Any) -> time | None:
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    if isinstance(value, time):
        return value.replace(microsecond=0)
    if value is None:
        return None
    text = str(value).strip()
    if "T" in text:
        text = text.rsplit("T", 1)[1]
    if " " in text:
        text = text.rsplit(" ", 1)[1]
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            pass
    return None


def _minutes_from_hhmm(value: str) -> int:
    if value == "unknown":
        return 0
    parts = value.split(":")
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (IndexError, TypeError, ValueError):
        return 0


def _hhmm(minutes: int) -> str:
    minutes = minutes % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _value(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    for name in names:
        if isinstance(obj, Mapping) and name in obj:
            value = obj[name]
            return default if _is_missing(value) else value
        if is_dataclass(obj) and not isinstance(obj, type) and hasattr(obj, name):
            value = getattr(obj, name)
            return default if _is_missing(value) else value
        try:
            value = obj.get(name)
            if not _is_missing(value):
                return value
        except AttributeError:
            pass
        if hasattr(obj, name):
            value = getattr(obj, name)
            return default if _is_missing(value) else value
    return default


def _list_value(obj: Any, *names: str) -> list[Any]:
    value = _value(obj, *names, default=[])
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    if isinstance(value, Mapping):
        return list(value.values())
    try:
        return list(value)
    except TypeError:
        return [value]


def _normalize_ids(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        text = str(values).strip()
        if not text:
            return []
        chunks = [text]
        for separator in (",", ";", "|"):
            chunks = [part for chunk in chunks for part in chunk.split(separator)]
        return [_clean_text(chunk) for chunk in chunks if _clean_text(chunk)]
    try:
        return [_clean_text(value) for value in values if _clean_text(value)]
    except TypeError:
        text = _clean_text(values)
        return [text] if text else []


def _clean_text(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip()


def _clean_key(value: Any) -> str:
    return _clean_text(value).lower() or "unknown"


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(value != value)
    except Exception:
        return False


def _dedupe(values: Iterable[Any]) -> list[Any]:
    output = []
    seen = set()
    for value in values:
        key = repr(value)
        if key in seen:
            continue
        output.append(value)
        seen.add(key)
    return output


def _float_value(obj: Any, *names: str, default: float = 0.0) -> float:
    value = _value(obj, *names, default=default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_value(obj: Any, *names: str, default: int = 0) -> int:
    value = _value(obj, *names, default=default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "si", "vehicle", "cotxe", "coche"}
    return bool(value)


def _transport_has_vehicle(value: Any) -> bool:
    text = _clean_text(value).lower()
    return any(token in text for token in ("cotxe", "coche", "moto", "vehicle", "furgoneta"))


def _modality_matches(tutor_modality: str, bucket_modality: str) -> bool:
    return tutor_modality in {bucket_modality, "any", "unknown", ""} or bucket_modality in {"unknown", ""}


def _clusters_need_vehicle(cluster_ids: Iterable[Any]) -> bool:
    cleaned = {_clean_key(cluster) for cluster in cluster_ids if _clean_key(cluster) != "unknown"}
    return len(cleaned) > 1


def _pressure(demand: float, supply: int | float) -> float:
    return float(demand) / max(float(supply), 1.0)


def _minutes_apart(left: datetime, right: datetime | None) -> float:
    if right is None:
        return float("inf")
    return abs((left - right).total_seconds()) / 60.0


__all__ = [
    "PeakAnchor",
    "PhaseBucketPressure",
    "TimeBucket",
    "bucket_key_for_fragment",
    "build_peak_anchors",
    "compute_time_buckets",
    "estimate_phase_bucket_pressure",
    "estimate_phase_local_pressure",
    "select_top_peak_anchors",
]
