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

    teams_by_entity: dict[str, list[str]] = defaultdict(list)
    for team in context.teams:
        teams_by_entity[team.entity].append(team.team_id)

    num_groups = len(context.groups)
    weight = int(getattr(context.config, "entity_excess_weight", 10_000))
    for entity, team_ids in sorted(teams_by_entity.items()):
        for group in context.groups:
            terms = [
                variables.x[c.candidate_id]
                for team_id in team_ids
                for c in variables.candidates_by_team.get(team_id, [])
                if c.group_id == group.group_id
            ]
            count_expr = linear_sum(terms)
            if len(team_ids) <= num_groups:
                model.Add(count_expr <= 1)
                audit.count_constraint("hard_entity_separation")
                continue

            excess = model.NewIntVar(0, len(team_ids), f"entity_excess_{entity}_{group.group_id}")
            model.Add(excess >= count_expr - 1)
            variables.entity_excess[(entity, group.group_id)] = excess
            objective_terms.append(("entity_excess", weight, excess))
            audit.count_constraint("soft_entity_excess")
            audit.count_objective_term("entity_excess")

