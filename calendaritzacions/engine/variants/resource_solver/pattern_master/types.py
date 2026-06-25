"""Data contracts for the pattern-master resource solver variant."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from calendaritzacions.engine.variants.resource_solver.types import Assignment


@dataclass(frozen=True)
class MicroHub:
    hub_id: str
    team_ids: tuple[str, ...]
    resource_keys: tuple[str, ...] = ()
    linkage_keys: tuple[str, ...] = ()
    competition_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class PatternAssignment:
    team_id: str
    number: int


@dataclass(frozen=True)
class HubPattern:
    pattern_id: str
    hub_id: str
    assignments: tuple[PatternAssignment, ...]
    cost: int
    cost_breakdown: dict[str, int] = field(default_factory=dict)
    resource_usage: dict[str, int] = field(default_factory=dict)
    competition_number_counts: dict[str, dict[int, int]] = field(default_factory=dict)
    variant: str = "base"


@dataclass(frozen=True)
class PatternConflict:
    left_pattern_id: str
    right_pattern_id: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MasterSelection:
    status: str
    selected_pattern_ids: tuple[str, ...]
    objective_value: float | None = None
    materialized_assignments: tuple[Assignment, ...] = ()
    conflicts: tuple[PatternConflict, ...] = ()
    logs: tuple[str, ...] = ()


__all__ = [
    "HubPattern",
    "MasterSelection",
    "MicroHub",
    "PatternAssignment",
    "PatternConflict",
]
