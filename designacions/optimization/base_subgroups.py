from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
from inspect import signature
from typing import Any, Iterable

from .classification import package_classification_importance, weighted_coverage
from .levels import hardest_match_level


try:
    from .contracts import BaseSubgroup as ContractBaseSubgroup
except Exception:  # pragma: no cover - contracts.py is optional during rollout.
    ContractBaseSubgroup = None


@dataclass(frozen=True)
class LocalBaseSubgroup:
    id: str
    match_ids: list[str]
    date: date | str | None
    modality: str
    start_dt: datetime | Any | None
    end_dt: datetime | Any | None
    venues: list[str] = field(default_factory=list)
    venue_ids: list[str] = field(default_factory=list)
    cluster_ids: list[str | None] = field(default_factory=list)
    cluster_statuses: list[str | None] = field(default_factory=list)
    match_count: int = 0
    level_demand: Any = None
    classification_pressure: float = 0.0
    classification_importance: float = 0.0
    weighted_coverage_value: float = 0.0
    rows: list[Any] = field(default_factory=list, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("rows", None)
        return payload


BaseSubgroup = ContractBaseSubgroup or LocalBaseSubgroup


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row.get(key, default)
    except AttributeError:
        return getattr(row, key, default)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(value != value)
    except Exception:
        return False


def _clean_text(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip()


def _dedupe(values: Iterable[Any]) -> list[Any]:
    out = []
    seen = set()
    for value in values:
        key = repr(value)
        if key not in seen:
            out.append(value)
            seen.add(key)
    return out


def _parse_date(value: Any) -> date | str | None:
    if _is_missing(value) or _clean_text(value).lower() in {"", "nat"}:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date") and not isinstance(value, str):
        try:
            return value.date()
        except Exception:
            pass
    raw = _clean_text(value)
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return raw


def _parse_time(value: Any) -> time | None:
    if _is_missing(value) or _clean_text(value) in {"", "-", "NaT"}:
        return None
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    if isinstance(value, time):
        return value.replace(microsecond=0)
    raw = _clean_text(value)
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


def _combine_datetime(row: Any) -> datetime | Any | None:
    value = _row_get(row, "__match_datetime")
    if not _is_missing(value):
        if hasattr(value, "to_pydatetime"):
            try:
                return value.to_pydatetime()
            except Exception:
                return value
        return value

    parsed_date = _parse_date(_row_get(row, "Data"))
    parsed_time = _parse_time(_row_get(row, "Hora"))
    if isinstance(parsed_date, date) and parsed_time is not None:
        return datetime.combine(parsed_date, parsed_time)
    return None


def _sort_key(row: Any) -> tuple[int, Any, str]:
    dt_value = _combine_datetime(row)
    if dt_value is None:
        return (1, datetime.max, _clean_text(_row_get(row, "ID") or _row_get(row, "Codi")))
    return (0, dt_value, _clean_text(_row_get(row, "ID") or _row_get(row, "Codi")))


def _match_id(row: Any, subgroup_index: int, row_index: int) -> str:
    for field_name in ("ID", "id", "Codi", "Codi Partit", "match_id"):
        value = _row_get(row, field_name)
        if not _is_missing(value) and _clean_text(value):
            return _clean_text(value)
    return f"sg{subgroup_index + 1}:match{row_index + 1}"


def _cluster_id(row: Any) -> str | None:
    value = _row_get(row, "cluster", _row_get(row, "cluster_id"))
    if _is_missing(value):
        return None
    text = _clean_text(value)
    if text in {"", "-1", "nan", "NaN", "None"}:
        return None
    try:
        parsed = float(text.replace(",", "."))
    except ValueError:
        return text
    if int(parsed) == -1:
        return None
    if parsed.is_integer():
        return str(int(parsed))
    return text


def _level_demand(rows: list[Any]) -> Any:
    values = [_row_get(row, "Categoria", _row_get(row, "Nivell")) for row in rows]
    values = [value for value in values if not _is_missing(value) and _clean_text(value)]
    return hardest_match_level(values)


def _build_base_subgroup(payload: dict[str, Any]) -> Any:
    if ContractBaseSubgroup is None:
        return LocalBaseSubgroup(**payload)
    accepted = set(signature(ContractBaseSubgroup).parameters)
    return ContractBaseSubgroup(**{key: value for key, value in payload.items() if key in accepted})


def build_base_subgroups_from_rows(subgroups: Iterable[Iterable[Any]]) -> list[Any]:
    """Convert current engine subgroup rows into pure BaseSubgroup objects."""
    base_subgroups = []
    for subgroup_index, subgroup in enumerate(subgroups or []):
        rows = sorted(list(subgroup or []), key=_sort_key)
        if not rows:
            continue

        datetimes = [dt for dt in (_combine_datetime(row) for row in rows) if dt is not None]
        dates = [_parse_date(_row_get(row, "Data")) for row in rows]
        dates = [value for value in dates if value is not None]
        match_ids = [_match_id(row, subgroup_index, row_index) for row_index, row in enumerate(rows)]
        venues = _dedupe(_clean_text(_row_get(row, "Pista joc", _row_get(row, "venue"))) for row in rows)
        venues = [venue for venue in venues if venue]
        cluster_ids = [_cluster_id(row) for row in rows]
        cluster_statuses = [
            (_clean_text(_row_get(row, "cluster_status")) or None)
            for row in rows
        ]
        modality = next(
            (
                _clean_text(_row_get(row, "Modalitat", _row_get(row, "modality")))
                for row in rows
                if _clean_text(_row_get(row, "Modalitat", _row_get(row, "modality")))
            ),
            "",
        )
        classification_importance = package_classification_importance(rows, _row_get)
        payload = {
            "id": f"base:{subgroup_index + 1}",
            "match_ids": match_ids,
            "date": dates[0] if dates else None,
            "modality": modality,
            "start_dt": min(datetimes) if datetimes else None,
            "end_dt": max(datetimes) if datetimes else None,
            "venues": venues,
            "venue_ids": venues,
            "cluster_ids": cluster_ids,
            "cluster_statuses": cluster_statuses,
            "match_count": len(match_ids),
            "level_demand": _level_demand(rows),
            "classification_pressure": 0.0,
            "classification_importance": classification_importance,
            "weighted_coverage_value": weighted_coverage(len(match_ids), classification_importance),
            "rows": rows,
        }
        base_subgroups.append(_build_base_subgroup(payload))
    return base_subgroups


__all__ = ["BaseSubgroup", "build_base_subgroups_from_rows"]
