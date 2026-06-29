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
    bucket_terms: dict[str, list[Any]] = {}
    bucket_targets: dict[str, int] = {}
    for group in context.groups:
        terms = [
            variables.x[c.candidate_id]
            for c in variables.candidate_by_id.values()
            if c.group_id == group.group_id
        ]
        bucket_id = str(getattr(group, "size_bucket_id", "") or "")
        if bucket_id:
            bucket_terms.setdefault(bucket_id, []).extend(terms)
            bucket_targets[bucket_id] = int(getattr(group, "size_bucket_target", 0) or 0)
            audit.count_constraint("flex_group_size_member")
            continue
        model.Add(linear_sum(terms) == group.target_size)
        audit.count_constraint("exact_group_size")

    for bucket_id, terms in sorted(bucket_terms.items()):
        model.Add(linear_sum(terms) == bucket_targets[bucket_id])
        audit.count_constraint("bucket_group_size")
