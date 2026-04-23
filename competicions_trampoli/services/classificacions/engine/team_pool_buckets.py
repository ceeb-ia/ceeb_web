from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from ..provenance.builders import clone_row
from ..provenance.queries import collect_contributor_rows
from .common import normalize_positive_int
from .score_values import _apply_simple_agg, _to_float
from .selection import _normalize_participants_cfg, _pick_exercicis_rows


TEAM_POOL_MODE_FLAT = "flat"
TEAM_POOL_MODE_PER_EXERCISE = "per_exercici"
ALLOWED_AGGREGATIONS = {"sum", "avg", "median", "max", "min"}
DEFAULT_BUCKET_PARTICIPANTS_CFG = {"mode": "tots"}
DEFAULT_BUCKET_AGGREGATION = "sum"


def _lookup_mapping_value(mapping, *keys):
    if not isinstance(mapping, Mapping):
        return None
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def _normalize_agg(raw_value, fallback=DEFAULT_BUCKET_AGGREGATION):
    agg = str(raw_value or fallback or DEFAULT_BUCKET_AGGREGATION).strip().lower()
    if agg not in ALLOWED_AGGREGATIONS:
        agg = str(fallback or DEFAULT_BUCKET_AGGREGATION).strip().lower()
    if agg not in ALLOWED_AGGREGATIONS:
        agg = DEFAULT_BUCKET_AGGREGATION
    return agg


def _normalize_bucket_row(row, *, fallback_app_id, fallback_equip_id):
    item = clone_row(row)
    app_id = normalize_positive_int(item.get("app_id")) or normalize_positive_int(fallback_app_id) or 0
    exercici = normalize_positive_int(item.get("exercici") or item.get("idx")) or 1
    equip_id = normalize_positive_int(item.get("equip_id")) or normalize_positive_int(fallback_equip_id)
    item["app_id"] = app_id
    item["app_order"] = normalize_positive_int(item.get("app_order")) or app_id
    item["exercici"] = exercici
    item["idx"] = exercici
    item["equip_id"] = equip_id
    item["value"] = _to_float(item.get("value"))
    item["by_camp"] = dict(item.get("by_camp") or {})
    return item


def _row_sort_key(row):
    item = row or {}
    return (
        normalize_positive_int(item.get("app_order")) or normalize_positive_int(item.get("app_id")) or 0,
        normalize_positive_int(item.get("app_id")) or 0,
        normalize_positive_int(item.get("exercici") or item.get("idx")) or 0,
        normalize_positive_int(item.get("inscripcio_id")) or 0,
        normalize_positive_int(item.get("equip_id")) or 0,
    )


def resolve_team_pool_mode_for_app(team_pool_mode_per_aparell, app_id: int):
    raw_mode = _lookup_mapping_value(team_pool_mode_per_aparell, str(app_id), app_id)
    mode = str(raw_mode or TEAM_POOL_MODE_FLAT).strip().lower()
    return TEAM_POOL_MODE_PER_EXERCISE if mode == TEAM_POOL_MODE_PER_EXERCISE else TEAM_POOL_MODE_FLAT


def resolve_team_pool_bucket_config_for_exercise(
    *,
    app_id: int,
    exercici: int,
    team_pool_participants_per_exercici_per_aparell: Mapping[Any, Any] | None = None,
    team_pool_agregacio_participants_per_exercici_per_aparell: Mapping[Any, Any] | None = None,
):
    participants_map = _lookup_mapping_value(
        team_pool_participants_per_exercici_per_aparell,
        str(app_id),
        app_id,
    )
    aggregation_map = _lookup_mapping_value(
        team_pool_agregacio_participants_per_exercici_per_aparell,
        str(app_id),
        app_id,
    )

    raw_participants_cfg = _lookup_mapping_value(participants_map, str(exercici), exercici)
    participants_cfg = _normalize_participants_cfg(raw_participants_cfg if isinstance(raw_participants_cfg, Mapping) else {})
    if not participants_cfg:
        participants_cfg = dict(DEFAULT_BUCKET_PARTICIPANTS_CFG)

    raw_aggregation = _lookup_mapping_value(aggregation_map, str(exercici), exercici)
    aggregation = _normalize_agg(raw_aggregation, DEFAULT_BUCKET_AGGREGATION)
    return participants_cfg, aggregation


def _pick_rows_for_bucket(rows, participants_cfg):
    indexed_rows = []
    for idx, row in enumerate(sorted(rows or [], key=_row_sort_key), start=1):
        item = clone_row(row)
        item["idx"] = idx
        indexed_rows.append(item)

    if not indexed_rows:
        return []

    return _pick_exercicis_rows(
        indexed_rows,
        participants_cfg.get("mode"),
        participants_cfg.get("n", 1),
        max_per_participant=1,
        participant_key="inscripcio_id",
    )


def _aggregate_bucket_rows(rows, *, app_id: int, equip_id: int | None, exercici: int, aggregation: str):
    picked_rows = [clone_row(row) for row in (rows or []) if isinstance(row, Mapping)]
    if not picked_rows:
        return None

    field_codes = []
    seen_codes = set()
    for row in picked_rows:
        for code in dict(row.get("by_camp") or {}).keys():
            code_str = str(code or "").strip()
            if not code_str or code_str in seen_codes:
                continue
            seen_codes.add(code_str)
            field_codes.append(code_str)

    by_camp = {}
    for code in field_codes:
        by_camp[code] = _apply_simple_agg(
            [_to_float(dict((row or {}).get("by_camp") or {}).get(code)) for row in picked_rows],
            aggregation,
        )

    first_row = picked_rows[0]
    bucket_row = clone_row(first_row)
    bucket_row["app_id"] = normalize_positive_int(first_row.get("app_id")) or normalize_positive_int(app_id) or 0
    bucket_row["app_order"] = (
        normalize_positive_int(first_row.get("app_order"))
        or normalize_positive_int(bucket_row.get("app_id"))
        or normalize_positive_int(app_id)
        or 0
    )
    bucket_row["equip_id"] = normalize_positive_int(first_row.get("equip_id")) or normalize_positive_int(equip_id)
    bucket_row["inscripcio_id"] = f"bucket:{bucket_row['app_id']}:{exercici}"
    bucket_row["idx"] = exercici
    bucket_row["exercici"] = exercici
    bucket_row["value"] = _apply_simple_agg([_to_float(row.get("value")) for row in picked_rows], aggregation)
    bucket_row["by_camp"] = by_camp
    bucket_row["source_rows"] = collect_contributor_rows(picked_rows)
    bucket_row["team_pool_bucket_mode"] = TEAM_POOL_MODE_PER_EXERCISE
    bucket_row["team_pool_bucket_member_count"] = len(picked_rows)
    bucket_row["team_pool_bucket_aggregation"] = aggregation
    return bucket_row


def build_team_pool_bucket_rows(
    *,
    app_id: int,
    equip_id: int | None = None,
    rows: Iterable[Mapping[str, Any]] | None = None,
    team_pool_participants_per_exercici_per_aparell: Mapping[Any, Any] | None = None,
    team_pool_agregacio_participants_per_exercici_per_aparell: Mapping[Any, Any] | None = None,
):
    grouped_rows = defaultdict(list)
    for raw_row in rows or []:
        if not isinstance(raw_row, Mapping):
            continue
        row = _normalize_bucket_row(
            raw_row,
            fallback_app_id=app_id,
            fallback_equip_id=equip_id,
        )
        grouped_rows[row["exercici"]].append(row)

    out = []
    for exercici in sorted(grouped_rows.keys()):
        participants_cfg, aggregation = resolve_team_pool_bucket_config_for_exercise(
            app_id=app_id,
            exercici=exercici,
            team_pool_participants_per_exercici_per_aparell=team_pool_participants_per_exercici_per_aparell,
            team_pool_agregacio_participants_per_exercici_per_aparell=team_pool_agregacio_participants_per_exercici_per_aparell,
        )
        picked_rows = _pick_rows_for_bucket(grouped_rows[exercici], participants_cfg)
        bucket_row = _aggregate_bucket_rows(
            picked_rows,
            app_id=app_id,
            equip_id=equip_id,
            exercici=exercici,
            aggregation=aggregation,
        )
        if bucket_row is not None:
            out.append(bucket_row)
    return out


__all__ = [
    "DEFAULT_BUCKET_AGGREGATION",
    "DEFAULT_BUCKET_PARTICIPANTS_CFG",
    "TEAM_POOL_MODE_FLAT",
    "TEAM_POOL_MODE_PER_EXERCISE",
    "build_team_pool_bucket_rows",
    "resolve_team_pool_bucket_config_for_exercise",
    "resolve_team_pool_mode_for_app",
]
