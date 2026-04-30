from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Iterable, Mapping

from .diagnostics import build_engine_summary, build_load_distribution_summary, build_phase_summary
from .level_fragments import LevelFragment, build_level_fragments
from .phase_solver import solve_phase_routes
from .phases import PhaseSpec, default_phase_specs, phase_allows_fragment, phase_allows_tutor
from .recommendations import build_swap_recommendations
from .rescue import run_final_rescue, run_individual_rescue, run_new_route_rescue, run_partial_rescue
from .route_generation import RouteCandidate, generate_phase_route_candidates
from .state import DesignationState, apply_route_assignment, create_initial_state


@dataclass
class PhasedRouteSolverResult:
    selected_routes: list[Any]
    unassigned_match_ids: list[str]
    state: DesignationState
    fragments: list[LevelFragment]
    phase_summaries: list[dict[str, Any]]
    final_rescue_summary: dict[str, Any]
    swap_recommendations: list[Any]
    engine_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_routes": [_json_safe(_object_to_dict(route)) for route in self.selected_routes],
            "unassigned_match_ids": list(self.unassigned_match_ids),
            "fragments": [_json_safe(fragment.to_dict()) for fragment in self.fragments],
            "phase_summaries": list(self.phase_summaries),
            "final_rescue_summary": dict(self.final_rescue_summary),
            "swap_recommendations": [_json_safe(_object_to_dict(item)) for item in self.swap_recommendations],
            "engine_summary": dict(self.engine_summary),
        }


def run_phased_route_solver(
    base_subgroups: Iterable[Any],
    tutors: Iterable[Any],
    config: Mapping[str, Any] | None = None,
) -> PhasedRouteSolverResult:
    config = dict(config or {})
    fragments = build_level_fragments(base_subgroups, config)
    tutor_list = list(tutors or [])
    all_match_ids = [match_id for fragment in fragments for match_id in _match_ids(fragment)]
    state = create_initial_state(all_match_ids)
    selected_routes: list[Any] = []
    phase_summaries: list[dict[str, Any]] = []

    for phase in default_phase_specs(config):
        pending_fragments = _pending_phase_fragments(fragments, state, phase)
        eligible_tutors = [tutor for tutor in tutor_list if phase_allows_tutor(tutor, phase)]
        route_candidates = generate_phase_route_candidates(pending_fragments, eligible_tutors, state, phase, config)
        phase_result = solve_phase_routes(route_candidates, config)

        for route in phase_result.selected_routes:
            _apply_selected_route(state, route, stage=f"phase:{phase.name}")
            selected_routes.append(route)

        pending_after = _pending_match_ids(fragments, state)
        phase_summaries.append(
            build_phase_summary(
                phase.name,
                eligible_tutors=eligible_tutors,
                pending_fragments_before=pending_fragments,
                route_candidates=route_candidates,
                selected_routes=phase_result.selected_routes,
                pending_match_ids_after=pending_after,
            )
        )

        if phase.rescue_after_phase and pending_fragments:
            rescue_phase_name = f"partial_rescue:{phase.name}"
            rescue_payload = run_partial_rescue(
                _pending_phase_fragments(fragments, state, phase),
                eligible_tutors,
                state,
                {
                    **config,
                    "allow_exceptional_routes": phase.allow_exceptional,
                    "_rescue_phase_name": rescue_phase_name,
                    "_rescue_max_matches_per_route": phase.max_route_size,
                },
            )
            rescued_routes = list(rescue_payload.get("selected_routes") or [])
            for route in rescued_routes:
                _apply_selected_route(state, route, stage=rescue_phase_name)
                selected_routes.append(route)
            phase_summaries.append(
                {
                    "phase_name": rescue_phase_name,
                    **dict(rescue_payload.get("summary") or {}),
                }
            )

    final_rescue_payload = run_final_rescue(_pending_fragments(fragments, state), tutor_list, state, config)
    base_final_rescue_summary = dict(final_rescue_payload.get("summary") or {})
    for route in final_rescue_payload.get("selected_routes") or []:
        _apply_selected_route(state, route, stage="final_rescue")
        selected_routes.append(route)

    new_route_rescue_payload = run_new_route_rescue(_pending_fragments(fragments, state), tutor_list, state, config)
    new_route_rescue_summary = dict(new_route_rescue_payload.get("summary") or {})
    for route in new_route_rescue_payload.get("selected_routes") or []:
        _apply_selected_route(state, route, stage="new_route_rescue")
        selected_routes.append(route)
    if new_route_rescue_summary:
        phase_summaries.append({"phase_name": "new_route_rescue", **new_route_rescue_summary})

    individual_rescue_payload = run_individual_rescue(_pending_fragments(fragments, state), tutor_list, state, config)
    individual_rescue_summary = dict(individual_rescue_payload.get("summary") or {})
    for route in individual_rescue_payload.get("selected_routes") or []:
        _apply_selected_route(state, route, stage=_value(route, "phase_name", default="individual_rescue"))
        selected_routes.append(route)
    if individual_rescue_summary:
        phase_summaries.append({"phase_name": "individual_rescue", **individual_rescue_summary})

    final_rescue_summary = {
        "existing_final_rescue": base_final_rescue_summary,
        "new_route_rescue": new_route_rescue_summary,
        "individual_rescue": individual_rescue_summary,
        "recovered_match_count": int(base_final_rescue_summary.get("recovered_match_count", 0) or 0)
        + int(new_route_rescue_summary.get("recovered_match_count", 0) or 0)
        + int(individual_rescue_summary.get("recovered_match_count", 0) or 0),
        "selected_route_count": int(base_final_rescue_summary.get("selected_route_count", 0) or 0)
        + int(new_route_rescue_summary.get("selected_route_count", 0) or 0)
        + int(individual_rescue_summary.get("selected_route_count", 0) or 0),
    }

    unassigned_fragments = _pending_fragments(fragments, state)
    swap_recommendations = build_swap_recommendations(unassigned_fragments, tutor_list, state, config)
    unassigned_match_ids = _pending_match_ids(fragments, state)
    engine_summary = build_engine_summary(
        engine_name="phased_route_solver",
        phases=phase_summaries,
        selected_routes=selected_routes,
        all_fragments=fragments,
        unassigned_fragments=unassigned_fragments,
        rescue_summary=final_rescue_summary,
        swap_recommendations=swap_recommendations,
    )
    engine_summary["load_distribution_summary"] = build_load_distribution_summary(tutor_list, selected_routes)

    return PhasedRouteSolverResult(
        selected_routes=selected_routes,
        unassigned_match_ids=unassigned_match_ids,
        state=state,
        fragments=fragments,
        phase_summaries=phase_summaries,
        final_rescue_summary=final_rescue_summary,
        swap_recommendations=swap_recommendations,
        engine_summary=engine_summary,
    )


def _pending_phase_fragments(fragments: Iterable[Any], state: DesignationState, phase: PhaseSpec) -> list[Any]:
    return [
        fragment
        for fragment in _pending_fragments(fragments, state)
        if phase_allows_fragment(fragment, phase)
    ]


def _pending_fragments(fragments: Iterable[Any], state: DesignationState) -> list[Any]:
    assigned = set(state.assigned_match_ids)
    return [
        fragment
        for fragment in fragments
        if _match_ids(fragment) and not (set(_match_ids(fragment)) & assigned)
    ]


def _pending_match_ids(fragments: Iterable[Any], state: DesignationState) -> list[str]:
    assigned = set(state.assigned_match_ids)
    out: list[str] = []
    seen: set[str] = set()
    for fragment in fragments:
        for match_id in _match_ids(fragment):
            if match_id not in assigned and match_id not in seen:
                out.append(match_id)
                seen.add(match_id)
    return out


def _apply_selected_route(state: DesignationState, route: Any, *, stage: str) -> None:
    match_ids = _route_new_match_ids(route)
    if not match_ids:
        return
    route_match_ids = _route_match_ids(route, default=match_ids)
    route_id = _value(route, "route_id", "id", default="")
    apply_route_assignment(
        state,
        _value(route, "tutor_id", default=""),
        _value(route, "date", default=""),
        match_ids,
        segment_rows=[route],
        descriptors=[route],
        stage=stage,
        route_id=route_id,
        candidate_id=_value(route, "candidate_id", "id", default=route_id),
        phase_name=_value(route, "phase_name", default=_phase_name_from_stage(stage)),
        route_match_ids=route_match_ids,
        new_match_ids=match_ids,
        inserted_into_existing_route=bool(_value(route, "inserted_into_existing_route", default=False)),
        warning_codes=_normalize_ids(_value(route, "warning_codes", default=[])),
        selected_cost=_value(route, "selected_cost", "cost", default=None),
        level_fit=_value(route, "level_fit", "level_fit_label", default=None),
        score_breakdown=_mapping_value(_value(route, "score_breakdown", default={})),
        route_size=_value(route, "route_size", default=len(route_match_ids)),
    )


def _route_new_match_ids(route: Any) -> list[str]:
    return _normalize_ids(_value(route, "new_match_ids", "match_ids", default=[]))


def _route_match_ids(route: Any, *, default: Iterable[Any] | None = None) -> list[str]:
    return _normalize_ids(
        _value(
            route,
            "route_match_ids",
            "full_route_match_ids",
            "match_ids",
            "new_match_ids",
            default=list(default or []),
        )
    )


def _phase_name_from_stage(stage: str) -> str:
    if ":" in stage:
        return stage.split(":", 1)[1]
    return stage


def _match_ids(fragment: Any) -> list[str]:
    return _normalize_ids(_value(fragment, "match_ids", "new_match_ids", default=[]))


def _value(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(obj, Mapping) and name in obj:
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


def _mapping_value(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _object_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return dict(value.to_dict())
    if not hasattr(value, "__dict__"):
        return {"value": value}
    return {key: item for key, item in vars(value).items() if not key.startswith("_")}


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


__all__ = ["PhasedRouteSolverResult", "run_phased_route_solver"]
