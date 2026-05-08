"""Assignment constraints: one candidate per team and unique numbers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from calendaritzacions.engine.variants.resource_solver.constraints.base import (
    ConstraintAudit,
    ModelVariables,
    ObjectiveTerm,
    linear_sum,
)


@dataclass(frozen=True)
class AssignmentConstraints:
    name: str = "assignment"

    def add(
        self,
        model: Any,
        variables: ModelVariables,
        context: Any,
        objective_terms: list[ObjectiveTerm],
        audit: ConstraintAudit,
    ) -> None:
        add_assignment_constraints(model, variables, context, objective_terms, audit)


def add_assignment_constraints(
    model: Any,
    variables: ModelVariables,
    context: Any,
    objective_terms: list[ObjectiveTerm],
    audit: ConstraintAudit,
) -> None:
    """Require every team to select exactly one candidate."""

    for team in context.teams:
        candidates = variables.candidates_by_team.get(team.team_id, [])
        model.Add(linear_sum([variables.x[c.candidate_id] for c in candidates]) == 1)
        audit.count_constraint("one_assignment_per_team")


def add_unique_group_number_constraints(
    model: Any,
    variables: ModelVariables,
    context: Any,
    audit: ConstraintAudit,
) -> None:
    """Require a draw number to be used by at most one team inside a group."""

    for group in context.groups:
        for number in group.numbers:
            candidates = variables.candidates_by_group_number.get((group.group_id, number), [])
            terms = [variables.x[c.candidate_id] for c in candidates]
            occupied = variables.occupied[(group.group_id, number)]
            model.Add(linear_sum(terms) <= 1)
            model.Add(occupied == linear_sum(terms))
            audit.count_constraint("unique_group_number", 2)

