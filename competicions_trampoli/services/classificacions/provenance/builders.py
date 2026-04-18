from typing import Any, Iterable, Mapping

from .models import DerivedRow, RawRow, SelectionSnapshot


def clone_row(row: Mapping[str, Any] | None) -> dict[str, Any]:
    item = dict(row or {})
    item["by_camp"] = dict(item.get("by_camp") or {})
    source_rows = item.get("source_rows")
    if isinstance(source_rows, (list, tuple)):
        item["source_rows"] = [clone_row(source_row) for source_row in source_rows if isinstance(source_row, Mapping)]
    return item


def clone_rows(rows: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    return [clone_row(row) for row in (rows or []) if isinstance(row, Mapping)]


def row_identity(row: Mapping[str, Any] | None) -> str:
    item = row or {}
    explicit = str(item.get("row_id") or "").strip()
    if explicit:
        return explicit
    app_id = item.get("app_id") or 0
    exercici = item.get("exercici") or item.get("idx") or 0
    if item.get("inscripcio_id"):
        participant_kind = "inscripcio"
        participant_id = item.get("inscripcio_id")
    elif item.get("equip_id"):
        participant_kind = "equip"
        participant_id = item.get("equip_id")
    elif item.get("participant_id"):
        participant_kind = str(item.get("participant_kind") or "participant")
        participant_id = item.get("participant_id")
    else:
        participant_kind = "unknown"
        participant_id = 0
    return f"row:{participant_kind}:{participant_id}:{app_id}:{exercici}"


def with_source_rows(
    row: Mapping[str, Any] | None,
    source_rows: Iterable[Mapping[str, Any]] | None,
    *,
    row_id: str | None = None,
) -> dict[str, Any]:
    item = clone_row(row)
    item["row_id"] = str(row_id or row_identity(item))
    source_items = clone_rows(source_rows)
    item["source_rows"] = source_items
    item["source_row_ids"] = tuple(row_identity(source_item) for source_item in source_items)
    return item


def build_raw_row(
    row: Mapping[str, Any] | None,
    *,
    row_id: str | None = None,
    participant_kind: str = "participant",
    participant_id: int | None = None,
) -> RawRow:
    item = clone_row(row)
    resolved_participant_id = participant_id
    if resolved_participant_id is None:
        resolved_participant_id = item.get("inscripcio_id") or item.get("equip_id") or item.get("participant_id")
    return RawRow(
        row_id=str(row_id or row_identity(item)),
        app_id=_to_int_or_none(item.get("app_id")),
        exercici=_to_int_or_none(item.get("exercici") or item.get("idx")),
        participant_kind=str(participant_kind or item.get("participant_kind") or "participant"),
        participant_id=_to_int_or_none(resolved_participant_id),
        value=_to_float_or_none(item.get("value")),
        by_camp=dict(item.get("by_camp") or {}),
    )


def build_derived_row(
    row: Mapping[str, Any] | None,
    *,
    stage: str,
    source_rows: Iterable[Mapping[str, Any]] | None = None,
    row_id: str | None = None,
    participant_kind: str = "participant",
    participant_id: int | None = None,
) -> DerivedRow:
    item = clone_row(row)
    source_items = clone_rows(source_rows if source_rows is not None else item.get("source_rows"))
    resolved_participant_id = participant_id
    if resolved_participant_id is None:
        resolved_participant_id = item.get("inscripcio_id") or item.get("equip_id") or item.get("participant_id")
    return DerivedRow(
        row_id=str(row_id or row_identity(item)),
        stage=str(stage or "").strip().lower(),
        app_id=_to_int_or_none(item.get("app_id")),
        exercici=None,
        participant_kind=str(participant_kind or item.get("participant_kind") or "participant"),
        participant_id=_to_int_or_none(resolved_participant_id),
        value=_to_float_or_none(item.get("value")),
        by_camp=dict(item.get("by_camp") or {}),
        source_row_ids=tuple(row_identity(source_item) for source_item in source_items),
    )


def build_selection_snapshot(
    *,
    stage: str,
    app_id: int | None,
    subject_kind: str,
    subject_id: str | int,
    rows: Iterable[Mapping[str, Any]] | None,
    snapshot_id: str | None = None,
) -> SelectionSnapshot:
    resolved_subject_id = str(subject_id)
    selected_row_ids = tuple(row_identity(row) for row in (rows or []) if isinstance(row, Mapping))
    return SelectionSnapshot(
        snapshot_id=str(snapshot_id or f"snapshot:{stage}:{app_id or 0}:{subject_kind}:{resolved_subject_id}"),
        stage=str(stage or "").strip().lower(),
        app_id=_to_int_or_none(app_id),
        subject_kind=str(subject_kind or "").strip().lower(),
        subject_id=resolved_subject_id,
        selected_row_ids=selected_row_ids,
    )


def _to_int_or_none(value):
    try:
        return int(value)
    except Exception:
        return None


def _to_float_or_none(value):
    try:
        return float(value)
    except Exception:
        return None

