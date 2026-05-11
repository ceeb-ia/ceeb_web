"""Configuration for the resource solver engine."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ResourceSolverConfig:
    """Runtime settings for the resource solver MVP."""

    time_limit_seconds: float = field(
        default_factory=lambda: _env_float("CALENDARITZACIONS_SOLVER_TIME_LIMIT_SECONDS", 1800.0)
    )
    num_search_workers: int = field(
        default_factory=lambda: _env_int("CALENDARITZACIONS_SOLVER_NUM_SEARCH_WORKERS", 2)
    )
    capacity_mode: str = "soft"
    resource_excess_weight: int = 100_000
    entity_excess_weight: int = 10_000
    empty_number_balance_mode: str = "hard"
    empty_number_imbalance_weight: int = 1_000
    capacity_estimation_method: str = "floor_half_min_one"
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
        time_limit_seconds=float(
            getattr(
                config,
                "time_limit_seconds",
                _env_float("CALENDARITZACIONS_SOLVER_TIME_LIMIT_SECONDS", 1800.0),
            )
        ),
        num_search_workers=int(
            getattr(
                config,
                "num_search_workers",
                _env_int("CALENDARITZACIONS_SOLVER_NUM_SEARCH_WORKERS", 2),
            )
        ),
    )
