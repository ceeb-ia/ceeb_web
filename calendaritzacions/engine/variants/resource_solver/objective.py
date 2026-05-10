"""Objective construction for the resource solver."""

from __future__ import annotations

from typing import Any

from calendaritzacions.engine.variants.resource_solver.constraints.base import ObjectiveTerm


def build_objective_expression(objective_terms: list[ObjectiveTerm]) -> Any:
    """Build a CP-SAT objective expression from weighted terms."""

    expression = 0
    for _name, weight, term in objective_terms:
        expression += int(weight) * term
    return expression


def objective_summary(objective_terms: list[ObjectiveTerm]) -> dict[str, int]:
    """Return JSON-ready counts by objective family."""

    summary: dict[str, int] = {}
    for name, _weight, _term in objective_terms:
        summary[name] = summary.get(name, 0) + 1
    return summary


def objective_weights(objective_terms: list[ObjectiveTerm]) -> dict[str, int]:
    """Return the configured weight by objective family."""

    weights: dict[str, int] = {}
    for name, weight, _term in objective_terms:
        weights[name] = int(weight)
    return weights

