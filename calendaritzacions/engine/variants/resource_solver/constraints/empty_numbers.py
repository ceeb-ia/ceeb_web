"""Balanced empty-number constraints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from calendaritzacions.engine.variants.resource_solver.constraints.base import (
    ConstraintAudit,
    ModelVariables,
    ObjectiveTerm,
)


@dataclass(frozen=True)
class EmptyNumberConstraints:
    name: str = "empty_numbers"

    def add(
        self,
        model: Any,
        variables: ModelVariables,
        context: Any,
        objective_terms: list[ObjectiveTerm],
        audit: ConstraintAudit,
    ) -> None:
        add_empty_number_constraints(model, variables, context, objective_terms, audit)


def add_empty_number_constraints(
    model: Any,
    variables: ModelVariables,
    context: Any,
    objective_terms: list[ObjectiveTerm],
    audit: ConstraintAudit,
) -> None:
    """Keep empty draw numbers balanced across comparable groups."""

    if len(context.groups) <= 1:
        return

    empty_by_group: dict[str, int] = {
        group.group_id: len(group.numbers) - group.target_size for group in context.groups
    }
    max_empty = max(empty_by_group.values())
    min_empty = min(empty_by_group.values())
    imbalance = max_empty - min_empty

    mode = getattr(context.config, "empty_number_balance_mode", "hard")
    if mode == "hard":
        if imbalance > 1:
            model.Add(0 == 1)
        audit.count_constraint("balanced_empty_numbers")
        return

    if imbalance > 0:
        weight = int(getattr(context.config, "empty_number_imbalance_weight", 1_000))
        objective_terms.append(("empty_number_imbalance", weight, imbalance))
        audit.count_objective_term("empty_number_imbalance")

