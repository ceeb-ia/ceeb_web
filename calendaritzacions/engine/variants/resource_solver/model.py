"""CP-SAT model and deterministic fallback for the resource solver."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import product
from time import perf_counter
from typing import Any

from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.constraints import DEFAULT_CONSTRAINT_BUILDERS
from calendaritzacions.engine.variants.resource_solver.constraints.base import (
    ConstraintAudit,
    ModelVariables,
    ObjectiveTerm,
)
from calendaritzacions.engine.variants.resource_solver.constraints.resource_capacity import (
    candidate_resource_by_round,
    capacity_for_resource,
)
from calendaritzacions.engine.variants.resource_solver.objective import (
    build_objective_expression,
    objective_summary,
    objective_weights,
)
from calendaritzacions.engine.variants.resource_solver.types import Assignment, Candidate, SolverContext


@dataclass
class BuiltModel:
    context: SolverContext
    backend: str
    model: Any | None
    variables: ModelVariables
    objective_terms: list[ObjectiveTerm]
    audit: ConstraintAudit
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawSolverResult:
    status: str
    objective_value: float | None
    best_bound: float | None
    wall_time: float
    assignments: tuple[Assignment, ...]
    variable_values: dict[str, int]
    entity_excess: dict[tuple[str, str], int]
    resource_excess: dict[tuple[str, int], int]
    logs: tuple[str, ...] = ()


def _load_cp_model() -> Any | None:
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return None
    return cp_model


def build_solver_model(context: SolverContext, use_ortools: bool | None = None) -> BuiltModel:
    """Build the resource solver model using CP-SAT when available."""

    cp_model = _load_cp_model() if use_ortools is not False else None
    if cp_model is None:
        return _build_fallback_model(context)
    return _build_cp_sat_model(context, cp_model)


def solve_model(built_model: BuiltModel, config: ResourceSolverConfig | None = None) -> RawSolverResult:
    """Solve a previously built model."""

    if built_model.backend == "cp_sat":
        return _solve_cp_sat_model(built_model, config or built_model.context.config)
    return _solve_fallback_model(built_model)


def solve_context(context: SolverContext, use_ortools: bool | None = None) -> RawSolverResult:
    """Convenience helper for tests and early integration."""

    built_model = build_solver_model(context, use_ortools=use_ortools)
    return solve_model(built_model, context.config)


def _index_candidates(candidates: tuple[Candidate, ...]) -> ModelVariables:
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    by_team: dict[str, list[Candidate]] = defaultdict(list)
    by_group_number: dict[tuple[str, int], list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        by_team[candidate.team_id].append(candidate)
        by_group_number[(candidate.group_id, candidate.number)].append(candidate)
    return ModelVariables(
        x={},
        candidate_by_id=by_id,
        candidates_by_team=dict(by_team),
        candidates_by_group_number=dict(by_group_number),
    )


def _build_cp_sat_model(context: SolverContext, cp_model: Any) -> BuiltModel:
    model = cp_model.CpModel()
    variables = _index_candidates(context.candidates)
    for candidate in context.candidates:
        variables.x[candidate.candidate_id] = model.NewBoolVar(f"x_{candidate.candidate_id}")
    for group in context.groups:
        for number in group.numbers:
            variables.occupied[(group.group_id, number)] = model.NewBoolVar(
                f"occupied_{group.group_id}_{number}"
            )

    objective_terms: list[ObjectiveTerm] = []
    audit = ConstraintAudit()
    for builder in DEFAULT_CONSTRAINT_BUILDERS:
        builder.add(model, variables, context, objective_terms, audit)

    model.Minimize(build_objective_expression(objective_terms))
    summary = _model_summary(context, variables, objective_terms, audit, "cp_sat")
    return BuiltModel(
        context=context,
        backend="cp_sat",
        model=model,
        variables=variables,
        objective_terms=objective_terms,
        audit=audit,
        summary=summary,
    )


def _build_fallback_model(context: SolverContext) -> BuiltModel:
    variables = _index_candidates(context.candidates)
    audit = ConstraintAudit()
    summary = _model_summary(context, variables, [], audit, "fallback")
    return BuiltModel(
        context=context,
        backend="fallback",
        model=None,
        variables=variables,
        objective_terms=[],
        audit=audit,
        summary=summary,
    )


def _model_summary(
    context: SolverContext,
    variables: ModelVariables,
    objective_terms: list[ObjectiveTerm],
    audit: ConstraintAudit,
    backend: str,
) -> dict[str, Any]:
    return {
        "backend": backend,
        "num_teams": len(context.teams),
        "num_groups": len(context.groups),
        "num_candidates": len(context.candidates),
        "num_variables": len(variables.x)
        + len(variables.occupied)
        + len(variables.real_home)
        + len(variables.entity_excess)
        + len(variables.resource_excess),
        "constraints": dict(audit.constraints),
        "objective_terms": objective_summary(objective_terms),
        "weights": objective_weights(objective_terms),
        "time_limit_seconds": getattr(context.config, "time_limit_seconds", None),
    }


def _solve_cp_sat_model(
    built_model: BuiltModel,
    config: ResourceSolverConfig,
) -> RawSolverResult:
    cp_model = _load_cp_model()
    if cp_model is None:
        return _solve_fallback_model(built_model)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(getattr(config, "time_limit_seconds", 30.0))
    started = perf_counter()
    status_code = solver.Solve(built_model.model)
    wall_time = perf_counter() - started
    status = _cp_status_name(cp_model, status_code)

    if status not in {"OPTIMAL", "FEASIBLE"}:
        return RawSolverResult(
            status=status,
            objective_value=None,
            best_bound=None,
            wall_time=wall_time,
            assignments=(),
            variable_values={},
            entity_excess={},
            resource_excess={},
        )

    assignments = []
    variable_values: dict[str, int] = {}
    for candidate_id, var in built_model.variables.x.items():
        value = int(solver.Value(var))
        variable_values[candidate_id] = value
        if value == 1:
            candidate = built_model.variables.candidate_by_id[candidate_id]
            assignments.append(
                Assignment(candidate.team_id, candidate.group_id, candidate.number)
            )

    entity_excess = {
        key: int(solver.Value(var)) for key, var in built_model.variables.entity_excess.items()
    }
    resource_excess = {
        key: int(solver.Value(var)) for key, var in built_model.variables.resource_excess.items()
    }

    return RawSolverResult(
        status=status,
        objective_value=float(solver.ObjectiveValue()),
        best_bound=float(solver.BestObjectiveBound()),
        wall_time=wall_time,
        assignments=tuple(sorted(assignments, key=lambda item: item.team_id)),
        variable_values=variable_values,
        entity_excess=entity_excess,
        resource_excess=resource_excess,
    )


def _cp_status_name(cp_model: Any, status_code: int) -> str:
    if status_code == cp_model.OPTIMAL:
        return "OPTIMAL"
    if status_code == cp_model.FEASIBLE:
        return "FEASIBLE"
    if status_code == cp_model.INFEASIBLE:
        return "INFEASIBLE"
    return "UNKNOWN"


def _solve_fallback_model(built_model: BuiltModel) -> RawSolverResult:
    """Exhaustively solve small contexts without OR-Tools."""

    context = built_model.context
    started = perf_counter()
    choices = [
        sorted(
            built_model.variables.candidates_by_team.get(team.team_id, []),
            key=lambda candidate: (candidate.group_id, candidate.number, candidate.candidate_id),
        )
        for team in sorted(context.teams, key=lambda item: item.team_id)
    ]
    if any(not team_choices for team_choices in choices):
        return _fallback_result("INFEASIBLE", started)

    search_space = 1
    for team_choices in choices:
        search_space *= len(team_choices)
    if search_space > 200_000:
        greedy = _construct_greedy_assignment(context, built_model.variables)
        if greedy is None:
            return _fallback_result(
                "UNKNOWN",
                started,
                logs=(f"fallback search space too large: {search_space}",),
            )
        evaluation = _evaluate_assignment_combo(context, greedy)
        if evaluation is None:
            return _fallback_result(
                "UNKNOWN",
                started,
                logs=(f"fallback search space too large: {search_space}",),
            )
        objective_value, entity_excess, resource_excess = evaluation
        status = "OPTIMAL" if objective_value == 0 else "FEASIBLE"
        assignments = tuple(
            sorted(
                (Assignment(c.team_id, c.group_id, c.number) for c in greedy),
                key=lambda item: item.team_id,
            )
        )
        variable_values = {candidate.candidate_id: 0 for candidate in context.candidates}
        for candidate in greedy:
            variable_values[candidate.candidate_id] = 1
        return RawSolverResult(
            status=status,
            objective_value=float(objective_value),
            best_bound=0.0 if status == "OPTIMAL" else None,
            wall_time=perf_counter() - started,
            assignments=assignments,
            variable_values=variable_values,
            entity_excess=entity_excess,
            resource_excess=resource_excess,
            logs=(f"deterministic greedy fallback used; search space {search_space}",),
        )

    best: tuple[int, tuple[Candidate, ...], dict[tuple[str, str], int], dict[tuple[str, int], int]] | None = None
    for combo in product(*choices):
        evaluation = _evaluate_assignment_combo(context, combo)
        if evaluation is None:
            continue
        objective_value, entity_excess, resource_excess = evaluation
        if best is None or objective_value < best[0] or (
            objective_value == best[0]
            and _combo_sort_key(combo) < _combo_sort_key(best[1])
        ):
            best = (objective_value, combo, entity_excess, resource_excess)

    if best is None:
        return _fallback_result("INFEASIBLE", started)

    objective_value, combo, entity_excess, resource_excess = best
    assignments = tuple(
        sorted(
            (Assignment(c.team_id, c.group_id, c.number) for c in combo),
            key=lambda item: item.team_id,
        )
    )
    variable_values = {candidate.candidate_id: 0 for candidate in context.candidates}
    for candidate in combo:
        variable_values[candidate.candidate_id] = 1
    return RawSolverResult(
        status="OPTIMAL",
        objective_value=float(objective_value),
        best_bound=float(objective_value),
        wall_time=perf_counter() - started,
        assignments=assignments,
        variable_values=variable_values,
        entity_excess=entity_excess,
        resource_excess=resource_excess,
        logs=("deterministic fallback solver used",),
    )


def _fallback_result(
    status: str,
    started: float,
    logs: tuple[str, ...] = (),
) -> RawSolverResult:
    return RawSolverResult(
        status=status,
        objective_value=None,
        best_bound=None,
        wall_time=perf_counter() - started,
        assignments=(),
        variable_values={},
        entity_excess={},
        resource_excess={},
        logs=logs,
    )


def _combo_sort_key(combo: tuple[Candidate, ...]) -> tuple[tuple[str, str, int], ...]:
    return tuple(sorted((c.team_id, c.group_id, c.number) for c in combo))


def _construct_greedy_assignment(
    context: SolverContext,
    variables: ModelVariables,
) -> tuple[Candidate, ...] | None:
    """Build a deterministic feasible-looking assignment for large fallback cases."""

    remaining_by_group = {group.group_id: group.target_size for group in context.groups}
    used_slots: set[tuple[str, int]] = set()
    selected: list[Candidate] = []
    group_entity_counts: dict[tuple[str, str], int] = defaultdict(int)
    team_by_id = {team.team_id: team for team in context.teams}
    entity_team_count: dict[str, int] = defaultdict(int)
    for team in context.teams:
        entity_team_count[team.entity] += 1
    num_groups = len(context.groups)

    for team in sorted(context.teams, key=lambda item: item.team_id):
        options = sorted(
            variables.candidates_by_team.get(team.team_id, []),
            key=lambda candidate: (
                group_entity_counts[(candidate.group_id, team.entity)],
                candidate.group_id,
                candidate.number,
                candidate.candidate_id,
            ),
        )
        chosen = None
        for candidate in options:
            slot = (candidate.group_id, candidate.number)
            if remaining_by_group.get(candidate.group_id, 0) <= 0 or slot in used_slots:
                continue
            if entity_team_count[team.entity] <= num_groups:
                if group_entity_counts[(candidate.group_id, team.entity)] > 0:
                    continue
            chosen = candidate
            break
        if chosen is None:
            for candidate in options:
                slot = (candidate.group_id, candidate.number)
                if remaining_by_group.get(candidate.group_id, 0) > 0 and slot not in used_slots:
                    chosen = candidate
                    break
        if chosen is None:
            return None
        selected.append(chosen)
        used_slots.add((chosen.group_id, chosen.number))
        remaining_by_group[chosen.group_id] -= 1
        group_entity_counts[(chosen.group_id, team_by_id[chosen.team_id].entity)] += 1

    if any(value != 0 for value in remaining_by_group.values()):
        return None
    return tuple(selected)


def _evaluate_assignment_combo(
    context: SolverContext,
    combo: tuple[Candidate, ...],
) -> tuple[int, dict[tuple[str, str], int], dict[tuple[str, int], int]] | None:
    occupied_slots: set[tuple[str, int]] = set()
    count_by_group: dict[str, int] = defaultdict(int)
    candidate_by_group_number: dict[tuple[str, int], Candidate] = {}
    for candidate in combo:
        slot = (candidate.group_id, candidate.number)
        if slot in occupied_slots:
            return None
        occupied_slots.add(slot)
        count_by_group[candidate.group_id] += 1
        candidate_by_group_number[slot] = candidate

    for group in context.groups:
        if count_by_group[group.group_id] != group.target_size:
            return None

    empty_counts = [len(group.numbers) - count_by_group[group.group_id] for group in context.groups]
    objective_value = 0
    empty_mode = getattr(context.config, "empty_number_balance_mode", "hard")
    if empty_counts and max(empty_counts) - min(empty_counts) > 1:
        if empty_mode == "hard":
            return None
        objective_value += (
            max(empty_counts)
            - min(empty_counts)
        ) * int(getattr(context.config, "empty_number_imbalance_weight", 1_000))

    entity_excess = _fallback_entity_excess(context, combo)
    if entity_excess is None:
        return None
    objective_value += sum(entity_excess.values()) * int(
        getattr(context.config, "entity_excess_weight", 10_000)
    )

    usage = _fallback_resource_usage(combo, candidate_by_group_number)
    resource_excess: dict[tuple[str, int], int] = {}
    for key, locals_count in usage.items():
        resource_id, _round_index = key
        capacity = capacity_for_resource(context, resource_id)
        excess = max(0, locals_count - capacity)
        if excess == 0:
            continue
        if getattr(context.config, "capacity_mode", "soft") == "hard":
            return None
        resource_excess[key] = excess
    objective_value += sum(resource_excess.values()) * int(
        getattr(context.config, "resource_excess_weight", 100_000)
    )

    return objective_value, entity_excess, resource_excess


def _fallback_entity_excess(
    context: SolverContext,
    combo: tuple[Candidate, ...],
) -> dict[tuple[str, str], int] | None:
    team_entity = {team.team_id: team.entity for team in context.teams}
    entity_team_count: dict[str, int] = defaultdict(int)
    for team in context.teams:
        entity_team_count[team.entity] += 1

    count_by_entity_group: dict[tuple[str, str], int] = defaultdict(int)
    for candidate in combo:
        count_by_entity_group[(team_entity[candidate.team_id], candidate.group_id)] += 1

    num_groups = len(context.groups)
    excess: dict[tuple[str, str], int] = {}
    for (entity, group_id), count in count_by_entity_group.items():
        if entity_team_count[entity] <= num_groups:
            if count > 1:
                return None
            continue
        value = max(0, count - 1)
        if value:
            excess[(entity, group_id)] = value
    return excess


def _fallback_resource_usage(
    combo: tuple[Candidate, ...],
    candidate_by_group_number: dict[tuple[str, int], Candidate],
) -> dict[tuple[str, int], int]:
    usage: dict[tuple[str, int], int] = defaultdict(int)
    for candidate in combo:
        for round_index, resource_id in candidate_resource_by_round(candidate).items():
            opponent_number = candidate.opponent_number_by_round.get(round_index)
            if opponent_number is None:
                continue
            if (candidate.group_id, opponent_number) not in candidate_by_group_number:
                continue
            usage[(resource_id, round_index)] += 1
    return dict(usage)
