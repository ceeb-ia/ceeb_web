from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from .contracts import normalize_id, normalize_ids
from .levels import is_high_match_level


DateLike = date | datetime | str | None


@dataclass
class TutorRouteState:
    tutor_id: str
    date: str
    assigned_match_ids: list[str] = field(default_factory=list)
    assigned_segments: list[Any] = field(default_factory=list)
    descriptors: list[Any] = field(default_factory=list)
    route_start_dt: DateLike = None
    route_end_dt: DateLike = None
    match_count: int = 0
    route_count: int = 0
    has_high_level_assignment: bool = False
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.tutor_id = normalize_id(self.tutor_id)
        self.date = normalize_date_key(self.date)
        self.assigned_match_ids = normalize_ids(self.assigned_match_ids)
        self.warnings = normalize_ids(self.warnings)
        if not self.match_count:
            self.match_count = len(self.assigned_match_ids)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DesignationState:
    assigned_match_ids: set[str] = field(default_factory=set)
    pending_match_ids: set[str] = field(default_factory=set)
    assignments_by_tutor_day: dict[tuple[str, str], TutorRouteState] = field(default_factory=dict)
    frozen_assignments: list[Any] = field(default_factory=list)
    stage_records: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.assigned_match_ids = set(normalize_ids(self.assigned_match_ids))
        self.pending_match_ids = set(normalize_ids(self.pending_match_ids))

    def to_dict(self) -> dict[str, Any]:
        return {
            "assigned_match_ids": sorted(self.assigned_match_ids),
            "pending_match_ids": sorted(self.pending_match_ids),
            "assignments_by_tutor_day": {
                f"{tutor_id}|{date_key}": route_state.to_dict()
                for (tutor_id, date_key), route_state in self.assignments_by_tutor_day.items()
            },
            "frozen_assignments": list(self.frozen_assignments),
            "stage_records": list(self.stage_records),
            "diagnostics": dict(self.diagnostics),
        }


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


def normalize_date_key(value: Any) -> str:
    if _is_missing(value):
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "date") and not isinstance(value, str):
        try:
            dated = value.date()
            if isinstance(dated, date):
                return dated.isoformat()
        except Exception:
            pass
    return str(value).strip()


def _route_key(tutor_id: Any, date_key: Any) -> tuple[str, str]:
    return (normalize_id(tutor_id), normalize_date_key(date_key))


def _segment_datetime(segment: Any, *keys: str) -> DateLike:
    return _first_value(segment, keys, default=None)


def _descriptor_level(descriptor: Any) -> Any:
    return _first_value(descriptor, ("level_demand", "Categoria", "categoria", "Nivell", "nivell", "level", "match_level"))


def _has_high_level(descriptors: Iterable[Any]) -> bool:
    return any(is_high_match_level(_descriptor_level(descriptor)) for descriptor in descriptors or [])


def _safe_min(values: Iterable[Any]) -> Any:
    values = [value for value in values if not _is_missing(value)]
    if not values:
        return None
    try:
        return min(values)
    except TypeError:
        return sorted(values, key=str)[0]


def _safe_max(values: Iterable[Any]) -> Any:
    values = [value for value in values if not _is_missing(value)]
    if not values:
        return None
    try:
        return max(values)
    except TypeError:
        return sorted(values, key=str)[-1]


def create_initial_state(match_ids: Iterable[Any] | None = None) -> DesignationState:
    pending = set(normalize_ids(match_ids))
    return DesignationState(assigned_match_ids=set(), pending_match_ids=pending)


def get_tutor_day_state(state: DesignationState, tutor_id: Any, date_key: Any) -> TutorRouteState | None:
    return state.assignments_by_tutor_day.get(_route_key(tutor_id, date_key))


def route_state_for(state: DesignationState, tutor_id: Any, date_key: Any) -> TutorRouteState:
    key = _route_key(tutor_id, date_key)
    route_state = state.assignments_by_tutor_day.get(key)
    if route_state is None:
        route_state = TutorRouteState(tutor_id=key[0], date=key[1])
        state.assignments_by_tutor_day[key] = route_state
    return route_state


def apply_route_assignment(
    state: DesignationState,
    tutor_id: Any,
    date_key: Any,
    match_ids: Iterable[Any],
    segment_rows: Iterable[Any] | None = None,
    descriptors: Iterable[Any] | None = None,
    stage: str | None = None,
    route_id: Any = None,
    candidate_id: Any = None,
    phase_name: Any = None,
    route_match_ids: Iterable[Any] | None = None,
    new_match_ids: Iterable[Any] | None = None,
    inserted_into_existing_route: bool | None = None,
    warning_codes: Iterable[Any] | None = None,
    selected_cost: Any = None,
    level_fit: Any = None,
    score_breakdown: Mapping[str, Any] | None = None,
    route_size: Any = None,
) -> DesignationState:
    route_state = route_state_for(state, tutor_id, date_key)
    normalized_match_ids = normalize_ids(match_ids)
    normalized_new_match_ids = normalize_ids(new_match_ids if new_match_ids is not None else normalized_match_ids)
    normalized_route_match_ids = normalize_ids(route_match_ids if route_match_ids is not None else normalized_new_match_ids)
    segment_rows = list(segment_rows or [])
    descriptors = list(descriptors or [])

    for match_id in normalized_match_ids:
        if match_id not in route_state.assigned_match_ids:
            route_state.assigned_match_ids.append(match_id)
        state.assigned_match_ids.add(match_id)
        state.pending_match_ids.discard(match_id)

    if segment_rows:
        route_state.assigned_segments.extend(segment_rows)
    if descriptors:
        route_state.descriptors.extend(descriptors)

    starts = [
        value
        for value in (
            *(_segment_datetime(segment, "start_dt", "inici", "__match_datetime") for segment in segment_rows),
            *(_segment_datetime(descriptor, "start_dt", "inici", "__match_datetime") for descriptor in descriptors),
        )
        if not _is_missing(value)
    ]
    ends = [
        value
        for value in (
            *(_segment_datetime(segment, "end_dt", "fi", "__match_datetime") for segment in segment_rows),
            *(_segment_datetime(descriptor, "end_dt", "fi", "__match_datetime") for descriptor in descriptors),
        )
        if not _is_missing(value)
    ]
    if starts:
        route_state.route_start_dt = _safe_min([route_state.route_start_dt, *starts])
    if ends:
        route_state.route_end_dt = _safe_max([route_state.route_end_dt, *ends])

    route_state.match_count = len(route_state.assigned_match_ids)
    route_state.route_count += 1
    route_state.has_high_level_assignment = route_state.has_high_level_assignment or _has_high_level(
        [*descriptors, *segment_rows]
    )

    state.stage_records.append(
        {
            "stage": stage or "",
            "route_id": "" if _is_missing(route_id) else str(route_id),
            "candidate_id": "" if _is_missing(candidate_id) else str(candidate_id),
            "phase_name": "" if _is_missing(phase_name) else str(phase_name),
            "route_match_ids": list(normalized_route_match_ids),
            "new_match_ids": list(normalized_new_match_ids),
            "inserted_into_existing_route": bool(inserted_into_existing_route)
            if inserted_into_existing_route is not None
            else False,
            "warning_codes": normalize_ids(warning_codes if warning_codes is not None else []),
            "selected_cost": selected_cost,
            "level_fit": level_fit,
            "score_breakdown": dict(score_breakdown or {}),
            "route_size": _normalize_route_size(route_size, normalized_route_match_ids),
            "tutor_id": route_state.tutor_id,
            "date": route_state.date,
            "match_ids": list(normalized_match_ids),
            "match_count": len(normalized_match_ids),
        }
    )
    return state


def _normalize_route_size(value: Any, route_match_ids: list[str]) -> int:
    if not _is_missing(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return len(route_match_ids)


__all__ = [
    "DesignationState",
    "TutorRouteState",
    "apply_route_assignment",
    "create_initial_state",
    "get_tutor_day_state",
    "normalize_date_key",
    "route_state_for",
]
