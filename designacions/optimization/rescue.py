from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, time, timedelta
from itertools import combinations
from typing import Any, Iterable, Mapping

from .route_points import (
    required_gap as atomic_required_gap,
    route_points_from_segments,
    transition_requires_vehicle as atomic_transition_requires_vehicle,
    validate_atomic_gaps,
)


DEFAULT_PARTIAL_TOP_N_TUTORS = 5
DEFAULT_FINAL_TOP_N_TUTORS = 8
DEFAULT_NEW_ROUTE_TOP_N_PER_TUTOR = 30
DEFAULT_NEW_ROUTE_TOP_N_PER_MATCH = 10
DEFAULT_INDIVIDUAL_TOP_N_TUTORS = 8
DEFAULT_INDIVIDUAL_MAX_ITERATIONS = 5


@dataclass
class RescueResult:
    selected_routes: list[dict[str, Any]]
    recovered_match_ids: list[str]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_routes": list(self.selected_routes),
            "recovered_match_ids": list(self.recovered_match_ids),
            "summary": dict(self.summary),
        }


def run_partial_rescue(
    fragments: Iterable[Any],
    tutors: Iterable[Any],
    state: Any,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Conservative rescue pass for critical phase leftovers.

    This function is deliberately pure: it never mutates the accumulated state
    and only returns auditable route candidates that a caller may later apply.
    """

    cfg = dict(config or {})
    max_matches = int(
        cfg.get(
            "partial_rescue_max_matches_per_route",
            cfg.get("_rescue_max_matches_per_route", cfg.get("route_max_new_matches_per_phase", 2)),
        )
        or 2
    )
    cfg["_rescue_max_matches_per_route"] = max_matches
    return _run_rescue(
        fragments=fragments,
        tutors=tutors,
        state=state,
        config=cfg,
        rescue_kind="partial_rescue",
        top_n_tutors=int(cfg.get("partial_rescue_top_n_tutors", DEFAULT_PARTIAL_TOP_N_TUTORS) or 0),
        max_matches_per_route=max_matches,
        allow_exceptional=bool(cfg.get("allow_exceptional_routes", False)),
    ).to_dict()


def run_final_rescue(
    fragments: Iterable[Any],
    tutors: Iterable[Any],
    state: Any,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Final safe rescue pass for all still-pending fragments."""

    cfg = dict(config or {})
    return _run_rescue(
        fragments=fragments,
        tutors=tutors,
        state=state,
        config=cfg,
        rescue_kind="final_rescue",
        top_n_tutors=int(cfg.get("final_rescue_top_n_tutors", DEFAULT_FINAL_TOP_N_TUTORS) or 0),
        max_matches_per_route=int(cfg.get("final_rescue_max_matches_per_route", 2) or 2),
        allow_exceptional=bool(cfg.get("allow_exceptional_routes", False)),
    ).to_dict()


def run_new_route_rescue(
    fragments: Iterable[Any],
    tutors: Iterable[Any],
    state: Any,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build brand-new rescue routes from still-pending fragments only."""

    cfg = dict(config or {})
    rescue_kind = "new_route_rescue"
    tutor_list = list(tutors or [])
    if cfg.get("rescue_new_routes_enabled", True) is False:
        return RescueResult(
            selected_routes=[],
            recovered_match_ids=[],
            summary={
                "kind": rescue_kind,
                "attempted_match_count": 0,
                "recovered_match_count": 0,
                "selected_route_count": 0,
                "candidate_count": 0,
                "viable_candidate_count": 0,
                "blocking_reason_counts": {},
                "unrecovered_match_ids": [],
                "disabled": True,
            },
        ).to_dict()

    pending_fragments = _pending_unassigned_fragments(fragments, state)
    attempted_match_ids = sorted({match_id for fragment in pending_fragments for match_id in _fragment_match_ids(fragment)})
    route_drafts = _build_new_route_drafts(pending_fragments, cfg)
    candidates, blocking_reason_counts = _generate_direct_candidates(
        route_drafts,
        tutor_list,
        state,
        cfg,
        rescue_kind=rescue_kind,
        include_existing_route_conflicts=True,
    )
    viable_candidates = _prune_direct_candidates(
        candidates,
        top_n_per_tutor=int(cfg.get("rescue_new_routes_top_n_per_tutor", DEFAULT_NEW_ROUTE_TOP_N_PER_TUTOR) or 0),
        top_n_per_match=int(cfg.get("rescue_new_routes_top_n_per_match", DEFAULT_NEW_ROUTE_TOP_N_PER_MATCH) or 0),
    )
    selected_routes = _select_non_overlapping_routes(viable_candidates, prefer_coverage=True)
    recovered_match_ids = sorted(
        {
            match_id
            for route in selected_routes
            for match_id in _normalize_ids(route.get("new_match_ids") or route.get("match_ids"))
        }
    )
    return RescueResult(
        selected_routes=selected_routes,
        recovered_match_ids=recovered_match_ids,
        summary={
            "kind": rescue_kind,
            "attempted_match_count": len(attempted_match_ids),
            "recovered_match_count": len(recovered_match_ids),
            "selected_route_count": len(selected_routes),
            "candidate_count": len(route_drafts) * len(tutor_list),
            "viable_candidate_count": len(viable_candidates),
            "blocking_reason_counts": blocking_reason_counts,
            "unrecovered_match_ids": sorted(set(attempted_match_ids) - set(recovered_match_ids)),
            "route_draft_count": len(route_drafts),
        },
    ).to_dict()


def run_individual_rescue(
    fragments: Iterable[Any],
    tutors: Iterable[Any],
    state: Any,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Iteratively assign individual pending fragments to viable tutors.

    The input state is never mutated; selected routes from previous iterations
    are tracked in a local overlay used only for subsequent feasibility checks.
    """

    cfg = dict(config or {})
    rescue_kind = "individual_rescue"
    if cfg.get("individual_rescue_enabled", True) is False:
        return RescueResult(
            selected_routes=[],
            recovered_match_ids=[],
            summary={
                "kind": rescue_kind,
                "attempted_match_count": 0,
                "recovered_match_count": 0,
                "selected_route_count": 0,
                "iteration_summaries": [],
                "stopped_reason": "disabled",
                "disabled": True,
            },
        ).to_dict()

    tutor_list = list(tutors or [])
    pending_fragments = _pending_unassigned_fragments(fragments, state)
    single_fragments = _individual_fragments_from_pending(pending_fragments)
    fragment_by_match = {match_id: fragment for fragment in single_fragments for match_id in _fragment_match_ids(fragment)}
    pending_ids = set(fragment_by_match)
    attempted_match_ids = sorted(pending_ids)
    selected_routes: list[dict[str, Any]] = []
    recovered: set[str] = set()
    local_assignments = _copy_assignments_by_tutor_day(state)
    iteration_summaries: list[dict[str, Any]] = []
    max_iterations = int(cfg.get("individual_rescue_max_iterations", DEFAULT_INDIVIDUAL_MAX_ITERATIONS) or 0)
    max_total = cfg.get("individual_rescue_max_total_assignments")
    max_total_assignments = None if max_total in (None, "") else int(max_total)
    stopped_reason = "no_pending_matches" if not pending_ids else "max_iterations_reached"

    for iteration in range(1, max_iterations + 1):
        if not pending_ids:
            stopped_reason = "no_pending_matches"
            break
        if max_total_assignments is not None and len(recovered) >= max_total_assignments:
            stopped_reason = "max_total_assignments_reached"
            break

        pending_before = set(pending_ids)
        overlay_state = _state_overlay(state, local_assignments)
        include_after = int(cfg.get("individual_rescue_include_assigned_tutors_after_iteration", 1) or 0)
        candidate_tutors = _individual_iteration_tutors(tutor_list, overlay_state, iteration, include_after)
        drafts = [
            _route_draft_from_fragments([fragment_by_match[match_id]], rescue_kind=f"{rescue_kind}:{iteration}")
            for match_id in sorted(pending_ids)
        ]
        candidates, blocking_counts = _generate_direct_candidates(
            drafts,
            candidate_tutors,
            overlay_state,
            cfg,
            rescue_kind=f"{rescue_kind}:{iteration}",
            include_existing_route_conflicts=True,
        )
        viable_candidates = _prune_direct_candidates(
            candidates,
            top_n_per_tutor=0,
            top_n_per_match=int(cfg.get("individual_rescue_top_n_tutors", DEFAULT_INDIVIDUAL_TOP_N_TUTORS) or 0),
        )
        selected_this_iteration = _select_non_overlapping_routes(viable_candidates, prefer_coverage=True)
        if max_total_assignments is not None:
            remaining_slots = max(0, max_total_assignments - len(recovered))
            selected_this_iteration = selected_this_iteration[:remaining_slots]

        newly_recovered = {
            match_id
            for route in selected_this_iteration
            for match_id in _normalize_ids(route.get("new_match_ids") or route.get("match_ids"))
            if match_id in pending_ids
        }
        pending_after = set(pending_ids) - newly_recovered
        if not viable_candidates:
            stopped_reason = "no_viable_candidates"
        elif not newly_recovered or pending_after == pending_before:
            stopped_reason = "no_progress"
        elif max_total_assignments is not None and len(recovered) + len(newly_recovered) >= max_total_assignments:
            stopped_reason = "max_total_assignments_reached"
        elif iteration == max_iterations:
            stopped_reason = "max_iterations_reached"
        else:
            stopped_reason = ""

        iteration_summaries.append(
            {
                "iteration": iteration,
                "pending_before": len(pending_before),
                "candidate_count": len(candidates),
                "viable_candidate_count": len(viable_candidates),
                "selected_count": len(selected_this_iteration),
                "recovered_match_count": len(newly_recovered),
                "pending_after": len(pending_after),
                "blocking_reason_counts": blocking_counts,
                "stopped_reason": stopped_reason or None,
            }
        )
        if stopped_reason in {"no_viable_candidates", "no_progress"}:
            break

        selected_routes.extend(selected_this_iteration)
        recovered.update(newly_recovered)
        pending_ids = pending_after
        _overlay_selected_routes(local_assignments, selected_this_iteration)

        if stopped_reason in {"max_iterations_reached", "max_total_assignments_reached"}:
            break

    return RescueResult(
        selected_routes=selected_routes,
        recovered_match_ids=sorted(recovered),
        summary={
            "kind": rescue_kind,
            "attempted_match_count": len(attempted_match_ids),
            "recovered_match_count": len(recovered),
            "selected_route_count": len(selected_routes),
            "iteration_summaries": iteration_summaries,
            "stopped_reason": stopped_reason,
            "unrecovered_match_ids": sorted(set(attempted_match_ids) - recovered),
        },
    ).to_dict()


def _run_rescue(
    *,
    fragments: Iterable[Any],
    tutors: Iterable[Any],
    state: Any,
    config: Mapping[str, Any],
    rescue_kind: str,
    top_n_tutors: int,
    max_matches_per_route: int,
    allow_exceptional: bool,
) -> RescueResult:
    tutor_list = list(tutors or [])
    assigned_match_ids = set(_normalize_ids(_get(state, "assigned_match_ids", default=[])))
    pending_match_ids = set(_normalize_ids(_get(state, "pending_match_ids", default=[])))
    candidate_fragments = [
        fragment
        for fragment in fragments or []
        if _fragment_match_ids(fragment)
        and not (set(_fragment_match_ids(fragment)) & assigned_match_ids)
        and (not pending_match_ids or set(_fragment_match_ids(fragment)) & pending_match_ids)
        and len(_fragment_match_ids(fragment)) <= max_matches_per_route
    ]

    candidates = _generate_external_candidates(
        candidate_fragments,
        tutor_list,
        state,
        config,
        rescue_kind=rescue_kind,
    )
    fallback_blocking_reason_counts: dict[str, int] = {}
    if not candidates:
        candidates, fallback_blocking_reason_counts = _generate_validated_fallback_candidates(
            candidate_fragments,
            tutor_list,
            state,
            config,
            rescue_kind=rescue_kind,
            top_n_tutors=top_n_tutors,
        )

    viable_candidates: list[dict[str, Any]] = []
    blocking_reason_counts: dict[str, int] = dict(fallback_blocking_reason_counts)
    for candidate in candidates:
        candidate_dict = _candidate_to_dict(candidate, rescue_kind=rescue_kind)
        blocking_reasons = _normalize_ids(candidate_dict.get("blocking_reasons"))
        if _has_forbidden_level(candidate_dict):
            blocking_reasons.append("level_forbidden")
        if blocking_reasons:
            for reason in sorted(set(blocking_reasons)):
                blocking_reason_counts[reason] = blocking_reason_counts.get(reason, 0) + 1
            continue
        if _is_exceptional(candidate_dict) and not allow_exceptional:
            blocking_reason_counts["exceptional_not_allowed"] = blocking_reason_counts.get(
                "exceptional_not_allowed", 0
            ) + 1
            continue
        viable_candidates.append(candidate_dict)

    selected_routes = _select_non_overlapping_routes(viable_candidates, prefer_coverage=True)
    recovered_match_ids = sorted(
        {
            match_id
            for route in selected_routes
            for match_id in _normalize_ids(route.get("new_match_ids") or route.get("match_ids"))
        }
    )
    attempted_match_ids = sorted(
        {match_id for fragment in candidate_fragments for match_id in _fragment_match_ids(fragment)}
    )

    summary = {
        "kind": rescue_kind,
        "attempted_match_count": len(attempted_match_ids),
        "recovered_match_count": len(recovered_match_ids),
        "selected_route_count": len(selected_routes),
        "candidate_count": len(candidates),
        "viable_candidate_count": len(viable_candidates),
        "blocking_reason_counts": blocking_reason_counts,
        "unrecovered_match_ids": sorted(set(attempted_match_ids) - set(recovered_match_ids)),
    }
    return RescueResult(
        selected_routes=selected_routes,
        recovered_match_ids=recovered_match_ids,
        summary=summary,
    )


def _generate_external_candidates(
    fragments: list[Any],
    tutors: Iterable[Any],
    state: Any,
    config: Mapping[str, Any],
    *,
    rescue_kind: str,
) -> list[Any]:
    try:
        from .phases import PhaseSpec
        from .route_generation import generate_phase_route_candidates  # type: ignore
    except Exception:
        return []

    phase = PhaseSpec(
        name=str(config.get("_rescue_phase_name") or rescue_kind),
        tutor_levels=[],
        allowed_max_level_position=None,
        allowed_level_labels=[],
        allow_exceptional=bool(config.get("allow_exceptional_routes", False)),
        rescue_after_phase=False,
        max_route_size=int(config.get("_rescue_max_matches_per_route", config.get("final_rescue_max_matches_per_route", 2)) or 2),
        top_n_routes_per_tutor=int(config.get("route_top_n_per_tutor", 80) or 80),
    )
    call_patterns = (
        lambda: generate_phase_route_candidates(fragments, tutors, state, phase, dict(config)),
        lambda: generate_phase_route_candidates(
            fragments=fragments,
            tutors=tutors,
            state=state,
            phase=phase,
            config=dict(config),
        ),
    )
    for call in call_patterns:
        try:
            generated = call()
        except TypeError:
            continue
        except Exception:
            return []
        return list(generated or [])
    return []


def _generate_validated_fallback_candidates(
    fragments: list[Any],
    tutors: Iterable[Any],
    state: Any,
    config: Mapping[str, Any],
    *,
    rescue_kind: str,
    top_n_tutors: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    max_matches = int(config.get("_rescue_max_matches_per_route", 1) or 1)
    drafts = _build_rescue_route_drafts(
        fragments,
        rescue_kind=rescue_kind,
        phase_name=str(config.get("_rescue_phase_name") or rescue_kind),
        max_matches_per_route=max_matches,
        config=config,
    )
    candidates, blocking_reason_counts = _generate_direct_candidates(
        drafts,
        tutors,
        state,
        config,
        rescue_kind=rescue_kind,
        include_existing_route_conflicts=True,
    )
    retained = _prune_direct_candidates(
        candidates,
        top_n_per_tutor=0,
        top_n_per_match=top_n_tutors,
    )
    for candidate in retained:
        score_breakdown = candidate.setdefault("score_breakdown", {})
        if isinstance(score_breakdown, dict):
            score_breakdown["source"] = "validated_fallback_rescue"
        warnings = _normalize_ids(candidate.get("warning_codes"))
        if "validated_fallback_rescue_candidate" not in warnings:
            warnings.append("validated_fallback_rescue_candidate")
        candidate["warning_codes"] = warnings
    return retained, blocking_reason_counts


def _pending_unassigned_fragments(fragments: Iterable[Any], state: Any) -> list[Any]:
    assigned_match_ids = set(_normalize_ids(_get(state, "assigned_match_ids", default=[])))
    pending_match_ids = set(_normalize_ids(_get(state, "pending_match_ids", default=[])))
    pending: list[Any] = []
    for fragment in fragments or []:
        match_ids = set(_fragment_match_ids(fragment))
        if not match_ids or match_ids & assigned_match_ids:
            continue
        if pending_match_ids and not (match_ids & pending_match_ids):
            continue
        pending.append(fragment)
    return pending


def _individual_fragments_from_pending(fragments: Iterable[Any]) -> list[Any]:
    individual: list[Any] = []
    for fragment in fragments or []:
        match_ids = _fragment_match_ids(fragment)
        if len(match_ids) <= 1:
            individual.append(fragment)
            continue
        rows = _list_value(fragment, "rows")
        for index, match_id in enumerate(match_ids):
            row = rows[index] if index < len(rows) else None
            payload = _object_to_dict(fragment)
            payload["id"] = f"{_fragment_id(fragment)}:individual:{index + 1}"
            payload["match_ids"] = [match_id]
            payload["rows"] = [row] if row is not None else []
            if row is not None:
                row_dt = _datetime_value(_get(row, "__match_datetime", "match_datetime", "start_dt", "Hora", default=None))
                payload["start_dt"] = row_dt or payload.get("start_dt")
                payload["end_dt"] = row_dt or payload.get("end_dt")
                payload["level_demand"] = _get(row, "Categoria", "categoria", "Nivell", "nivell", default=payload.get("level_demand"))
                venue = _get(row, "Pista joc", "venue", default=None)
                if venue:
                    payload["venues"] = [venue]
                cluster = _get(row, "cluster", "cluster_id", default=None)
                if cluster is not None:
                    payload["cluster_ids"] = [cluster]
                status = _get(row, "cluster_status", default=None)
                if status is not None:
                    payload["cluster_statuses"] = [status]
            if payload.get("weighted_coverage_value"):
                payload["weighted_coverage_value"] = 1.0
            individual.append(payload)
    return individual


def _build_new_route_drafts(fragments: list[Any], config: Mapping[str, Any]) -> list[dict[str, Any]]:
    max_size = int(config.get("rescue_new_routes_max_size", 2) or 2)
    same_venue_max_size = int(config.get("rescue_new_routes_same_venue_max_size", max_size) or max_size)
    allowed_sizes = [1]
    if max_size >= 2:
        allowed_sizes.append(2)
    if max(max_size, same_venue_max_size) >= 3:
        allowed_sizes.append(3)

    drafts: list[dict[str, Any]] = []
    for size in allowed_sizes:
        for group in combinations(fragments, size):
            draft = _route_draft_from_fragments(group, rescue_kind="new_route_rescue")
            if not draft:
                continue
            if size >= 2 and not _draft_group_is_compatible(draft, config):
                continue
            if size >= 3 and not _draft_allows_three_fragments(draft, config):
                continue
            drafts.append(draft)
    return drafts


def _build_rescue_route_drafts(
    fragments: list[Any],
    *,
    rescue_kind: str,
    phase_name: str,
    max_matches_per_route: int,
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    max_size = max(1, int(max_matches_per_route or 1))
    allowed_sizes = range(1, min(max_size, len(fragments)) + 1)
    drafts: list[dict[str, Any]] = []
    for size in allowed_sizes:
        for group in combinations(fragments, size):
            draft = _route_draft_from_fragments(group, rescue_kind=rescue_kind, phase_name=phase_name)
            if not draft:
                continue
            if len(_normalize_ids(draft.get("match_ids"))) > max_size:
                continue
            if size >= 2 and not _draft_group_is_compatible(draft, config):
                continue
            if size >= 3 and not _draft_allows_three_fragments(draft, config):
                continue
            drafts.append(draft)
    return drafts


def _route_draft_from_fragments(
    fragments: Iterable[Any],
    *,
    rescue_kind: str,
    phase_name: str | None = None,
) -> dict[str, Any]:
    fragment_list = list(fragments or [])
    if not fragment_list:
        return {}
    match_ids: list[str] = []
    levels: list[Any] = []
    cluster_ids: list[Any] = []
    cluster_statuses: list[Any] = []
    venues: list[str] = []
    starts: list[datetime] = []
    ends: list[datetime] = []
    classification = 0.0
    weighted = 0.0
    modalities: list[str] = []
    dates: list[str] = []
    fragment_ids: list[str] = []
    for fragment in fragment_list:
        ids = _fragment_match_ids(fragment)
        match_ids.extend(ids)
        fragment_ids.append(_fragment_id(fragment))
        levels.append(_get(fragment, "level_demand", "level", "categoria", "Categoria", default=None))
        cluster_ids.extend(_list_value(fragment, "cluster_ids", "clusters", "cluster_id", "cluster"))
        cluster_statuses.extend(_list_value(fragment, "cluster_statuses", "cluster_status"))
        venues.extend(str(value) for value in _list_value(fragment, "venues", "venue", "Pista joc") if value)
        start = _datetime_value(_get(fragment, "start_dt", "start_datetime", "start", "match_datetime", "__match_datetime"))
        end = _datetime_value(_get(fragment, "end_dt", "end_datetime", "end", "match_datetime", "__match_datetime")) or start
        if start:
            starts.append(start)
        if end:
            ends.append(end)
        classification = max(classification, _float_value(fragment, "classification_importance", default=0.0))
        weighted += _float_value(fragment, "weighted_coverage_value", default=float(len(ids)))
        modalities.append(_normalize_text(_get(fragment, "modality", "Modalitat", default="")))
        dates.append(_date_key(_get(fragment, "date", "Data", default=None) or start))

    match_ids = _dedupe(match_ids)
    if not match_ids:
        return {}
    return {
        "id": "+".join(fragment_ids) or "-".join(match_ids),
        "phase_name": str(phase_name or rescue_kind),
        "fragments": fragment_list,
        "match_ids": match_ids,
        "date": dates[0] if dates else "",
        "dates": _dedupe([value for value in dates if value]),
        "modality": modalities[0] if modalities else "",
        "modalities": _dedupe([value for value in modalities if value]),
        "start_dt": min(starts) if starts else None,
        "end_dt": max(ends) if ends else None,
        "level_demand": _hardest_level(levels),
        "cluster_ids": _dedupe(cluster_ids),
        "cluster_statuses": _dedupe(cluster_statuses),
        "venues": _dedupe(venues),
        "classification_importance": classification,
        "weighted_coverage_value": weighted or float(len(match_ids)),
    }


def _draft_group_is_compatible(draft: Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    if len(_normalize_ids(draft.get("dates"))) > 1:
        return False
    if len(_normalize_ids(draft.get("modalities"))) > 1:
        return False
    if len(_normalize_ids(draft.get("match_ids"))) != len(set(_normalize_ids(draft.get("match_ids")))):
        return False
    _warnings, blocked = _validate_gaps(_draft_fragments(draft), config)
    return not blocked


def _draft_allows_three_fragments(draft: Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    max_size = int(config.get("rescue_new_routes_max_size", 2) or 2)
    same_venue_max_size = int(config.get("rescue_new_routes_same_venue_max_size", max_size) or max_size)
    if max(max_size, same_venue_max_size) < 3:
        return False
    venues = set(_normalize_ids(draft.get("venues")))
    clusters = {_normalize_text(value) for value in _list_value(draft, "cluster_ids") if _normalize_text(value)}
    return bool(len(venues) == 1 or len(clusters) == 1)


def _generate_direct_candidates(
    drafts: list[dict[str, Any]],
    tutors: Iterable[Any],
    state: Any,
    config: Mapping[str, Any],
    *,
    rescue_kind: str,
    include_existing_route_conflicts: bool,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    allow_exceptional = bool(config.get("allow_exceptional_routes", False))
    candidates: list[dict[str, Any]] = []
    blocking_reason_counts: dict[str, int] = {}
    for tutor in tutors or []:
        tutor_id = _tutor_id(tutor)
        if not tutor_id:
            continue
        for draft in drafts:
            candidate, blocking_reasons = _score_direct_candidate(
                tutor,
                draft,
                state,
                config,
                rescue_kind=rescue_kind,
                include_existing_route_conflicts=include_existing_route_conflicts,
                allow_exceptional=allow_exceptional,
            )
            if blocking_reasons:
                for reason in sorted(set(blocking_reasons)):
                    blocking_reason_counts[reason] = blocking_reason_counts.get(reason, 0) + 1
                continue
            if candidate is not None:
                candidates.append(candidate)
    return candidates, blocking_reason_counts


def _score_direct_candidate(
    tutor: Any,
    draft: Mapping[str, Any],
    state: Any,
    config: Mapping[str, Any],
    *,
    rescue_kind: str,
    include_existing_route_conflicts: bool,
    allow_exceptional: bool,
) -> tuple[dict[str, Any] | None, list[str]]:
    tutor_id = _tutor_id(tutor)
    match_ids = _normalize_ids(draft.get("match_ids"))
    route_date = str(draft.get("date") or "")
    existing_route = _existing_route_state(state, tutor_id, route_date)
    existing_segments = _existing_segments(existing_route) if include_existing_route_conflicts else []
    draft_segments = _draft_fragments(draft)
    full_segments = sorted(existing_segments + draft_segments, key=lambda item: _segment_start(item) or datetime.min)
    full_match_ids = _dedupe(_existing_match_ids(existing_route) + list(match_ids))
    blocking: list[str] = []
    warnings: list[str] = []

    tutor_modality = _normalize_text(_get(tutor, "modality", "Modalitat", default=""))
    draft_modality = _normalize_text(draft.get("modality"))
    if tutor_modality and draft_modality and tutor_modality != draft_modality:
        blocking.append("modality_mismatch")

    if not _availability_covers(tutor, route_date, _route_start(draft_segments), _route_end(draft_segments), config):
        blocking.append("outside_availability_window")
    elif not _availability_respects_buffer(tutor, route_date, _route_start(draft_segments), _route_end(draft_segments), config):
        warnings.append("availability_end_buffer_warning")

    needs_vehicle = _route_requires_vehicle(full_segments)
    tutor_has_vehicle = _tutor_has_vehicle(tutor)
    if needs_vehicle and not tutor_has_vehicle:
        blocking.append("vehicle_required")
    elif needs_vehicle:
        warnings.append("cross_cluster_with_vehicle_warning")

    gap_warnings, gap_blocked = _validate_gaps(full_segments, config)
    warnings.extend(gap_warnings)
    if gap_blocked:
        blocking.append("gap_too_short")

    fit = _level_fit(
        _get(tutor, "level", "nivell", "Nivell", default=None),
        draft.get("level_demand"),
        {**dict(config), "classification_importance": draft.get("classification_importance", 0.0)},
    )
    if _is_level_forbidden(fit):
        blocking.append("level_forbidden")
    if _is_level_exceptional(fit) and not allow_exceptional:
        blocking.append("level_exceptional_not_allowed")
    if _is_level_unscorable(fit) and bool(config.get("block_unscorable_level", False)):
        blocking.append("level_unscorable")

    cluster_warnings = _cluster_warnings(draft.get("cluster_ids", []), draft.get("cluster_statuses", []))
    if cluster_warnings and not bool(config.get("allow_outlier_or_missing_cluster_routes", True)):
        blocking.extend(cluster_warnings)
    else:
        warnings.extend(cluster_warnings)

    blocking = _dedupe(blocking)
    if blocking:
        return None, blocking

    assigned_count = _assigned_count_for_tutor(state, tutor_id)
    existing_route_count = int(_get(existing_route, "route_count", default=1 if existing_segments else 0) or 0)
    weighted = float(draft.get("weighted_coverage_value") or len(match_ids))
    load_penalty = (
        assigned_count * float(config.get("load_penalty_per_assigned_match", 60.0))
        + existing_route_count * float(config.get("load_penalty_per_existing_route", 30.0))
    )
    underused_bonus = float(config.get("underused_tutor_bonus", 50.0)) if assigned_count == 0 else 0.0
    exceptional_penalty = float(config.get("exceptional_level_penalty", 3000.0)) if _is_level_exceptional(fit) else 0.0
    mobility_cost = (40.0 if needs_vehicle else 0.0) + 10.0 * len(set(warnings))
    level_cost = _level_distance_cost(
        _get(tutor, "level", "nivell", "Nivell", default=None),
        draft.get("level_demand"),
        float(config.get("level_distance_weight", 1000.0)),
    )
    coverage_reward = weighted * float(config.get("coverage_reward", 1000.0))
    cost = max(0.0, level_cost + exceptional_penalty + mobility_cost + load_penalty - underused_bonus - coverage_reward)
    phase_name = str(config.get("_rescue_phase_name") or draft.get("phase_name") or rescue_kind)
    candidate = {
        "id": f"{rescue_kind}:{tutor_id}:{draft.get('id') or '-'.join(match_ids)}",
        "phase_name": phase_name,
        "tutor_id": tutor_id,
        "new_match_ids": list(match_ids),
        "match_ids": list(match_ids),
        "full_route_match_ids": list(full_match_ids),
        "inserted_into_existing_route": bool(existing_segments),
        "date": route_date,
        "start_dt": _route_start(draft_segments),
        "end_dt": _route_end(draft_segments),
        "level_demand": draft.get("level_demand"),
        "level_fit": fit,
        "requires_vehicle": needs_vehicle,
        "cluster_ids": list(draft.get("cluster_ids") or []),
        "cluster_statuses": list(draft.get("cluster_statuses") or []),
        "venues": list(draft.get("venues") or []),
        "warning_codes": _dedupe(warnings),
        "blocking_reasons": [],
        "cost": float(cost),
        "score_breakdown": {
            "source": "direct_rescue",
            "weighted_coverage_value": weighted,
            "match_count": len(match_ids),
            "level_cost": float(level_cost),
            "level_fit": fit,
            "level_exceptional": _is_level_exceptional(fit),
            "exceptional_penalty": float(exceptional_penalty),
            "mobility_cost": float(mobility_cost),
            "load_penalty": float(load_penalty),
            "underused_bonus": float(underused_bonus),
            "assigned_match_count_for_tutor": assigned_count,
            "existing_route_count_for_tutor": existing_route_count,
            "requires_vehicle": needs_vehicle,
            "tutor_has_vehicle": tutor_has_vehicle,
        },
    }
    return _json_safe(candidate), []


def _prune_direct_candidates(
    candidates: list[dict[str, Any]],
    *,
    top_n_per_tutor: int,
    top_n_per_match: int,
) -> list[dict[str, Any]]:
    retained: dict[str, dict[str, Any]] = {}
    by_tutor_day: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_tutor_day.setdefault((str(candidate.get("tutor_id") or ""), str(candidate.get("date") or "")), []).append(candidate)
    for items in by_tutor_day.values():
        ranked = sorted(items, key=_direct_candidate_rank)
        for candidate in ranked[:top_n_per_tutor or len(ranked)]:
            retained[str(candidate.get("id"))] = candidate
    if top_n_per_match <= 0:
        return sorted(retained.values(), key=_direct_candidate_rank)

    final: dict[str, dict[str, Any]] = {}
    by_match: dict[str, list[dict[str, Any]]] = {}
    for candidate in retained.values():
        for match_id in _normalize_ids(candidate.get("new_match_ids") or candidate.get("match_ids")):
            by_match.setdefault(match_id, []).append(candidate)
    for items in by_match.values():
        for candidate in sorted(items, key=_direct_candidate_rank)[:top_n_per_match]:
            final[str(candidate.get("id"))] = candidate
    return sorted(final.values(), key=_direct_candidate_rank)


def _direct_candidate_rank(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    match_ids = _normalize_ids(candidate.get("new_match_ids") or candidate.get("match_ids"))
    warnings = _normalize_ids(candidate.get("warning_codes"))
    breakdown = candidate.get("score_breakdown") or {}
    return (
        -float(breakdown.get("weighted_coverage_value", len(match_ids)) or 0.0),
        _is_exceptional(candidate),
        len(warnings),
        float(candidate.get("cost") or 0.0),
        str(candidate.get("tutor_id") or ""),
        str(candidate.get("id") or ""),
    )


def _select_non_overlapping_routes(candidates: list[dict[str, Any]], *, prefer_coverage: bool = False) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used_matches: set[str] = set()
    used_tutor_days: set[tuple[str, str]] = set()
    if prefer_coverage:
        ranked = sorted(candidates, key=_direct_candidate_rank)
    else:
        ranked = sorted(
            candidates,
            key=lambda candidate: (
                float(candidate.get("cost") or 0.0),
                -len(_normalize_ids(candidate.get("new_match_ids") or candidate.get("match_ids"))),
                str(candidate.get("tutor_id") or ""),
                str(candidate.get("id") or ""),
            ),
        )
    for candidate in ranked:
        match_ids = set(_normalize_ids(candidate.get("new_match_ids") or candidate.get("match_ids")))
        tutor_day = (str(candidate.get("tutor_id") or ""), str(candidate.get("date") or ""))
        if not match_ids or match_ids & used_matches or tutor_day in used_tutor_days:
            continue
        selected.append(_json_safe(candidate))
        used_matches.update(match_ids)
        used_tutor_days.add(tutor_day)
    return selected


def _candidate_to_dict(candidate: Any, *, rescue_kind: str) -> dict[str, Any]:
    data = _object_to_dict(candidate)
    match_ids = _normalize_ids(data.get("new_match_ids") or data.get("match_ids"))
    data.setdefault("id", f"{rescue_kind}:{data.get('tutor_id', '')}:{'-'.join(match_ids)}")
    data.setdefault("phase_name", rescue_kind)
    data["new_match_ids"] = match_ids
    data.setdefault("match_ids", list(match_ids))
    data.setdefault("blocking_reasons", [])
    data.setdefault("warning_codes", [])
    data.setdefault("score_breakdown", {})
    data.setdefault("cost", 0.0)
    return _json_safe(data)


def _fragment_match_ids(fragment: Any) -> list[str]:
    return _normalize_ids(_get(fragment, "match_ids", "new_match_ids", "partit_ids", "match_id", "partit_id", default=[]))


def _fragment_id(fragment: Any) -> str:
    explicit_id = _get(fragment, "id", "fragment_id", default="")
    if explicit_id:
        return str(explicit_id)
    return "-".join(_fragment_match_ids(fragment)) or "fragment"


def _tutor_id(tutor: Any) -> str:
    return str(_get(tutor, "id", "tutor_id", "persona_id", "code", "codi", default="")).strip()


def _assigned_count_for_tutor(state: Any, tutor_id: str) -> int:
    assignments_by_tutor_day = _get(state, "assignments_by_tutor_day", default={}) or {}
    count = 0
    if isinstance(assignments_by_tutor_day, Mapping):
        iterable = assignments_by_tutor_day.items()
    else:
        iterable = []
    for key, route_state in iterable:
        key_tutor_id = key[0] if isinstance(key, tuple) and key else _get(route_state, "tutor_id", default="")
        if str(key_tutor_id) != str(tutor_id):
            continue
        assigned = _normalize_ids(_get(route_state, "assigned_match_ids", "match_ids", default=[]))
        count += len(assigned)
    return count


def _copy_assignments_by_tutor_day(state: Any) -> dict[Any, dict[str, Any]]:
    assignments = _get(state, "assignments_by_tutor_day", default={}) or {}
    if not isinstance(assignments, Mapping):
        return {}
    return {key: _object_to_dict(value) for key, value in assignments.items()}


def _state_overlay(state: Any, assignments_by_tutor_day: Mapping[Any, Any]) -> dict[str, Any]:
    return {
        "assigned_match_ids": _normalize_ids(_get(state, "assigned_match_ids", default=[])),
        "pending_match_ids": _normalize_ids(_get(state, "pending_match_ids", default=[])),
        "assignments_by_tutor_day": dict(assignments_by_tutor_day),
    }


def _overlay_selected_routes(assignments_by_tutor_day: dict[Any, dict[str, Any]], selected_routes: list[dict[str, Any]]) -> None:
    for route in selected_routes:
        tutor_id = str(route.get("tutor_id") or "")
        route_date = str(route.get("date") or "")
        key = (tutor_id, route_date)
        current = assignments_by_tutor_day.setdefault(
            key,
            {
                "tutor_id": tutor_id,
                "date": route_date,
                "assigned_match_ids": [],
                "assigned_segments": [],
                "route_count": 0,
            },
        )
        match_ids = _dedupe(_normalize_ids(current.get("assigned_match_ids")) + _normalize_ids(route.get("new_match_ids")))
        current["assigned_match_ids"] = match_ids
        current["match_ids"] = match_ids
        current.setdefault("assigned_segments", [])
        current["assigned_segments"].append(route)
        current["route_count"] = int(current.get("route_count") or 0) + 1


def _individual_iteration_tutors(tutors: list[Any], state: Any, iteration: int, include_assigned_after_iteration: int) -> list[Any]:
    if iteration > include_assigned_after_iteration:
        return tutors
    unused = [tutor for tutor in tutors if _assigned_count_for_tutor(state, _tutor_id(tutor)) == 0]
    return unused or tutors


def _existing_route_state(state: Any, tutor_id: str, date_key: str) -> Any:
    assignments = _get(state, "assignments_by_tutor_day", default={}) or {}
    if not isinstance(assignments, Mapping):
        return None
    return (
        assignments.get((tutor_id, date_key))
        or assignments.get((tutor_id, str(date_key)))
        or assignments.get(f"{tutor_id}:{date_key}")
        or assignments.get(f"{tutor_id}|{date_key}")
    )


def _existing_segments(route_state: Any) -> list[Any]:
    if route_state is None:
        return []
    for name in ("descriptors", "assigned_segments", "segments", "routes"):
        values = _list_value(route_state, name)
        if values:
            return values
    return []


def _existing_match_ids(route_state: Any) -> list[str]:
    ids = _normalize_ids(_get(route_state, "assigned_match_ids", "match_ids", default=[]))
    if ids:
        return ids
    out: list[str] = []
    for segment in _existing_segments(route_state):
        out.extend(_fragment_match_ids(segment))
        identifier = _get(segment, "identifier", "id", "match_id", default=None)
        if identifier is not None:
            out.append(str(identifier))
    return _dedupe(out)


def _draft_fragments(draft: Mapping[str, Any]) -> list[Any]:
    fragments = draft.get("fragments")
    if fragments:
        try:
            return list(fragments)
        except TypeError:
            return [fragments]
    return [draft]


def _route_start(segments: list[Any]) -> datetime | None:
    starts = [_segment_start(segment) for segment in segments if _segment_start(segment) is not None]
    return min(starts) if starts else None


def _route_end(segments: list[Any]) -> datetime | None:
    ends = [_segment_end(segment) for segment in segments if _segment_end(segment) is not None]
    return max(ends) if ends else None


def _segment_start(segment: Any) -> datetime | None:
    return _datetime_value(_get(segment, "start_dt", "start_datetime", "start", "match_datetime", "__match_datetime", default=None))


def _segment_end(segment: Any) -> datetime | None:
    return _datetime_value(_get(segment, "end_dt", "end_datetime", "end", "match_datetime", "__match_datetime", default=None)) or _segment_start(segment)


def _segment_clusters(segment: Any) -> list[Any]:
    return _list_value(segment, "cluster_ids", "clusters", "cluster_id", "cluster")


def _segment_venues(segment: Any) -> list[str]:
    return [str(value) for value in _list_value(segment, "venues", "venue", "Pista joc") if value]


def _combined_cluster_ids(segments: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    for segment in segments:
        out.extend(_segment_clusters(segment))
    return out


def _clusters_need_vehicle(cluster_ids: Iterable[Any]) -> bool:
    cleaned = {_normalize_text(cluster) for cluster in cluster_ids if _normalize_text(cluster)}
    return len(cleaned) > 1


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


def _has_uncertain_cluster(segments: Iterable[Any]) -> bool:
    statuses = {
        _normalize_text(status)
        for segment in segments
        for status in _list_value(segment, "cluster_statuses", "cluster_status")
        if _normalize_text(status)
    }
    if statuses & {"outlier", "missing_geocode", "pending", "not_found"}:
        return True
    return any(
        not _normalize_text(cluster)
        for segment in segments
        for cluster in _segment_clusters(segment)
    )


def _segments_same_location(segments: Iterable[Any]) -> bool:
    segment_list = list(segments)
    venues = {
        _normalize_text(venue)
        for segment in segment_list
        for venue in _segment_venues(segment)
        if _normalize_text(venue)
    }
    if len(venues) == 1:
        return True
    if len(venues) > 1:
        return False
    return _segment_match_count(segment_list) <= 1


def _segment_match_count(segments: Iterable[Any]) -> int:
    count = 0
    for segment in segments:
        ids = _normalize_ids(_get(segment, "match_ids", "new_match_ids", default=[]))
        count += len(ids) if ids else 1
    return count


def _cluster_warnings(cluster_ids: Iterable[Any], statuses: Iterable[Any]) -> list[str]:
    normalized_statuses = {_normalize_text(status) for status in statuses if _normalize_text(status)}
    warnings: list[str] = []
    if "outlier" in normalized_statuses:
        warnings.append("outlier_mobility_warning")
    if any(not _normalize_text(cluster) for cluster in cluster_ids) or normalized_statuses & {"missing_geocode", "pending", "not_found"}:
        warnings.append("missing_cluster_mobility_warning")
    return warnings


def _tutor_has_vehicle(tutor: Any) -> bool:
    explicit = _get(tutor, "has_vehicle", default=None)
    if explicit is not None:
        return bool(explicit)
    transport = _get(tutor, "transport", "Mitja de Transport", "Mitja de transport", default="")
    try:
        from designacions.services.assignment_feasibility import has_vehicle

        return bool(has_vehicle(transport))
    except Exception:
        normalized = _normalize_text(transport)
        return any(token in normalized for token in ("cotxe", "car", "vehicle", "moto"))


def _validate_gaps(segments: list[Any], config: Mapping[str, Any]) -> tuple[list[str], bool]:
    ordered = sorted(segments, key=lambda item: _segment_start(item) or datetime.min)
    return validate_atomic_gaps(ordered, {**dict(config), "has_vehicle": True})


def _required_gap(left: Any, right: Any, config: Mapping[str, Any]) -> int:
    left_points = route_points_from_segments([left])
    right_points = route_points_from_segments([right])
    if left_points and right_points:
        return atomic_required_gap(left_points[-1], right_points[0], config)
    return int(config.get("gap_diff_cluster_min", 150))


def _availability_covers(tutor: Any, route_date: str, start_dt: datetime | None, end_dt: datetime | None, config: Mapping[str, Any]) -> bool:
    return _availability_window_check(tutor, route_date, start_dt, end_dt, config, use_buffer=False)


def _availability_respects_buffer(tutor: Any, route_date: str, start_dt: datetime | None, end_dt: datetime | None, config: Mapping[str, Any]) -> bool:
    return _availability_window_check(tutor, route_date, start_dt, end_dt, config, use_buffer=True)


def _availability_window_check(
    tutor: Any,
    route_date: str,
    start_dt: datetime | None,
    end_dt: datetime | None,
    config: Mapping[str, Any],
    *,
    use_buffer: bool,
) -> bool:
    availability = _get(tutor, "availability_by_date", default=None)
    if not availability:
        return bool(config.get("assume_available_when_missing", True))
    if start_dt is None or end_dt is None:
        return bool(config.get("assume_available_when_time_missing", True))
    raw = None
    if isinstance(availability, Mapping):
        raw = availability.get(route_date) or availability.get(start_dt.date()) or availability.get(start_dt.date().isoformat())
    if raw is None:
        return False
    windows = raw if isinstance(raw, list) else [raw]
    for window in windows:
        if isinstance(window, Mapping):
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


def _window_covers(start_dt: datetime, end_dt: datetime, start: time, end: time, config: Mapping[str, Any], *, use_buffer: bool = False) -> bool:
    buffer_min = int(config.get("availability_end_buffer_min", 60) or 0) if use_buffer else 0
    window_start = datetime.combine(start_dt.date(), start)
    window_end = datetime.combine(start_dt.date(), end) - timedelta(minutes=buffer_min)
    return window_start <= start_dt and end_dt <= window_end


def _hardest_level(levels: Iterable[Any]) -> Any:
    try:
        from .levels import hardest_match_level

        return hardest_match_level(list(levels))
    except Exception:
        cleaned = [level for level in levels if level not in (None, "")]
        return cleaned[-1] if cleaned else None


def _level_fit(tutor_level: Any, level_demand: Any, config: Mapping[str, Any]) -> str:
    try:
        from .levels import level_fit

        return str(level_fit(tutor_level, level_demand, dict(config)))
    except Exception:
        return "unknown"


def _level_distance_cost(tutor_level: Any, level_demand: Any, weight: float) -> float:
    try:
        from .levels import level_distance_cost

        return float(level_distance_cost(tutor_level, level_demand, weight))
    except Exception:
        return 0.0


def _is_level_forbidden(value: Any) -> bool:
    return "forbidden" in str(value or "").lower()


def _is_level_exceptional(value: Any) -> bool:
    return "exceptional" in str(value or "").lower()


def _is_level_unscorable(value: Any) -> bool:
    return "unscorable" in str(value or "").lower()


def _has_forbidden_level(candidate: Mapping[str, Any]) -> bool:
    values = _normalize_ids(
        [
            candidate.get("level_fit"),
            candidate.get("level_fit_label"),
            *(candidate.get("warning_codes") or []),
            *(candidate.get("blocking_reasons") or []),
        ]
    )
    return any("forbidden" in value.lower() or "level_forbidden" in value.lower() for value in values)


def _is_exceptional(candidate: Mapping[str, Any]) -> bool:
    values = _normalize_ids(
        [
            candidate.get("level_fit"),
            candidate.get("level_fit_label"),
            *(candidate.get("warning_codes") or []),
            *(candidate.get("blocking_reasons") or []),
        ]
    )
    return any("exceptional" in value.lower() for value in values)


def _get(source: Any, *keys: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, Mapping):
        for key in keys:
            if key in source:
                return source[key]
        return default
    get_method = getattr(source, "get", None)
    if callable(get_method):
        for key in keys:
            try:
                value = get_method(key)
            except Exception:
                continue
            if value is not None:
                return value
    for key in keys:
        if hasattr(source, key):
            return getattr(source, key)
    return default


def _list_value(source: Any, *keys: str) -> list[Any]:
    value = _get(source, *keys, default=[])
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _normalize_ids(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [part.strip() for part in values.replace(";", ",").replace("|", ",").split(",") if part.strip()]
    try:
        return [str(value).strip() for value in values if str(value).strip()]
    except TypeError:
        value = str(values).strip()
        return [value] if value else []


def _normalize_text(value: Any) -> str:
    try:
        from designacions.services.assignment_feasibility import normalize_text_key

        return str(normalize_text_key(value))
    except Exception:
        return str(value or "").strip().lower()


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


def _float_value(source: Any, *keys: str, default: float = 0.0) -> float:
    value = _get(source, *keys, default=default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dedupe(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[Any] = set()
    for value in values:
        marker = value
        try:
            already_seen = marker in seen
        except TypeError:
            marker = str(value)
            already_seen = marker in seen
        if already_seen:
            continue
        out.append(value)
        seen.add(marker)
    return out


def _object_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return dict(value.to_dict())
    if not hasattr(value, "__dict__"):
        return {"value": value}
    return {
        key: item
        for key, item in vars(value).items()
        if not key.startswith("_")
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return value.isoformat()
    return value
