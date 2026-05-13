"""JSON-ready audit payloads for the resource solver."""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from calendaritzacions.engine.variants.resource_solver.solution import result_to_json_ready
from calendaritzacions.engine.variants.resource_solver.constraints.level_band import (
    level_constraint_enabled,
    level_mismatch_family,
    level_mismatch_weight,
    normalize_level,
)
from calendaritzacions.engine.variants.resource_solver.types import (
    ResourceSolverResult,
    SolverContext,
)

try:
    from calendaritzacions.engine.variants.resource_solver import linkage as _linkage_helpers
except Exception:  # pragma: no cover - linkage helpers may be absent in older checkouts.
    _linkage_helpers = None


def build_audit_payloads(
    result: ResourceSolverResult,
    context: SolverContext,
    raw_result: Any | None = None,
    built_model: Any | None = None,
    local_explanations: Any | None = None,
) -> dict[str, Any]:
    """Build all standard resource solver audit payloads."""

    payloads = {
        "team_catalog": build_team_catalog_audit(context),
        "resource_pressure": build_resource_pressure_audit(context),
        "candidate_catalog": build_candidate_catalog_audit(context),
        "solver_model_summary": build_solver_model_summary(raw_result, built_model, context, result),
        "resource_solution": build_resource_solution_audit(result),
        "solver_explanations": build_solver_explanations(result, context),
    }
    if local_explanations is not None:
        payloads["local_combinations"] = json_ready(local_explanations)
    return json_ready(payloads)


def build_team_catalog_audit(context: SolverContext) -> list[dict[str, Any]]:
    return [
        {
            "team_id": team.team_id,
            "name": team.name,
            "entity": team.entity,
            "league_name": team.league_name,
            "modality": team.modality,
            "category": team.category,
            "subcategory": team.subcategory,
            "level": team.level,
            "venue": team.venue,
            "day": team.day,
            "time": team.time,
            "seed_request_original": team.seed_request_original,
            **_linkage_fields(team),
        }
        for team in context.teams
    ]


def build_resource_pressure_audit(context: SolverContext) -> list[dict[str, Any]]:
    return [
        {
            "resource_id": row.base_resource_id,
            "venue": row.venue,
            "day": row.day,
            "hour_slot": row.hour_slot,
            "teams": list(row.team_ids),
            "demand_count": row.demand_count,
            "estimated_capacity": row.estimated_capacity,
            "pressure": row.pressure,
            "capacity_method": row.capacity_method,
            "is_critical": row.is_critical,
        }
        for row in context.pressure
    ]


def build_candidate_catalog_audit(context: SolverContext) -> list[dict[str, Any]]:
    teams_by_id = {team.team_id: team for team in context.teams}
    return [
        {
            "candidate_id": candidate.candidate_id,
            "team_id": candidate.team_id,
            "group_id": candidate.group_id,
            "number": candidate.number,
            "seed_request_original": candidate.seed_request_original,
            "potential_home_rounds": list(candidate.potential_home_rounds),
            "opponent_number_by_round": {
                str(round_index): opponent
                for round_index, opponent in sorted(candidate.opponent_number_by_round.items())
            },
            "potential_resources": list(candidate.potential_resources),
            **_linkage_fields(candidate, fallback=teams_by_id.get(candidate.team_id)),
        }
        for candidate in context.candidates
    ]


def build_solver_model_summary(
    raw_result: Any | None,
    built_model: Any | None,
    context: SolverContext,
    result: ResourceSolverResult | None = None,
) -> dict[str, Any]:
    """Return model and run metadata without requiring a concrete model class."""

    status = getattr(raw_result, "status", None) or (result.status if result else "UNKNOWN")
    model_summary = getattr(built_model, "summary", {}) or {}
    return {
        "num_teams": len(context.teams),
        "num_groups": len(context.groups),
        "num_candidates": len(context.candidates),
        "num_variables": _summary_int(built_model, model_summary, "num_variables"),
        "num_constraints": _summary_int(built_model, model_summary, "num_constraints"),
        "num_resource_constraints": _summary_int(
            built_model,
            model_summary,
            "num_resource_constraints",
        ),
        "num_entity_constraints": _summary_int(
            built_model,
            model_summary,
            "num_entity_constraints",
        ),
        "objective_terms": _objective_terms_summary(built_model, model_summary),
        "weights": {
            "resource_excess_weight": getattr(context.config, "resource_excess_weight", None),
            "entity_excess_weight": getattr(context.config, "entity_excess_weight", None),
            "empty_number_imbalance_weight": getattr(
                context.config,
                "empty_number_imbalance_weight",
                None,
            ),
            "level_a_mismatch_weight": getattr(context.config, "level_a_mismatch_weight", None),
            "level_band_mismatch_weight": getattr(
                context.config,
                "level_band_mismatch_weight",
                None,
            ),
        },
        "time_limit_seconds": getattr(context.config, "time_limit_seconds", None),
        "num_search_workers": getattr(context.config, "num_search_workers", None),
        "status": status,
        "objective_value": getattr(raw_result, "objective_value", None)
        if raw_result is not None
        else (result.objective_value if result else None),
        "best_bound": getattr(raw_result, "best_bound", None)
        if raw_result is not None
        else (result.best_bound if result else None),
        "wall_time": getattr(raw_result, "wall_time", None)
        if raw_result is not None
        else (result.wall_time if result else None),
    }


def build_resource_solution_audit(result: ResourceSolverResult) -> dict[str, Any]:
    return result_to_json_ready(result)


def build_solver_explanations(
    result: ResourceSolverResult,
    context: SolverContext,
) -> dict[str, Any]:
    saturated = [
        {
            "resource_id": usage.resource_id,
            "locals_count": usage.locals_count,
            "capacity": usage.capacity,
            "excess": usage.excess,
            "teams": list(usage.team_ids),
        }
        for usage in result.resource_usage
        if usage.locals_count >= usage.capacity
    ]
    excess_resources = [item for item in saturated if item["excess"] > 0]
    rests = {
        summary.group_id: {
            team_id: list(rounds)
            for team_id, rounds in summary.rests_by_team.items()
        }
        for summary in result.group_summary
    }
    seed_deviations = _seed_deviations(result, context)
    linkage = build_linkage_audit(result, context)
    level_band = build_level_band_audit(result, context)

    return {
        "status": result.status,
        "optimality": _optimality_text(result.status),
        "resource_saturation": saturated,
        "resource_excess": excess_resources,
        "entity_excess": {
            f"{entity}|{group_id}": value
            for (entity, group_id), value in sorted(result.entity_excess.items())
        },
        "rests_by_group": rests,
        "seed_request_deviations_informative_only": seed_deviations,
        "linkage": linkage,
        "level_band": level_band,
        "notes": _explanation_notes(result),
    }


def build_level_band_audit(
    result: ResourceSolverResult,
    context: SolverContext,
) -> dict[str, Any]:
    """Summarize normalized level compatibility from final same-group assignments."""

    enabled = level_constraint_enabled(context)
    teams_by_id = {team.team_id: team for team in context.teams}
    assigned_by_team = {assignment.team_id: assignment for assignment in result.assignments}
    rows_by_group: dict[str, list[dict[str, Any]]] = {}
    normalized_teams: list[dict[str, Any]] = []

    for team_id, assignment in sorted(assigned_by_team.items()):
        team = teams_by_id.get(team_id)
        if team is None:
            continue
        raw_level = getattr(team, "level", "")
        normalized_level = normalize_level(raw_level)
        row = {
            "team_id": team_id,
            "team_name": getattr(team, "name", team_id),
            "assigned_group_id": assignment.group_id,
            "assigned_number": int(assignment.number),
            "raw_level": "" if raw_level is None else str(raw_level),
            "normalized_level": normalized_level,
        }
        normalized_teams.append(row)
        rows_by_group.setdefault(assignment.group_id, []).append(row)

    if not enabled:
        return {
            "enabled": False,
            "mode": str(getattr(context.config, "level_constraint_mode", "off") or "off"),
            "summary": {
                "groups": len(rows_by_group),
                "teams": len(normalized_teams),
                "checked_pairs": 0,
                "ok_pairs": 0,
                "violations": 0,
                "cost": 0,
            },
            "normalized_teams": normalized_teams,
            "groups": [],
            "violations": [],
        }

    groups: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    checked_pairs = 0
    ok_pairs = 0

    for group_id, rows in sorted(rows_by_group.items()):
        sorted_rows = sorted(rows, key=lambda row: str(row["team_id"]))
        group_violations: list[dict[str, Any]] = []
        group_checked_pairs = 0
        for left, right in itertools.combinations(sorted_rows, 2):
            checked_pairs += 1
            group_checked_pairs += 1
            family = level_mismatch_family(left["normalized_level"], right["normalized_level"])
            if family is None:
                ok_pairs += 1
                continue
            cost = level_mismatch_weight(context, family)
            violation = {
                "group_id": group_id,
                "team_ids": [left["team_id"], right["team_id"]],
                "team_levels": {
                    left["team_id"]: left["normalized_level"],
                    right["team_id"]: right["normalized_level"],
                },
                "raw_levels": {
                    left["team_id"]: left["raw_level"],
                    right["team_id"]: right["raw_level"],
                },
                "family": family,
                "severity": "violation",
                "cost": cost,
                "violation_cost": cost,
            }
            group_violations.append(violation)
            violations.append(violation)
        groups.append(
            {
                "group_id": group_id,
                "teams_count": len(sorted_rows),
                "checked_pairs": group_checked_pairs,
                "violations_count": len(group_violations),
                "cost": sum(int(item.get("cost", 0) or 0) for item in group_violations),
                "result": "OK" if not group_violations else "Violation",
                "teams": sorted_rows,
                "violations": group_violations,
            }
        )

    return {
        "enabled": enabled,
        "mode": str(getattr(context.config, "level_constraint_mode", "off") or "off"),
        "summary": {
            "groups": len(groups),
            "teams": len(normalized_teams),
            "checked_pairs": checked_pairs,
            "ok_pairs": ok_pairs,
            "violations": len(violations),
            "cost": sum(int(item.get("cost", 0) or 0) for item in violations),
        },
        "normalized_teams": normalized_teams,
        "groups": groups,
        "violations": violations,
    }


def build_linkage_audit(
    result: ResourceSolverResult,
    context: SolverContext,
) -> dict[str, Any]:
    """Summarize linkage compliance from final assignments only."""

    teams_by_id = {team.team_id: team for team in context.teams}
    assigned_by_team = {assignment.team_id: assignment for assignment in result.assignments}
    rows_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for team_id, assignment in sorted(assigned_by_team.items()):
        team = teams_by_id.get(team_id)
        if team is None:
            continue
        linkage_group = _clean_linkage_value(getattr(team, "linkage_group", ""))
        if not linkage_group:
            continue
        venue = str(getattr(team, "venue", "") or "")
        key = (venue, linkage_group)
        rows_by_key.setdefault(key, []).append(
            {
                "team_id": team_id,
                "team_name": getattr(team, "name", team_id),
                "assigned_group_id": assignment.group_id,
                "assigned_number": int(assignment.number),
                "linkage_group": linkage_group,
                "linkage_side": _normalize_linkage_side(getattr(team, "linkage_side", "")),
                "linkage_source": _clean_linkage_value(getattr(team, "linkage_source", "")),
                "venue": venue,
                "day": str(getattr(team, "day", "") or ""),
                "time": str(getattr(team, "time", "") or ""),
            }
        )

    groups: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    checked_pairs = 0
    ok_pairs = 0
    violation_weight = int(getattr(context.config, "linkage_violation_weight", 100_000) or 100_000)

    for (venue, linkage_group), rows in sorted(rows_by_key.items(), key=lambda item: item[0]):
        group_checked_pairs = 0
        group_violations: list[dict[str, Any]] = []
        sorted_rows = sorted(rows, key=lambda row: (str(row["linkage_side"]), str(row["team_id"])))
        for left, right in itertools.combinations(sorted_rows, 2):
            relation = _expected_linkage_relation(left["linkage_side"], right["linkage_side"])
            if relation is None:
                continue
            checked_pairs += 1
            group_checked_pairs += 1
            ok, expected_numbers = _linkage_pair_ok(left, right, relation)
            if ok:
                ok_pairs += 1
                continue
            violation = {
                "team_ids": [left["team_id"], right["team_id"]],
                "assigned_numbers": {
                    left["team_id"]: left["assigned_number"],
                    right["team_id"]: right["assigned_number"],
                },
                "expected_numbers": expected_numbers,
                "expected_relation": relation,
                "linkage_group": linkage_group,
                "venue": venue,
                "day": _common_value([left["day"], right["day"]]),
                "time": _common_value([left["time"], right["time"]]),
                "times": sorted(
                    {
                        str(value)
                        for value in (left["time"], right["time"])
                        if _clean_linkage_value(value)
                    }
                ),
                "severity": "violation",
                "cost": violation_weight,
                "violation_cost": violation_weight,
            }
            group_violations.append(violation)
            violations.append(violation)
        groups.append(
            {
                "venue": venue,
                "linkage_group": linkage_group,
                "teams_count": len(sorted_rows),
                "checked_pairs": group_checked_pairs,
                "violations_count": len(group_violations),
                "result": "OK" if not group_violations else "Violation",
                "teams": sorted_rows,
            }
        )

    return {
        "summary": {
            "groups": len(groups),
            "teams": sum(len(group["teams"]) for group in groups),
            "checked_pairs": checked_pairs,
            "ok_pairs": ok_pairs,
            "violations": len(violations),
            "cost": sum(int(item.get("cost", 0) or 0) for item in violations),
        },
        "groups": groups,
        "violations": violations,
    }


def write_audit_payloads(payloads: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    """Write audit payloads as pretty JSON and return paths by payload name."""

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for name, payload in sorted(payloads.items()):
        path = directory / f"{name}.json"
        path.write_text(
            json.dumps(json_ready(payload), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        paths[name] = str(path)
    return paths


def json_ready(value: Any) -> Any:
    """Convert dataclasses, tuples and non-string keys to JSON-ready values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_ready(item) for item in value]
    if isinstance(value, Path):
        return str(value)

    name = getattr(value, "Name", None)
    if callable(name):
        try:
            return name()
        except Exception:
            pass
    return str(value)


def _objective_terms_summary(built_model: Any | None, model_summary: Mapping[str, Any]) -> dict[str, int]:
    summary_terms = model_summary.get("objective_terms", {}) if isinstance(model_summary, Mapping) else {}
    if isinstance(summary_terms, Mapping):
        prepared = {str(key): int(value or 0) for key, value in summary_terms.items()}
        if prepared:
            return prepared

    counts: dict[str, int] = {}
    for term in getattr(built_model, "objective_terms", None) or ():
        try:
            name = term[0]
        except Exception:
            name = "unknown"
        key = str(name)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _seed_deviations(
    result: ResourceSolverResult,
    context: SolverContext,
) -> list[dict[str, Any]]:
    request_by_team = {team.team_id: team.seed_request_original for team in context.teams}
    deviations: list[dict[str, Any]] = []
    for assignment in result.assignments:
        requested = request_by_team.get(assignment.team_id)
        if requested in (None, ""):
            continue
        try:
            requested_number = int(requested)
        except (TypeError, ValueError):
            requested_number = None
        if requested_number is not None and requested_number != assignment.number:
            deviations.append(
                {
                    "team_id": assignment.team_id,
                    "requested": requested,
                    "assigned_number": assignment.number,
                }
            )
    return deviations


def _linkage_fields(record: Any, fallback: Any | None = None) -> dict[str, Any]:
    return {
        "linkage_group": _clean_linkage_value(
            getattr(record, "linkage_group", getattr(fallback, "linkage_group", ""))
        ),
        "linkage_side": _normalize_linkage_side(
            getattr(record, "linkage_side", getattr(fallback, "linkage_side", ""))
        ),
        "linkage_source": _clean_linkage_value(
            getattr(record, "linkage_source", getattr(fallback, "linkage_source", ""))
        ),
    }


def _clean_linkage_value(value: Any) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).strip().split())
    if text.casefold() in {"nan", "none", "null"}:
        return ""
    return text


def _normalize_linkage_side(value: Any) -> str:
    text = _clean_linkage_value(value).casefold()
    if text in {"casa", "home", "local"}:
        return "Casa"
    if text in {"fora", "away", "visitant", "visitor"}:
        return "Fora"
    if text in {"indiferent", "indifferent", "neutral", "sense preferencia"}:
        return "Indiferent"
    return _clean_linkage_value(value)


def _expected_linkage_relation(left_side: Any, right_side: Any) -> str | None:
    left = _normalize_linkage_side(left_side)
    right = _normalize_linkage_side(right_side)
    if left in {"", "Indiferent"} or right in {"", "Indiferent"}:
        return None
    helper_relation = _helper_linkage_relation(left, right)
    if helper_relation is not None:
        return helper_relation
    if left == right:
        return "same_number"
    if {left, right} == {"Casa", "Fora"}:
        return "opposite_number"
    return None


def _linkage_pair_ok(
    left: dict[str, Any],
    right: dict[str, Any],
    relation: str,
) -> tuple[bool, dict[str, int]]:
    left_number = int(left["assigned_number"])
    right_number = int(right["assigned_number"])
    if relation == "same_number":
        expected = {
            str(left["team_id"]): left_number,
            str(right["team_id"]): left_number,
        }
        return left_number == right_number, expected

    expected_right = _opposite_linkage_number(left_number)
    expected_left = _opposite_linkage_number(right_number)
    expected = {
        str(left["team_id"]): expected_left or left_number,
        str(right["team_id"]): expected_right or right_number,
    }
    return expected_right is not None and right_number == expected_right, expected


def _opposite_linkage_number(number: int) -> int | None:
    helper = getattr(_linkage_helpers, "opposite_number", None)
    if helper is not None:
        try:
            value = helper(number)
        except Exception:
            value = None
        if value is not None:
            return int(value)
    opposite_by_number = {
        1: 5,
        5: 1,
        6: 2,
        2: 6,
        7: 3,
        3: 7,
        8: 4,
        4: 8,
    }
    return opposite_by_number.get(int(number))


def _helper_linkage_relation(left_side: Any, right_side: Any) -> str | None:
    if _linkage_helpers is None:
        return None
    sides_match = getattr(_linkage_helpers, "linkage_sides_match", None)
    if sides_match is not None:
        try:
            if bool(sides_match(left_side, right_side)):
                return "same_number"
        except Exception:
            pass
    sides_are_opposites = getattr(_linkage_helpers, "linkage_sides_are_opposites", None)
    if sides_are_opposites is not None:
        try:
            if bool(sides_are_opposites(left_side, right_side)):
                return "opposite_number"
        except Exception:
            pass
    return None


def _common_value(values: list[Any]) -> str:
    clean = [_clean_linkage_value(value) for value in values if _clean_linkage_value(value)]
    if not clean:
        return ""
    first = clean[0]
    return first if all(value == first for value in clean) else ""


def _summary_int(built_model: Any | None, summary: dict[str, Any], name: str) -> int:
    return int(getattr(built_model, name, None) or summary.get(name, 0) or 0)


def _optimality_text(status: str) -> str:
    if status == "OPTIMAL":
        return "optimal_solution_proven"
    if status == "FEASIBLE":
        return "feasible_solution_without_optimality_proof"
    if status == "INFEASIBLE":
        return "no_solution_satisfies_hard_constraints"
    return "solver_status_unknown"


def _explanation_notes(result: ResourceSolverResult) -> list[str]:
    notes: list[str] = []
    if result.status == "FEASIBLE":
        notes.append("The solver found a feasible solution but did not prove optimality.")
    if result.status == "INFEASIBLE":
        notes.append("No assignments are valid under the hard constraints currently active.")
    if any(usage.excess > 0 for usage in result.resource_usage):
        notes.append("Resource excess is local to the affected timed resource.")
    if result.entity_excess:
        notes.append("Entity excess is reported only for entity/group pairs with conflicts.")
    return notes
