"""Pure linkage helpers for resource-solver team records."""

from __future__ import annotations

from dataclasses import replace
from itertools import combinations
from typing import Any, Iterable
import math
import re
import unicodedata

from calendaritzacions.engine.variants.resource_solver.types import TeamRecord


CASA = "casa"
FORA = "fora"
INDIFERENT = "indiferent"
SIMULATED_SOURCE = "simulated_resource_solver"

HOME_NUMBERS = frozenset({1, 6, 7, 8})
AWAY_NUMBERS = frozenset({2, 3, 4, 5})
OPPOSITE_NUMBER_BY_NUMBER = {
    1: 5,
    5: 1,
    6: 2,
    2: 6,
    7: 3,
    3: 7,
    8: 4,
    4: 8,
}
OPPOSITE_NUMBER_MAP = OPPOSITE_NUMBER_BY_NUMBER

PREFERRED_PATTERNS = (
    (CASA, CASA),
    (CASA, FORA),
    (CASA, CASA, FORA),
)


def normalize_linkage_group(value: Any) -> str:
    """Return a stable ASCII group key, or an empty string for no group."""

    text = _normalized_text(value)
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def normalize_linkage_side_from_seed(value: Any) -> str:
    """Project a seed request to casa, fora, or indiferent."""

    number = _coerce_int(value)
    if number in HOME_NUMBERS:
        return CASA
    if number in AWAY_NUMBERS:
        return FORA

    text = _normalized_text(value)
    if text == CASA:
        return CASA
    if text == FORA:
        return FORA
    return INDIFERENT


def opposite_number(number: Any) -> int | None:
    """Return the opposite linked number, when the request maps to one."""

    return OPPOSITE_NUMBER_BY_NUMBER.get(_coerce_int(number))


def are_opposite_numbers(left: Any, right: Any) -> bool:
    return opposite_number(left) == _coerce_int(right)


def linkage_sides_match(left: Any, right: Any) -> bool:
    """Return whether two side requirements can share the same side."""

    left_side = _normalize_side(left)
    right_side = _normalize_side(right)
    return INDIFERENT in {left_side, right_side} or left_side == right_side


def linkage_sides_are_opposites(left: Any, right: Any) -> bool:
    left_side = _normalize_side(left)
    right_side = _normalize_side(right)
    return {left_side, right_side} == {CASA, FORA}


def seed_request_matches_side(seed_request: Any, side: str) -> bool:
    """Return whether a seed request is compatible with an assigned side."""

    requested_side = normalize_linkage_side_from_seed(seed_request)
    assigned_side = _normalize_side(side)
    return requested_side == INDIFERENT or requested_side == assigned_side


def simulate_linkage_groups(
    teams: Iterable[TeamRecord],
) -> tuple[tuple[TeamRecord, ...], tuple[dict[str, Any], ...]]:
    """Generate conservative deterministic linkage groups by venue and day.

    The simulator is intentionally sparse: at least a strict majority of teams
    remains unlinked, and teams are only linked inside the same venue/day bucket.
    """

    original = tuple(teams)
    if len(original) < 5:
        return original, ()

    updated_by_id = {team.team_id: team for team in original}
    used_team_ids = {
        team.team_id
        for team in original
        if normalize_linkage_group(team.linkage_group)
    }
    linked_budget = max(0, (len(original) - 1) // 2 - len(used_team_ids))
    generated: list[dict[str, Any]] = []

    buckets: dict[tuple[str, str], list[TeamRecord]] = {}
    for team in original:
        if team.team_id in used_team_ids:
            continue
        if not team.venue or not team.day:
            continue
        buckets.setdefault((team.venue, team.day), []).append(team)

    sequence = 1
    for bucket_key in sorted(buckets, key=_bucket_sort_key):
        bucket = tuple(sorted(buckets[bucket_key], key=_team_sort_key))
        while linked_budget >= 2:
            selected = _best_group_for_patterns(bucket, used_team_ids, linked_budget)
            if selected is None:
                break

            group_teams, pattern, consecutive = selected
            group_id = _generated_group_id(group_teams[0], sequence)
            sequence += 1

            sides_by_team_id: dict[str, str] = {}
            times_by_team_id: dict[str, str] = {}
            for team, side in zip(group_teams, pattern):
                used_team_ids.add(team.team_id)
                sides_by_team_id[team.team_id] = side
                times_by_team_id[team.team_id] = team.time
                updated_by_id[team.team_id] = replace(
                    team,
                    linkage_group=group_id,
                    linkage_side=side,
                    linkage_source=SIMULATED_SOURCE,
                )

            linked_budget -= len(group_teams)
            generated.append(
                {
                    "group": group_id,
                    "source": SIMULATED_SOURCE,
                    "venue": group_teams[0].venue,
                    "day": group_teams[0].day,
                    "pattern": "-".join(side.upper() for side in pattern),
                    "team_ids": tuple(team.team_id for team in group_teams),
                    "sides": sides_by_team_id,
                    "times": times_by_team_id,
                    "consecutive_hour_slots": consecutive,
                }
            )

    return tuple(updated_by_id[team.team_id] for team in original), tuple(generated)


normalized_linkage_group = normalize_linkage_group
normalized_linkage_side_from_seed_request = normalize_linkage_side_from_seed
simulate_resource_solver_linkage_groups = simulate_linkage_groups


def _best_group_for_patterns(
    bucket: tuple[TeamRecord, ...],
    used_team_ids: set[str],
    linked_budget: int,
) -> tuple[tuple[TeamRecord, ...], tuple[str, ...], bool] | None:
    best_score = None
    best_group = None
    for pattern_index, pattern in enumerate(PREFERRED_PATTERNS):
        if len(pattern) > linked_budget:
            continue
        group = _best_group_for_pattern(bucket, used_team_ids, pattern)
        if group is None:
            continue
        group_teams, _pattern, consecutive = group
        score = (
            0 if consecutive else 1,
            -len(pattern),
            pattern_index,
            _hour_span(group_teams),
            tuple(_team_sort_key(team) for team in group_teams),
        )
        if best_score is None or score < best_score:
            best_score = score
            best_group = group
    return best_group


def _best_group_for_pattern(
    bucket: tuple[TeamRecord, ...],
    used_team_ids: set[str],
    pattern: tuple[str, ...],
) -> tuple[tuple[TeamRecord, ...], tuple[str, ...], bool] | None:
    available = tuple(team for team in bucket if team.team_id not in used_team_ids)
    if len(available) < len(pattern):
        return None

    best_score = None
    best_group = None
    indexed = tuple(enumerate(available))
    for group in combinations(indexed, len(pattern)):
        indexes = tuple(index for index, _team in group)
        teams = tuple(team for _index, team in group)
        if not all(
            seed_request_matches_side(team.seed_request_original, side)
            for team, side in zip(teams, pattern)
        ):
            continue
        consecutive = _has_consecutive_hour_slots(teams)
        span = _hour_span(teams)
        score = (0 if consecutive else 1, span, indexes)
        if best_score is None or score < best_score:
            best_score = score
            best_group = (teams, pattern, consecutive)
    return best_group


def _generated_group_id(team: TeamRecord, sequence: int) -> str:
    base = normalize_linkage_group(f"{team.venue}-{team.day}")
    if not base:
        base = "missing"
    return f"link-{base}-{sequence:03d}"


def _has_consecutive_hour_slots(teams: tuple[TeamRecord, ...]) -> bool:
    minutes = [_parse_hour_slot(team.time) for team in teams]
    if any(value is None for value in minutes):
        return False
    sorted_minutes = sorted(int(value) for value in minutes)
    return all(
        right - left == 60
        for left, right in zip(sorted_minutes, sorted_minutes[1:])
    )


def _hour_span(teams: tuple[TeamRecord, ...]) -> int:
    minutes = sorted(
        minute
        for minute in (_parse_hour_slot(team.time) for team in teams)
        if minute is not None
    )
    if len(minutes) < len(teams):
        return 10_000
    return minutes[-1] - minutes[0]


def _parse_hour_slot(value: Any) -> int | None:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(value))
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _team_sort_key(team: TeamRecord) -> tuple[Any, ...]:
    minutes = _parse_hour_slot(team.time)
    return (
        minutes is None,
        minutes if minutes is not None else 10_000,
        str(team.time),
        team.team_id,
        team.name,
        team.entity,
        team.league_name,
    )


def _bucket_sort_key(bucket_key: tuple[str, str]) -> tuple[str, str]:
    venue, day = bucket_key
    return (_normalized_text(venue), _normalized_text(day))


def _normalize_side(value: Any) -> str:
    text = _normalized_text(value)
    if text == CASA:
        return CASA
    if text == FORA:
        return FORA
    if text == INDIFERENT:
        return INDIFERENT
    return normalize_linkage_side_from_seed(value)


def _normalized_text(value: Any) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).strip().split())
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or not value.is_integer():
            return None
        return int(value)
    text = str(value).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    if re.fullmatch(r"\d+\.0+", text):
        return int(float(text))
    return None


__all__ = [
    "AWAY_NUMBERS",
    "CASA",
    "FORA",
    "HOME_NUMBERS",
    "INDIFERENT",
    "OPPOSITE_NUMBER_BY_NUMBER",
    "OPPOSITE_NUMBER_MAP",
    "PREFERRED_PATTERNS",
    "SIMULATED_SOURCE",
    "are_opposite_numbers",
    "linkage_sides_are_opposites",
    "linkage_sides_match",
    "normalize_linkage_group",
    "normalize_linkage_side_from_seed",
    "normalized_linkage_group",
    "normalized_linkage_side_from_seed_request",
    "opposite_number",
    "seed_request_matches_side",
    "simulate_linkage_groups",
    "simulate_resource_solver_linkage_groups",
]
