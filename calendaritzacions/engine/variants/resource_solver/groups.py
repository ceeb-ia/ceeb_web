"""Group sizing helpers for the resource solver."""

from __future__ import annotations

import math
from typing import Iterable

from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.types import GroupSpec, TeamRecord


def group_size_targets(
    num_teams: int,
    *,
    max_group_size: int = 8,
) -> tuple[int, ...]:
    if num_teams < 0:
        raise ValueError("num_teams must be non-negative")
    if max_group_size <= 0:
        raise ValueError("max_group_size must be positive")
    if num_teams == 0:
        return ()

    num_groups = math.ceil(num_teams / max_group_size)
    base_size, remainder = divmod(num_teams, num_groups)
    targets = [base_size + 1] * remainder + [base_size] * (num_groups - remainder)
    return tuple(targets)


def build_group_specs(
    teams: Iterable[TeamRecord],
    phase_name: str,
    config: ResourceSolverConfig,
    *,
    group_prefix: str = "G",
) -> tuple[GroupSpec, ...]:
    targets = group_size_targets(
        len(tuple(teams)),
        max_group_size=config.max_group_size,
    )
    return tuple(
        GroupSpec(
            group_id=f"{group_prefix}{index}",
            min_size=target_size,
            max_size=target_size,
            target_size=target_size,
            phase_name=phase_name,
        )
        for index, target_size in enumerate(targets, start=1)
    )


def empty_numbers_by_group(group_specs: Iterable[GroupSpec]) -> dict[str, int]:
    return {
        group.group_id: len(group.numbers) - group.target_size
        for group in group_specs
    }


def validate_common_phase(group_specs: Iterable[GroupSpec], phase_name: str) -> None:
    bad = [
        group.group_id
        for group in group_specs
        if group.phase_name != phase_name
    ]
    if bad:
        raise ValueError(
            f"All group specs must use phase {phase_name!r}; invalid groups: {bad}"
        )


__all__ = [
    "build_group_specs",
    "empty_numbers_by_group",
    "group_size_targets",
    "validate_common_phase",
]
