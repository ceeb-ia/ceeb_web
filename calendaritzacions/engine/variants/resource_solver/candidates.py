"""Candidate generation and phase projection for the resource solver."""

from __future__ import annotations

from typing import Iterable

from calendaritzacions.domain.phases import CalendarPhase
from calendaritzacions.engine.variants.resource_solver.resources import (
    base_resource_id_for_team,
    build_timed_resource_id,
)
from calendaritzacions.engine.variants.resource_solver.types import (
    Candidate,
    GroupSpec,
    TeamRecord,
)


def opponent_by_round(number: int, phase: CalendarPhase) -> dict[int, int]:
    opponents: dict[int, int] = {}
    for round_index, round_matches in enumerate(phase, start=1):
        for home_number, away_number in round_matches:
            if home_number == number:
                opponents[round_index] = away_number
                break
            if away_number == number:
                opponents[round_index] = home_number
                break
    return opponents


def home_rounds_for_number(number: int, phase: CalendarPhase) -> tuple[int, ...]:
    rounds: list[int] = []
    for round_index, round_matches in enumerate(phase, start=1):
        if any(home_number == number for home_number, _away_number in round_matches):
            rounds.append(round_index)
    return tuple(rounds)


def potential_home_resource_ids(
    team: TeamRecord,
    number: int,
    phase: CalendarPhase,
) -> tuple[str, ...]:
    base_resource_id = base_resource_id_for_team(team)
    return tuple(
        build_timed_resource_id(base_resource_id, round_index)
        for round_index in home_rounds_for_number(number, phase)
    )


def generate_candidates(
    teams: Iterable[TeamRecord],
    group_specs: Iterable[GroupSpec],
    phase: CalendarPhase,
) -> tuple[Candidate, ...]:
    candidates: list[Candidate] = []
    sorted_teams = sorted(teams, key=lambda team: team.team_id)
    sorted_groups = sorted(group_specs, key=lambda group: group.group_id)

    for team in sorted_teams:
        for group in sorted_groups:
            for number in group.numbers:
                candidate_id = _candidate_id(team.team_id, group.group_id, number)
                candidates.append(
                    Candidate(
                        candidate_id=candidate_id,
                        team_id=team.team_id,
                        group_id=group.group_id,
                        number=number,
                        seed_request_original=team.seed_request_original,
                        potential_home_rounds=home_rounds_for_number(number, phase),
                        opponent_number_by_round=opponent_by_round(number, phase),
                        potential_resources=potential_home_resource_ids(
                            team,
                            number,
                            phase,
                        ),
                    )
                )
    return tuple(candidates)


def _candidate_id(team_id: str, group_id: str, number: int) -> str:
    return f"{team_id}-{group_id}-{number}"


__all__ = [
    "generate_candidates",
    "home_rounds_for_number",
    "opponent_by_round",
    "potential_home_resource_ids",
]
