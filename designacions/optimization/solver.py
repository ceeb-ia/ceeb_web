from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .package_scoring import AssignmentCandidate

try:
    from .contracts import SolverResult as ContractSolverResult
except ImportError:  # pragma: no cover - contracts are optional during rollout.
    ContractSolverResult = None


@dataclass(frozen=True)
class LocalSolverResult:
    selected_assignments: tuple[AssignmentCandidate, ...]
    unassigned_match_ids: tuple[Any, ...]
    rejected_candidates_summary: dict[str, Any] = field(default_factory=dict)
    objective_summary: dict[str, Any] = field(default_factory=dict)


SolverResult = ContractSolverResult or LocalSolverResult


def solve_assignment_candidates(candidates, packages, tutors, config=None):
    """Select viable tutor-package assignments.

    Objective order is lexicographic: maximize covered matches first, then
    minimize total cost. The implementation uses a bounded exact search for
    small candidate sets and a deterministic greedy multi-pass fallback for
    larger runs.
    """
    config = config or {}
    candidates = list(candidates or [])
    packages = list(packages or [])
    viable_candidates = [candidate for candidate in candidates if getattr(candidate, "is_viable", False)]

    all_match_ids = _all_match_ids(packages)
    package_dates = {_value(package, "id", "package_id"): _value(package, "date") for package in packages}
    package_values = _package_values(packages)
    exact_limit = int(_cfg(config, "exact_solver_candidate_limit", 22))

    if len(viable_candidates) <= exact_limit:
        selected = _exact_select(viable_candidates, package_dates, package_values)
        strategy = "bounded_exact"
    else:
        selected = _greedy_select(viable_candidates, package_dates, package_values)
        strategy = "greedy"

    covered = set()
    for candidate in selected:
        covered.update(getattr(candidate, "match_ids", ()) or ())
    unassigned = tuple(match_id for match_id in all_match_ids if match_id not in covered)

    return SolverResult(
        selected_assignments=tuple(selected),
        unassigned_match_ids=unassigned,
        rejected_candidates_summary=_rejected_summary(candidates, viable_candidates, selected),
        objective_summary={
            "strategy": strategy,
            "assigned_match_count": len(covered),
            "unassigned_match_count": len(unassigned),
            "selected_assignment_count": len(selected),
            "selected_exceptional_level_count": _selected_exceptional_level_count(selected),
            "total_cost": float(sum(float(candidate.cost) for candidate in selected)),
            "weighted_covered_value": float(_covered_value(selected, package_values)),
            "candidate_count": len(candidates),
            "viable_candidate_count": len(viable_candidates),
        },
    )


def _exact_select(candidates, package_dates, package_values):
    ordered = sorted(candidates, key=lambda candidate: _candidate_sort_key(candidate, package_values))
    best = []
    best_key = _solution_key(best, package_values)

    def visit(index, selected, used_matches, used_tutor_days):
        nonlocal best, best_key
        optimistic_value = _covered_value(selected, package_values)
        for candidate in ordered[index:]:
            if not (set(candidate.match_ids) & used_matches):
                optimistic_value += _candidate_value(candidate, package_values)
        if optimistic_value < best_key[0]:
            return

        if index >= len(ordered):
            key = _solution_key(selected, package_values)
            if key > best_key:
                best = list(selected)
                best_key = key
            return

        candidate = ordered[index]
        tutor_day = _tutor_day(candidate, package_dates)
        candidate_matches = set(candidate.match_ids)
        if not candidate_matches & used_matches and tutor_day not in used_tutor_days:
            visit(
                index + 1,
                selected + [candidate],
                used_matches | candidate_matches,
                used_tutor_days | {tutor_day},
            )
        visit(index + 1, selected, used_matches, used_tutor_days)

    visit(0, [], set(), set())
    return sorted(best, key=lambda candidate: _candidate_sort_key(candidate, package_values))


def _greedy_select(candidates, package_dates, package_values):
    orderings = [
        sorted(candidates, key=lambda candidate: _candidate_sort_key(candidate, package_values)),
        sorted(candidates, key=lambda candidate: (_is_level_exceptional(candidate), float(candidate.cost), -_candidate_value(candidate, package_values), str(candidate.tutor_id))),
        sorted(candidates, key=lambda candidate: (-_pressure_value(candidate), -_candidate_value(candidate, package_values), _is_level_exceptional(candidate), float(candidate.cost))),
    ]
    solutions = [_greedy_pass(ordering, package_dates) for ordering in orderings]
    return sorted(max(solutions, key=lambda selected: _solution_key(selected, package_values)), key=lambda candidate: _candidate_sort_key(candidate, package_values))


def _greedy_pass(candidates, package_dates):
    selected = []
    used_matches = set()
    used_tutor_days = set()
    for candidate in candidates:
        candidate_matches = set(candidate.match_ids)
        if candidate_matches & used_matches:
            continue
        tutor_day = _tutor_day(candidate, package_dates)
        if tutor_day in used_tutor_days:
            continue
        selected.append(candidate)
        used_matches.update(candidate_matches)
        used_tutor_days.add(tutor_day)
    return selected


def _candidate_sort_key(candidate, package_values):
    return (
        -_candidate_value(candidate, package_values),
        -len(getattr(candidate, "match_ids", ()) or ()),
        _is_level_exceptional(candidate),
        float(getattr(candidate, "cost", 0.0)),
        str(getattr(candidate, "tutor_id", "")),
        str(getattr(candidate, "package_id", "")),
    )


def _solution_key(selected, package_values):
    covered = set()
    for candidate in selected:
        covered.update(getattr(candidate, "match_ids", ()) or ())
    return (
        _covered_value(selected, package_values),
        len(covered),
        -_selected_exceptional_level_count(selected),
        -float(sum(float(getattr(candidate, "cost", 0.0)) for candidate in selected)),
        -len(selected),
    )


def _selected_exceptional_level_count(selected):
    return sum(1 for candidate in selected if _is_level_exceptional(candidate))


def _is_level_exceptional(candidate):
    breakdown = getattr(candidate, "score_breakdown", {}) or {}
    value = breakdown.get("level_exceptional", False)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "si", "sí", "exceptional"}
    return bool(value)


def _candidate_value(candidate, package_values):
    return float(package_values.get(str(getattr(candidate, "package_id", "")), len(getattr(candidate, "match_ids", ()) or ())))


def _covered_value(selected, package_values):
    return float(sum(_candidate_value(candidate, package_values) for candidate in selected))


def _package_values(packages):
    values = {}
    for package in packages:
        package_id = str(_value(package, "id", "package_id", default=""))
        default_value = len(_list_value(package, "match_ids"))
        try:
            values[package_id] = float(_value(package, "weighted_coverage_value", default=default_value) or default_value)
        except (TypeError, ValueError):
            values[package_id] = float(default_value)
    return values


def _pressure_value(candidate):
    breakdown = getattr(candidate, "score_breakdown", {}) or {}
    try:
        return abs(float(breakdown.get("pressure_relief_reward", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _tutor_day(candidate, package_dates):
    package_date = package_dates.get(getattr(candidate, "package_id", None))
    return (getattr(candidate, "tutor_id", None), str(package_date))


def _all_match_ids(packages):
    match_ids = []
    seen = set()
    for package in packages:
        for match_id in _list_value(package, "match_ids"):
            if match_id not in seen:
                match_ids.append(match_id)
                seen.add(match_id)
    return tuple(match_ids)


def _rejected_summary(candidates, viable_candidates, selected):
    selected_ids = {(candidate.tutor_id, candidate.package_id) for candidate in selected}
    blocking_counts = {}
    for candidate in candidates:
        for reason in getattr(candidate, "blocking_reasons", ()) or ():
            blocking_counts[reason] = blocking_counts.get(reason, 0) + 1
    return {
        "inviable_candidate_count": len(candidates) - len(viable_candidates),
        "viable_not_selected_count": sum(
            1 for candidate in viable_candidates if (candidate.tutor_id, candidate.package_id) not in selected_ids
        ),
        "blocking_reason_counts": blocking_counts,
    }


def _value(obj, *names, default=None):
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _list_value(obj, *names):
    value = _value(obj, *names, default=())
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _cfg(config, name, default):
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)
