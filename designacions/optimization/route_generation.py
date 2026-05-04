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
from .peak_pressure import PeakAnchor, build_peak_anchors
from .route_points import (
    required_gap as atomic_required_gap,
    route_points_from_segments,
    same_location as atomic_same_location,
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
    peak_anchor: bool = False
    peak_bucket: str = ""
    peak_pressure_score: float = 0.0
    peak_anchor_match_ids: tuple[str, ...] = ()
    peak_anchor_bonus: float = 0.0


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
    eligible_tutors = [tutor for tutor in (tutors or []) if phase_allows_tutor(tutor, phase)]
    single_drafts = [_draft_from_fragments((fragment,)) for fragment in pending_fragments]
    drafts = list(single_drafts)
    peak_anchors: list[PeakAnchor] = []
    if _peak_routes_enabled(config):
        peak_anchors = build_peak_anchors(
            pending_fragments,
            eligible_tutors,
            state,
            _peak_config(config),
            top_n=int(config.get("peak_top_n_per_phase", config.get("peak_anchor_top_n", 8)) or 0),
        )
        drafts.extend(_peak_anchored_drafts(single_drafts, peak_anchors, phase, config))
    if int(phase.max_route_size or 1) >= 2:
        for left, right in combinations(single_drafts, 2):
            merged = _merge_drafts(left, right, config)
            if merged is not None:
                drafts.append(merged)
    if int(phase.max_route_size or 1) >= 3 and bool(config.get("route_generate_general_deep_routes", True)):
        drafts.extend(_general_centered_drafts(single_drafts, phase, config))
    drafts = _dedupe_drafts(drafts)

    candidates: list[RouteCandidate] = []
    for tutor in eligible_tutors:
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

    full_segments = _existing_segments(existing_route) + _draft_segments(draft)
    full_segments = sorted(full_segments, key=lambda item: _segment_start(item) or datetime.min)
    full_match_ids = _dedupe(_existing_match_ids(existing_route) + list(draft.match_ids))
    inserted = bool(_value(existing_route, "assigned_match_ids") or _existing_segments(existing_route))

    if not _availability_covers(tutor, draft.date, _route_start(full_segments), _route_end(full_segments), config):
        blocking.append("outside_availability_window")
    elif not _availability_respects_buffer(tutor, draft.date, _route_start(full_segments), _route_end(full_segments), config):
        warnings.append("availability_end_buffer_warning")

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
    gap_laxity_cost = _gap_laxity_cost(full_segments, config)
    mobility_cost = (40.0 if needs_vehicle else 0.0) + 10.0 * len(set(warnings))
    classification_cost = draft.classification_importance * float(config.get("classification_fit_weight", 500.0))
    coverage_reward = draft.weighted_coverage_value * float(config.get("coverage_reward", 1000.0))
    non_peak_capacity_penalty = 0.0
    if _peak_routes_enabled(config) and not draft.peak_anchor and assigned_count == 0:
        non_peak_capacity_penalty = float(config.get("peak_anchor_non_peak_capacity_penalty", 0.0) or 0.0)
    cost = max(
        0.0,
        level_cost
        + exceptional_penalty
        + mobility_cost
        + gap_laxity_cost
        + classification_cost
        + load_penalty
        + non_peak_capacity_penalty
        - underused_bonus,
    )

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
            "peak_anchor": bool(draft.peak_anchor),
            "peak_bucket": draft.peak_bucket,
            "peak_pressure_score": float(draft.peak_pressure_score),
            "peak_anchor_match_ids": list(draft.peak_anchor_match_ids),
            "peak_anchor_bonus": float(draft.peak_anchor_bonus),
            "non_peak_capacity_penalty": float(non_peak_capacity_penalty),
            "match_count": len(draft.match_ids),
            "level_cost": float(level_cost),
            "level_fit": fit,
            "level_exceptional": fit == LEVEL_FIT_EXCEPTIONAL,
            "exceptional_penalty": float(exceptional_penalty),
            "mobility_cost": float(mobility_cost),
            "gap_laxity_cost": float(gap_laxity_cost),
            "gap_laxity_summary": _gap_laxity_summary(full_segments, config),
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


def _draft_segments(draft: _RouteDraft) -> list[Any]:
    return list(draft.fragments) if draft.fragments else [draft]


def _with_peak_metadata(draft: _RouteDraft, anchor: PeakAnchor, config: dict[str, Any]) -> _RouteDraft:
    anchor_match_ids = tuple(_dedupe([*draft.peak_anchor_match_ids, *anchor.match_ids]))
    anchor_bonus = (
        float(anchor.pressure_score)
        * float(anchor.demand or 1.0)
        * float(config.get("peak_anchor_route_bonus", 0.35) or 0.0)
    )
    return _RouteDraft(
        id=f"peak:{draft.id}",
        fragments=draft.fragments,
        match_ids=draft.match_ids,
        date=draft.date,
        modality=draft.modality,
        start_dt=draft.start_dt,
        end_dt=draft.end_dt,
        level_demand=draft.level_demand,
        cluster_ids=draft.cluster_ids,
        cluster_statuses=draft.cluster_statuses,
        venues=draft.venues,
        classification_importance=draft.classification_importance,
        weighted_coverage_value=draft.weighted_coverage_value + anchor_bonus,
        peak_anchor=True,
        peak_bucket=anchor.key,
        peak_pressure_score=float(anchor.pressure_score),
        peak_anchor_match_ids=anchor_match_ids,
        peak_anchor_bonus=anchor_bonus,
    )


def _merge_drafts(left: _RouteDraft, right: _RouteDraft, config: dict[str, Any]) -> _RouteDraft | None:
    return _merge_many_drafts((left, right), config)


def _merge_many_drafts(drafts: tuple[_RouteDraft, ...], config: dict[str, Any]) -> _RouteDraft | None:
    if len(drafts) < 2:
        return None
    dates = {draft.date for draft in drafts}
    modalities = {normalize_text_key(draft.modality) for draft in drafts}
    if len(dates) > 1 or len(modalities) > 1:
        return None
    all_match_ids = [match_id for draft in drafts for match_id in draft.match_ids]
    if len(all_match_ids) != len(set(all_match_ids)):
        return None
    ordered = sorted(drafts, key=lambda item: item.start_dt or datetime.min)
    warnings, blocked = _validate_gaps(ordered, config)
    if blocked:
        return None
    cluster_ids: list[Any] = []
    cluster_statuses: list[Any] = []
    venues: list[str] = []
    for draft in ordered:
        cluster_ids.extend(draft.cluster_ids)
        cluster_statuses.extend(draft.cluster_statuses)
        venues.extend(draft.venues)
    return _RouteDraft(
        id="+".join(draft.id for draft in ordered),
        fragments=tuple(fragment for draft in ordered for fragment in draft.fragments),
        match_ids=tuple(match_id for draft in ordered for match_id in draft.match_ids),
        date=ordered[0].date,
        modality=ordered[0].modality,
        start_dt=ordered[0].start_dt,
        end_dt=ordered[-1].end_dt,
        level_demand=hardest_match_level([draft.level_demand for draft in ordered]),
        cluster_ids=tuple(cluster_ids),
        cluster_statuses=tuple(cluster_statuses),
        venues=tuple(_dedupe(venues)),
        classification_importance=max(draft.classification_importance for draft in ordered),
        weighted_coverage_value=sum(draft.weighted_coverage_value for draft in ordered),
        peak_anchor=any(draft.peak_anchor for draft in ordered),
        peak_bucket=next((draft.peak_bucket for draft in ordered if draft.peak_bucket), ""),
        peak_pressure_score=max(draft.peak_pressure_score for draft in ordered),
        peak_anchor_match_ids=tuple(_dedupe(match_id for draft in ordered for match_id in draft.peak_anchor_match_ids)),
        peak_anchor_bonus=sum(draft.peak_anchor_bonus for draft in ordered),
    )


def _peak_anchored_drafts(
    single_drafts: list[_RouteDraft],
    anchors: list[PeakAnchor],
    phase: PhaseSpec,
    config: dict[str, Any],
) -> list[_RouteDraft]:
    if not anchors:
        return []
    by_fragment_id = {str(_value(draft.fragments[0], "id", default=draft.id)): draft for draft in single_drafts if draft.fragments}
    out: list[_RouteDraft] = []
    max_size = int(phase.max_route_size or 1)
    neighbor_limit = int(config.get("peak_anchor_neighbor_limit", 6) or 0)
    per_anchor_limit = int(config.get("peak_anchor_route_limit_per_anchor", 80) or 0)
    for anchor in anchors:
        anchor_drafts = [by_fragment_id[fragment_id] for fragment_id in anchor.fragment_ids if fragment_id in by_fragment_id]
        for anchor_draft in anchor_drafts:
            marked_anchor = _with_peak_metadata(anchor_draft, anchor, config)
            out.append(marked_anchor)
            if max_size < 2:
                continue
            before, after = _neighbor_drafts(single_drafts, anchor_draft, neighbor_limit)
            neighbors = _dedupe_drafts(before + after)
            generated = 0
            for route_size in range(2, max_size + 1):
                for extra_drafts in combinations(neighbors, route_size - 1):
                    merged = _merge_many_drafts((marked_anchor, *extra_drafts), config)
                    if merged is not None and _draft_contains_anchor(merged, anchor):
                        out.append(merged)
                        generated += 1
                    if per_anchor_limit > 0 and generated >= per_anchor_limit:
                        break
                if per_anchor_limit > 0 and generated >= per_anchor_limit:
                    break
    return out


def _general_centered_drafts(
    single_drafts: list[_RouteDraft],
    phase: PhaseSpec,
    config: dict[str, Any],
) -> list[_RouteDraft]:
    max_size = int(phase.max_route_size or 1)
    if max_size < 3:
        return []
    neighbor_limit = int(config.get("route_general_neighbor_limit", 4) or 0)
    per_center_limit = int(config.get("route_general_deep_limit_per_center", 40) or 0)
    out: list[_RouteDraft] = []
    for center in single_drafts:
        before, after = _neighbor_drafts(single_drafts, center, neighbor_limit)
        neighbors = _dedupe_drafts(before + after)
        generated = 0
        for route_size in range(3, max_size + 1):
            for extra_drafts in combinations(neighbors, route_size - 1):
                merged = _merge_many_drafts((center, *extra_drafts), config)
                if merged is not None:
                    out.append(merged)
                    generated += 1
                if per_center_limit > 0 and generated >= per_center_limit:
                    break
            if per_center_limit > 0 and generated >= per_center_limit:
                break
    return out


def _neighbor_drafts(
    single_drafts: list[_RouteDraft],
    anchor: _RouteDraft,
    limit: int,
) -> tuple[list[_RouteDraft], list[_RouteDraft]]:
    compatible = [
        draft
        for draft in single_drafts
        if draft is not anchor
        and draft.date == anchor.date
        and normalize_text_key(draft.modality) == normalize_text_key(anchor.modality)
        and not (set(draft.match_ids) & set(anchor.match_ids))
    ]
    before = sorted(
        [draft for draft in compatible if (draft.start_dt or datetime.min) <= (anchor.start_dt or datetime.min)],
        key=lambda item: item.start_dt or datetime.min,
        reverse=True,
    )
    after = sorted(
        [draft for draft in compatible if (draft.start_dt or datetime.min) >= (anchor.start_dt or datetime.min)],
        key=lambda item: item.start_dt or datetime.min,
    )
    if limit > 0:
        before = before[:limit]
        after = after[:limit]
    return before, after


def _draft_contains_anchor(draft: _RouteDraft, anchor: PeakAnchor) -> bool:
    return bool(set(draft.match_ids) & set(anchor.match_ids))


def _dedupe_drafts(drafts: list[_RouteDraft]) -> list[_RouteDraft]:
    retained: dict[tuple[Any, ...], _RouteDraft] = {}
    for draft in drafts:
        key = (draft.date, tuple(sorted(draft.match_ids)))
        current = retained.get(key)
        if current is None or _draft_rank(draft) < _draft_rank(current):
            retained[key] = draft
    return list(retained.values())


def _draft_rank(draft: _RouteDraft) -> tuple[Any, ...]:
    return (
        not draft.peak_anchor,
        -float(draft.weighted_coverage_value or 0.0),
        float(draft.start_dt.timestamp()) if draft.start_dt else 0.0,
        draft.id,
    )


def _peak_routes_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("peak_anchored_routes_enabled", True))


def _peak_config(config: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(config)
    if "peak_bucket_minutes" in cfg and "peak_time_bucket_minutes" not in cfg:
        cfg["peak_time_bucket_minutes"] = cfg["peak_bucket_minutes"]
    if "peak_top_n_per_phase" in cfg and "peak_anchor_top_n" not in cfg:
        cfg["peak_anchor_top_n"] = cfg["peak_top_n_per_phase"]
    if "peak_anchor_min_pressure_ratio" in cfg and "peak_anchor_min_pressure" not in cfg:
        cfg["peak_anchor_min_pressure"] = cfg["peak_anchor_min_pressure_ratio"]
    if "peak_anchor_max_matches_per_bucket" in cfg and "peak_anchor_fragment_limit" not in cfg:
        cfg["peak_anchor_fragment_limit"] = cfg["peak_anchor_max_matches_per_bucket"]
    return cfg


def _validate_gaps(segments: list[Any], config: dict[str, Any]) -> tuple[list[str], bool]:
    return validate_atomic_gaps(segments, {**dict(config), "has_vehicle": True})


def _gap_laxity_cost(segments: list[Any], config: dict[str, Any]) -> float:
    cost_per_min = float(config.get("gap_laxity_cost_per_min", 0.35) or 0.0)
    if cost_per_min <= 0:
        return 0.0
    return sum(item["extra_minutes"] * item["weight"] * cost_per_min for item in _gap_laxity_items(segments, config))


def _gap_laxity_summary(segments: list[Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "left_match_id": item["left_match_id"],
            "right_match_id": item["right_match_id"],
            "gap_type": item["gap_type"],
            "actual_gap_min": item["actual_gap_min"],
            "required_gap_min": item["required_gap_min"],
            "extra_minutes": item["extra_minutes"],
        }
        for item in _gap_laxity_items(segments, config)
        if item["extra_minutes"] > 0
    ]


def _gap_laxity_items(segments: list[Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    points = route_points_from_segments(segments)
    items: list[dict[str, Any]] = []
    for left, right in zip(points, points[1:]):
        left_end = left.end_dt or left.start_dt
        right_start = right.start_dt
        if left_end is None or right_start is None:
            continue
        actual = (right_start - left_end).total_seconds() / 60.0
        required = float(atomic_required_gap(left, right, config))
        extra = max(0.0, actual - required)
        if atomic_same_location(left, right):
            gap_type = "same_pitch"
            weight = float(config.get("gap_laxity_same_pitch_weight", 0.25) or 0.25)
        elif atomic_transition_requires_vehicle(left, right):
            gap_type = "diff_cluster"
            weight = float(config.get("gap_laxity_diff_cluster_weight", 1.0) or 1.0)
        else:
            gap_type = "diff_pitch_same_cluster"
            weight = float(config.get("gap_laxity_diff_pitch_weight", 0.55) or 0.55)
        items.append(
            {
                "left_match_id": left.match_id,
                "right_match_id": right.match_id,
                "gap_type": gap_type,
                "actual_gap_min": round(actual, 4),
                "required_gap_min": required,
                "extra_minutes": round(extra, 4),
                "weight": weight,
            }
        )
    return items


def _required_gap(left: Any, right: Any, config: dict[str, Any]) -> int:
    left_points = route_points_from_segments([left])
    right_points = route_points_from_segments([right])
    if left_points and right_points:
        return atomic_required_gap(left_points[-1], right_points[0], config)
    return int(config.get("gap_diff_cluster_min", 150))


def _availability_covers(tutor: Any, route_date: str, start_dt: datetime | None, end_dt: datetime | None, config: dict[str, Any]) -> bool:
    return _availability_window_check(tutor, route_date, start_dt, end_dt, config, use_buffer=False)


def _availability_respects_buffer(tutor: Any, route_date: str, start_dt: datetime | None, end_dt: datetime | None, config: dict[str, Any]) -> bool:
    return _availability_window_check(tutor, route_date, start_dt, end_dt, config, use_buffer=True)


def _availability_window_check(
    tutor: Any,
    route_date: str,
    start_dt: datetime | None,
    end_dt: datetime | None,
    config: dict[str, Any],
    *,
    use_buffer: bool,
) -> bool:
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
        if start is not None and end is not None and _window_covers(start_dt, end_dt, start, end, config, use_buffer=use_buffer):
            return True
    return False


def _window_covers(start_dt: datetime, end_dt: datetime, start: time, end: time, config: dict[str, Any], *, use_buffer: bool = False) -> bool:
    buffer_min = int(config.get("availability_end_buffer_min", 60) or 0) if use_buffer else 0
    window_start = datetime.combine(start_dt.date(), start)
    window_end = datetime.combine(start_dt.date(), end) - timedelta(minutes=buffer_min)
    return window_start <= start_dt and end_dt <= window_end


def _prune_candidates(candidates: list[RouteCandidate], phase: PhaseSpec, config: dict[str, Any]) -> list[RouteCandidate]:
    top_per_tutor = int(phase.top_n_routes_per_tutor or config.get("route_top_n_per_tutor", 80))
    top_per_match = int(config.get("route_top_n_per_match", 30))
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
