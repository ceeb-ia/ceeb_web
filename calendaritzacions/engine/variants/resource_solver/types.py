"""Shared data contracts for the resource solver."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from calendaritzacions.domain.phases import CalendarPhase


@dataclass(frozen=True)
class TeamRecord:
    team_id: str
    name: str
    entity: str
    league_name: str
    modality: str = ""
    category: str = ""
    subcategory: str = ""
    level: str = ""
    venue: str = ""
    day: str = ""
    time: str = ""
    seed_request_original: Any = ""
    linkage_group: str = ""
    linkage_side: str = ""
    linkage_source: str = ""


@dataclass(frozen=True)
class BaseResource:
    resource_id: str
    venue: str
    day: str
    hour_slot: str


@dataclass(frozen=True)
class TimedResource:
    resource_id: str
    base_resource_id: str
    venue: str
    day: str
    hour_slot: str
    round_index: int
    date: str | None = None


@dataclass(frozen=True)
class CapacityEstimate:
    base_resource_id: str
    capacity: int
    method: str
    demand_count: int


@dataclass(frozen=True)
class PressureRow:
    base_resource_id: str
    venue: str
    day: str
    hour_slot: str
    team_ids: tuple[str, ...]
    demand_count: int
    estimated_capacity: int
    pressure: float
    capacity_method: str
    is_critical: bool


@dataclass(frozen=True)
class GroupSpec:
    group_id: str
    min_size: int
    max_size: int
    target_size: int
    phase_name: str
    numbers: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    team_id: str
    group_id: str
    number: int
    seed_request_original: Any
    potential_home_rounds: tuple[int, ...]
    opponent_number_by_round: dict[int, int]
    potential_resources: tuple[str, ...]


@dataclass(frozen=True)
class SolverContext:
    teams: tuple[TeamRecord, ...]
    phase: CalendarPhase
    phase_name: str
    base_resources: dict[str, BaseResource]
    capacities: dict[str, CapacityEstimate]
    pressure: tuple[PressureRow, ...]
    groups: tuple[GroupSpec, ...]
    candidates: tuple[Candidate, ...]
    config: Any


@dataclass(frozen=True)
class Assignment:
    team_id: str
    group_id: str
    number: int


@dataclass(frozen=True)
class RealMatch:
    round_index: int
    group_id: str
    home_team_id: str
    away_team_id: str
    home_number: int
    away_number: int
    resource_id: str


@dataclass(frozen=True)
class ResourceUsage:
    resource_id: str
    locals_count: int
    capacity: int
    excess: int
    team_ids: tuple[str, ...]


@dataclass(frozen=True)
class GroupSummary:
    group_id: str
    assigned_numbers: dict[int, str]
    empty_numbers: tuple[int, ...]
    rests_by_team: dict[str, tuple[int, ...]]
    entity_excess: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ResourceSolverResult:
    status: str
    objective_value: float | None
    best_bound: float | None
    wall_time: float
    assignments: tuple[Assignment, ...]
    real_matches: tuple[RealMatch, ...]
    resource_usage: tuple[ResourceUsage, ...]
    group_summary: tuple[GroupSummary, ...]
    entity_excess: dict[tuple[str, str], int]
    audit_payloads: dict[str, Any] = field(default_factory=dict)
    logs: tuple[str, ...] = ()
