from __future__ import annotations

from dataclasses import dataclass, is_dataclass
from datetime import date, datetime, time
from typing import Any, Iterable, Mapping


UNCERTAIN_CLUSTER_STATUSES = {"outlier", "missing_geocode", "pending", "not_found", "missing", "unknown"}


@dataclass(frozen=True)
class AtomicRoutePoint:
    match_id: str
    start_dt: datetime | None
    end_dt: datetime | None
    venue: str
    venue_id: str | None = None
    cluster_id: str | None = None
    cluster_status: str | None = None
    source_segment_id: str | None = None
    source_is_aggregate: bool = False


def route_points_from_segments(segments: Iterable[Any]) -> list[AtomicRoutePoint]:
    """Expand route segments/fragments into ordered atomic match points."""
    points: list[AtomicRoutePoint] = []
    for segment_index, segment in enumerate(segments or []):
        if isinstance(segment, AtomicRoutePoint):
            points.append(segment)
            continue
        rows = _list_value(segment, "rows")
        if rows:
            points.extend(_points_from_rows(segment, rows, segment_index))
        else:
            points.append(_point_from_aggregate(segment, segment_index))
    return sorted(points, key=_point_sort_key)


def same_location(left: Any, right: Any) -> bool:
    left_point = _coerce_point(left)
    right_point = _coerce_point(right)
    left_venue_id = _normalize_text(left_point.venue_id)
    right_venue_id = _normalize_text(right_point.venue_id)
    if left_venue_id and right_venue_id:
        return left_venue_id == right_venue_id
    left_venue = _normalize_text(left_point.venue)
    right_venue = _normalize_text(right_point.venue)
    return bool(left_venue and right_venue and left_venue == right_venue)


def transition_requires_vehicle(left: Any, right: Any) -> bool:
    if same_location(left, right):
        return False
    left_point = _coerce_point(left)
    right_point = _coerce_point(right)
    if _reliable_same_cluster(left_point, right_point):
        return False
    return True


def required_gap(left: Any, right: Any, config: Mapping[str, Any] | None = None) -> int:
    config = config or {}
    if same_location(left, right):
        return _int_config(config, "gap_same_pitch_min", 90)
    if transition_requires_vehicle(left, right):
        return _int_config(config, "gap_diff_cluster_min", 150)
    return _int_config(config, "gap_diff_pitch_min", 120)


def validate_atomic_gaps(
    points_or_segments: Iterable[Any],
    config: Mapping[str, Any] | None = None,
) -> tuple[list[str], bool]:
    config = config or {}
    points = route_points_from_segments(points_or_segments)
    warnings: list[str] = []
    blocked = False
    has_vehicle = _config_has_vehicle(config)

    for left, right in zip(points, points[1:]):
        left_end = left.end_dt or left.start_dt
        right_start = right.start_dt
        warnings.extend(_transition_warnings(left, right))

        if transition_requires_vehicle(left, right) and has_vehicle is False:
            warnings.append("vehicle_required")
            blocked = True

        if left_end is None or right_start is None:
            continue
        minutes = (right_start - left_end).total_seconds() / 60.0
        if minutes < required_gap(left, right, config):
            warnings.append("gap_too_short")
            blocked = True

    return _dedupe(warnings), blocked


def _points_from_rows(segment: Any, rows: list[Any], segment_index: int) -> list[AtomicRoutePoint]:
    source_id = _source_segment_id(segment, segment_index)
    match_ids = _list_value(segment, "match_ids", "new_match_ids", "partit_ids")
    venues = _list_value(segment, "venues", "pistes")
    venue_ids = _list_value(segment, "venue_ids", "pista_ids")
    cluster_ids = _list_value(segment, "cluster_ids", "clusters")
    cluster_statuses = _list_value(segment, "cluster_statuses", "estats_cluster")
    segment_date = _first_value(segment, ("date", "data", "Data"))

    points: list[AtomicRoutePoint] = []
    for row_index, row in enumerate(rows):
        start_dt = _row_datetime(row, fallback_date=segment_date)
        end_dt = _datetime_value(_first_value(row, ("end_dt", "end_datetime", "end", "fi")))
        if end_dt is None:
            end_dt = start_dt
        points.append(
            AtomicRoutePoint(
                match_id=_row_match_id(row) or _at_index(match_ids, row_index) or f"{source_id}:match{row_index + 1}",
                start_dt=start_dt,
                end_dt=end_dt,
                venue=_clean_text(
                    _first_value(row, ("venue", "Pista joc", "pista", "venue_name"), default=_at_index(venues, row_index) or "")
                ),
                venue_id=_clean_optional(
                    _first_value(row, ("venue_id", "pista_id", "Pista ID"), default=_at_index(venue_ids, row_index))
                ),
                cluster_id=_clean_cluster(
                    _first_value(row, ("cluster_id", "cluster", "Cluster"), default=_at_index(cluster_ids, row_index))
                ),
                cluster_status=_normalize_optional(
                    _first_value(row, ("cluster_status", "estat_cluster"), default=_at_index(cluster_statuses, row_index))
                ),
                source_segment_id=source_id,
                source_is_aggregate=False,
            )
        )
    return points


def _point_from_aggregate(segment: Any, segment_index: int) -> AtomicRoutePoint:
    source_id = _source_segment_id(segment, segment_index)
    match_ids = _list_value(segment, "match_ids", "new_match_ids", "partit_ids")
    venues = _list_value(segment, "venues", "venue", "Pista joc")
    venue_ids = _list_value(segment, "venue_ids", "venue_id", "pista_id")
    cluster_ids = _list_value(segment, "cluster_ids", "clusters", "cluster_id", "cluster")
    cluster_statuses = _list_value(segment, "cluster_statuses", "cluster_status", "estats_cluster")
    return AtomicRoutePoint(
        match_id=_clean_text(match_ids[0]) if match_ids else _clean_text(_first_value(segment, ("match_id", "id"), default=source_id)),
        start_dt=_datetime_value(_first_value(segment, ("start_dt", "start_datetime", "start", "match_datetime", "__match_datetime"))),
        end_dt=_datetime_value(_first_value(segment, ("end_dt", "end_datetime", "end", "match_datetime", "__match_datetime")))
        or _datetime_value(_first_value(segment, ("start_dt", "start_datetime", "start", "match_datetime", "__match_datetime"))),
        venue=_clean_text(venues[0]) if venues else "",
        venue_id=_clean_optional(venue_ids[0]) if venue_ids else None,
        cluster_id=_clean_cluster(cluster_ids[0]) if cluster_ids else None,
        cluster_status=_normalize_optional(cluster_statuses[0]) if cluster_statuses else None,
        source_segment_id=source_id,
        source_is_aggregate=True,
    )


def _coerce_point(value: Any) -> AtomicRoutePoint:
    if isinstance(value, AtomicRoutePoint):
        return value
    points = route_points_from_segments([value])
    return points[0] if points else _point_from_aggregate({}, 0)


def _transition_warnings(left: AtomicRoutePoint, right: AtomicRoutePoint) -> list[str]:
    warnings: list[str] = []
    uncertain = _is_uncertain(left) or _is_uncertain(right)
    if same_location(left, right):
        if uncertain:
            warnings.extend(_uncertain_warnings(left, right))
        return warnings
    if transition_requires_vehicle(left, right):
        warnings.append("cross_cluster_with_vehicle_warning")
        warnings.extend(_uncertain_warnings(left, right))
    else:
        warnings.append("same_cluster_pitch_change_warning")
    return warnings


def _uncertain_warnings(left: AtomicRoutePoint, right: AtomicRoutePoint) -> list[str]:
    statuses = {_normalize_text(left.cluster_status), _normalize_text(right.cluster_status)}
    warnings: list[str] = []
    if "outlier" in statuses:
        warnings.append("outlier_mobility_warning")
    if _is_uncertain(left) or _is_uncertain(right):
        warnings.append("missing_cluster_mobility_warning")
    return warnings


def _reliable_same_cluster(left: AtomicRoutePoint, right: AtomicRoutePoint) -> bool:
    left_cluster = _normalize_text(left.cluster_id)
    right_cluster = _normalize_text(right.cluster_id)
    return bool(left_cluster and right_cluster and left_cluster == right_cluster and not _is_uncertain(left) and not _is_uncertain(right))


def _is_uncertain(point: AtomicRoutePoint) -> bool:
    status = _normalize_text(point.cluster_status)
    if status in UNCERTAIN_CLUSTER_STATUSES:
        return True
    return not bool(_normalize_text(point.cluster_id))


def _config_has_vehicle(config: Mapping[str, Any]) -> bool | None:
    explicit = _first_value(config, ("has_vehicle", "tutor_has_vehicle"), default=None)
    if explicit is not None:
        return bool(explicit)
    transport = _first_value(config, ("transport", "Mitja de Transport", "Mitja de transport"), default=None)
    if transport is None:
        return None
    try:
        from designacions.services.assignment_feasibility import has_vehicle

        return bool(has_vehicle(transport))
    except Exception:
        normalized = _normalize_text(transport)
        return any(token in normalized for token in ("cotxe", "coche", "car", "vehicle", "moto"))


def _point_sort_key(point: AtomicRoutePoint) -> tuple[int, Any, str]:
    if point.start_dt is None:
        return (1, datetime.max, point.match_id)
    return (0, point.start_dt, point.match_id)


def _value_get(source: Any, key: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, Mapping):
        value = source.get(key, default)
    elif is_dataclass(source) and not isinstance(source, type):
        value = getattr(source, key, default)
    else:
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


def _list_value(source: Any, *keys: str) -> list[Any]:
    for key in keys:
        value = _value_get(source, key, default=None)
        if _is_missing(value):
            continue
        if isinstance(value, str):
            return [value] if value else []
        try:
            return list(value)
        except TypeError:
            return [value]
    return []


def _at_index(values: list[Any], index: int) -> Any:
    if index < len(values):
        return values[index]
    return None


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


def _normalize_text(value: Any) -> str:
    return _clean_text(value).casefold()


def _clean_optional(value: Any) -> str | None:
    text = _clean_text(value)
    return text or None


def _normalize_optional(value: Any) -> str | None:
    text = _normalize_text(value)
    return text or None


def _clean_cluster(value: Any) -> str | None:
    text = _clean_text(value)
    if not text or text.casefold() in {"none", "nan", "nat", "-1"}:
        return None
    try:
        parsed = float(text.replace(",", "."))
    except ValueError:
        return text
    if parsed == -1:
        return None
    if parsed.is_integer():
        return str(int(parsed))
    return text


def _row_match_id(row: Any) -> str:
    return _clean_text(_first_value(row, ("match_id", "ID", "id", "Codi", "Codi Partit"), default=""))


def _source_segment_id(segment: Any, segment_index: int) -> str:
    return _clean_text(_first_value(segment, ("id", "segment_id", "fragment_id"), default=f"segment:{segment_index + 1}"))


def _row_datetime(row: Any, *, fallback_date: Any = None) -> datetime | None:
    value = _datetime_value(_first_value(row, ("__match_datetime", "match_datetime", "start_dt", "start_datetime", "inici")))
    if value is not None:
        return value
    parsed_date = _parse_date(_first_value(row, ("Data", "date", "data"), default=fallback_date))
    parsed_time = _parse_time(_first_value(row, ("Hora", "hora", "time"), default=None))
    if isinstance(parsed_date, date) and parsed_time is not None:
        return datetime.combine(parsed_date, parsed_time)
    return None


def _datetime_value(value: Any) -> datetime | None:
    if _is_missing(value):
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_pydatetime"):
        try:
            converted = value.to_pydatetime()
            return converted if isinstance(converted, datetime) else None
        except Exception:
            return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    return None


def _parse_date(value: Any) -> date | None:
    if _is_missing(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date") and not isinstance(value, str):
        try:
            parsed = value.date()
            return parsed if isinstance(parsed, date) else None
        except Exception:
            pass
    raw = _clean_text(value)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(value: Any) -> time | None:
    if _is_missing(value):
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


def _int_config(config: Mapping[str, Any], key: str, default: int) -> int:
    try:
        return int(config.get(key, default))
    except (TypeError, ValueError):
        return default


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        out.append(value)
        seen.add(value)
    return out


__all__ = [
    "AtomicRoutePoint",
    "required_gap",
    "route_points_from_segments",
    "same_location",
    "transition_requires_vehicle",
    "validate_atomic_gaps",
]
