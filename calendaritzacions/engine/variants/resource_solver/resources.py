"""Resource normalization and grouping for the resource solver."""

from __future__ import annotations

from datetime import datetime, time, timedelta
import math
import re
from typing import Any, Iterable
import unicodedata

try:
    import pandas as pd
except ImportError:  # pragma: no cover - pandas is a runtime dependency upstream.
    pd = None

from calendaritzacions.engine.variants.resource_solver.types import (
    BaseResource,
    TeamRecord,
    TimedResource,
)


VENUE_COLUMN = "Pista joc"
DAY_COLUMN = "Dia partit"
TIME_COLUMN = "Horari partit"

MISSING_VENUE = "(sense pista)"
MISSING_DAY = "(sense dia)"
MISSING_TIME = "(sense hora)"


def normalize_venue(value: Any) -> str:
    return _normalize_text(value, MISSING_VENUE)


def normalize_day(value: Any) -> str:
    text = _normalize_text(value, MISSING_DAY)
    if text == MISSING_DAY:
        return text
    return text.capitalize()


def normalize_hour_slot(value: Any) -> str:
    formatted = _format_time_value(value)
    if formatted == MISSING_TIME:
        return formatted
    match = re.fullmatch(r"(\d{2}):(\d{2})", formatted)
    if not match:
        return formatted
    return f"{int(match.group(1)):02d}:00"


def build_base_resource_id(venue: str, day: str, hour_slot: str) -> str:
    return "|".join(_slug_part(part) for part in (venue, day, hour_slot))


def build_timed_resource_id(base_resource_id: str, round_index: int) -> str:
    return f"{base_resource_id}|J{round_index}"


def base_resource_id_for_team(team: TeamRecord) -> str:
    return build_base_resource_id(team.venue, team.day, team.time)


def build_base_resources(teams: Iterable[TeamRecord]) -> dict[str, BaseResource]:
    resources: dict[str, BaseResource] = {}
    for team in teams:
        resource_id = base_resource_id_for_team(team)
        resources.setdefault(
            resource_id,
            BaseResource(
                resource_id=resource_id,
                venue=team.venue,
                day=team.day,
                hour_slot=team.time,
            ),
        )
    return dict(sorted(resources.items()))


def build_timed_resources(
    base_resources: dict[str, BaseResource],
    round_indexes: Iterable[int],
) -> dict[str, TimedResource]:
    timed: dict[str, TimedResource] = {}
    for base_resource in base_resources.values():
        for round_index in round_indexes:
            resource_id = build_timed_resource_id(
                base_resource.resource_id,
                round_index,
            )
            timed[resource_id] = TimedResource(
                resource_id=resource_id,
                base_resource_id=base_resource.resource_id,
                venue=base_resource.venue,
                day=base_resource.day,
                hour_slot=base_resource.hour_slot,
                round_index=round_index,
            )
    return dict(sorted(timed.items()))


def teams_by_base_resource(
    teams: Iterable[TeamRecord],
) -> dict[str, tuple[TeamRecord, ...]]:
    grouped: dict[str, dict[str, TeamRecord]] = {}
    for team in teams:
        grouped.setdefault(base_resource_id_for_team(team), {})[team.team_id] = team
    return {
        resource_id: tuple(sorted(items.values(), key=lambda team: team.team_id))
        for resource_id, items in sorted(grouped.items())
    }


def _normalize_text(value: Any, missing_label: str) -> str:
    if _is_missing(value):
        return missing_label
    text = " ".join(str(value).strip().split())
    return text if text else missing_label


def _format_time_value(value: Any) -> str:
    if _is_missing(value):
        return MISSING_TIME
    if pd is not None and isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return MISSING_TIME
        return value.strftime("%H:%M")
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, timedelta):
        return _format_minutes(int(value.total_seconds() // 60))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if math.isnan(numeric):
            return MISSING_TIME
        if 0 <= numeric < 1:
            return _format_minutes(round(numeric * 24 * 60))
        if 0 <= numeric < 24:
            hours = int(numeric)
            minutes = round((numeric - hours) * 60)
            return _format_minutes(hours * 60 + minutes)
    text = " ".join(str(value).strip().split())
    if not text:
        return MISSING_TIME
    match = re.search(r"(\d{1,2})[:.hH](\d{2})", text)
    if match:
        return _format_minutes(int(match.group(1)) * 60 + int(match.group(2)))
    match = re.fullmatch(r"\d{1,2}", text)
    if match:
        return _format_minutes(int(text) * 60)
    return text


def _format_minutes(total_minutes: int) -> str:
    total_minutes = total_minutes % (24 * 60)
    hours, _minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:00"


def _slug_part(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value).strip().casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "missing"


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd is not None:
            return bool(pd.isna(value))
        return bool(math.isnan(value))
    except (TypeError, ValueError):
        return False


__all__ = [
    "DAY_COLUMN",
    "MISSING_DAY",
    "MISSING_TIME",
    "MISSING_VENUE",
    "TIME_COLUMN",
    "VENUE_COLUMN",
    "base_resource_id_for_team",
    "build_base_resource_id",
    "build_base_resources",
    "build_timed_resource_id",
    "build_timed_resources",
    "normalize_day",
    "normalize_hour_slot",
    "normalize_venue",
    "teams_by_base_resource",
]
