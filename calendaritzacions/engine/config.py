"""Engine configuration primitives."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineConfig:
    """Minimal engine selection configuration."""

    name: str = "legacy"
    phase_name: str = "primera_fase"
    resource_solver_level_constraint_mode: str = "off"
    resource_solver_linkage_mode: str = "default"
    resource_solver_decomposition_mode: str = "audit_only"
