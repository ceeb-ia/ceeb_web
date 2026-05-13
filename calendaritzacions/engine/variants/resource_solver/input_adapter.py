"""Input adapters for resource solver records."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import fields, replace
from typing import Any
import unicodedata

try:
    import pandas as pd
except ImportError:  # pragma: no cover - pandas is declared by the application.
    pd = None

from calendaritzacions.engine.variants.resource_solver.resources import (
    DAY_COLUMN,
    TIME_COLUMN,
    VENUE_COLUMN,
    build_base_resources,
    normalize_day,
    normalize_hour_slot,
    normalize_venue,
)
from calendaritzacions.domain.phases import PRIMERA_FASE, SEGONA_FASE
from calendaritzacions.engine.variants.resource_solver.capacities import (
    build_resource_pressure,
    estimate_capacities,
)
from calendaritzacions.engine.variants.resource_solver.candidates import generate_candidates
from calendaritzacions.engine.variants.resource_solver.groups import build_group_specs
from calendaritzacions.engine.variants.resource_solver.types import SolverContext, TeamRecord

try:
    from calendaritzacions.engine.variants.resource_solver import linkage as linkage_domain
except ImportError:  # pragma: no cover - optional integration point.
    linkage_domain = None


TEAM_ID_COLUMN = "Id"
TEAM_NAME_COLUMN = "Nom"
ENTITY_COLUMN = "Entitat"
LEAGUE_COLUMN = "Nom Lliga"
MODALITY_COLUMN = "Modalitat"
CATEGORY_COLUMN = "Categoria"
SUBCATEGORY_COLUMN = "Subcategoria"
LEVEL_COLUMN = "Nivell"
SEED_COLUMN_CANDIDATES = (
    "N\u00fam. sorteig",
    "Num. sorteig",
    "N\u00c3\u00bam. sorteig",
)
SIDE_REQUEST_COLUMN_CANDIDATES = (
    "Peticio",
    "Petici\u00f3",
    "Petici\u00c3\u00b3",
    "Peticio sorteig",
    "Petici\u00f3 sorteig",
    "Petici\u00c3\u00b3 sorteig",
    *SEED_COLUMN_CANDIDATES,
)
LINKAGE_GROUP_COLUMN_CANDIDATES = (
    "Grup vinculacio",
    "Grup vinculaci\u00f3",
    "Grup vinculaci\u00c3\u00b3",
)
LINKAGE_GROUP_FIELD = "linkage_group"
LINKAGE_SIDE_FIELD = "linkage_side"
LINKAGE_SOURCE_FIELD = "linkage_source"
LINKAGE_INPUT_SOURCE = "input"


def build_team_records(df: pd.DataFrame) -> tuple[TeamRecord, ...]:
    """Build stable team records from a legacy input DataFrame.

    Duplicate rows for the same team are collapsed. The first non-empty value for
    each descriptive column is kept, while resource fields are normalized before
    storing them in the record.
    """

    records: dict[str, TeamRecord] = {}
    row_positions = {index: position for position, index in enumerate(df.index)}

    for index, row in df.iterrows():
        fallback_id = f"row-{row_positions[index] + 1}"
        team_id = _text(row.get(TEAM_ID_COLUMN), fallback_id)
        if team_id in records:
            continue
        seed_request_original = _first_existing(row, SEED_COLUMN_CANDIDATES)
        linkage_group = _normalize_linkage_group(
            _first_existing(row, LINKAGE_GROUP_COLUMN_CANDIDATES)
        )
        records[team_id] = TeamRecord(
            team_id=team_id,
            name=_text(row.get(TEAM_NAME_COLUMN), team_id),
            entity=_text(row.get(ENTITY_COLUMN), ""),
            league_name=_text(row.get(LEAGUE_COLUMN), ""),
            modality=_text(row.get(MODALITY_COLUMN), ""),
            category=_text(row.get(CATEGORY_COLUMN), ""),
            subcategory=_text(row.get(SUBCATEGORY_COLUMN), ""),
            level=_text(row.get(LEVEL_COLUMN), ""),
            venue=normalize_venue(row.get(VENUE_COLUMN)),
            day=normalize_day(row.get(DAY_COLUMN)),
            time=normalize_hour_slot(row.get(TIME_COLUMN)),
            seed_request_original=seed_request_original,
        )
        records[team_id] = _with_linkage(
            records[team_id],
            linkage_group,
            _normalize_linkage_side(_first_existing(row, SIDE_REQUEST_COLUMN_CANDIDATES)),
            LINKAGE_INPUT_SOURCE if linkage_group else "",
        )

    return tuple(records[key] for key in sorted(records))


def build_context_from_input(input_path: str, config: Any) -> SolverContext:
    """Build a full solver context from an Excel input path."""

    from calendaritzacions.ingestion import read_excel

    df = read_excel(input_path)
    return build_context_from_dataframe(df, config)


def build_context_from_dataframe(df: pd.DataFrame, config: Any) -> SolverContext:
    """Build a full solver context from a prepared or raw input DataFrame."""

    phase_name = "segona_fase" if getattr(config, "phase_name", "primera_fase") == "segona_fase" else "primera_fase"
    phase = SEGONA_FASE if phase_name == "segona_fase" else PRIMERA_FASE
    teams = build_team_records(df)
    teams = _apply_linkage_mode(teams, config)
    resources = build_base_resources(teams)
    capacities = estimate_capacities(resources, teams, config)
    pressure = build_resource_pressure(resources, teams, capacities)
    groups = []
    candidates = []
    for competition_index, (_key, competition_teams) in enumerate(
        _teams_by_competition(teams),
        start=1,
    ):
        competition_groups = build_group_specs(
            competition_teams,
            phase_name,
            config,
            group_prefix=f"C{competition_index}_G",
        )
        groups.extend(competition_groups)
        candidates.extend(generate_candidates(competition_teams, competition_groups, phase))
    return SolverContext(
        teams=teams,
        phase=phase,
        phase_name=phase_name,
        base_resources=resources,
        capacities=capacities,
        pressure=pressure,
        groups=tuple(groups),
        candidates=tuple(candidates),
        config=config,
    )


def _teams_by_competition(
    teams: tuple[TeamRecord, ...],
) -> tuple[tuple[tuple[str, ...], tuple[TeamRecord, ...]], ...]:
    buckets: dict[tuple[str, ...], list[TeamRecord]] = defaultdict(list)
    for team in teams:
        buckets[_competition_key(team)].append(team)
    return tuple(
        (key, tuple(sorted(items, key=lambda item: item.team_id)))
        for key, items in sorted(buckets.items())
    )


def _competition_key(team: TeamRecord) -> tuple[str, ...]:
    parts = (team.modality.strip(), team.category.strip(), team.subcategory.strip())
    if all(parts):
        return ("fields", *parts)
    league_name = team.league_name.strip() or "Sense lliga"
    return ("league", league_name)


def _first_existing(row: pd.Series, columns: tuple[str, ...]) -> Any:
    for column in columns:
        if column in row:
            return row[column]
    return ""


def _apply_linkage_mode(
    teams: tuple[TeamRecord, ...],
    config: Any,
) -> tuple[TeamRecord, ...]:
    mode = _normalized_linkage_mode(getattr(config, "linkage_mode", "off"))
    if mode == "off":
        return _clear_linkage_groups(teams, config)
    if mode == "input":
        return _apply_input_linkage_groups(teams, config)
    return _apply_simulated_linkage_groups(teams, config)


def _clear_linkage_groups(
    teams: tuple[TeamRecord, ...],
    config: Any,
) -> tuple[TeamRecord, ...]:
    helper_result = _call_linkage_helper("clear_linkage_groups", teams, config)
    if helper_result is not None:
        return helper_result
    return tuple(_with_linkage(team, "", "", "") for team in teams)


def _apply_input_linkage_groups(
    teams: tuple[TeamRecord, ...],
    config: Any,
) -> tuple[TeamRecord, ...]:
    helper_result = _call_linkage_helper("apply_input_linkage_groups", teams, config)
    if helper_result is not None:
        return helper_result
    return tuple(
        _with_input_linkage(team)
        for team in teams
    )


def _with_input_linkage(team: TeamRecord) -> TeamRecord:
    group = _team_linkage_group(team)
    return _with_linkage(
        team,
        group,
        _team_linkage_side(team),
        _team_linkage_source(team) or (LINKAGE_INPUT_SOURCE if group else ""),
    )


def _apply_simulated_linkage_groups(
    teams: tuple[TeamRecord, ...],
    config: Any,
) -> tuple[TeamRecord, ...]:
    helper_result = _call_linkage_helper("apply_simulated_linkage_groups", teams, config)
    if helper_result is not None:
        return helper_result

    simulation_teams = tuple(
        _with_linkage(
            team,
            "",
            _team_linkage_side(team),
            "",
        )
        for team in teams
    )
    simulate = getattr(linkage_domain, "simulate_linkage_groups", None) if linkage_domain is not None else None
    if callable(simulate):
        updated, _audit = simulate(simulation_teams)
        return tuple(updated)

    max_size = _linkage_max_group_size(config)
    by_team_id = {team.team_id: team for team in simulation_teams}
    for competition_index, (_key, competition_teams) in enumerate(
        _teams_by_competition(simulation_teams),
        start=1,
    ):
        for group_index, start in enumerate(range(0, len(competition_teams), max_size), start=1):
            chunk = competition_teams[start : start + max_size]
            if len(chunk) < 2:
                for team in chunk:
                    by_team_id[team.team_id] = _with_linkage(
                        team,
                        "",
                        _team_linkage_side(team),
                        "",
                    )
                continue

            group_id = f"sim-c{competition_index:03d}-g{group_index:03d}"
            for position, team in enumerate(chunk):
                side = _team_linkage_side(team)
                if side not in {"casa", "fora"}:
                    side = "casa" if position % 2 == 0 else "fora"
                by_team_id[team.team_id] = _with_linkage(team, group_id, side, "simulated")

    return tuple(by_team_id[team.team_id] for team in simulation_teams)


def _call_linkage_helper(
    name: str,
    teams: tuple[TeamRecord, ...],
    config: Any,
) -> tuple[TeamRecord, ...] | None:
    helper = getattr(linkage_domain, name, None) if linkage_domain is not None else None
    if not callable(helper):
        return None
    return tuple(helper(teams, config))


def _normalized_linkage_mode(value: Any) -> str:
    mode = str(value or "off").strip().casefold()
    if mode in {"off", "none", "disabled", "false", "0"}:
        return "off"
    if mode in {"input", "vinculacio", "vinculació"}:
        return "input"
    if mode in {"simulated", "simulate", "simulation", "linkage"}:
        return "simulated"
    return "off"


def _linkage_max_group_size(config: Any) -> int:
    try:
        value = int(getattr(config, "linkage_max_group_size", 2))
    except (TypeError, ValueError):
        value = 2
    return max(2, value)


def _normalize_linkage_group(value: Any) -> str:
    helper = getattr(linkage_domain, "normalize_linkage_group", None) if linkage_domain is not None else None
    if callable(helper):
        return _text(helper(value), "")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return _text(value, "")


def _normalize_linkage_side(value: Any) -> str:
    helper = getattr(linkage_domain, "normalize_linkage_side_from_seed", None) if linkage_domain is not None else None
    if callable(helper):
        return _text(helper(value), "")

    text = _text(value, "")
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    folded = folded.casefold().replace(" ", "").replace("-", "").replace("_", "")
    if folded in {"casa", "home", "local", "acasa"}:
        return "casa"
    if folded in {"fora", "away", "visitant", "visitante", "afora"}:
        return "fora"
    return "indiferent" if text else ""


def _with_linkage(team: TeamRecord, group_id: str, side: str, source: str = "") -> TeamRecord:
    updates: dict[str, str] = {}
    field_names = _team_record_field_names()
    if LINKAGE_GROUP_FIELD in field_names:
        updates[LINKAGE_GROUP_FIELD] = group_id
    if LINKAGE_SIDE_FIELD in field_names:
        updates[LINKAGE_SIDE_FIELD] = side
    if LINKAGE_SOURCE_FIELD in field_names:
        updates[LINKAGE_SOURCE_FIELD] = source

    if updates:
        team = replace(team, **updates)
    if LINKAGE_GROUP_FIELD not in field_names:
        object.__setattr__(team, LINKAGE_GROUP_FIELD, group_id)
    if LINKAGE_SIDE_FIELD not in field_names:
        object.__setattr__(team, LINKAGE_SIDE_FIELD, side)
    if LINKAGE_SOURCE_FIELD not in field_names:
        object.__setattr__(team, LINKAGE_SOURCE_FIELD, source)
    return team


def _team_linkage_group(team: TeamRecord) -> str:
    return _text(getattr(team, LINKAGE_GROUP_FIELD, ""), "")


def _team_linkage_side(team: TeamRecord) -> str:
    return _normalize_linkage_side(getattr(team, LINKAGE_SIDE_FIELD, ""))


def _team_linkage_source(team: TeamRecord) -> str:
    return _text(getattr(team, LINKAGE_SOURCE_FIELD, ""), "")


def _team_record_field_names() -> set[str]:
    return {field.name for field in fields(TeamRecord)}


def _text(value: Any, default: str) -> str:
    if value is None or (pd is not None and pd.isna(value)):
        return default
    text = " ".join(str(value).strip().split())
    return text if text else default


__all__ = ["build_context_from_dataframe", "build_context_from_input", "build_team_records"]
