"""Entity separation constraints."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from calendaritzacions.engine.variants.resource_solver.constraints.base import (
    ConstraintAudit,
    ModelVariables,
    ObjectiveTerm,
    linear_sum,
)


@dataclass(frozen=True)
class EntitySeparationConstraints:
    name: str = "entity_separation"

    def add(
        self,
        model: Any,
        variables: ModelVariables,
        context: Any,
        objective_terms: list[ObjectiveTerm],
        audit: ConstraintAudit,
    ) -> None:
        add_entity_separation_constraints(model, variables, context, objective_terms, audit)


def add_entity_separation_constraints(
    model: Any,
    variables: ModelVariables,
    context: Any,
    objective_terms: list[ObjectiveTerm],
    audit: ConstraintAudit,
) -> None:
    """Separate same-entity teams unless that is structurally impossible."""

    entity_by_team = {team.team_id: team.entity for team in context.teams}
    groups_by_team: dict[str, set[str]] = defaultdict(set)
    teams_by_group: dict[str, set[str]] = defaultdict(set)
    for candidate in variables.candidate_by_id.values():
        groups_by_team[candidate.team_id].add(candidate.group_id)
        teams_by_group[candidate.group_id].add(candidate.team_id)

    weight = int(getattr(context.config, "entity_excess_weight", 10_000))
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

        for entity, team_ids in sorted(competition_teams_by_entity.items()):
            terms = [
                variables.x[c.candidate_id]
                for team_id in team_ids
                for c in variables.candidates_by_team.get(team_id, [])
                if c.group_id == group.group_id
            ]
            count_expr = linear_sum(terms)
            if entity_can_be_separated(team_ids, groups_by_team, competition_group_ids):
                model.Add(count_expr <= 1)
                audit.count_constraint("hard_entity_separation")
                continue

            excess = model.NewIntVar(0, len(team_ids), f"entity_excess_{entity}_{group.group_id}")
            model.Add(excess >= count_expr - 1)
            variables.entity_excess[(entity, group.group_id)] = excess
            objective_terms.append(("entity_excess", weight, excess))
            audit.count_constraint("soft_entity_excess")
            audit.count_objective_term("entity_excess")


def entity_can_be_separated(
    team_ids: list[str],
    groups_by_team: dict[str, set[str]],
    competition_group_ids: set[str],
) -> bool:
    """Return whether the entity teams can occupy distinct accessible groups."""

    if len(team_ids) <= 1:
        return True

    available_by_team = {
        team_id: sorted(groups_by_team.get(team_id, set()).intersection(competition_group_ids))
        for team_id in team_ids
    }
    if any(not group_ids for group_ids in available_by_team.values()):
        return False

    match_by_group: dict[str, str] = {}
    for team_id in sorted(team_ids, key=lambda item: len(available_by_team[item])):
        seen: set[str] = set()
        if not _assign_distinct_group(team_id, available_by_team, match_by_group, seen):
            return False
    return True


def _assign_distinct_group(
    team_id: str,
    available_by_team: dict[str, list[str]],
    match_by_group: dict[str, str],
    seen: set[str],
) -> bool:
    for group_id in available_by_team.get(team_id, []):
        if group_id in seen:
            continue
        seen.add(group_id)
        matched_team_id = match_by_group.get(group_id)
        if matched_team_id is None or _assign_distinct_group(
            matched_team_id,
            available_by_team,
            match_by_group,
            seen,
        ):
            match_by_group[group_id] = team_id
            return True
    return False
