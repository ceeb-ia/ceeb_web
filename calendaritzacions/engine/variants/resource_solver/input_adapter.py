"""Input adapters for resource solver records."""

from __future__ import annotations

from typing import Any

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
            seed_request_original=_first_existing(row, SEED_COLUMN_CANDIDATES),
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
    resources = build_base_resources(teams)
    capacities = estimate_capacities(resources, teams, config)
    pressure = build_resource_pressure(resources, teams, capacities)
    groups = build_group_specs(teams, phase_name, config)
    candidates = generate_candidates(teams, groups, phase)
    return SolverContext(
        teams=teams,
        phase=phase,
        phase_name=phase_name,
        base_resources=resources,
        capacities=capacities,
        pressure=pressure,
        groups=groups,
        candidates=candidates,
        config=config,
    )


def _first_existing(row: pd.Series, columns: tuple[str, ...]) -> Any:
    for column in columns:
        if column in row:
            return row[column]
    return ""


def _text(value: Any, default: str) -> str:
    if value is None or (pd is not None and pd.isna(value)):
        return default
    text = " ".join(str(value).strip().split())
    return text if text else default


__all__ = ["build_context_from_dataframe", "build_context_from_input", "build_team_records"]
