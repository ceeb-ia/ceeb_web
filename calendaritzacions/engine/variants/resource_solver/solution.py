"""Build business-level resource solver solutions from raw solver output."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, is_dataclass
from typing import Any

from calendaritzacions.engine.variants.resource_solver.types import (
    Assignment,
    Candidate,
    GroupSummary,
    RealMatch,
    ResourceSolverResult,
    ResourceUsage,
    SolverContext,
)


def build_solution(raw_result: Any, context: SolverContext) -> ResourceSolverResult:
    """Convert a raw solver result into the public resource solver result."""

    assignments = tuple(build_assignments(raw_result, context))
    real_matches = tuple(build_real_matches(assignments, context))
    resource_usage = tuple(build_resource_usage(real_matches, context))
    group_summary = tuple(build_group_summary(assignments, context))
    entity_excess = build_entity_excess(assignments, context, raw_result)

    logs = tuple(str(item) for item in getattr(raw_result, "logs", ()) or ())
    return ResourceSolverResult(
        status=str(getattr(raw_result, "status", "UNKNOWN")),
        objective_value=_optional_float(getattr(raw_result, "objective_value", None)),
        best_bound=_optional_float(getattr(raw_result, "best_bound", None)),
        wall_time=float(getattr(raw_result, "wall_time", 0.0) or 0.0),
        assignments=assignments,
        real_matches=real_matches,
        resource_usage=resource_usage,
        group_summary=group_summary,
        entity_excess=entity_excess,
        audit_payloads={},
        logs=logs,
    )


def build_assignments(raw_result: Any, context: SolverContext) -> list[Assignment]:
    """Read selected assignments from a raw solver result.

    The function accepts several simple shapes so RS-C can be tested before the
    CP-SAT model has a stable RawSolverResult class.
    """

    explicit = getattr(raw_result, "assignments", None)
    if explicit:
        return sorted(
            (_coerce_assignment(item) for item in explicit),
            key=lambda item: item.team_id,
        )

    selected_candidate_ids = set(getattr(raw_result, "selected_candidate_ids", ()) or ())
    if selected_candidate_ids:
        return sorted(
            (
                Assignment(candidate.team_id, candidate.group_id, candidate.number)
                for candidate in context.candidates
                if candidate.candidate_id in selected_candidate_ids
            ),
            key=lambda item: item.team_id,
        )

    values = getattr(raw_result, "values", None) or getattr(raw_result, "x_values", None)
    if isinstance(values, dict):
        return _assignments_from_values(values, context)

    return []


def build_real_matches(
    assignments: tuple[Assignment, ...] | list[Assignment],
    context: SolverContext,
) -> list[RealMatch]:
    """Build real home matches, excluding matches against empty numbers."""

    by_group_number = _assigned_by_group_number(assignments)
    candidates = _candidate_lookup(context)
    matches: list[RealMatch] = []

    for group_id, numbers in sorted(by_group_number.items()):
        for round_index, round_matches in enumerate(context.phase, start=1):
            for home_number, away_number in round_matches:
                home_team = numbers.get(home_number)
                away_team = numbers.get(away_number)
                if not home_team or not away_team:
                    continue
                resource_id = _resource_for_home(
                    candidates.get((home_team, group_id, home_number)),
                    context,
                    round_index,
                    home_team,
                )
                matches.append(
                    RealMatch(
                        round_index=round_index,
                        group_id=group_id,
                        home_team_id=home_team,
                        away_team_id=away_team,
                        home_number=home_number,
                        away_number=away_number,
                        resource_id=resource_id,
                    )
                )
    return matches


def build_resource_usage(
    real_matches: tuple[RealMatch, ...] | list[RealMatch],
    context: SolverContext,
) -> list[ResourceUsage]:
    """Aggregate real matches by timed resource id."""

    teams_by_resource: dict[str, list[str]] = defaultdict(list)
    for match in real_matches:
        teams_by_resource[match.resource_id].append(match.home_team_id)

    usage: list[ResourceUsage] = []
    for resource_id, team_ids in sorted(teams_by_resource.items()):
        capacity = _capacity_for_resource(resource_id, context)
        locals_count = len(team_ids)
        usage.append(
            ResourceUsage(
                resource_id=resource_id,
                locals_count=locals_count,
                capacity=capacity,
                excess=max(0, locals_count - capacity),
                team_ids=tuple(sorted(team_ids)),
            )
        )
    return usage


def build_group_summary(
    assignments: tuple[Assignment, ...] | list[Assignment],
    context: SolverContext,
) -> list[GroupSummary]:
    """Summarize assigned and empty numbers, plus rests, for each group."""

    by_group_number = _assigned_by_group_number(assignments)
    summaries: list[GroupSummary] = []
    for group in context.groups:
        assigned_numbers = dict(sorted(by_group_number.get(group.group_id, {}).items()))
        empty_numbers = tuple(number for number in group.numbers if number not in assigned_numbers)
        rests_by_team = _rests_by_team(group.group_id, assigned_numbers, context)
        entity_excess = _entity_excess_for_group(group.group_id, assigned_numbers, context)
        summaries.append(
            GroupSummary(
                group_id=group.group_id,
                assigned_numbers=assigned_numbers,
                empty_numbers=empty_numbers,
                rests_by_team=rests_by_team,
                entity_excess=entity_excess,
            )
        )
    return summaries


def build_entity_excess(
    assignments: tuple[Assignment, ...] | list[Assignment],
    context: SolverContext,
    raw_result: Any | None = None,
) -> dict[tuple[str, str], int]:
    """Return entity excess keyed by ``(entity, group_id)``."""

    raw_entity_excess = getattr(raw_result, "entity_excess", None) if raw_result else None
    if isinstance(raw_entity_excess, dict):
        return {
            _coerce_entity_group_key(key): int(value)
            for key, value in raw_entity_excess.items()
            if int(value) > 0
        }

    entity_by_team = {team.team_id: team.entity for team in context.teams}
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for assignment in assignments:
        entity = entity_by_team.get(assignment.team_id, "")
        if entity:
            counts[(entity, assignment.group_id)] += 1
    return {key: count - 1 for key, count in counts.items() if count > 1}


def result_to_json_ready(result: ResourceSolverResult) -> dict[str, Any]:
    """Return the result as a JSON-ready dictionary."""

    payload = _json_ready(asdict(result))
    payload["entity_excess"] = {
        f"{entity}|{group_id}": value
        for (entity, group_id), value in result.entity_excess.items()
    }
    return payload


def _assignments_from_values(values: dict[Any, Any], context: SolverContext) -> list[Assignment]:
    candidate_by_id = {candidate.candidate_id: candidate for candidate in context.candidates}
    selected: list[Assignment] = []
    for key, value in values.items():
        if float(value or 0) < 0.5:
            continue
        candidate = _candidate_from_value_key(key, candidate_by_id, context)
        if candidate:
            selected.append(Assignment(candidate.team_id, candidate.group_id, candidate.number))
    return sorted(selected, key=lambda item: item.team_id)


def _candidate_from_value_key(
    key: Any,
    candidate_by_id: dict[str, Candidate],
    context: SolverContext,
) -> Candidate | None:
    if isinstance(key, str):
        return candidate_by_id.get(key)
    if isinstance(key, tuple):
        if len(key) == 1:
            return candidate_by_id.get(str(key[0]))
        if len(key) >= 3:
            team_id, group_id, number = str(key[0]), str(key[1]), int(key[2])
            for candidate in context.candidates:
                if (
                    candidate.team_id == team_id
                    and candidate.group_id == group_id
                    and candidate.number == number
                ):
                    return candidate
    return None


def _coerce_assignment(item: Any) -> Assignment:
    if isinstance(item, Assignment):
        return item
    if isinstance(item, dict):
        return Assignment(
            team_id=str(item["team_id"]),
            group_id=str(item["group_id"]),
            number=int(item["number"]),
        )
    return Assignment(
        team_id=str(getattr(item, "team_id")),
        group_id=str(getattr(item, "group_id")),
        number=int(getattr(item, "number")),
    )


def _assigned_by_group_number(
    assignments: tuple[Assignment, ...] | list[Assignment],
) -> dict[str, dict[int, str]]:
    by_group_number: dict[str, dict[int, str]] = defaultdict(dict)
    for assignment in assignments:
        by_group_number[assignment.group_id][assignment.number] = assignment.team_id
    return by_group_number


def _candidate_lookup(context: SolverContext) -> dict[tuple[str, str, int], Candidate]:
    return {
        (candidate.team_id, candidate.group_id, candidate.number): candidate
        for candidate in context.candidates
    }


def _resource_for_home(
    candidate: Candidate | None,
    context: SolverContext,
    round_index: int,
    team_id: str,
) -> str:
    if candidate:
        rounds = list(candidate.potential_home_rounds)
        resources = list(candidate.potential_resources)
        if round_index in rounds and resources:
            index = rounds.index(round_index)
            if index < len(resources):
                return _timed_resource_id(resources[index], round_index)
            return _timed_resource_id(resources[0], round_index)

    team = next((item for item in context.teams if item.team_id == team_id), None)
    if team:
        base_id = f"{team.venue}|{team.day}|{team.time}"
        return _timed_resource_id(base_id, round_index)
    return _timed_resource_id("unknown-resource", round_index)


def _timed_resource_id(resource_id: str, round_index: int) -> str:
    if "::R" in resource_id or resource_id.endswith(f"|J{round_index}"):
        return resource_id
    return f"{resource_id}|J{round_index}"


def _capacity_for_resource(resource_id: str, context: SolverContext) -> int:
    direct = context.capacities.get(resource_id)
    if direct:
        return max(1, int(direct.capacity))
    if "|J" in resource_id:
        base_id = resource_id.rsplit("|J", 1)[0]
        base = context.capacities.get(base_id)
        if base:
            return max(1, int(base.capacity))
    base_id = resource_id.split("::R", 1)[0]
    base = context.capacities.get(base_id)
    if base:
        return max(1, int(base.capacity))
    return 1


def _rests_by_team(
    group_id: str,
    assigned_numbers: dict[int, str],
    context: SolverContext,
) -> dict[str, tuple[int, ...]]:
    rests: dict[str, list[int]] = defaultdict(list)
    occupied = set(assigned_numbers)
    for round_index, round_matches in enumerate(context.phase, start=1):
        for home_number, away_number in round_matches:
            home_team = assigned_numbers.get(home_number)
            away_team = assigned_numbers.get(away_number)
            if home_team and away_number not in occupied:
                rests[home_team].append(round_index)
            if away_team and home_number not in occupied:
                rests[away_team].append(round_index)
    return {team_id: tuple(rounds) for team_id, rounds in sorted(rests.items())}


def _entity_excess_for_group(
    group_id: str,
    assigned_numbers: dict[int, str],
    context: SolverContext,
) -> dict[str, int]:
    entity_by_team = {team.team_id: team.entity for team in context.teams}
    counts: dict[str, int] = defaultdict(int)
    for team_id in assigned_numbers.values():
        entity = entity_by_team.get(team_id, "")
        if entity:
            counts[entity] += 1
    return {entity: count - 1 for entity, count in sorted(counts.items()) if count > 1}


def _coerce_entity_group_key(key: Any) -> tuple[str, str]:
    if isinstance(key, tuple) and len(key) >= 2:
        return str(key[0]), str(key[1])
    if isinstance(key, str) and "|" in key:
        entity, group_id = key.split("|", 1)
        return entity, group_id
    return str(key), ""


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value
