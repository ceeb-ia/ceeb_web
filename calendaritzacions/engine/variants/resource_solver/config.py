"""Configuration for the resource solver engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceSolverConfig:
    """Runtime settings for the resource solver MVP."""

    time_limit_seconds: float = 30.0
    capacity_mode: str = "soft"
    resource_excess_weight: int = 100_000
    entity_excess_weight: int = 10_000
    empty_number_balance_mode: str = "hard"
    empty_number_imbalance_weight: int = 1_000
    capacity_estimation_method: str = "max_demand_half_minus_one"
    local_explanation_threshold: int = 50_000
    phase_name: str = "primera_fase"
    max_group_size: int = 8
    min_group_size: int = 6


def coerce_resource_solver_config(config: object | None = None) -> ResourceSolverConfig:
    """Return a ResourceSolverConfig, accepting the generic EngineConfig shape."""

    if isinstance(config, ResourceSolverConfig):
        return config
    return ResourceSolverConfig(
        phase_name=getattr(config, "phase_name", "primera_fase"),
    )

