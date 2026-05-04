from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Iterable

from .levels import LEVEL_FIT_EXCEPTIONAL
from .route_generation import RouteCandidate


@dataclass(frozen=True)
class PhaseSolverResult:
    selected_routes: tuple[RouteCandidate, ...]
    unassigned_match_ids: tuple[str, ...]
    rejected_candidates_summary: dict[str, Any] = field(default_factory=dict)
    objective_summary: dict[str, Any] = field(default_factory=dict)


def solve_phase_routes(candidates: Iterable[RouteCandidate], config: dict[str, Any] | None = None) -> PhaseSolverResult:
    config = dict(config or {})
    all_candidates = list(candidates or [])
    viable = [candidate for candidate in all_candidates if not candidate.blocking_reasons]
    exact_limit = int(config.get("set_packing_exact_candidate_limit", config.get("exact_solver_candidate_limit", 80)))
    solver_meta: dict[str, Any] = {}

    cp_sat_result = _cp_sat_select(viable, config) if _cp_sat_enabled(config) else None
    if cp_sat_result is not None:
        selected, solver_meta = cp_sat_result
        strategy = solver_meta.get("strategy", "cp_sat")
    elif len(viable) <= exact_limit:
        selected = _exact_select(viable)
        strategy = "bounded_exact"
    else:
        selected = _greedy_select(viable)
        strategy = "greedy_fallback"

    covered = _covered_matches(selected)
    all_match_ids = []
    seen = set()
    for candidate in all_candidates:
        for match_id in candidate.new_match_ids:
            if match_id not in seen:
                all_match_ids.append(match_id)
                seen.add(match_id)
    unassigned = tuple(match_id for match_id in all_match_ids if match_id not in covered)

    return PhaseSolverResult(
        selected_routes=tuple(sorted(selected, key=_stable_order_key)),
        unassigned_match_ids=unassigned,
        rejected_candidates_summary=_rejected_summary(all_candidates, viable, selected),
        objective_summary={
            "strategy": strategy,
            **solver_meta,
            "candidate_count": len(all_candidates),
            "viable_candidate_count": len(viable),
            "selected_route_count": len(selected),
            "selected_match_count": len(covered),
            "unassigned_match_count": len(unassigned),
            "selected_exceptional_level_count": _exceptional_count(selected),
            "weighted_covered_value": float(sum(_weighted_value(candidate) for candidate in selected)),
            "high_level_covered_value": float(sum(_high_level_value(candidate) for candidate in selected)),
            "total_cost": float(sum(float(candidate.cost) for candidate in selected)),
            "load_penalty_total": float(sum(_breakdown_float(candidate, "load_penalty") for candidate in selected)),
            "warning_count": sum(len(candidate.warning_codes) for candidate in selected),
        },
    )


def _cp_sat_select(candidates: list[RouteCandidate], config: dict[str, Any]) -> tuple[list[RouteCandidate], dict[str, Any]] | None:
    if not _cp_sat_enabled(config):
        return None
    try:
        from ortools.sat.python import cp_model
    except Exception as exc:
        return (
            [],
            {
                "strategy": "cp_sat_unavailable",
                "solver_backend": "cp_sat",
                "solver_status": "IMPORT_ERROR",
                "fallback_reason": str(exc),
            },
        ) if bool(config.get("phase_solver_fail_closed", False)) else None

    if not candidates:
        return [], {"strategy": "cp_sat_empty", "solver_backend": "cp_sat", "solver_status": "EMPTY"}

    objectives = _cp_sat_objectives(candidates)
    fixed: list[tuple[list[int], int]] = []
    selected: list[RouteCandidate] = []
    statuses: list[dict[str, Any]] = []
    started = monotonic()
    total_limit = float(config.get("cp_sat_phase_time_limit_sec", config.get("ilp_phase_time_limit_sec", 120.0)) or 120.0)
    step_limit = float(
        config.get(
            "cp_sat_phase_step_time_limit_sec",
            config.get("ilp_phase_step_time_limit_sec", max(1.0, total_limit / max(len(objectives), 1))),
        )
        or 1.0
    )

    for name, coefficients, maximize in objectives:
        elapsed = monotonic() - started
        remaining = total_limit - elapsed
        if remaining <= 0:
            return selected, {
                "strategy": "cp_sat_feasible",
                "solver_backend": "cp_sat",
                "solver_status": "TIME_LIMIT",
                "solver_objective_steps": statuses,
                "solver_elapsed_sec": round(elapsed, 4),
            }

        model, variables = _build_cp_sat_model(cp_model, candidates, fixed)
        expression = sum(int(coefficients[index]) * variables[index] for index in range(len(candidates)))
        if maximize:
            model.Maximize(expression)
        else:
            model.Minimize(expression)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(0.1, min(step_limit, remaining))
        solver.parameters.num_search_workers = int(config.get("cp_sat_num_workers", config.get("ilp_num_workers", 8)) or 8)
        status = solver.Solve(model)
        status_name = solver.StatusName(status)
        statuses.append({"objective": name, "status": status_name, "maximize": maximize})

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if selected:
                return selected, {
                    "strategy": "cp_sat_feasible",
                    "solver_backend": "cp_sat",
                    "solver_status": status_name,
                    "solver_objective_steps": statuses,
                    "solver_elapsed_sec": round(monotonic() - started, 4),
                }
            return None

        selected_indexes = [index for index, variable in enumerate(variables) if solver.BooleanValue(variable)]
        selected = [candidates[index] for index in selected_indexes]
        objective_value = int(round(solver.ObjectiveValue()))

        if status == cp_model.OPTIMAL:
            fixed.append((coefficients, objective_value))
            statuses[-1]["value"] = objective_value
            continue

        return selected, {
            "strategy": "cp_sat_feasible",
            "solver_backend": "cp_sat",
            "solver_status": status_name,
            "solver_objective_steps": statuses,
            "solver_elapsed_sec": round(monotonic() - started, 4),
        }

    return selected, {
        "strategy": "cp_sat_optimal",
        "solver_backend": "cp_sat",
        "solver_status": "OPTIMAL",
        "solver_objective_steps": statuses,
        "solver_elapsed_sec": round(monotonic() - started, 4),
    }


def _cp_sat_enabled(config: dict[str, Any]) -> bool:
    backend = str(config.get("phase_solver_backend", config.get("solver_backend", "cp_sat")) or "cp_sat").strip().lower()
    return backend in {"cp_sat", "cpsat", "ilp", "auto"}


def _build_cp_sat_model(cp_model: Any, candidates: list[RouteCandidate], fixed: list[tuple[list[int], int]]) -> tuple[Any, list[Any]]:
    model = cp_model.CpModel()
    variables = [model.NewBoolVar(f"route_{index}") for index in range(len(candidates))]

    by_match: dict[str, list[Any]] = {}
    by_tutor_day: dict[tuple[str, str], list[Any]] = {}
    for index, candidate in enumerate(candidates):
        for match_id in candidate.new_match_ids:
            by_match.setdefault(str(match_id), []).append(variables[index])
        by_tutor_day.setdefault(_tutor_day(candidate), []).append(variables[index])

    for match_variables in by_match.values():
        model.Add(sum(match_variables) <= 1)
    for tutor_day_variables in by_tutor_day.values():
        model.Add(sum(tutor_day_variables) <= 1)
    for coefficients, value in fixed:
        model.Add(sum(int(coefficients[index]) * variables[index] for index in range(len(candidates))) == int(value))

    return model, variables


def _cp_sat_objectives(candidates: list[RouteCandidate]) -> list[tuple[str, list[int], bool]]:
    return [
        ("selected_match_count", [len(candidate.new_match_ids) for candidate in candidates], True),
        ("weighted_covered_value", [_scaled(_weighted_value(candidate), 1000) for candidate in candidates], True),
        ("high_level_covered_value", [_scaled(_high_level_value(candidate), 1000) for candidate in candidates], True),
        ("selected_exceptional_level_count", [1 if _is_exceptional(candidate) else 0 for candidate in candidates], False),
        ("load_penalty_total", [_scaled(_breakdown_float(candidate, "load_penalty"), 100) for candidate in candidates], False),
        ("mobility_cost_total", [_scaled(_mobility_vehicle_cost(candidate), 100) for candidate in candidates], False),
        ("warning_count", [len(candidate.warning_codes) for candidate in candidates], False),
        ("total_cost", [_scaled(float(candidate.cost), 100) for candidate in candidates], False),
        ("selected_route_count", [1 for _candidate in candidates], False),
    ]


def _scaled(value: float, factor: int) -> int:
    return int(round(float(value or 0.0) * int(factor)))


def _exact_select(candidates: list[RouteCandidate]) -> list[RouteCandidate]:
    ordered = sorted(candidates, key=_candidate_sort_key)
    best: list[RouteCandidate] = []
    best_key = _solution_key(best)

    suffix_values = [0.0] * (len(ordered) + 1)
    for index in range(len(ordered) - 1, -1, -1):
        suffix_values[index] = suffix_values[index + 1] + max(_weighted_value(ordered[index]), 0.0)

    def visit(index: int, selected: list[RouteCandidate], used_matches: set[str], used_tutor_days: set[tuple[str, str]]) -> None:
        nonlocal best, best_key
        current_key = _solution_key(selected)
        if current_key[0] + suffix_values[index] < best_key[0]:
            return
        if index >= len(ordered):
            if current_key > best_key:
                best = list(selected)
                best_key = current_key
            return

        candidate = ordered[index]
        match_ids = set(candidate.new_match_ids)
        tutor_day = _tutor_day(candidate)
        if not (match_ids & used_matches) and tutor_day not in used_tutor_days:
            visit(index + 1, selected + [candidate], used_matches | match_ids, used_tutor_days | {tutor_day})
        visit(index + 1, selected, used_matches, used_tutor_days)

    visit(0, [], set(), set())
    return best


def _greedy_select(candidates: list[RouteCandidate]) -> list[RouteCandidate]:
    orderings = [
        sorted(candidates, key=_candidate_sort_key),
        sorted(candidates, key=lambda item: (_is_exceptional(item), float(item.cost), -len(item.new_match_ids), item.tutor_id, item.id)),
        sorted(candidates, key=lambda item: (-_high_level_value(item), -_weighted_value(item), _is_exceptional(item), float(item.cost), item.id)),
        sorted(candidates, key=lambda item: (-len(item.new_match_ids), float(item.cost), len(item.warning_codes), item.tutor_id, item.id)),
    ]
    solutions = [_greedy_pass(ordering) for ordering in orderings]
    return max(solutions, key=_solution_key)


def _greedy_pass(candidates: list[RouteCandidate]) -> list[RouteCandidate]:
    selected: list[RouteCandidate] = []
    used_matches: set[str] = set()
    used_tutor_days: set[tuple[str, str]] = set()
    for candidate in candidates:
        match_ids = set(candidate.new_match_ids)
        tutor_day = _tutor_day(candidate)
        if match_ids & used_matches or tutor_day in used_tutor_days:
            continue
        selected.append(candidate)
        used_matches.update(match_ids)
        used_tutor_days.add(tutor_day)
    return selected


def _solution_key(selected: list[RouteCandidate]) -> tuple[float, float, int, int, float, float, int, float, int]:
    covered = _covered_matches(selected)
    return (
        float(sum(_weighted_value(candidate) for candidate in selected)),
        float(sum(_high_level_value(candidate) for candidate in selected)),
        -_exceptional_count(selected),
        len(covered),
        -float(sum(_breakdown_float(candidate, "load_penalty") for candidate in selected)),
        -float(sum(_mobility_vehicle_cost(candidate) for candidate in selected)),
        -sum(len(candidate.warning_codes) for candidate in selected),
        -float(sum(float(candidate.cost) for candidate in selected)),
        -len(selected),
    )


def _candidate_sort_key(candidate: RouteCandidate) -> tuple[Any, ...]:
    return (
        -_weighted_value(candidate),
        -_high_level_value(candidate),
        _is_exceptional(candidate),
        -len(candidate.new_match_ids),
        float(candidate.cost),
        len(candidate.warning_codes),
        candidate.tutor_id,
        candidate.id,
    )


def _stable_order_key(candidate: RouteCandidate) -> tuple[str, str, str]:
    return (candidate.date, candidate.tutor_id, candidate.id)


def _covered_matches(selected: Iterable[RouteCandidate]) -> set[str]:
    covered: set[str] = set()
    for candidate in selected:
        covered.update(str(match_id) for match_id in candidate.new_match_ids)
    return covered


def _weighted_value(candidate: RouteCandidate) -> float:
    default = float(len(candidate.new_match_ids))
    return _breakdown_float(candidate, "weighted_coverage_value", default)


def _high_level_value(candidate: RouteCandidate) -> float:
    return _breakdown_float(candidate, "high_level_value", 0.0)


def _mobility_vehicle_cost(candidate: RouteCandidate) -> float:
    return _breakdown_float(candidate, "mobility_cost", 0.0) + (40.0 if candidate.requires_vehicle else 0.0)


def _is_exceptional(candidate: RouteCandidate) -> bool:
    if candidate.level_fit == LEVEL_FIT_EXCEPTIONAL:
        return True
    value = (candidate.score_breakdown or {}).get("level_exceptional", False)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "si", "sÃ­", "exceptional"}
    return bool(value)


def _exceptional_count(selected: Iterable[RouteCandidate]) -> int:
    return sum(1 for candidate in selected if _is_exceptional(candidate))


def _breakdown_float(candidate: RouteCandidate, key: str, default: float = 0.0) -> float:
    try:
        return float((candidate.score_breakdown or {}).get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _tutor_day(candidate: RouteCandidate) -> tuple[str, str]:
    return (candidate.tutor_id, candidate.date)


def _rejected_summary(all_candidates: list[RouteCandidate], viable: list[RouteCandidate], selected: list[RouteCandidate]) -> dict[str, Any]:
    selected_ids = {candidate.id for candidate in selected}
    blocking_counts: dict[str, int] = {}
    for candidate in all_candidates:
        for reason in candidate.blocking_reasons:
            blocking_counts[reason] = blocking_counts.get(reason, 0) + 1
    return {
        "inviable_candidate_count": len(all_candidates) - len(viable),
        "viable_not_selected_count": sum(1 for candidate in viable if candidate.id not in selected_ids),
        "blocking_reason_counts": blocking_counts,
    }


__all__ = ["PhaseSolverResult", "solve_phase_routes"]
