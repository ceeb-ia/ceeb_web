from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from .classification import package_classification_importance, weighted_coverage
from .contracts import normalize_id, normalize_ids
from .levels import hardest_match_level, match_level_position


DateLike = date | datetime | str | None

DEFAULT_MAX_SIZE = 2
DEFAULT_MAX_SPAN = 3


@dataclass(frozen=True)
class LevelFragment:
    id: str
    source_subgroup_id: str
    match_ids: list[str]
    rows: list[Any] = field(default_factory=list, repr=False, compare=False)
    date: DateLike = None
    modality: str = ""
    start_dt: DateLike = None
    end_dt: DateLike = None
    venues: list[str] = field(default_factory=list)
    venue_ids: list[str] = field(default_factory=list)
    cluster_ids: list[str | None] = field(default_factory=list)
    cluster_statuses: list[str | None] = field(default_factory=list)
    level_demand: Any = None
    max_level_span: int = 0
    classification_pressure: float = 0.0
    classification_importance: float = 0.0
    weighted_coverage_value: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", normalize_id(self.id))
        object.__setattr__(self, "source_subgroup_id", normalize_id(self.source_subgroup_id))
        object.__setattr__(self, "match_ids", normalize_ids(self.match_ids))
        object.__setattr__(self, "venues", normalize_ids(self.venues))
        object.__setattr__(self, "venue_ids", normalize_ids(self.venue_ids))

    @property
    def match_count(self) -> int:
        return len(self.match_ids)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("rows", None)
        payload["match_count"] = self.match_count
        return payload


def _value_get(source: Any, key: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, Mapping):
        return source.get(key, default)
    if is_dataclass(source) and not isinstance(source, type):
        return getattr(source, key, default)
    try:
        value = source.get(key, default)
    except AttributeError:
        value = getattr(source, key, default)
    return default if _is_missing(value) else value


def _first_value(source: Any, keys: Iterable[str], default: Any = None) -> Any:
    for key in keys:
        value = _value_get(source, key, default=None)
        if not _is_missing(value):
            return value
    return default


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
    output = []
    seen = set()
    for value in values:
        key = repr(value)
        if key in seen:
            continue
        output.append(value)
        seen.add(key)
    return output


def _as_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _row_level(row: Any) -> Any:
    return _first_value(row, ("Categoria", "categoria", "Nivell", "nivell", "level", "match_level"))


def _row_match_id(row: Any) -> str:
    return _clean_text(_first_value(row, ("ID", "id", "Codi", "Codi Partit", "match_id")))


def _row_sort_key(row: Any) -> tuple[int, Any, str]:
    value = _first_value(row, ("__match_datetime", "start_dt", "inici", "Hora", "hora"), default=None)
    if _is_missing(value):
        return (1, "", _row_match_id(row))
    if hasattr(value, "to_pydatetime"):
        try:
            value = value.to_pydatetime()
        except Exception:
            pass
    return (0, str(value), _row_match_id(row))


def _non_missing_values(values: Iterable[Any]) -> list[Any]:
    return [value for value in values if not _is_missing(value)]


def _safe_min(values: Iterable[Any]) -> Any:
    values = _non_missing_values(values)
    if not values:
        return None
    try:
        return min(values)
    except TypeError:
        return sorted(values, key=str)[0]


def _safe_max(values: Iterable[Any]) -> Any:
    values = _non_missing_values(values)
    if not values:
        return None
    try:
        return max(values)
    except TypeError:
        return sorted(values, key=str)[-1]


def _row_get_for_classification(row: Any, key: str, default: Any = None) -> Any:
    return _value_get(row, key, default)


def _levels_span(rows: list[Any]) -> int:
    positions = [match_level_position(_row_level(row)) for row in rows]
    positions = [position for position in positions if position is not None]
    if len(positions) < 2:
        return 0
    return max(positions) - min(positions)


def _fragment_level_demand(rows: list[Any]) -> Any:
    values = [_row_level(row) for row in rows]
    values = [value for value in values if not _is_missing(value) and _clean_text(value)]
    return hardest_match_level(values)


def _split_rows_by_level(rows: list[Any], max_size: int, max_span: int) -> list[list[Any]]:
    fragments: list[list[Any]] = []
    current: list[Any] = []
    for row in rows:
        candidate = [*current, row]
        if current and (len(candidate) > max_size or _levels_span(candidate) > max_span):
            fragments.append(current)
            current = [row]
        else:
            current = candidate
    if current:
        fragments.append(current)
    return fragments


def _sequence_for_rows(subgroup: Any, rows: list[Any]) -> list[int]:
    source_rows = list(_value_get(subgroup, "rows", default=[]) or [])
    if not source_rows:
        return list(range(len(rows)))

    by_identity = {id(row): index for index, row in enumerate(source_rows)}
    indexes = []
    for row in rows:
        indexes.append(by_identity.get(id(row), len(indexes)))
    return indexes


def _select_aligned_values(values: Any, indexes: list[int]) -> list[Any]:
    if values is None:
        return []
    values_list = list(values) if not isinstance(values, str) else [values]
    if not values_list:
        return []
    if len(values_list) > max(indexes, default=-1):
        return _dedupe(values_list[index] for index in indexes)
    return _dedupe(values_list)


def _source_match_ids(subgroup: Any, rows: list[Any], indexes: list[int]) -> list[str]:
    subgroup_match_ids = normalize_ids(_value_get(subgroup, "match_ids", default=[]))
    if subgroup_match_ids and len(subgroup_match_ids) > max(indexes, default=-1):
        return [subgroup_match_ids[index] for index in indexes if subgroup_match_ids[index]]

    row_ids = [_row_match_id(row) for row in rows]
    row_ids = [match_id for match_id in row_ids if match_id]
    if row_ids:
        return row_ids

    source_id = normalize_id(_first_value(subgroup, ("id", "subgroup_id"), default="fragment"))
    return [f"{source_id}:match{index + 1}" for index in indexes]


def _build_fragment(subgroup: Any, rows: list[Any], fragment_index: int) -> LevelFragment:
    source_id = normalize_id(_first_value(subgroup, ("id", "subgroup_id"), default="subgroup"))
    indexes = _sequence_for_rows(subgroup, rows)
    match_ids = _source_match_ids(subgroup, rows, indexes)
    row_classification_importance = package_classification_importance(rows, _row_get_for_classification)
    source_classification_importance = float(
        _first_value(subgroup, ("classification_importance", "importancia_classificacio"), default=0.0) or 0.0
    )
    classification_importance = max(row_classification_importance, source_classification_importance)
    source_weighted_value = float(
        _first_value(subgroup, ("weighted_coverage_value", "valor_cobertura_ponderat"), default=0.0) or 0.0
    )
    weighted_value = source_weighted_value if len(match_ids) == len(normalize_ids(_value_get(subgroup, "match_ids", []))) else 0.0
    if not weighted_value:
        weighted_value = weighted_coverage(len(match_ids), classification_importance)
    return LevelFragment(
        id=f"{source_id}:level:{fragment_index + 1}",
        source_subgroup_id=source_id,
        match_ids=match_ids,
        rows=list(rows),
        date=_first_value(subgroup, ("date", "data")),
        modality=normalize_id(_first_value(subgroup, ("modality", "modalitat"), default="")),
        start_dt=_safe_min(_first_value(row, ("__match_datetime", "start_dt", "inici", "Hora"), default=None) for row in rows),
        end_dt=_safe_max(_first_value(row, ("__match_datetime", "end_dt", "fi", "Hora"), default=None) for row in rows),
        venues=normalize_ids(_select_aligned_values(_first_value(subgroup, ("venues", "pistes"), default=[]), indexes)),
        venue_ids=normalize_ids(_select_aligned_values(_first_value(subgroup, ("venue_ids", "pista_ids"), default=[]), indexes)),
        cluster_ids=_select_aligned_values(_first_value(subgroup, ("cluster_ids", "clusters"), default=[]), indexes),
        cluster_statuses=normalize_ids(
            _select_aligned_values(_first_value(subgroup, ("cluster_statuses", "estats_cluster"), default=[]), indexes)
        ),
        level_demand=_fragment_level_demand(rows),
        max_level_span=_levels_span(rows),
        classification_pressure=float(_first_value(subgroup, ("classification_pressure", "pressio_classificacio"), default=0.0) or 0.0),
        classification_importance=classification_importance,
        weighted_coverage_value=weighted_value,
    )


def build_level_fragments(base_subgroups: Iterable[Any], config: Mapping[str, Any] | None = None) -> list[LevelFragment]:
    """Split base subgroups into coherent level fragments.

    The function is intentionally pure and accepts contract dataclasses,
    dictionaries, pandas Series, or compatible objects.
    """
    config = config or {}
    max_size = _as_int(config.get("level_fragment_max_size"), DEFAULT_MAX_SIZE)
    max_span = _as_int(config.get("level_fragment_max_span"), DEFAULT_MAX_SPAN)

    fragments: list[LevelFragment] = []
    for subgroup in base_subgroups or []:
        rows = sorted(list(_value_get(subgroup, "rows", default=[]) or []), key=_row_sort_key)
        if not rows:
            synthetic_rows = [
                {"match_id": match_id, "Categoria": _value_get(subgroup, "level_demand")}
                for match_id in normalize_ids(_value_get(subgroup, "match_ids", default=[]))
            ]
            rows = synthetic_rows
        for local_index, fragment_rows in enumerate(_split_rows_by_level(rows, max_size, max_span)):
            fragments.append(_build_fragment(subgroup, fragment_rows, local_index))
    return fragments


__all__ = ["LevelFragment", "build_level_fragments"]
