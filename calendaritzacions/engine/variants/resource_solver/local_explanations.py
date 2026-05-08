"""Optional local explanations for critical resource blocks."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from calendaritzacions.engine.variants.resource_solver.types import (
    ResourceSolverResult,
    SolverContext,
)


def build_local_explanations(
    result: ResourceSolverResult,
    context: SolverContext,
) -> list[dict[str, Any]]:
    """Build lightweight local resource explanations.

    This intentionally does not decide numbers or prove optimality. It reports
    solver usage for blocks that are critical, saturated or have excess, and it
    skips enumeration when the local option product exceeds the configured
    threshold.
    """

    threshold = int(getattr(context.config, "local_explanation_threshold", 50_000) or 50_000)
    assignments_by_team = {assignment.team_id: assignment for assignment in result.assignments}
    usage_by_base = _usage_by_base(result)
    explanations: list[dict[str, Any]] = []

    for pressure in sorted(context.pressure, key=lambda row: row.base_resource_id):
        block_usage = usage_by_base.get(pressure.base_resource_id, [])
        has_excess = any(item["excess"] > 0 for item in block_usage)
        is_saturated = any(item["locals_count"] >= item["capacity"] for item in block_usage)
        if not (pressure.is_critical or has_excess or is_saturated):
            continue

        option_product = _option_product(pressure.team_ids, context)
        enumerated = option_product <= threshold
        explanations.append(
            {
                "resource_id": pressure.base_resource_id,
                "venue": pressure.venue,
                "day": pressure.day,
                "hour_slot": pressure.hour_slot,
                "capacity": pressure.estimated_capacity,
                "input_pressure": pressure.pressure,
                "team_ids": list(pressure.team_ids),
                "option_product": option_product,
                "enumerated": enumerated,
                "skip_reason": None
                if enumerated
                else f"option_product_above_threshold:{threshold}",
                "solver_solution_local": [
                    {
                        "team_id": team_id,
                        "group_id": assignments_by_team[team_id].group_id,
                        "number": assignments_by_team[team_id].number,
                    }
                    for team_id in pressure.team_ids
                    if team_id in assignments_by_team
                ],
                "round_usage": block_usage,
                "nearby_alternatives": _nearby_alternatives(enumerated, has_excess),
            }
        )
    return explanations


def _usage_by_base(result: ResourceSolverResult) -> dict[str, list[dict[str, Any]]]:
    usage_by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for usage in result.resource_usage:
        base_id, round_index = _split_timed_resource_id(usage.resource_id)
        usage_by_base[base_id].append(
            {
                "resource_id": usage.resource_id,
                "round_index": round_index,
                "locals_count": usage.locals_count,
                "capacity": usage.capacity,
                "excess": usage.excess,
                "teams": list(usage.team_ids),
            }
        )
    for rows in usage_by_base.values():
        rows.sort(key=lambda item: (item["round_index"] or 0, item["resource_id"]))
    return usage_by_base


def _option_product(team_ids: tuple[str, ...], context: SolverContext) -> int:
    options_by_team: dict[str, int] = defaultdict(int)
    team_set = set(team_ids)
    for candidate in context.candidates:
        if candidate.team_id in team_set:
            options_by_team[candidate.team_id] += 1
    product = 1
    for team_id in team_ids:
        product *= max(1, options_by_team.get(team_id, 1))
    return product


def _nearby_alternatives(enumerated: bool, has_excess: bool) -> list[dict[str, Any]]:
    if not enumerated:
        return []
    if not has_excess:
        return [
            {
                "kind": "not_needed",
                "reason": "solver_solution_has_no_capacity_excess_for_this_block",
            }
        ]
    return [
        {
            "kind": "not_enumerated_in_mvp",
            "reason": "local alternatives are explanatory only; CP-SAT remains the source of optimality",
        }
    ]


def _split_timed_resource_id(resource_id: str) -> tuple[str, int | None]:
    if "::R" not in resource_id:
        return resource_id, None
    base_id, suffix = resource_id.rsplit("::R", 1)
    try:
        return base_id, int(suffix)
    except ValueError:
        return base_id, None
