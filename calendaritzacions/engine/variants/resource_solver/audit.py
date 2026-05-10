"""JSON-ready audit payloads for the resource solver."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from calendaritzacions.engine.variants.resource_solver.solution import result_to_json_ready
from calendaritzacions.engine.variants.resource_solver.types import (
    ResourceSolverResult,
    SolverContext,
)


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
        },
        "time_limit_seconds": getattr(context.config, "time_limit_seconds", None),
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
        "notes": _explanation_notes(result),
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
