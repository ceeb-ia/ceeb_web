"""Compatibility graph helpers for pattern-master candidates."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from typing import Any, Iterable

from calendaritzacions.engine.variants.resource_solver.pattern_master.patterns import (
    competition_number_capacity,
    pattern_slot_domain_number_counts,
    slot_domain_number_capacity,
)
from calendaritzacions.engine.variants.resource_solver.pattern_master.types import HubPattern, PatternConflict
from calendaritzacions.engine.variants.resource_solver.types import SolverContext


def build_pattern_conflicts(
    context: SolverContext,
    patterns: Iterable[HubPattern],
) -> tuple[PatternConflict, ...]:
    """Return genuinely binary hard conflicts.

    Capacity pressure is intentionally not encoded as pairwise exclusions here:
    the master owns those decisions through aggregate constraints and soft costs.
    """

    return ()


def compatibility_payload(
    context: SolverContext,
    patterns: Iterable[HubPattern],
    conflicts: Iterable[PatternConflict],
) -> dict[str, Any]:
    pattern_rows = tuple(patterns)
    conflict_rows = tuple(conflicts)
    return {
        "artifact_type": "resource_solver_pattern_master_compatibility_graph",
        "pattern_count": len(pattern_rows),
        "conflict_count": len(conflict_rows),
        "competition_number_capacity": {
            competition_key: {str(number): capacity for number, capacity in counts.items()}
            for competition_key, counts in competition_number_capacity(context).items()
        },
        "slot_domain_number_capacity": {
            domain_key: {str(number): capacity for number, capacity in counts.items()}
            for domain_key, counts in slot_domain_number_capacity(context).items()
        },
        "conflicts": [_conflict_payload(conflict) for conflict in conflict_rows],
        "aggregate_constraints": _aggregate_constraints_payload(context, pattern_rows),
    }


def _aggregate_constraints_payload(context: SolverContext, patterns: tuple[HubPattern, ...]) -> list[dict[str, Any]]:
    owners: dict[tuple[str, int], list[str]] = defaultdict(list)
    for pattern in patterns:
        for competition_key, counts in pattern.competition_number_counts.items():
            for number, count in counts.items():
                if int(count) > 0:
                    owners[(competition_key, int(number))].append(pattern.pattern_id)
    payload = [
        {
            "type": "competition_number_capacity",
            "competition_key": competition_key,
            "number": number,
            "pattern_ids": sorted(pattern_ids),
        }
        for (competition_key, number), pattern_ids in sorted(owners.items())
    ]

    domain_owners: dict[tuple[str, int], list[str]] = defaultdict(list)
    for pattern in patterns:
        domain_counts = pattern_slot_domain_number_counts(context, pattern)
        for domain_key, counts in domain_counts.items():
            for number, count in counts.items():
                if int(count) > 0:
                    domain_owners[(domain_key, int(number))].append(pattern.pattern_id)
    payload.extend(
        {
            "type": "slot_domain_number_capacity",
            "domain_key": domain_key,
            "number": number,
            "pattern_ids": sorted(pattern_ids),
        }
        for (domain_key, number), pattern_ids in sorted(domain_owners.items())
    )
    return payload


def _conflict_payload(conflict: PatternConflict) -> dict[str, Any]:
    return asdict(conflict)


__all__ = ["build_pattern_conflicts", "compatibility_payload"]
