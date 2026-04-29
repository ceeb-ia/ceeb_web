from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from itertools import combinations
from typing import Any, Iterable

from designacions.services.assignment_feasibility import has_vehicle, normalize_text_key

from .levels import (
    LEVEL_FIT_EXCEPTIONAL,
    LEVEL_FIT_FORBIDDEN,
    LEVEL_FIT_UNSCORABLE,
    hardest_match_level,
    level_distance_cost,
    level_fit,
)
from .phases import PhaseSpec, phase_allows_fragment, phase_allows_tutor
from .route_points import (
    required_gap as atomic_required_gap,
    route_points_from_segments,
    transition_requires_vehicle as atomic_transition_requires_vehicle,
    validate_atomic_gaps,
)


@dataclass(frozen=True)
class RouteCandidate:
    id: str
    phase_name: str
    tutor_id: str
    new_match_ids: list[str]
    full_route_match_ids: list[str]
    inserted_into_existing_route: bool
    date: str
    start_dt: datetime | None
    end_dt: datetime | None
    level_demand: Any
    level_fit: str
    requires_vehicle: bool
    cluster_ids: list[Any] = field(default_factory=list)
    cluster_statuses: list[Any] = field(default_factory=list)
    venues: list[str] = field(default_factory=list)
    warning_codes: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
    cost: float = 0.0
    score_breakdown: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _RouteDraft:
    id: str
    fragments: tuple[Any, ...]
    match_ids: tuple[str, ...]
    date: str
    modality: str
    start_dt: datetime | None
    end_dt: datetime | None
    level_demand: Any
    cluster_ids: tuple[Any, ...]
    cluster_statuses: tuple[Any, ...]
    venues: tuple[str, ...]
    classification_importance: float
    weighted_coverage_value: float


def generate_phase_route_candidates(
    fragments: Iterable[Any],
    tutors: Iterable[Any],
    state: Any,
    phase: PhaseSpec,
    config: dict[str, Any] | None = None,
) -> list[RouteCandidate]:
    config = dict(config or {})
    assigned_match_ids = {str(match_id) for match_id in _list_value(state, "assigned_match_ids")}
    pending_fragments = [
        fragment
        for fragment in fragments or []
        if phase_allows_fragment(fragment, phase)
        and not (set(_str_list(_value(fragment, "match_ids"))) & assigned_match_ids)
    ]
    single_drafts = [_draft_from_fragments((fragment,)) for fragment in pending_fragments]
    drafts = list(single_drafts)
    if int(phase.max_route_size or 1) >= 2:
        for left, right in combinations(single_drafts, 2):
            merged = _merge_drafts(left, right, config)
            if merged is not None:
                drafts.append(merged)

    candidates: list[RouteCandidate] = []
    for tutor in tutors or []:
        if not phase_allows_tutor(tutor, phase):
            continue
        tutor_id = str(_value(tutor, "id", "tutor_id", "code", default=""))
        if not tutor_id:
            continue
        for draft in drafts:
            existing_route = _existing_route_state(state, tutor_id, draft.date)
            scored = _score_route_candidate(tutor, draft, existing_route, phase, config)
            if scored is not None:
                candidates.append(scored)

    return _prune_candidates(candidates, phase, config)


def _score_route_candidate(
    tutor: Any,
    draft: _RouteDraft,
    existing_route: Any,
    phase: PhaseSpec,
    config: dict[str, Any],
) -> RouteCandidate | None:
    tutor_id = str(_value(tutor, "id", "tutor_id", "code", default=""))
    blocking: list[str] = []
    warnings: list[str] = []

    tutor_modality = normalize_text_key(_value(tutor, "modality", "Modalitat", default=""))
    if tutor_modality and normalize_text_key(draft.modality) and tutor_modality != normalize_text_key(draft.modality):
        blocking.append("modality_mismatch")

    full_segments = _existing_segments(existing_route) + [draft]
    full_segments = sorted(full_segments, key=lambda item: _segment_start(item) or datetime.min)
    full_match_ids = _dedupe(_existing_match_ids(existing_route) + list(draft.match_ids))
    inserted = bool(_value(existing_route, "assigned_match_ids") or _existing_segments(existing_route))

    if not _availability_covers(tutor, draft.date, _route_start(full_segments), _route_end(full_segments), config):
        blocking.append("outside_availability_window")

    needs_vehicle = _route_requires_vehicle(full_segments)
    tutor_has_vehicle = _tutor_has_vehicle(tutor)
    if needs_vehicle and not tutor_has_vehicle:
        blocking.append("vehicle_required")
    elif needs_vehicle:
        warnings.append("cross_cluster_with_vehicle_warning")

    gap_warnings, gap_block = _validate_gaps(full_segments, config)
    warnings.extend(gap_warnings)
    if gap_block:
        blocking.append("gap_too_short")

    fit = level_fit(
        _value(tutor, "level", "nivell", "Nivell"),
        draft.level_demand,
        {**config, "classification_importance": draft.classification_importance},
    )
    if fit == LEVEL_FIT_FORBIDDEN:
        blocking.append("level_forbidden")
    if fit == LEVEL_FIT_EXCEPTIONAL and not phase.allow_exceptional:
        blocking.append("level_exceptional_not_allowed")
    if fit == LEVEL_FIT_UNSCORABLE and bool(config.get("block_unscorable_level", False)):
        blocking.append("level_unscorable")

    warnings.extend(_cluster_warnings(draft.cluster_ids, draft.cluster_statuses))
    blocking = _dedupe(blocking)
    if blocking:
        return None

    assigned_count = len(_str_list(_value(existing_route, "assigned_match_ids")))
    existing_route_count = int(_value(existing_route, "route_count", default=1 if inserted else 0) or 0)
    load_penalty = (
        assigned_count * float(config.get("load_penalty_per_assigned_match", 60.0))
        + existing_route_count * float(config.get("load_penalty_per_existing_route", 30.0))
    )
    underused_bonus = float(config.get("underused_tutor_bonus", 50.0)) if assigned_count == 0 else 0.0
    level_cost = level_distance_cost(
        _value(tutor, "level", "nivell", "Nivell"),
        draft.level_demand,
        float(config.get("level_distance_weight", 1000.0)),
    )
    exceptional_penalty = float(config.get("exceptional_level_penalty", 3000.0)) if fit == LEVEL_FIT_EXCEPTIONAL else 0.0
    mobility_cost = (40.0 if needs_vehicle else 0.0) + 10.0 * len(set(warnings))
    classification_cost = draft.classification_importance * float(config.get("classification_fit_weight", 500.0))
    coverage_reward = draft.weighted_coverage_value * float(config.get("coverage_reward", 1000.0))
    cost = max(0.0, level_cost + exceptional_penalty + mobility_cost + classification_cost + load_penalty - underused_bonus)

    candidate_id = f"{phase.name}:{tutor_id}:{draft.id}"
    if inserted:
        candidate_id = f"{candidate_id}:insert"
    return RouteCandidate(
        id=candidate_id,
        phase_name=phase.name,
        tutor_id=tutor_id,
        new_match_ids=list(draft.match_ids),
        full_route_match_ids=full_match_ids,
        inserted_into_existing_route=inserted,
        date=draft.date,
        start_dt=_route_start(full_segments),
        end_dt=_route_end(full_segments),
        level_demand=draft.level_demand,
        level_fit=fit,
        requires_vehicle=needs_vehicle,
        cluster_ids=list(draft.cluster_ids),
        cluster_statuses=list(draft.cluster_statuses),
        venues=list(draft.venues),
        warning_codes=_dedupe(warnings),
        blocking_reasons=[],
        cost=float(cost),
        score_breakdown={
            "coverage_reward": -float(coverage_reward),
            "weighted_coverage_value": float(draft.weighted_coverage_value),
            "high_level_value": float(_high_level_value(draft.level_demand, draft.weighted_coverage_value)),
            "match_count": len(draft.match_ids),
            "level_cost": float(level_cost),
            "level_fit": fit,
            "level_exceptional": fit == LEVEL_FIT_EXCEPTIONAL,
            "exceptional_penalty": float(exceptional_penalty),
            "mobility_cost": float(mobility_cost),
            "classification_cost": float(classification_cost),
            "load_penalty": float(load_penalty),
            "underused_bonus": float(underused_bonus),
            "assigned_match_count_for_tutor": assigned_count,
            "existing_route_count_for_tutor": existing_route_count,
            "requires_vehicle": needs_vehicle,
            "tutor_has_vehicle": tutor_has_vehicle,
        },
    )


def _draft_from_fragments(fragments: tuple[Any, ...]) -> _RouteDraft:
    match_ids: list[str] = []
    levels = []
    cluster_ids: list[Any] = []
    statuses: list[Any] = []
    venues: list[str] = []
    starts = []
    ends = []
    classification = 0.0
    weighted = 0.0
    for fragment in fragments:
        match_ids.extend(_str_list(_value(fragment, "match_ids")))
        levels.append(_value(fragment, "level_demand", "level", "categoria", "Categoria"))
        cluster_ids.extend(_list_value(fragment, "cluster_ids"))
        statuses.extend(_list_value(fragment, "cluster_statuses"))
        venues.extend(str(value) for value in _list_value(fragment, "venues") if value)
        start = _datetime_value(_value(fragment, "start_dt", "start_datetime", "start"))
        end = _datetime_value(_value(fragment, "end_dt", "end_datetime", "end")) or start
        if start:
            starts.append(start)
        if end:
            ends.append(end)
        classification = max(classification, _float_value(fragment, "classification_importance", default=0.0))
        weighted += _float_value(fragment, "weighted_coverage_value", default=len(_str_list(_value(fragment, "match_ids"))))
    fragment_ids = [str(_value(fragment, "id", default="fragment")) for fragment in fragments]
    first = fragments[0]
    return _RouteDraft(
        id="+".join(fragment_ids),
        fragments=fragments,
        match_ids=tuple(_dedupe(match_ids)),
        date=_date_key(_value(first, "date", "Data")),
        modality=str(_value(first, "modality", "Modalitat", default="")),
        start_dt=min(starts) if starts else None,
        end_dt=max(ends) if ends else None,
        level_demand=hardest_match_level(levels),
        cluster_ids=tuple(cluster_ids),
        cluster_statuses=tuple(statuses),
        venues=tuple(_dedupe(venues)),
        classification_importance=classification,
        weighted_coverage_value=weighted or float(len(match_ids)),
    )


def _merge_drafts(left: _RouteDraft, right: _RouteDraft, config: dict[str, Any]) -> _RouteDraft | None:
    if left.date != right.date or normalize_text_key(left.modality) != normalize_text_key(right.modality):
        return None
    if set(left.match_ids) & set(right.match_ids):
        return None
    ordered = sorted([left, right], key=lambda item: item.start_dt or datetime.min)
    warnings, blocked = _validate_gaps(ordered, config)
    if blocked:
        return None
    return _RouteDraft(
        id=f"{ordered[0].id}+{ordered[1].id}",
        fragments=ordered[0].fragments + ordered[1].fragments,
        match_ids=ordered[0].match_ids + ordered[1].match_ids,
        date=left.date,
        modality=left.modality,
        start_dt=ordered[0].start_dt,
        end_dt=ordered[-1].end_dt,
        level_demand=hardest_match_level([left.level_demand, right.level_demand]),
        cluster_ids=ordered[0].cluster_ids + ordered[1].cluster_ids,
        cluster_statuses=ordered[0].cluster_statuses + ordered[1].cluster_statuses,
        venues=tuple(_dedupe(list(ordered[0].venues) + list(ordered[1].venues))),
        classification_importance=max(left.classification_importance, right.classification_importance),
        weighted_coverage_value=left.weighted_coverage_value + right.weighted_coverage_value,
    )


def _validate_gaps(segments: list[Any], config: dict[str, Any]) -> tuple[list[str], bool]:
    return validate_atomic_gaps(segments, {**dict(config), "has_vehicle": True})


def _required_gap(left: Any, right: Any, config: dict[str, Any]) -> int:
    left_points = route_points_from_segments([left])
    right_points = route_points_from_segments([right])
    if left_points and right_points:
        return atomic_required_gap(left_points[-1], right_points[0], config)
    return int(config.get("gap_diff_cluster_min", 150))


def _availability_covers(tutor: Any, route_date: str, start_dt: datetime | None, end_dt: datetime | None, config: dict[str, Any]) -> bool:
    availability = _value(tutor, "availability_by_date", default=None)
    if not availability:
        return bool(config.get("assume_available_when_missing", True))
    if start_dt is None or end_dt is None:
        return bool(config.get("assume_available_when_time_missing", True))
    raw = availability.get(route_date) or availability.get(start_dt.date()) if isinstance(availability, dict) else None
    if raw is None:
        return False
    windows = raw if isinstance(raw, list) else [raw]
    for window in windows:
        if isinstance(window, dict):
            start = _time_value(window.get("start") or window.get("Hora Inici") or window.get("hora_inici"))
            end = _time_value(window.get("end") or window.get("Hora Fi") or window.get("hora_fi"))
        elif isinstance(window, tuple) and len(window) >= 2:
            start = _time_value(window[0])
            end = _time_value(window[1])
        else:
            continue
        if start is not None and end is not None and _window_covers(start_dt, end_dt, start, end, config):
            return True
    return False


def _window_covers(start_dt: datetime, end_dt: datetime, start: time, end: time, config: dict[str, Any]) -> bool:
    buffer_min = int(config.get("availability_end_buffer_min", 60) or 0)
    window_start = datetime.combine(start_dt.date(), start)
    window_end = datetime.combine(start_dt.date(), end) - timedelta(minutes=buffer_min)
    return window_start <= start_dt and end_dt <= window_end


def _prune_candidates(candidates: list[RouteCandidate], phase: PhaseSpec, config: dict[str, Any]) -> list[RouteCandidate]:
    top_per_tutor = int(phase.top_n_routes_per_tutor or config.get("route_top_n_per_tutor", 20))
    top_per_match = int(config.get("route_top_n_per_match", 8))
    by_tutor: dict[tuple[str, str], list[RouteCandidate]] = {}
    for candidate in candidates:
        by_tutor.setdefault((candidate.tutor_id, candidate.date), []).append(candidate)
    retained: dict[str, RouteCandidate] = {}
    for items in by_tutor.values():
        for candidate in sorted(items, key=_candidate_rank)[:top_per_tutor]:
            retained[candidate.id] = candidate
    by_match: dict[str, list[RouteCandidate]] = {}
    for candidate in retained.values():
        for match_id in candidate.new_match_ids:
            by_match.setdefault(match_id, []).append(candidate)
    final: dict[str, RouteCandidate] = {}
    for items in by_match.values():
        for candidate in sorted(items, key=_candidate_rank)[:top_per_match]:
            final[candidate.id] = candidate
    return sorted(final.values(), key=_candidate_rank)


def _candidate_rank(candidate: RouteCandidate) -> tuple[Any, ...]:
    breakdown = candidate.score_breakdown or {}
    return (
        -float(breakdown.get("weighted_coverage_value", len(candidate.new_match_ids)) or 0.0),
        not bool(breakdown.get("high_level_value", 0.0)),
        candidate.level_fit == LEVEL_FIT_EXCEPTIONAL,
        float(candidate.cost),
        candidate.tutor_id,
        candidate.id,
    )


def _existing_route_state(state: Any, tutor_id: str, date_key: str) -> Any:
    assignments = _value(state, "assignments_by_tutor_day", default={}) or {}
    if not isinstance(assignments, dict):
        return None
    return assignments.get((tutor_id, date_key)) or assignments.get((tutor_id, str(date_key)))


def _existing_segments(route_state: Any) -> list[Any]:
    if route_state is None:
        return []
    for name in ("descriptors", "assigned_segments", "segments"):
        values = _list_value(route_state, name)
        if values:
            return values
    return []


def _existing_match_ids(route_state: Any) -> list[str]:
    ids = _str_list(_value(route_state, "assigned_match_ids"))
    if ids:
        return ids
    out: list[str] = []
    for segment in _existing_segments(route_state):
        out.extend(_str_list(_value(segment, "match_ids")))
        identifier = _value(segment, "identifier", "id", "match_id")
        if identifier is not None:
            out.append(str(identifier))
    return _dedupe(out)


def _route_start(segments: list[Any]) -> datetime | None:
    starts = [_segment_start(segment) for segment in segments if _segment_start(segment) is not None]
    return min(starts) if starts else None


def _route_end(segments: list[Any]) -> datetime | None:
    ends = [_segment_end(segment) for segment in segments if _segment_end(segment) is not None]
    return max(ends) if ends else None


def _segment_start(segment: Any) -> datetime | None:
    return _datetime_value(_value(segment, "start_dt", "start_datetime", "start", "match_datetime", "__match_datetime"))


def _segment_end(segment: Any) -> datetime | None:
    return _datetime_value(_value(segment, "end_dt", "end_datetime", "end", "match_datetime", "__match_datetime")) or _segment_start(segment)


def _segment_clusters(segment: Any) -> list[Any]:
    return _list_value(segment, "cluster_ids", "clusters", "cluster_id", "cluster")


def _segment_venues(segment: Any) -> list[str]:
    return [str(value) for value in _list_value(segment, "venues", "venue", "Pista joc") if value]


def _combined_cluster_ids(segments: list[Any]) -> list[Any]:
    out: list[Any] = []
    for segment in segments:
        out.extend(_segment_clusters(segment))
    return out


def _route_requires_vehicle(segments: list[Any]) -> bool:
    points = route_points_from_segments(segments)
    if len(points) >= 2:
        return any(atomic_transition_requires_vehicle(left, right) for left, right in zip(points, points[1:]))
    if _clusters_need_vehicle(_combined_cluster_ids(segments)):
        return True
    return _has_uncertain_cluster(segments) and not _segments_same_location(segments)


def _transition_requires_vehicle(left: Any, right: Any) -> bool:
    left_points = route_points_from_segments([left])
    right_points = route_points_from_segments([right])
    if left_points and right_points:
        return atomic_transition_requires_vehicle(left_points[-1], right_points[0])
    segments = [left, right]
    if _clusters_need_vehicle(_combined_cluster_ids(segments)):
        return True
    return _has_uncertain_cluster(segments) and not _segments_same_location(segments)


def _clusters_need_vehicle(cluster_ids: Iterable[Any]) -> bool:
    cleaned = {normalize_text_key(cluster) for cluster in cluster_ids if normalize_text_key(cluster)}
    return len(cleaned) > 1


def _has_uncertain_cluster(segments: Iterable[Any]) -> bool:
    statuses = {
        normalize_text_key(status)
        for segment in segments
        for status in _list_value(segment, "cluster_statuses", "cluster_status")
        if normalize_text_key(status)
    }
    if statuses & {"outlier", "missing_geocode", "pending", "not_found"}:
        return True
    return any(
        not normalize_text_key(cluster)
        for segment in segments
        for cluster in _segment_clusters(segment)
    )


def _segments_same_location(segments: Iterable[Any]) -> bool:
    segment_list = list(segments)
    venues = {
        normalize_text_key(venue)
        for segment in segment_list
        for venue in _segment_venues(segment)
        if normalize_text_key(venue)
    }
    if len(venues) == 1:
        return True
    if len(venues) > 1:
        return False
    return _segment_match_count(segment_list) <= 1


def _segment_match_count(segments: Iterable[Any]) -> int:
    count = 0
    for segment in segments:
        ids = _str_list(_value(segment, "match_ids", "new_match_ids", default=[]))
        count += len(ids) if ids else 1
    return count


def _cluster_warnings(cluster_ids: Iterable[Any], statuses: Iterable[Any]) -> list[str]:
    normalized_statuses = {normalize_text_key(status) for status in statuses if normalize_text_key(status)}
    warnings = []
    if "outlier" in normalized_statuses:
        warnings.append("outlier_mobility_warning")
    if any(not normalize_text_key(cluster) for cluster in cluster_ids) or normalized_statuses & {"missing_geocode", "pending", "not_found"}:
        warnings.append("missing_cluster_mobility_warning")
    return warnings


def _tutor_has_vehicle(tutor: Any) -> bool:
    explicit = _value(tutor, "has_vehicle", default=None)
    if explicit is not None:
        return bool(explicit)
    return has_vehicle(_value(tutor, "transport", "Mitja de Transport", "Mitja de transport", default=""))


def _high_level_value(level: Any, fallback: float) -> float:
    from .levels import is_high_match_level

    return float(fallback) if is_high_match_level(level) else 0.0


def _date_key(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return "" if value is None else str(value)


def _datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime()
        except Exception:
            return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _time_value(value: Any) -> time | None:
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


def _value(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        try:
            value = obj.get(name)
            if value is not None:
                return value
        except AttributeError:
            pass
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _list_value(obj: Any, *names: str) -> list[Any]:
    value = _value(obj, *names, default=())
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [str(value)]
    try:
        return [str(item) for item in value]
    except TypeError:
        return [str(value)]


def _float_value(obj: Any, *names: str, default: float = 0.0) -> float:
    value = _value(obj, *names, default=default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dedupe(values: Iterable[Any]) -> list[Any]:
    out = []
    seen = set()
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


__all__ = ["RouteCandidate", "generate_phase_route_candidates"]
