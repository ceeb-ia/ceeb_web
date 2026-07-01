"""Configuration for the resource solver engine."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any

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
    internal_solve_time_limit_seconds: float = field(
        default_factory=lambda: _env_float("CALENDARITZACIONS_SOLVER_INTERNAL_TIME_LIMIT_SECONDS", 900.0)
    )
    initial_solve_time_limit_seconds: float = field(
        default_factory=lambda: _env_float(
            "CALENDARITZACIONS_SOLVER_INITIAL_TIME_LIMIT_SECONDS",
            _env_float("CALENDARITZACIONS_SOLVER_TIME_LIMIT_SECONDS", 1800.0),
        )
    )
    repair_solve_time_limit_seconds: float = field(
        default_factory=lambda: _env_float(
            "CALENDARITZACIONS_SOLVER_REPAIR_TIME_LIMIT_SECONDS",
            _env_float("CALENDARITZACIONS_SOLVER_INTERNAL_TIME_LIMIT_SECONDS", 900.0),
        )
    )
    worker_time_limit_seconds: float = field(
        default_factory=lambda: _env_float(
            "CALENDARITZACIONS_SOLVER_WORKER_TIME_LIMIT_SECONDS",
            _env_float("CELERY_TASK_TIME_LIMIT", 0.0),
        )
    )
    finalization_margin_seconds: float = field(
        default_factory=lambda: _env_float("CALENDARITZACIONS_SOLVER_FINALIZATION_MARGIN_SECONDS", 1800.0)
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
    capacity_estimation_method: str = "ceil_half_min_one"
    local_explanation_threshold: int = 50_000
    linkage_mode: str = "off"
    linkage_violation_weight: int = 100_000
    calendar_mismatch_weight: int = 1_000_000
    linkage_number_warning_weight: int = 1_000
    linkage_max_group_size: int = 2
    pattern_master_local_min_patterns: int = 12
    pattern_master_local_max_patterns: int = 96
    pattern_master_local_patterns_per_team: int = 6
    pattern_master_local_patterns_per_linkage: int = 8
    pattern_master_local_base_solve_seconds: float = 3.0
    pattern_master_local_extra_seconds_per_team_over_8: float = 2.0
    pattern_master_solve_time_limit_seconds: float = field(
        default_factory=lambda: _env_float("CALENDARITZACIONS_PATTERN_MASTER_SOLVE_TIME_LIMIT_SECONDS", 0.0)
    )
    pattern_master_materialization_reserve_seconds: float = field(
        default_factory=lambda: _env_float("CALENDARITZACIONS_PATTERN_MASTER_MATERIALIZATION_RESERVE_SECONDS", 3600.0)
    )
    pattern_master_inline_materialization_max_terms: int = field(
        default_factory=lambda: _env_int("CALENDARITZACIONS_PATTERN_MASTER_INLINE_MATERIALIZATION_MAX_TERMS", 150_000)
    )
    initial_linkage_connector_mode: str = "off"
    intra_hub_cut_enabled: bool = True
    intra_hub_cut_min_teams: int = 10
    intra_hub_cut_max_rounds: int = 3
    local_linkage_repair_enabled: bool = True
    local_linkage_repair_max_iterations: int = 50
    local_linkage_repair_max_pair_evaluations: int = 500
    level_constraint_mode: str = "off"
    level_a_mismatch_weight: int = 1_000_000
    level_band_mismatch_weight: int = 200_000
    decomposition_mode: str = "audit_only"
    phase_name: str = "primera_fase"
    max_group_size: int = 8
    min_group_size: int = 6
    level_group_size_audit: tuple[dict[str, Any], ...] = ()
    competition_grouping: str = "auto"


def coerce_resource_solver_config(config: object | None = None) -> ResourceSolverConfig:
    """Return a ResourceSolverConfig, accepting the generic EngineConfig shape."""

    if isinstance(config, ResourceSolverConfig):
        return config
    engine_name = str(getattr(config, "name", "") or "")
    default_linkage_mode = (
        "input"
        if engine_name
        in {
            "resource_solver_linkage",
            "resource_solver_vinculacio",
            "resource_solver_conflict_repair",
            "resource_solver_pattern_master",
        }
        else "off"
    )
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
    competition_grouping = _normalize_competition_grouping(
        getattr(
            config,
            "resource_solver_competition_grouping",
            getattr(config, "competition_grouping", "auto"),
        )
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
        internal_solve_time_limit_seconds=float(
            getattr(
                config,
                "internal_solve_time_limit_seconds",
                _env_float("CALENDARITZACIONS_SOLVER_INTERNAL_TIME_LIMIT_SECONDS", 900.0),
            )
        ),
        initial_solve_time_limit_seconds=float(
            getattr(
                config,
                "initial_solve_time_limit_seconds",
                _env_float(
                    "CALENDARITZACIONS_SOLVER_INITIAL_TIME_LIMIT_SECONDS",
                    _env_float("CALENDARITZACIONS_SOLVER_TIME_LIMIT_SECONDS", 1800.0),
                ),
            )
        ),
        repair_solve_time_limit_seconds=float(
            getattr(
                config,
                "repair_solve_time_limit_seconds",
                _env_float(
                    "CALENDARITZACIONS_SOLVER_REPAIR_TIME_LIMIT_SECONDS",
                    _env_float("CALENDARITZACIONS_SOLVER_INTERNAL_TIME_LIMIT_SECONDS", 900.0),
                ),
            )
        ),
        worker_time_limit_seconds=float(
            getattr(
                config,
                "worker_time_limit_seconds",
                _env_float(
                    "CALENDARITZACIONS_SOLVER_WORKER_TIME_LIMIT_SECONDS",
                    _env_float("CELERY_TASK_TIME_LIMIT", 0.0),
                ),
            )
        ),
        finalization_margin_seconds=float(
            getattr(
                config,
                "finalization_margin_seconds",
                _env_float("CALENDARITZACIONS_SOLVER_FINALIZATION_MARGIN_SECONDS", 1800.0),
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
        calendar_mismatch_weight=int(getattr(config, "calendar_mismatch_weight", 1_000_000)),
        linkage_number_warning_weight=int(getattr(config, "linkage_number_warning_weight", 1_000)),
        linkage_max_group_size=int(getattr(config, "linkage_max_group_size", 2)),
        pattern_master_local_min_patterns=int(getattr(config, "pattern_master_local_min_patterns", 12)),
        pattern_master_local_max_patterns=int(getattr(config, "pattern_master_local_max_patterns", 96)),
        pattern_master_local_patterns_per_team=int(getattr(config, "pattern_master_local_patterns_per_team", 6)),
        pattern_master_local_patterns_per_linkage=int(getattr(config, "pattern_master_local_patterns_per_linkage", 8)),
        pattern_master_local_base_solve_seconds=float(
            getattr(config, "pattern_master_local_base_solve_seconds", 3.0)
        ),
        pattern_master_local_extra_seconds_per_team_over_8=float(
            getattr(config, "pattern_master_local_extra_seconds_per_team_over_8", 2.0)
        ),
        pattern_master_solve_time_limit_seconds=float(
            getattr(
                config,
                "pattern_master_solve_time_limit_seconds",
                _env_float("CALENDARITZACIONS_PATTERN_MASTER_SOLVE_TIME_LIMIT_SECONDS", 0.0),
            )
        ),
        pattern_master_materialization_reserve_seconds=float(
            getattr(
                config,
                "pattern_master_materialization_reserve_seconds",
                _env_float("CALENDARITZACIONS_PATTERN_MASTER_MATERIALIZATION_RESERVE_SECONDS", 3600.0),
            )
        ),
        pattern_master_inline_materialization_max_terms=int(
            getattr(
                config,
                "pattern_master_inline_materialization_max_terms",
                _env_int("CALENDARITZACIONS_PATTERN_MASTER_INLINE_MATERIALIZATION_MAX_TERMS", 150_000),
            )
        ),
        initial_linkage_connector_mode=_normalize_initial_linkage_connector_mode(
            getattr(
                config,
                "initial_linkage_connector_mode",
                os.getenv("CALENDARITZACIONS_SOLVER_INITIAL_LINKAGE_CONNECTOR_MODE", "off"),
            )
        ),
        intra_hub_cut_enabled=_coerce_bool(
            getattr(
                config,
                "intra_hub_cut_enabled",
                os.getenv("CALENDARITZACIONS_SOLVER_INTRA_HUB_CUT_ENABLED", "1"),
            ),
            default=True,
        ),
        intra_hub_cut_min_teams=int(
            getattr(
                config,
                "intra_hub_cut_min_teams",
                _env_int("CALENDARITZACIONS_SOLVER_INTRA_HUB_CUT_MIN_TEAMS", 10),
            )
        ),
        intra_hub_cut_max_rounds=int(
            getattr(
                config,
                "intra_hub_cut_max_rounds",
                _env_int("CALENDARITZACIONS_SOLVER_INTRA_HUB_CUT_MAX_ROUNDS", 3),
            )
        ),
        local_linkage_repair_enabled=_coerce_bool(
            getattr(
                config,
                "local_linkage_repair_enabled",
                os.getenv("CALENDARITZACIONS_SOLVER_LOCAL_LINKAGE_REPAIR_ENABLED", "1"),
            ),
            default=True,
        ),
        local_linkage_repair_max_iterations=int(
            getattr(
                config,
                "local_linkage_repair_max_iterations",
                _env_int("CALENDARITZACIONS_SOLVER_LOCAL_LINKAGE_REPAIR_MAX_ITERATIONS", 50),
            )
        ),
        local_linkage_repair_max_pair_evaluations=int(
            getattr(
                config,
                "local_linkage_repair_max_pair_evaluations",
                _env_int("CALENDARITZACIONS_SOLVER_LOCAL_LINKAGE_REPAIR_MAX_PAIR_EVALUATIONS", 500),
            )
        ),
        level_constraint_mode=str(level_constraint_mode or "off"),
        level_a_mismatch_weight=int(getattr(config, "level_a_mismatch_weight", 1_000_000)),
        level_band_mismatch_weight=int(getattr(config, "level_band_mismatch_weight", 200_000)),
        decomposition_mode=decomposition_mode,
        max_group_size=int(getattr(config, "max_group_size", 8)),
        min_group_size=int(getattr(config, "min_group_size", 6)),
        competition_grouping=competition_grouping,
    )


def with_level_group_size_audit(config: object, audit: tuple[dict[str, Any], ...]) -> object:
    """Return config carrying hard-level group planning audit rows."""

    if isinstance(config, ResourceSolverConfig):
        return replace(config, level_group_size_audit=audit)
    try:
        setattr(config, "level_group_size_audit", audit)
    except Exception:
        object.__setattr__(config, "level_group_size_audit", audit)
    return config


def _normalize_competition_grouping(value: object) -> str:
    mode = str(value or "auto").strip().casefold()
    if mode in {"", "auto", "default"}:
        return "auto"
    if mode in {"league", "lliga", "nom_lliga", "nom-lliga"}:
        return "league"
    if mode in {"fields", "camp", "camps", "modalitat", "modalitat_categoria_subcategoria"}:
        return "fields"
    return "auto"


def _normalize_initial_linkage_connector_mode(value: object) -> str:
    mode = str(value or "off").strip().casefold()
    if mode in {"", "off", "none", "repair", "repair_only", "no"}:
        return "off"
    if mode in {"large", "large_only", "current", "legacy"}:
        return "large"
    if mode in {"all", "on", "yes"}:
        return "all"
    return "off"


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().casefold()
    if text in {"1", "true", "yes", "on", "si", "sí"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default
