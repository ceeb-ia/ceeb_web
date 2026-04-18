from collections import defaultdict
from typing import Any, Iterable, Mapping

from .builders import clone_row, row_identity


def has_source_rows(row: Mapping[str, Any] | None) -> bool:
    source_rows = (row or {}).get("source_rows")
    return isinstance(source_rows, (list, tuple)) and any(isinstance(item, Mapping) for item in source_rows)


def iter_contributor_rows(row: Mapping[str, Any] | None):
    item = row or {}
    source_rows = item.get("source_rows")
    if isinstance(source_rows, (list, tuple)):
        yielded = False
        for source_row in source_rows:
            if not isinstance(source_row, Mapping):
                continue
            yielded = True
            yield from iter_contributor_rows(source_row)
        if yielded:
            return
    yield clone_row(item)


def collect_contributor_rows(rows: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    seen = set()
    contributors = []
    for row in (rows or []):
        if not isinstance(row, Mapping):
            continue
        for contributor in iter_contributor_rows(row):
            identity = row_identity(contributor)
            if identity in seen:
                continue
            seen.add(identity)
            contributors.append(contributor)
    return sorted(contributors, key=_row_sort_key)


def filter_rows_by_participant_ids(
    rows: Iterable[Mapping[str, Any]] | None,
    participant_ids: Iterable[int] | None,
    *,
    participant_key: str = "inscripcio_id",
) -> list[dict[str, Any]]:
    allowed_ids = {int(participant_id) for participant_id in (participant_ids or []) if _is_intish(participant_id)}
    if not allowed_ids:
        return [clone_row(row) for row in (rows or []) if isinstance(row, Mapping)]
    filtered = []
    for row in (rows or []):
        if not isinstance(row, Mapping):
            continue
        value = row.get(participant_key)
        if not _is_intish(value):
            continue
        if int(value) not in allowed_ids:
            continue
        filtered.append(clone_row(row))
    return filtered


def collect_contributor_rows_by_app(
    rows_by_app: Mapping[Any, Iterable[Mapping[str, Any]]] | None,
    *,
    participant_ids: Iterable[int] | None = None,
    participant_key: str = "inscripcio_id",
) -> dict[int, list[dict[str, Any]]]:
    grouped = defaultdict(list)
    for _selected_app_id, rows in (rows_by_app or {}).items():
        scoped_rows = filter_rows_by_participant_ids(rows, participant_ids, participant_key=participant_key)
        for contributor in collect_contributor_rows(scoped_rows):
            app_id = _to_int_or_none(contributor.get("app_id"))
            if app_id is None:
                continue
            grouped[app_id].append(contributor)
    return {app_id: _dedupe_and_sort(rows) for app_id, rows in grouped.items()}


def resolve_main_selected_contributors(
    selected_rows_by_app: Mapping[Any, Iterable[Mapping[str, Any]]] | None,
    *,
    selected_participant_ids: Iterable[int] | None = None,
    participant_key: str = "inscripcio_id",
) -> dict[int, list[dict[str, Any]]]:
    return collect_contributor_rows_by_app(
        selected_rows_by_app,
        participant_ids=selected_participant_ids,
        participant_key=participant_key,
    )


def collect_participant_ids(rows: Iterable[Mapping[str, Any]] | None, *, participant_key: str = "inscripcio_id") -> tuple[int, ...]:
    ids = []
    seen = set()
    for row in (rows or []):
        if not isinstance(row, Mapping):
            continue
        value = row.get(participant_key)
        if not _is_intish(value):
            continue
        participant_id = int(value)
        if participant_id in seen:
            continue
        seen.add(participant_id)
        ids.append(participant_id)
    return tuple(ids)


def _dedupe_and_sort(rows: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    seen = set()
    items = []
    for row in (rows or []):
        if not isinstance(row, Mapping):
            continue
        identity = row_identity(row)
        if identity in seen:
            continue
        seen.add(identity)
        items.append(clone_row(row))
    return sorted(items, key=_row_sort_key)


def _row_sort_key(row: Mapping[str, Any] | None):
    item = row or {}
    return (
        _to_int_or_none(item.get("app_order")) or 0,
        _to_int_or_none(item.get("app_id")) or 0,
        _to_int_or_none(item.get("exercici") or item.get("idx")) or 0,
        _to_int_or_none(item.get("inscripcio_id")) or 0,
        _to_int_or_none(item.get("equip_id")) or 0,
        row_identity(item),
    )


def _is_intish(value) -> bool:
    try:
        int(value)
        return True
    except Exception:
        return False


def _to_int_or_none(value):
    try:
        return int(value)
    except Exception:
        return None

