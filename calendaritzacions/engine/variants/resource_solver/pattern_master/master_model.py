"""Master pattern-selection model."""

from __future__ import annotations

from collections import Counter, defaultdict
from time import perf_counter
from typing import Any, Iterable

from calendaritzacions.engine.variants.resource_solver.constraints.entity_separation import entity_can_be_separated
from calendaritzacions.engine.variants.resource_solver.constraints.resource_capacity import capacity_for_resource
from calendaritzacions.engine.variants.resource_solver.pattern_master.patterns import (
    competition_number_capacity,
    pattern_slot_domain_number_counts,
    slot_domain_number_capacity,
)
from calendaritzacions.engine.variants.resource_solver.pattern_master.types import (
    HubPattern,
    MasterSelection,
    PatternConflict,
)
from calendaritzacions.engine.variants.resource_solver.types import SolverContext
from calendaritzacions.engine.variants.resource_solver.types import Assignment
from calendaritzacions.engine.variants.resource_solver.types import Candidate


def solve_master_selection(
    context: SolverContext,
    patterns: Iterable[HubPattern],
    conflicts: Iterable[PatternConflict],
) -> MasterSelection:
    cp_model = _load_cp_model()
    rows = tuple(patterns)
    conflict_rows = tuple(conflicts)
    if cp_model is None:
        return _solve_master_fallback(context, rows, conflict_rows)
    started = perf_counter()
    model = cp_model.CpModel()
    x = {pattern.pattern_id: model.NewBoolVar(f"x_{_safe_name(pattern.pattern_id)}") for pattern in rows}

    by_hub: dict[str, list[HubPattern]] = defaultdict(list)
    for pattern in rows:
        by_hub[pattern.hub_id].append(pattern)
    for hub_id, hub_patterns in sorted(by_hub.items()):
        model.Add(sum(x[pattern.pattern_id] for pattern in hub_patterns) == 1)

    for conflict in conflict_rows:
        left = x.get(conflict.left_pattern_id)
        right = x.get(conflict.right_pattern_id)
        if left is not None and right is not None:
            model.Add(left + right <= 1)

    capacity = competition_number_capacity(context)
    for competition_key, counts in capacity.items():
        for number, cap in counts.items():
            terms = [
                int(pattern.competition_number_counts.get(competition_key, {}).get(number, 0))
                * x[pattern.pattern_id]
                for pattern in rows
                if int(pattern.competition_number_counts.get(competition_key, {}).get(number, 0)) > 0
            ]
            if terms:
                model.Add(sum(terms) <= int(cap))

    domain_capacity = slot_domain_number_capacity(context)
    domain_terms: dict[tuple[str, int], list[Any]] = defaultdict(list)
    for pattern in rows:
        for domain_key, counts in pattern_slot_domain_number_counts(context, pattern).items():
            for number, count in counts.items():
                if int(count) > 0:
                    domain_terms[(domain_key, int(number))].append(int(count) * x[pattern.pattern_id])
    for domain_key, counts in domain_capacity.items():
        for number, cap in counts.items():
            terms = domain_terms.get((domain_key, int(number)), [])
            if terms:
                model.Add(sum(terms) <= int(cap))
    del domain_terms

    logs: list[str] = []
    resource_excess_terms = []
    resource_weight = int(getattr(context.config, "resource_excess_weight", 100_000) or 100_000)
    materialization_vars: list[tuple[Any, str, str, int]] = []
    materialization_terms = _estimate_materialization_terms(context, rows)
    materialization_limit = int(getattr(context.config, "pattern_master_inline_materialization_max_terms", 150_000) or 0)
    if materialization_limit > 0 and materialization_terms <= materialization_limit:
        resource_terms, materialization_vars = _add_group_materialization_constraints(model, x, rows, context)
        for resource_id, terms in sorted(resource_terms.items()):
            if not terms:
                continue
            usage = sum(terms)
            excess = model.NewIntVar(0, len(terms), f"resource_excess_{_safe_name(resource_id)}")
            model.Add(excess >= usage - capacity_for_resource(context, resource_id))
            resource_excess_terms.append(excess)
        logs.append(f"pattern master inline materialization enabled: terms={materialization_terms}")
    else:
        resource_excess_terms.extend(_add_pattern_resource_excess_terms(model, x, rows, context))
        logs.append(
            "pattern master inline materialization skipped: "
            f"terms={materialization_terms} limit={materialization_limit}"
        )

    model.Minimize(
        sum(int(pattern.cost) * x[pattern.pattern_id] for pattern in rows)
        + resource_weight * sum(resource_excess_terms)
    )
    solver = cp_model.CpSolver()
    limit = float(getattr(context.config, "internal_solve_time_limit_seconds", 60.0) or 60.0)
    solver.parameters.max_time_in_seconds = limit
    solver.parameters.num_search_workers = 1
    status_code = solver.Solve(model)
    status = _status_name(cp_model, status_code)
    if status not in {"OPTIMAL", "FEASIBLE"}:
        return MasterSelection(status=status, selected_pattern_ids=(), conflicts=conflict_rows, logs=("pattern master found no selection",))
    selected = tuple(sorted(pattern_id for pattern_id, var in x.items() if int(solver.Value(var)) > 0))
    materialized_assignments = tuple(
        sorted(
            (
                Assignment(team_id=team_id, group_id=group_id, number=int(number))
                for var, team_id, group_id, number in materialization_vars
                if int(solver.Value(var)) > 0
            ),
            key=lambda item: item.team_id,
        )
    )
    return MasterSelection(
        status=status,
        selected_pattern_ids=selected,
        objective_value=float(solver.ObjectiveValue()),
        materialized_assignments=materialized_assignments,
        conflicts=conflict_rows,
        logs=(*logs, f"pattern master solved in {perf_counter() - started:.3f}s"),
    )


def master_selection_payload(selection: MasterSelection) -> dict[str, Any]:
    return {
        "artifact_type": "resource_solver_pattern_master_selection",
        "status": selection.status,
        "selected_pattern_ids": list(selection.selected_pattern_ids),
        "selected_pattern_count": len(selection.selected_pattern_ids),
        "materialized_assignments": [
            {"team_id": item.team_id, "group_id": item.group_id, "number": int(item.number)}
            for item in selection.materialized_assignments
        ],
        "materialized_assignment_count": len(selection.materialized_assignments),
        "objective_value": selection.objective_value,
        "conflict_count": len(selection.conflicts),
        "logs": list(selection.logs),
    }


def _estimate_materialization_terms(context: SolverContext, patterns: tuple[HubPattern, ...]) -> int:
    candidate_groups = _candidate_group_ids_by_team_number(context)
    terms = 0
    for pattern in patterns:
        for assignment in pattern.assignments:
            terms += len(candidate_groups.get((assignment.team_id, int(assignment.number)), ()))
    return terms


def _add_pattern_resource_excess_terms(
    model: Any,
    pattern_vars: dict[str, Any],
    patterns: tuple[HubPattern, ...],
    context: SolverContext,
) -> list[Any]:
    terms_by_resource: dict[str, list[Any]] = defaultdict(list)
    max_by_resource: Counter[str] = Counter()
    for pattern in patterns:
        pattern_var = pattern_vars[pattern.pattern_id]
        for resource_id, count in pattern.resource_usage.items():
            usage = int(count or 0)
            if usage <= 0:
                continue
            resource_key = str(resource_id)
            terms_by_resource[resource_key].append(usage * pattern_var)
            max_by_resource[resource_key] += usage

    excess_terms: list[Any] = []
    for resource_id, terms in sorted(terms_by_resource.items()):
        if max_by_resource[resource_id] <= capacity_for_resource(context, resource_id):
            continue
        excess = model.NewIntVar(0, int(max_by_resource[resource_id]), f"pattern_resource_excess_{_safe_name(resource_id)}")
        model.Add(excess >= sum(terms) - capacity_for_resource(context, resource_id))
        excess_terms.append(excess)
    return excess_terms


def _add_group_materialization_constraints(
    model: Any,
    pattern_vars: dict[str, Any],
    patterns: tuple[HubPattern, ...],
    context: SolverContext,
) -> tuple[dict[str, list[Any]], list[tuple[Any, str, str, int]]]:
    candidate_groups = _candidate_group_ids_by_team_number(context)
    candidate_by_assignment = _candidate_by_team_group_number(context)
    group_terms: dict[str, list[Any]] = defaultdict(list)
    slot_terms: dict[tuple[str, int], list[Any]] = defaultdict(list)
    team_group_terms: dict[tuple[str, str], list[Any]] = defaultdict(list)
    resource_terms: dict[str, list[Any]] = defaultdict(list)
    materialization_vars: list[tuple[Any, str, str, int]] = []
    for pattern in patterns:
        pattern_var = pattern_vars[pattern.pattern_id]
        for assignment in pattern.assignments:
            number = int(assignment.number)
            group_ids = tuple(sorted(candidate_groups.get((assignment.team_id, number), ())))
            if not group_ids:
                model.Add(pattern_var == 0)
                continue
            if len(group_ids) == 1:
                group_id = group_ids[0]
                group_terms[group_id].append(pattern_var)
                slot_terms[(group_id, number)].append(pattern_var)
                team_group_terms[(assignment.team_id, group_id)].append(pattern_var)
                materialization_vars.append((pattern_var, assignment.team_id, group_id, number))
                continue
            terms = []
            for group_id in group_ids:
                var = model.NewBoolVar(
                    f"y_{_safe_name(pattern.pattern_id)}_{_safe_name(assignment.team_id)}_{_safe_name(group_id)}"
                )
                model.Add(var <= pattern_var)
                terms.append(var)
                group_terms[group_id].append(var)
                slot_terms[(group_id, number)].append(var)
                team_group_terms[(assignment.team_id, group_id)].append(var)
                materialization_vars.append((var, assignment.team_id, group_id, number))
            model.Add(sum(terms) == pattern_var)

    bucket_terms: dict[str, list[Any]] = defaultdict(list)
    bucket_targets: dict[str, int] = {}
    for group in context.groups:
        bucket_id = str(getattr(group, "size_bucket_id", "") or "")
        if bucket_id:
            bucket_terms[bucket_id].extend(group_terms.get(group.group_id, []))
            bucket_targets[bucket_id] = int(getattr(group, "size_bucket_target", 0) or 0)
        else:
            model.Add(sum(group_terms.get(group.group_id, [])) == int(group.target_size))
        for number in group.numbers:
            terms = slot_terms.get((group.group_id, int(number)), [])
            if terms:
                model.Add(sum(terms) <= 1)
    for bucket_id, terms in sorted(bucket_terms.items()):
        model.Add(sum(terms) == bucket_targets[bucket_id])

    entity_by_team = {team.team_id: team.entity for team in context.teams}
    groups_by_team: dict[str, set[str]] = defaultdict(set)
    teams_by_group: dict[str, set[str]] = defaultdict(set)
    for candidate in context.candidates:
        groups_by_team[candidate.team_id].add(candidate.group_id)
        teams_by_group[candidate.group_id].add(candidate.team_id)
    for group in context.groups:
        competition_team_ids = teams_by_group.get(group.group_id, set())
        competition_group_ids = {
            group_id
            for team_id in competition_team_ids
            for group_id in groups_by_team.get(team_id, set())
        }
        competition_teams_by_entity: dict[str, list[str]] = defaultdict(list)
        for team_id in competition_team_ids:
            competition_teams_by_entity[entity_by_team.get(team_id, "")].append(team_id)
        for _entity, team_ids in sorted(competition_teams_by_entity.items()):
            if not entity_can_be_separated(team_ids, groups_by_team, competition_group_ids):
                continue
            terms = [
                term
                for team_id in team_ids
                for term in team_group_terms.get((team_id, group.group_id), ())
            ]
            if terms:
                model.Add(sum(terms) <= 1)
    _add_real_resource_terms(
        model,
        materialization_vars,
        slot_terms,
        candidate_by_assignment,
        resource_terms,
        context,
    )
    return dict(resource_terms), materialization_vars


def _solve_master_fallback(
    context: SolverContext,
    patterns: tuple[HubPattern, ...],
    conflicts: tuple[PatternConflict, ...],
) -> MasterSelection:
    by_hub: dict[str, list[HubPattern]] = defaultdict(list)
    for pattern in patterns:
        by_hub[pattern.hub_id].append(pattern)
    conflict_pairs = {
        frozenset({conflict.left_pattern_id, conflict.right_pattern_id})
        for conflict in conflicts
    }
    capacity = competition_number_capacity(context)
    domain_capacity = slot_domain_number_capacity(context)
    domain_counts_by_pattern = {
        pattern.pattern_id: pattern_slot_domain_number_counts(context, pattern)
        for pattern in patterns
    }
    selected: list[HubPattern] = []
    for hub_id in sorted(by_hub):
        chosen = None
        for pattern in sorted(by_hub[hub_id], key=lambda item: (item.cost, item.pattern_id)):
            if any(frozenset({pattern.pattern_id, item.pattern_id}) in conflict_pairs for item in selected):
                continue
            if not _competition_capacity_ok(capacity, (*selected, pattern)):
                continue
            if not _slot_domain_capacity_ok(domain_capacity, domain_counts_by_pattern, (*selected, pattern)):
                continue
            chosen = pattern
            break
        if chosen is None:
            return MasterSelection(status="INFEASIBLE", selected_pattern_ids=(), conflicts=conflicts)
        selected.append(chosen)
    return MasterSelection(
        status="FEASIBLE",
        selected_pattern_ids=tuple(pattern.pattern_id for pattern in selected),
        objective_value=float(sum(pattern.cost for pattern in selected)),
        conflicts=conflicts,
        logs=("deterministic fallback pattern master used",),
    )


def _competition_capacity_ok(capacity: dict[str, dict[int, int]], patterns: tuple[HubPattern, ...]) -> bool:
    counts: dict[tuple[str, int], int] = defaultdict(int)
    for pattern in patterns:
        for competition_key, number_counts in pattern.competition_number_counts.items():
            for number, count in number_counts.items():
                counts[(competition_key, int(number))] += int(count)
                if counts[(competition_key, int(number))] > int(capacity.get(competition_key, {}).get(int(number), 0)):
                    return False
    return True


def _slot_domain_capacity_ok(
    capacity: dict[str, dict[int, int]],
    counts_by_pattern: dict[str, dict[str, dict[int, int]]],
    patterns: tuple[HubPattern, ...],
) -> bool:
    counts: dict[tuple[str, int], int] = defaultdict(int)
    for pattern in patterns:
        for domain_key, number_counts in counts_by_pattern.get(pattern.pattern_id, {}).items():
            for number, count in number_counts.items():
                counts[(domain_key, int(number))] += int(count)
                if counts[(domain_key, int(number))] > int(capacity.get(domain_key, {}).get(int(number), 0)):
                    return False
    return True


def _candidate_group_ids_by_team_number(context: SolverContext) -> dict[tuple[str, int], set[str]]:
    candidate_groups: dict[tuple[str, int], set[str]] = defaultdict(set)
    for candidate in context.candidates:
        candidate_groups[(candidate.team_id, int(candidate.number))].add(candidate.group_id)
    return candidate_groups


def _iter_real_resource_match_inputs(
    materialization_vars: list[tuple[Any, str, str, int]],
    slot_terms: dict[tuple[str, int], list[Any]],
    candidate_by_assignment: dict[tuple[str, str, int], Candidate],
) -> Iterable[tuple[Any, str, str, int, int, str, list[Any]]]:
    for home_var, team_id, group_id, number in materialization_vars:
        candidate = candidate_by_assignment.get((team_id, group_id, int(number)))
        if candidate is None:
            continue
        home_rounds = tuple(int(round_index) for round_index in candidate.potential_home_rounds)
        resources = tuple(str(resource_id) for resource_id in candidate.potential_resources)
        for index, round_index in enumerate(home_rounds):
            if index >= len(resources):
                continue
            away_number = candidate.opponent_number_by_round.get(round_index)
            if away_number is None:
                continue
            away_terms = slot_terms.get((group_id, int(away_number)), [])
            if not away_terms:
                continue
            resource_id = resources[index]
            yield home_var, team_id, group_id, int(number), round_index, resource_id, away_terms


def _add_real_resource_terms(
    model: Any,
    materialization_vars: list[tuple[Any, str, str, int]],
    slot_terms: dict[tuple[str, int], list[Any]],
    candidate_by_assignment: dict[tuple[str, str, int], Candidate],
    resource_terms: dict[str, list[Any]],
    context: SolverContext,
) -> None:
    potential_by_resource = Counter(
        resource_id
        for _home_var, _team_id, _group_id, _number, _round_index, resource_id, _away_terms
        in _iter_real_resource_match_inputs(materialization_vars, slot_terms, candidate_by_assignment)
    )
    saturable_resources = {
        resource_id
        for resource_id, count in potential_by_resource.items()
        if int(count) > capacity_for_resource(context, resource_id)
    }
    if not saturable_resources:
        return

    for home_var, team_id, group_id, number, round_index, resource_id, away_terms in _iter_real_resource_match_inputs(
        materialization_vars,
        slot_terms,
        candidate_by_assignment,
    ):
        if resource_id not in saturable_resources:
            continue
        away_used = sum(away_terms)
        match_var = model.NewBoolVar(
            f"match_resource_{_safe_name(team_id)}_{_safe_name(group_id)}_{number}_{round_index}"
        )
        model.Add(match_var <= home_var)
        model.Add(match_var <= away_used)
        model.Add(match_var >= home_var + away_used - 1)
        resource_terms[resource_id].append(match_var)


def _candidate_by_team_group_number(context: SolverContext) -> dict[tuple[str, str, int], Candidate]:
    candidates: dict[tuple[str, str, int], Candidate] = {}
    for candidate in context.candidates:
        key = (candidate.team_id, candidate.group_id, int(candidate.number))
        candidates.setdefault(key, candidate)
    return candidates


def _load_cp_model() -> Any | None:
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return None
    return cp_model


def _status_name(cp_model: Any, status_code: int) -> str:
    if status_code == cp_model.OPTIMAL:
        return "OPTIMAL"
    if status_code == cp_model.FEASIBLE:
        return "FEASIBLE"
    if status_code == cp_model.INFEASIBLE:
        return "INFEASIBLE"
    return "UNKNOWN"


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in str(value))


__all__ = ["master_selection_payload", "solve_master_selection"]
