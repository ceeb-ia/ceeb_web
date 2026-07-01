"""Materialize selected number patterns into real group assignments."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any, Iterable

from calendaritzacions.engine.variants.resource_solver.model import build_solver_model, solve_model
from calendaritzacions.engine.variants.resource_solver.solution import build_solution
from calendaritzacions.engine.variants.resource_solver.pattern_master.types import HubPattern, MasterSelection
from calendaritzacions.engine.variants.resource_solver.types import Candidate, ResourceSolverResult, SolverContext


def selected_number_by_team(patterns: Iterable[HubPattern]) -> dict[str, int]:
    numbers: dict[str, int] = {}
    for pattern in patterns:
        for assignment in pattern.assignments:
            numbers[assignment.team_id] = int(assignment.number)
    return dict(sorted(numbers.items()))


def context_restricted_to_pattern_numbers(
    context: SolverContext,
    patterns: Iterable[HubPattern],
) -> SolverContext:
    numbers = selected_number_by_team(patterns)
    candidates = tuple(
        candidate
        for candidate in context.candidates
        if int(candidate.number) == int(numbers.get(candidate.team_id, -1))
    )
    return replace(context, candidates=candidates)


def materialize_patterns(
    context: SolverContext,
    selected_patterns: Iterable[HubPattern],
) -> tuple[ResourceSolverResult, Any, Any]:
    """Run the existing CP-SAT model over candidates restricted by selected numbers."""

    restricted = context_restricted_to_pattern_numbers(context, selected_patterns)
    missing = _teams_without_candidates(restricted)
    if missing:
        raw = _raw_result(
            "INFEASIBLE",
            (),
            logs=(f"pattern materialization missing candidates for teams: {', '.join(missing[:20])}",),
        )
        return build_solution(raw, restricted), raw, None
    built_model = build_solver_model(restricted)
    raw_result = solve_model(built_model, restricted.config)
    return build_solution(raw_result, restricted), raw_result, built_model


def materialize_master_selection(
    context: SolverContext,
    selected_patterns: Iterable[HubPattern],
    selection: MasterSelection,
) -> tuple[ResourceSolverResult, Any, Any]:
    """Use the group assignments selected inside the master CP-SAT model."""

    selected_patterns = tuple(selected_patterns)
    if (
        not selected_patterns
        and not selection.materialized_assignments
        and selection.status not in {"OPTIMAL", "FEASIBLE"}
    ):
        raw = _raw_result(
            selection.status,
            (),
            logs=("pattern master materialization skipped: no selected patterns",),
        )
        return build_solution(raw, context), raw, None
    if not selection.materialized_assignments:
        return materialize_patterns(context, selected_patterns)
    raw = _raw_result(
        selection.status,
        selection.materialized_assignments,
        objective_value=selection.objective_value,
        best_bound=selection.objective_value,
        logs=("pattern master materialization reused",),
    )
    return build_solution(raw, context), raw, None


def materialization_payload(
    context: SolverContext,
    selected_patterns: Iterable[HubPattern],
    result: ResourceSolverResult,
) -> dict[str, Any]:
    selected_numbers = selected_number_by_team(selected_patterns)
    assigned_numbers = {assignment.team_id: int(assignment.number) for assignment in result.assignments}
    changed = {
        team_id: {"pattern_number": number, "assigned_number": assigned_numbers.get(team_id)}
        for team_id, number in selected_numbers.items()
        if assigned_numbers.get(team_id) != number
    }
    return {
        "artifact_type": "resource_solver_pattern_master_materialization",
        "status": result.status,
        "team_count": len(context.teams),
        "selected_number_count": len(selected_numbers),
        "assignment_count": len(result.assignments),
        "candidate_count_after_filter": len(context_restricted_to_pattern_numbers(context, selected_patterns).candidates),
        "number_changes": changed,
        "resource_excess": sum(int(usage.excess) for usage in result.resource_usage),
        "entity_excess": {f"{entity}|{group_id}": value for (entity, group_id), value in result.entity_excess.items()},
    }


def selected_patterns_from_ids(patterns: Iterable[HubPattern], pattern_ids: Iterable[str]) -> tuple[HubPattern, ...]:
    wanted = {str(pattern_id) for pattern_id in pattern_ids}
    by_id = {pattern.pattern_id: pattern for pattern in patterns}
    return tuple(by_id[pattern_id] for pattern_id in sorted(wanted) if pattern_id in by_id)


def _teams_without_candidates(context: SolverContext) -> list[str]:
    candidate_counts = defaultdict(int)
    for candidate in context.candidates:
        candidate_counts[candidate.team_id] += 1
    return sorted(team.team_id for team in context.teams if candidate_counts[team.team_id] <= 0)


def _raw_result(
    status: str,
    assignments: tuple[Any, ...],
    logs: tuple[str, ...] = (),
    objective_value: float | None = None,
    best_bound: float | None = None,
):
    class Raw:
        pass

    raw = Raw()
    raw.status = status
    raw.objective_value = objective_value
    raw.best_bound = best_bound
    raw.wall_time = 0.0
    raw.assignments = assignments
    raw.entity_excess = None
    raw.resource_excess = {}
    raw.logs = logs
    return raw


__all__ = [
    "context_restricted_to_pattern_numbers",
    "materialize_master_selection",
    "materialization_payload",
    "materialize_patterns",
    "selected_number_by_team",
    "selected_patterns_from_ids",
]
