"""Soft linkage constraints for teams that should keep related draw numbers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from calendaritzacions.engine.variants.resource_solver.constraints.base import (
    ConstraintAudit,
    ModelVariables,
    ObjectiveTerm,
)
from calendaritzacions.engine.variants.resource_solver.types import Candidate

try:
    from calendaritzacions.engine.variants.resource_solver import linkage as _linkage_helpers
except Exception:
    try:
        import resource_solver.linkage as _linkage_helpers  # type: ignore[no-redef]
    except Exception:
        _linkage_helpers = None


OPPOSITE_NUMBER = {
    1: 5,
    2: 6,
    3: 7,
    4: 8,
    5: 1,
    6: 2,
    7: 3,
    8: 4,
}

INDIFFERENT_SIDES = {"", "indiferent", "indifferent", "none", "neutral", "neutre"}


@dataclass(frozen=True)
class LinkageConstraints:
    name: str = "linkage"

    def add(
        self,
        model: Any,
        variables: ModelVariables,
        context: Any,
        objective_terms: list[ObjectiveTerm],
        audit: ConstraintAudit,
    ) -> None:
        add_linkage_constraints(model, variables, context, objective_terms, audit)


def add_linkage_constraints(
    model: Any,
    variables: ModelVariables,
    context: Any,
    objective_terms: list[ObjectiveTerm],
    audit: ConstraintAudit,
) -> None:
    """Penalize broken same/opposite linkage pairs without making the model infeasible."""

    weight = _linkage_weight(context)
    for _key, teams in _linkage_buckets(context).items():
        for left, right in combinations(sorted(teams, key=lambda item: item.team_id), 2):
            relation = _side_relation(
                getattr(left, "linkage_side", None),
                getattr(right, "linkage_side", None),
            )
            if relation not in {"same", "opposite"}:
                continue

            left_candidates = variables.candidates_by_team.get(left.team_id, [])
            right_candidates = variables.candidates_by_team.get(right.team_id, [])
            if not left_candidates or not right_candidates:
                continue

            violation = model.NewBoolVar(
                f"linkage_violation_{_safe_name(left.team_id)}_{_safe_name(right.team_id)}"
            )
            implication_count = 0
            for left_candidate in left_candidates:
                left_var = variables.x[left_candidate.candidate_id]
                for right_candidate in right_candidates:
                    if not violates_linkage_relation(
                        left_candidate.number,
                        right_candidate.number,
                        relation,
                    ):
                        continue
                    right_var = variables.x[right_candidate.candidate_id]
                    model.Add(violation >= left_var + right_var - 1)
                    implication_count += 1

            if implication_count == 0:
                continue
            pair_key = (left.team_id, right.team_id)
            variables.linkage_violation[pair_key] = violation
            objective_terms.append(("linkage_violation", weight, violation))
            audit.count_constraint("soft_linkage_pair")
            audit.count_constraint("linkage_violation_implication", implication_count)
            audit.count_objective_term("linkage_violation")


def fallback_linkage_violations(
    context: Any,
    combo: tuple[Candidate, ...],
) -> dict[tuple[str, str], int]:
    """Return selected linkage-pair violations for deterministic fallback scoring."""

    candidate_by_team = {candidate.team_id: candidate for candidate in combo}
    violations: dict[tuple[str, str], int] = {}
    for _key, teams in _linkage_buckets(context).items():
        for left, right in combinations(sorted(teams, key=lambda item: item.team_id), 2):
            relation = _side_relation(
                getattr(left, "linkage_side", None),
                getattr(right, "linkage_side", None),
            )
            if relation not in {"same", "opposite"}:
                continue
            left_candidate = candidate_by_team.get(left.team_id)
            right_candidate = candidate_by_team.get(right.team_id)
            if left_candidate is None or right_candidate is None:
                continue
            if violates_linkage_relation(
                left_candidate.number,
                right_candidate.number,
                relation,
            ):
                violations[(left.team_id, right.team_id)] = 1
    return violations


def violates_linkage_relation(left_number: int, right_number: int, relation: str) -> bool:
    if relation == "same":
        return left_number != right_number
    if relation == "opposite":
        return left_number != opposite_number(right_number)
    return False


def opposite_number(number: int) -> int | None:
    for helper_name in ("opposite_number", "number_opposite", "opposite_draw_number"):
        helper = getattr(_linkage_helpers, helper_name, None)
        if helper is None:
            continue
        try:
            value = helper(number)
        except Exception:
            continue
        if value is not None:
            return int(value)
    return OPPOSITE_NUMBER.get(number)


def _linkage_buckets(context: Any) -> dict[tuple[str, str], list[Any]]:
    buckets: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for team in getattr(context, "teams", ()):
        linkage_group = _normalize_linkage_group(getattr(team, "linkage_group", None))
        if not linkage_group or _is_indifferent_side(getattr(team, "linkage_side", None)):
            continue
        venue = _normalize_value(getattr(team, "venue", None))
        buckets[(venue, linkage_group)].append(team)
    return {key: teams for key, teams in buckets.items() if len(teams) > 1}


def _side_relation(left_side: Any, right_side: Any) -> str | None:
    if _is_indifferent_side(left_side) or _is_indifferent_side(right_side):
        return None

    if _helper_side_is_known(left_side) and _helper_side_is_known(right_side):
        sides_match = getattr(_linkage_helpers, "linkage_sides_match", None)
        sides_are_opposites = getattr(_linkage_helpers, "linkage_sides_are_opposites", None)
        if sides_match is not None:
            try:
                if bool(sides_match(left_side, right_side)):
                    return "same"
            except Exception:
                pass
        if sides_are_opposites is not None:
            try:
                if bool(sides_are_opposites(left_side, right_side)):
                    return "opposite"
            except Exception:
                pass

    for helper_name in ("linkage_relation", "relation_for_sides", "relation"):
        helper = getattr(_linkage_helpers, helper_name, None)
        if helper is None:
            continue
        try:
            value = helper(left_side, right_side)
        except Exception:
            continue
        relation = _normalize_relation(value)
        if relation is not None:
            return relation

    left = _normalize_value(left_side)
    right = _normalize_value(right_side)
    if left in INDIFFERENT_SIDES or right in INDIFFERENT_SIDES:
        return None
    if left == right:
        return "same"
    return "opposite"


def _normalize_relation(value: Any) -> str | None:
    relation = _normalize_value(value)
    if relation in {"same", "igual", "mateix", "same_side"}:
        return "same"
    if relation in {"opposite", "oposat", "contrari", "opposite_side"}:
        return "opposite"
    if relation in INDIFFERENT_SIDES:
        return None
    return None


def _linkage_weight(context: Any) -> int:
    try:
        return int(getattr(context.config, "linkage_violation_weight", 1_000_000) or 1_000_000)
    except (TypeError, ValueError):
        return 1_000_000


def _normalize_value(value: Any) -> str:
    return str(value or "").strip().casefold()


def _normalize_linkage_group(value: Any) -> str:
    helper = getattr(_linkage_helpers, "normalize_linkage_group", None)
    if helper is not None:
        try:
            return str(helper(value) or "")
        except Exception:
            pass
    return _normalize_value(value)


def _is_indifferent_side(value: Any) -> bool:
    return _normalize_value(value) in INDIFFERENT_SIDES


def _helper_side_is_known(value: Any) -> bool:
    helper = getattr(_linkage_helpers, "normalize_linkage_side_from_seed", None)
    if helper is None:
        return True
    try:
        return _normalize_value(helper(value)) not in INDIFFERENT_SIDES
    except Exception:
        return False


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in str(value))
