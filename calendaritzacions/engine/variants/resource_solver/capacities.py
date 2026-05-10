"""Capacity estimation and resource pressure for the resource solver."""

from __future__ import annotations

import math
from typing import Iterable

from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.resources import teams_by_base_resource
from calendaritzacions.engine.variants.resource_solver.types import (
    BaseResource,
    CapacityEstimate,
    PressureRow,
    TeamRecord,
)


def estimate_capacity_from_demand(demand_count: int) -> int:
    return max(1, math.floor(demand_count / 2 - 1))


def estimate_capacities(
    resources: dict[str, BaseResource],
    teams: Iterable[TeamRecord],
    config: ResourceSolverConfig,
) -> dict[str, CapacityEstimate]:
    grouped = teams_by_base_resource(teams)
    capacities: dict[str, CapacityEstimate] = {}
    for resource_id in resources:
        demand_count = len(grouped.get(resource_id, ()))
        capacities[resource_id] = CapacityEstimate(
            base_resource_id=resource_id,
            capacity=estimate_capacity_from_demand(demand_count),
            method=config.capacity_estimation_method,
            demand_count=demand_count,
        )
    return dict(sorted(capacities.items()))


def build_resource_pressure(
    resources: dict[str, BaseResource],
    teams: Iterable[TeamRecord],
    capacities: dict[str, CapacityEstimate],
) -> tuple[PressureRow, ...]:
    grouped = teams_by_base_resource(teams)
    rows: list[PressureRow] = []
    for resource_id, resource in resources.items():
        resource_teams = grouped.get(resource_id, ())
        capacity = capacities[resource_id]
        pressure = (
            len(resource_teams) / capacity.capacity
            if capacity.capacity > 0
            else float("inf")
        )
        rows.append(
            PressureRow(
                base_resource_id=resource_id,
                venue=resource.venue,
                day=resource.day,
                hour_slot=resource.hour_slot,
                team_ids=tuple(team.team_id for team in resource_teams),
                demand_count=len(resource_teams),
                estimated_capacity=capacity.capacity,
                pressure=pressure,
                capacity_method=capacity.method,
                is_critical=pressure > 1.0,
            )
        )
    return tuple(rows)


__all__ = [
    "build_resource_pressure",
    "estimate_capacities",
    "estimate_capacity_from_demand",
]
