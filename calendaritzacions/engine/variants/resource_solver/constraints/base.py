"""Shared helpers for resource-solver constraint builders."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from calendaritzacions.engine.variants.resource_solver.types import Candidate


ObjectiveTerm = tuple[str, int, Any]


@dataclass
class ModelVariables:
    """Variable registry shared by the CP-SAT constraint modules."""

    x: dict[str, Any]
    candidate_by_id: dict[str, Candidate]
    candidates_by_team: dict[str, list[Candidate]]
    candidates_by_group_number: dict[tuple[str, int], list[Candidate]]
    occupied: dict[tuple[str, int], Any] = field(default_factory=dict)
    real_home: dict[tuple[str, int], Any] = field(default_factory=dict)
    entity_excess: dict[tuple[str, str], Any] = field(default_factory=dict)
    resource_excess: dict[tuple[str, int], Any] = field(default_factory=dict)
    resource_usage_terms: dict[tuple[str, int], list[Any]] = field(default_factory=dict)
    resource_usage_counts: dict[tuple[str, int], Any] = field(default_factory=dict)


@dataclass
class ConstraintAudit:
    """Small JSON-ready counters emitted while building constraints."""

    constraints: dict[str, int] = field(default_factory=dict)
    objective_terms: dict[str, int] = field(default_factory=dict)

    def count_constraint(self, name: str, amount: int = 1) -> None:
        self.constraints[name] = self.constraints.get(name, 0) + amount

    def count_objective_term(self, name: str, amount: int = 1) -> None:
        self.objective_terms[name] = self.objective_terms.get(name, 0) + amount


class ConstraintBuilder(Protocol):
    name: str

    def add(
        self,
        model: Any,
        variables: ModelVariables,
        context: Any,
        objective_terms: list[ObjectiveTerm],
        audit: ConstraintAudit,
    ) -> None:
        ...


def linear_sum(items: list[Any]) -> Any:
    """Return a CP-SAT friendly sum, preserving an integer zero for empties."""

    if not items:
        return 0
    return sum(items)

