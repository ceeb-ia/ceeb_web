from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_datetime


@dataclass(frozen=True)
class FeedCursor:
    dt: object | None
    after_id: str


def parse_feed_cursor(request, *, since_param: str = "since", after_param: str = "after_id") -> FeedCursor:
    since_raw = str(request.GET.get(since_param) or "").strip()
    dt = parse_datetime(since_raw) if since_raw else None
    if dt is not None and timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return FeedCursor(dt=dt, after_id=str(request.GET.get(after_param) or "").strip())


def apply_single_model_cursor(
    qs: QuerySet,
    cursor: FeedCursor,
    *,
    timestamp_field: str = "updated_at",
    id_field: str = "id",
) -> QuerySet:
    if cursor.dt is None:
        return qs

    filters = Q(**{f"{timestamp_field}__gt": cursor.dt})
    after_id = str(cursor.after_id or "").strip()
    if after_id:
        filters |= Q(**{timestamp_field: cursor.dt, f"{id_field}__gt": after_id})
    return qs.filter(filters)


def build_single_model_feed_meta(
    rows,
    *,
    limit: int,
    cursor: FeedCursor,
    timestamp_attr: str = "updated_at",
    id_attr: str = "id",
) -> dict:
    page = list(rows[:limit])
    if len(rows) > limit:
        has_more = True
    else:
        has_more = False

    if page:
        last_row = page[-1]
        next_dt = getattr(last_row, timestamp_attr, None)
        next_after_id = getattr(last_row, id_attr, "")
    else:
        next_dt = cursor.dt
        next_after_id = cursor.after_id

    return {
        "page": page,
        "has_more": has_more,
        "next_since": next_dt.isoformat() if next_dt else None,
        "next_after_id": str(next_after_id or ""),
    }
