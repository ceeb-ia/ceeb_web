"""Balanced empty-number constraints."""

from __future__ import annotations

from collections import defaultdict
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

    flexible_group_ids = {
        group.group_id
        for group in context.groups
        if str(getattr(group, "size_bucket_id", "") or "")
    }
    empty_by_group: dict[str, int] = {
        group.group_id: len(group.numbers) - group.target_size
        for group in context.groups
        if group.group_id not in flexible_group_ids
    }
    mode = getattr(context.config, "empty_number_balance_mode", "hard")
    imbalances = []
    for group_ids in _competition_group_sets(context):
        counts = [empty_by_group[group_id] for group_id in group_ids if group_id in empty_by_group]
        if not counts:
            continue
        imbalances.append(max(counts) - min(counts))

    if mode == "hard":
        if any(imbalance > 1 for imbalance in imbalances):
            model.Add(0 == 1)
        audit.count_constraint("balanced_empty_numbers")
        return

    imbalance = sum(imbalances)
    if imbalance > 0:
        weight = int(getattr(context.config, "empty_number_imbalance_weight", 1_000))
        objective_terms.append(("empty_number_imbalance", weight, imbalance))
        audit.count_objective_term("empty_number_imbalance")


def _competition_group_sets(context: Any) -> tuple[tuple[str, ...], ...]:
    team_to_groups: dict[str, set[str]] = defaultdict(set)
    group_to_teams: dict[str, set[str]] = defaultdict(set)
    for candidate in context.candidates:
        team_to_groups[candidate.team_id].add(candidate.group_id)
        group_to_teams[candidate.group_id].add(candidate.team_id)

    if not group_to_teams:
        return (tuple(group.group_id for group in context.groups),)

    seen: set[tuple[str, ...]] = set()
    group_sets: list[tuple[str, ...]] = []
    for group_id, team_ids in sorted(group_to_teams.items()):
        related = tuple(
            sorted(
                {
                    related_group_id
                    for team_id in team_ids
                    for related_group_id in team_to_groups.get(team_id, set())
                }
            )
        )
        if related and related not in seen:
            seen.add(related)
            group_sets.append(related)
    return tuple(group_sets)
