"""Soft level-band constraints for teams assigned to the same group."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import re
from typing import Any

from calendaritzacions.engine.variants.resource_solver.constraints.base import (
    ConstraintAudit,
    ModelVariables,
    ObjectiveTerm,
)
from calendaritzacions.engine.variants.resource_solver.types import Candidate


@dataclass(frozen=True)
class LevelBandConstraints:
    name: str = "level_band"

    def add(
        self,
        model: Any,
        variables: ModelVariables,
        context: Any,
        objective_terms: list[ObjectiveTerm],
        audit: ConstraintAudit,
    ) -> None:
        add_level_band_constraints(model, variables, context, objective_terms, audit)


def add_level_band_constraints(
    model: Any,
    variables: ModelVariables,
    context: Any,
    objective_terms: list[ObjectiveTerm],
    audit: ConstraintAudit,
) -> None:
    """Penalize incompatible normalized levels assigned inside the same group."""

    if not level_constraint_enabled(context):
        return

    if level_constraint_mode(context) == "aggregate":
        add_aggregate_level_band_constraints(model, variables, context, objective_terms, audit)
        return

    add_pairwise_level_band_constraints(model, variables, context, objective_terms, audit)


def add_pairwise_level_band_constraints(
    model: Any,
    variables: ModelVariables,
    context: Any,
    objective_terms: list[ObjectiveTerm],
    audit: ConstraintAudit,
) -> None:
    """Penalize every incompatible selected pair inside a shared group."""

    teams_by_id = {team.team_id: team for team in getattr(context, "teams", ())}
    for left, right in combinations(sorted(teams_by_id.values(), key=lambda item: item.team_id), 2):
        family = level_mismatch_family(
            normalize_level(getattr(left, "level", "")),
            normalize_level(getattr(right, "level", "")),
        )
        if family is None:
            continue

        for group_id in sorted(_shared_candidate_groups(variables, left.team_id, right.team_id)):
            violation = model.NewBoolVar(
                "level_band_violation_"
                f"{_safe_name(left.team_id)}_{_safe_name(right.team_id)}_{_safe_name(group_id)}"
            )
            implication_count = 0
            for left_candidate in variables.candidates_by_team.get(left.team_id, []):
                if left_candidate.group_id != group_id:
                    continue
                left_var = variables.x[left_candidate.candidate_id]
                for right_candidate in variables.candidates_by_team.get(right.team_id, []):
                    if right_candidate.group_id != group_id:
                        continue
                    right_var = variables.x[right_candidate.candidate_id]
                    model.Add(violation >= left_var + right_var - 1)
                    implication_count += 1

            if implication_count == 0:
                continue
            variables.level_band_violation[(left.team_id, right.team_id, group_id)] = violation
            objective_terms.append((family, level_mismatch_weight(context, family), violation))
            audit.count_constraint("soft_level_band_pair")
            audit.count_constraint("level_band_violation_implication", implication_count)
            audit.count_objective_term(family)


def add_aggregate_level_band_constraints(
    model: Any,
    variables: ModelVariables,
    context: Any,
    objective_terms: list[ObjectiveTerm],
    audit: ConstraintAudit,
) -> None:
    """Penalize incompatible level presence once per group."""

    team_level = {
        str(team.team_id): normalize_level(getattr(team, "level", ""))
        for team in getattr(context, "teams", ())
    }
    for group in sorted(getattr(context, "groups", ()), key=lambda item: str(item.group_id)):
        group_id = str(group.group_id)
        terms_by_level = {"A": [], "B": [], "B/C": [], "C": []}
        for candidate in variables.candidate_by_id.values():
            if str(candidate.group_id) != group_id:
                continue
            level = team_level.get(str(candidate.team_id), "B/C")
            terms_by_level.setdefault(level, []).append(variables.x[candidate.candidate_id])

        has_a = _presence_var(model, terms_by_level.get("A", []), f"level_has_A_{_safe_name(group_id)}", audit)
        has_b = _presence_var(model, terms_by_level.get("B", []), f"level_has_B_{_safe_name(group_id)}", audit)
        has_c = _presence_var(model, terms_by_level.get("C", []), f"level_has_C_{_safe_name(group_id)}", audit)
        non_a_terms = [
            *terms_by_level.get("B", []),
            *terms_by_level.get("B/C", []),
            *terms_by_level.get("C", []),
        ]
        has_non_a = _presence_var(model, non_a_terms, f"level_has_non_A_{_safe_name(group_id)}", audit)

        if has_a is not None and has_non_a is not None:
            violation = model.NewBoolVar(f"level_aggregate_A_non_A_{_safe_name(group_id)}")
            model.Add(violation >= has_a + has_non_a - 1)
            model.Add(violation <= has_a)
            model.Add(violation <= has_non_a)
            variables.level_band_violation[("__aggregate_a_non_a__", group_id, "A")] = violation
            objective_terms.append(("level_a_mismatch", level_mismatch_weight(context, "level_a_mismatch"), violation))
            audit.count_constraint("aggregate_level_band_violation", 3)
            audit.count_objective_term("level_a_mismatch")

        if has_b is not None and has_c is not None:
            violation = model.NewBoolVar(f"level_aggregate_B_C_{_safe_name(group_id)}")
            model.Add(violation >= has_b + has_c - 1)
            model.Add(violation <= has_b)
            model.Add(violation <= has_c)
            variables.level_band_violation[("__aggregate_b_c__", group_id, "B_C")] = violation
            objective_terms.append(("level_band_mismatch", level_mismatch_weight(context, "level_band_mismatch"), violation))
            audit.count_constraint("aggregate_level_band_violation", 3)
            audit.count_objective_term("level_band_mismatch")


def fallback_level_band_violations(
    context: Any,
    combo: tuple[Candidate, ...],
) -> dict[tuple[str, str, str], str]:
    """Return selected same-group level violations for deterministic fallback scoring."""

    if not level_constraint_enabled(context):
        return {}
    if level_constraint_mode(context) == "aggregate":
        return _fallback_aggregate_level_band_violations(context, combo)

    teams_by_id = {team.team_id: team for team in getattr(context, "teams", ())}
    selected_by_team = {candidate.team_id: candidate for candidate in combo}
    violations: dict[tuple[str, str, str], str] = {}
    for left, right in combinations(sorted(teams_by_id.values(), key=lambda item: item.team_id), 2):
        left_candidate = selected_by_team.get(left.team_id)
        right_candidate = selected_by_team.get(right.team_id)
        if left_candidate is None or right_candidate is None:
            continue
        if left_candidate.group_id != right_candidate.group_id:
            continue
        family = level_mismatch_family(
            normalize_level(getattr(left, "level", "")),
            normalize_level(getattr(right, "level", "")),
        )
        if family is not None:
            violations[(left.team_id, right.team_id, left_candidate.group_id)] = family
    return violations


def _fallback_aggregate_level_band_violations(
    context: Any,
    combo: tuple[Candidate, ...],
) -> dict[tuple[str, str, str], str]:
    team_level = {
        str(team.team_id): normalize_level(getattr(team, "level", ""))
        for team in getattr(context, "teams", ())
    }
    levels_by_group: dict[str, set[str]] = {}
    for candidate in combo:
        levels_by_group.setdefault(str(candidate.group_id), set()).add(team_level.get(str(candidate.team_id), "B/C"))

    violations: dict[tuple[str, str, str], str] = {}
    for group_id, levels in levels_by_group.items():
        if "A" in levels and any(level != "A" for level in levels):
            violations[("__aggregate_a_non_a__", group_id, "A")] = "level_a_mismatch"
        if "B" in levels and "C" in levels:
            violations[("__aggregate_b_c__", group_id, "B_C")] = "level_band_mismatch"
    return violations


def level_constraint_enabled(context: Any) -> bool:
    return level_constraint_mode(context) not in {"", "off", "false", "none", "disabled", "0"}


def level_constraint_mode(context: Any) -> str:
    mode = str(getattr(getattr(context, "config", None), "level_constraint_mode", "off") or "off")
    return mode.strip().casefold()


def normalize_level(value: Any) -> str:
    text = str(value or "").strip().upper()
    if re.search(r"\bB\s*[-/]\s*C\b", text):
        return "B/C"
    match = re.search(r"\b([A-E])\b", text)
    if not match:
        match = re.search(r"(?:NIVELL\s*)?([A-E])\s*$", text)
    if not match:
        return "B/C"
    return {"A": "A", "B": "B", "C": "B/C", "D": "B/C", "E": "C"}[match.group(1)]


def level_mismatch_family(left_level: str, right_level: str) -> str | None:
    if left_level == right_level:
        return None
    if "A" in {left_level, right_level}:
        return "level_a_mismatch"
    if {left_level, right_level} == {"B", "C"}:
        return "level_band_mismatch"
    return None


def level_mismatch_weight(context: Any, family: str) -> int:
    config = getattr(context, "config", None)
    if family == "level_a_mismatch":
        return _config_int(config, "level_a_mismatch_weight", 1_000_000)
    return _config_int(config, "level_band_mismatch_weight", 200_000)


def _shared_candidate_groups(variables: ModelVariables, left_team_id: str, right_team_id: str) -> set[str]:
    left_groups = {
        candidate.group_id for candidate in variables.candidates_by_team.get(left_team_id, [])
    }
    right_groups = {
        candidate.group_id for candidate in variables.candidates_by_team.get(right_team_id, [])
    }
    return left_groups & right_groups


def _config_int(config: Any, name: str, default: int) -> int:
    try:
        return int(getattr(config, name, default) or default)
    except (TypeError, ValueError):
        return default


def _presence_var(model: Any, terms: list[Any], name: str, audit: ConstraintAudit) -> Any | None:
    if not terms:
        return None
    present = model.NewBoolVar(name)
    for term in terms:
        model.Add(present >= term)
    model.Add(sum(terms) >= present)
    audit.count_constraint("aggregate_level_presence", len(terms) + 1)
    return present


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in str(value))
