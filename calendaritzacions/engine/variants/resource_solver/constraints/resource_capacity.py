"""Resource-capacity constraints based on real home matches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from calendaritzacions.engine.variants.resource_solver.constraints.base import (
    ConstraintAudit,
    ModelVariables,
    ObjectiveTerm,
    linear_sum,
)
from calendaritzacions.engine.variants.resource_solver.types import Candidate


@dataclass(frozen=True)
class ResourceCapacityConstraints:
    name: str = "resource_capacity"

    def add(
        self,
        model: Any,
        variables: ModelVariables,
        context: Any,
        objective_terms: list[ObjectiveTerm],
        audit: ConstraintAudit,
    ) -> None:
        add_resource_capacity_constraints(model, variables, context, objective_terms, audit)


def candidate_resource_by_round(candidate: Candidate) -> dict[int, str]:
    """Map each potential home round to the base resource consumed by the team."""

    rounds = tuple(candidate.potential_home_rounds)
    resources = tuple(candidate.potential_resources)
    if len(resources) == len(rounds):
        return dict(zip(rounds, resources))
    if len(resources) == 1:
        return {round_index: resources[0] for round_index in rounds}
    return {}


def capacity_for_resource(context: Any, resource_id: str) -> int:
    estimate = context.capacities.get(resource_id)
    if estimate is not None:
        return int(estimate.capacity)
    if "|J" in resource_id:
        base_id = resource_id.rsplit("|J", 1)[0]
        estimate = context.capacities.get(base_id)
        if estimate is not None:
            return int(estimate.capacity)
    base_id = resource_id.rsplit("::", 1)[0]
    estimate = context.capacities.get(base_id)
    if estimate is not None:
        return int(estimate.capacity)
    return 1


def add_resource_capacity_constraints(
    model: Any,
    variables: ModelVariables,
    context: Any,
    objective_terms: list[ObjectiveTerm],
    audit: ConstraintAudit,
) -> None:
    """Limit resource usage, counting only matches with an occupied opponent."""

    for candidate in variables.candidate_by_id.values():
        resource_by_round = candidate_resource_by_round(candidate)
        for round_index, resource_id in resource_by_round.items():
            opponent_number = candidate.opponent_number_by_round.get(round_index)
            if opponent_number is None:
                continue

            real_home = model.NewBoolVar(
                f"real_home_{candidate.candidate_id}_r{round_index}"
            )
            local = variables.x[candidate.candidate_id]
            opponent_occupied = variables.occupied[(candidate.group_id, opponent_number)]
            model.Add(real_home <= local)
            model.Add(real_home <= opponent_occupied)
            model.Add(real_home >= local + opponent_occupied - 1)
            variables.real_home[(candidate.candidate_id, round_index)] = real_home
            variables.resource_usage_terms.setdefault((resource_id, round_index), []).append(real_home)
            audit.count_constraint("real_home_indicator", 3)

    mode = getattr(context.config, "capacity_mode", "soft")
    weight = int(getattr(context.config, "resource_excess_weight", 100_000))
    for key, terms in sorted(variables.resource_usage_terms.items()):
        resource_id, round_index = key
        usage = linear_sum(terms)
        variables.resource_usage_counts[key] = usage
        capacity = capacity_for_resource(context, resource_id)
        if mode == "hard":
            model.Add(usage <= capacity)
            audit.count_constraint("hard_resource_capacity")
            continue

        excess = model.NewIntVar(0, len(terms), f"resource_excess_{resource_id}_r{round_index}")
        model.Add(excess >= usage - capacity)
        variables.resource_excess[key] = excess
        objective_terms.append(("resource_excess", weight, excess))
        audit.count_constraint("soft_resource_capacity")
        audit.count_objective_term("resource_excess")
