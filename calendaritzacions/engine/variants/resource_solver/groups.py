"""Group sizing helpers for the resource solver."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.types import GroupSpec, TeamRecord

IDEAL_MIN_GROUP_SIZE = 6
IDEAL_MAX_GROUP_SIZE = 8
EXCEPTIONAL_MAX_GROUP_SIZE = 10
DEFAULT_NUMBERS = tuple(range(1, 9))
EXCEPTIONAL_NUMBERS = tuple(range(1, 11))
HARD_LEVEL_FAMILIES = ("A", "B", "C")


@dataclass(frozen=True)
class HardLevelGroupPlan:
    groups: tuple[GroupSpec, ...]
    groups_by_family: dict[str, tuple[GroupSpec, ...]]
    audit: tuple[dict[str, object], ...]


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


def structural_group_size_targets(num_teams: int) -> tuple[int, ...]:
    """Plan sizes for hard structural groups.

    Ideal groups have 6-8 teams and are always preferred when a complete
    partition exists. A 9-10 team group is considered only for gap totals where
    no all-ideal partition exists.
    """

    if num_teams < 0:
        raise ValueError("num_teams must be non-negative")
    if num_teams == 0:
        return ()

    ideal_targets = _bounded_group_size_targets(
        num_teams,
        min_size=IDEAL_MIN_GROUP_SIZE,
        max_size=IDEAL_MAX_GROUP_SIZE,
    )
    if ideal_targets:
        return ideal_targets

    best: tuple[tuple[int, int, int, int, int], tuple[int, ...]] | None = None
    for num_groups in range(math.ceil(num_teams / EXCEPTIONAL_MAX_GROUP_SIZE), num_teams + 1):
        sizes = _balanced_descending_sizes(num_teams, num_groups)
        if not sizes or sizes[0] > EXCEPTIONAL_MAX_GROUP_SIZE:
            continue
        small_deficit = sum(max(0, IDEAL_MIN_GROUP_SIZE - size) for size in sizes)
        small_groups = sum(1 for size in sizes if size < IDEAL_MIN_GROUP_SIZE)
        exceptional_extra = sum(max(0, size - IDEAL_MAX_GROUP_SIZE) for size in sizes)
        exceptional_groups = sum(1 for size in sizes if size > IDEAL_MAX_GROUP_SIZE)
        score = (
            small_groups,
            small_deficit,
            exceptional_groups,
            exceptional_extra,
            num_groups,
        )
        if best is None or score < best[0]:
            best = (score, sizes)

    if best is None:
        return (num_teams,)
    return best[1]


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
            numbers=_numbers_for_target_size(target_size),
        )
        for index, target_size in enumerate(targets, start=1)
    )


def build_hard_level_group_plan(
    teams: Iterable[TeamRecord],
    phase_name: str,
    *,
    group_prefix: str = "G",
) -> HardLevelGroupPlan:
    """Build level-family groups for hard mode and return planner audit rows."""

    sorted_teams = tuple(sorted(teams, key=lambda team: team.team_id))
    fixed_counts = {"A": 0, "B": 0, "C": 0}
    flexible_count = 0
    for team in sorted_teams:
        family = normalize_hard_level(getattr(team, "level", ""))
        if family == "B/C":
            flexible_count += 1
        else:
            fixed_counts[family] += 1

    flex_to_b = _choose_flexible_b_allocation(fixed_counts["B"], fixed_counts["C"], flexible_count)
    planned_counts = {
        "A": fixed_counts["A"],
        "B": fixed_counts["B"] + flex_to_b,
        "C": fixed_counts["C"] + flexible_count - flex_to_b,
    }

    groups: list[GroupSpec] = []
    groups_by_family: dict[str, tuple[GroupSpec, ...]] = {}
    audit_rows: list[dict[str, object]] = []
    for family in HARD_LEVEL_FAMILIES:
        targets = structural_group_size_targets(planned_counts[family])
        family_groups = tuple(
            GroupSpec(
                group_id=f"{group_prefix}_{family}_G{index}",
                min_size=target_size,
                max_size=target_size,
                target_size=target_size,
                phase_name=phase_name,
                numbers=_numbers_for_target_size(target_size),
            )
            for index, target_size in enumerate(targets, start=1)
        )
        groups.extend(family_groups)
        groups_by_family[family] = family_groups
        audit_rows.extend(
            _audit_rows_for_targets(
                family=family,
                planned_count=planned_counts[family],
                targets=targets,
                group_prefix=group_prefix,
            )
        )

    if flexible_count:
        audit_rows.append(
            {
                "type": "level_flexible_allocation",
                "group_prefix": group_prefix,
                "level": "B/C",
                "flexible_teams": flexible_count,
                "assigned_to_B_capacity": flex_to_b,
                "assigned_to_C_capacity": flexible_count - flex_to_b,
            }
        )
    return HardLevelGroupPlan(
        groups=tuple(groups),
        groups_by_family=groups_by_family,
        audit=tuple(audit_rows),
    )


def hard_level_candidate_families(team: TeamRecord) -> tuple[str, ...]:
    level = normalize_hard_level(getattr(team, "level", ""))
    if level == "B/C":
        return ("B", "C")
    return (level,)


def normalize_hard_level(value: object) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return "B/C"
    if re.search(r"\bB\s*[-/]\s*C\b", text):
        return "B/C"
    match = re.search(r"\b([A-E])\b", text)
    if not match:
        match = re.search(r"(?:NIVELL\s*)?([A-E])\s*$", text)
    if not match:
        return "B/C"
    return {"A": "A", "B": "B", "C": "B/C", "D": "B/C", "E": "C"}[match.group(1)]


def _choose_flexible_b_allocation(b_count: int, c_count: int, flexible_count: int) -> int:
    if flexible_count <= 0:
        return 0

    best: tuple[tuple[int, ...], int] | None = None
    for flex_to_b in range(flexible_count + 1):
        b_targets = structural_group_size_targets(b_count + flex_to_b)
        c_targets = structural_group_size_targets(c_count + flexible_count - flex_to_b)
        connected_targets = b_targets + c_targets
        empty_counts = [_empty_count_for_target(size) for size in connected_targets]
        empty_imbalance = max(empty_counts, default=0) - min(empty_counts, default=0)
        small_groups = sum(1 for size in connected_targets if size < IDEAL_MIN_GROUP_SIZE)
        small_deficit = sum(max(0, IDEAL_MIN_GROUP_SIZE - size) for size in connected_targets)
        exceptional_groups = sum(1 for size in connected_targets if size > IDEAL_MAX_GROUP_SIZE)
        exceptional_extra = sum(max(0, size - IDEAL_MAX_GROUP_SIZE) for size in connected_targets)
        total_groups = len(connected_targets)
        balance = abs((b_count + flex_to_b) - (c_count + flexible_count - flex_to_b))
        score = (
            1 if empty_imbalance > 1 else 0,
            small_groups,
            small_deficit,
            exceptional_groups,
            exceptional_extra,
            total_groups,
            balance,
            flex_to_b,
        )
        if best is None or score < best[0]:
            best = (score, flex_to_b)
    return best[1] if best is not None else 0


def _balanced_descending_sizes(num_teams: int, num_groups: int) -> tuple[int, ...]:
    if num_groups <= 0:
        return ()
    base_size, remainder = divmod(num_teams, num_groups)
    if base_size <= 0:
        return ()
    return tuple([base_size + 1] * remainder + [base_size] * (num_groups - remainder))


def _bounded_group_size_targets(num_teams: int, *, min_size: int, max_size: int) -> tuple[int, ...]:
    for num_groups in range(math.ceil(num_teams / max_size), math.floor(num_teams / min_size) + 1):
        sizes = _balanced_descending_sizes(num_teams, num_groups)
        if sizes and min(sizes) >= min_size and max(sizes) <= max_size:
            return sizes
    return ()


def _numbers_for_target_size(target_size: int) -> tuple[int, ...]:
    return EXCEPTIONAL_NUMBERS if target_size > IDEAL_MAX_GROUP_SIZE else DEFAULT_NUMBERS


def _empty_count_for_target(target_size: int) -> int:
    return len(_numbers_for_target_size(target_size)) - target_size


def _audit_rows_for_targets(
    *,
    family: str,
    planned_count: int,
    targets: tuple[int, ...],
    group_prefix: str,
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for index, target in enumerate(targets, start=1):
        if target >= IDEAL_MIN_GROUP_SIZE:
            continue
        rows.append(
            {
                "type": "level_group_size_warning",
                "severity": "warning",
                "reason": "small_group_unavoidable",
                "group_prefix": group_prefix,
                "family": family,
                "group_id": f"{group_prefix}_{family}_G{index}",
                "planned_family_count": planned_count,
                "target_size": target,
            }
        )
    return tuple(rows)


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
    "HardLevelGroupPlan",
    "build_group_specs",
    "build_hard_level_group_plan",
    "empty_numbers_by_group",
    "group_size_targets",
    "hard_level_candidate_families",
    "normalize_hard_level",
    "structural_group_size_targets",
    "validate_common_phase",
]
