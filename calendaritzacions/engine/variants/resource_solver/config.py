"""Configuration for the resource solver engine."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DECOMPOSITION_MODES = frozenset({"off", "audit_only", "persist_components", "solve_components"})


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
    max_memory_mb: int = field(
        default_factory=lambda: _env_int("CALENDARITZACIONS_SOLVER_MAX_MEMORY_MB", 0)
    )
    capacity_mode: str = "soft"
    resource_excess_weight: int = 100_000
    entity_excess_weight: int = 10_000
    empty_number_balance_mode: str = "hard"
    empty_number_imbalance_weight: int = 1_000
    capacity_estimation_method: str = "floor_half_min_one"
    local_explanation_threshold: int = 50_000
    linkage_mode: str = "off"
    linkage_violation_weight: int = 100_000
    linkage_max_group_size: int = 2
    level_constraint_mode: str = "off"
    level_a_mismatch_weight: int = 1_000_000
    level_band_mismatch_weight: int = 200_000
    decomposition_mode: str = "audit_only"
    phase_name: str = "primera_fase"
    max_group_size: int = 8
    min_group_size: int = 6


def coerce_resource_solver_config(config: object | None = None) -> ResourceSolverConfig:
    """Return a ResourceSolverConfig, accepting the generic EngineConfig shape."""

    if isinstance(config, ResourceSolverConfig):
        return config
    engine_name = str(getattr(config, "name", "") or "")
    default_linkage_mode = "input" if engine_name in {"resource_solver_linkage", "resource_solver_vinculacio"} else "off"
    explicit_linkage_mode = getattr(
        config,
        "resource_solver_linkage_mode",
        getattr(config, "linkage_mode", "default"),
    )
    if str(explicit_linkage_mode or "default").strip().casefold() in {"", "default", "auto"}:
        linkage_mode = default_linkage_mode
    else:
        linkage_mode = str(explicit_linkage_mode)
    level_constraint_mode = getattr(
        config,
        "resource_solver_level_constraint_mode",
        getattr(config, "level_constraint_mode", "off"),
    )
    decomposition_mode = getattr(
        config,
        "resource_solver_decomposition_mode",
        getattr(config, "decomposition_mode", "audit_only"),
    )
    decomposition_mode = str(decomposition_mode or "audit_only").strip()
    if decomposition_mode not in DECOMPOSITION_MODES:
        raise ValueError(
            "Invalid resource_solver decomposition_mode "
            f"{decomposition_mode!r}; expected one of {sorted(DECOMPOSITION_MODES)}"
        )
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
        max_memory_mb=int(
            getattr(
                config,
                "max_memory_mb",
                _env_int("CALENDARITZACIONS_SOLVER_MAX_MEMORY_MB", 0),
            )
        ),
        linkage_mode=linkage_mode,
        linkage_violation_weight=int(getattr(config, "linkage_violation_weight", 100_000)),
        linkage_max_group_size=int(getattr(config, "linkage_max_group_size", 2)),
        level_constraint_mode=str(level_constraint_mode or "off"),
        level_a_mismatch_weight=int(getattr(config, "level_a_mismatch_weight", 1_000_000)),
        level_band_mismatch_weight=int(getattr(config, "level_band_mismatch_weight", 200_000)),
        decomposition_mode=decomposition_mode,
    )
