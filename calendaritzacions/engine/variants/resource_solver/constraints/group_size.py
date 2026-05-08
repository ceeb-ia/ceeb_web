"""Group-size constraints for the resource solver."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from calendaritzacions.engine.variants.resource_solver.constraints.assignment import (
    add_unique_group_number_constraints,
)
from calendaritzacions.engine.variants.resource_solver.constraints.base import (
    ConstraintAudit,
    ModelVariables,
    ObjectiveTerm,
    linear_sum,
)


@dataclass(frozen=True)
class GroupSizeConstraints:
    name: str = "group_size"

    def add(
        self,
        model: Any,
        variables: ModelVariables,
        context: Any,
        objective_terms: list[ObjectiveTerm],
        audit: ConstraintAudit,
    ) -> None:
        add_group_size_constraints(model, variables, context, objective_terms, audit)


def add_group_size_constraints(
    model: Any,
    variables: ModelVariables,
    context: Any,
    objective_terms: list[ObjectiveTerm],
    audit: ConstraintAudit,
) -> None:
    """Require exact target group sizes and unique group-number slots."""

    add_unique_group_number_constraints(model, variables, context, audit)
    for group in context.groups:
        terms = [
            variables.x[c.candidate_id]
            for c in variables.candidate_by_id.values()
            if c.group_id == group.group_id
        ]
        model.Add(linear_sum(terms) == group.target_size)
        audit.count_constraint("exact_group_size")

