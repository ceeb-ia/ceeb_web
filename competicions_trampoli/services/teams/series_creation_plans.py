from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
from typing import List, Sequence

from django.db import transaction

from ..shared.partition_plans import normalize_creation_strategy, sizes_for_strategy
from .team_series import (
    assign_subjects_to_serie,
    ensure_serie,
    next_serie_display_num,
    normalize_subject_ids,
    serie_label,
    summarize_subject_selection,
    workspace_subject_order,
)


SERIES_BUCKET_FIELDS = {"context", "group"}


def normalize_series_bucket_fields(values) -> List[str]:
    raw_values = values if isinstance(values, (list, tuple, set)) else []
    out = []
    for raw in raw_values:
        value = str(raw or "").strip().lower()
        if value == "competition_group":
            value = "group"
        if value in SERIES_BUCKET_FIELDS and value not in out:
            out.append(value)
    return out


def _subject_bucket_value(subject: dict, field: str):
    if field == "context":
        code = str(subject.get("context_code") or "").strip()
        label = str(subject.get("context_name") or code or "Sense context").strip()
        return code or "__NONE__", label
    if field == "group":
        value = int(subject.get("group") or 0)
        display = str(subject.get("group_display_num") or "").strip()
        label = f"Grup {display or value}" if value else "Sense grup"
        return str(value or "__NONE__"), label
    return "__NONE__", "Sense valor"


def _partition_subjects(subjects: Sequence[dict], fields: Sequence[str]):
    grouped = OrderedDict()
    for subject in list(subjects or []):
        values = [_subject_bucket_value(subject, field) for field in fields]
        key = json.dumps([value for value, _label in values], ensure_ascii=False)
        label = " | ".join(label for _value, label in values if label) or "Seleccio"
        grouped.setdefault(key, {"key": key, "label": label, "subjects": []})
        grouped[key]["subjects"].append(subject)
    return grouped


def _strategy_payload(payload):
    data = dict(payload or {})
    data["team_count"] = data.get("series_count")
    data["team_size"] = data.get("series_size")
    return data


def _plan_groups(subjects: Sequence[dict], payload) -> List[dict]:
    data = dict(payload or {})
    strategy = normalize_creation_strategy(data.get("strategy"), default="count")
    fields = normalize_series_bucket_fields(data.get("bucket_fields"))
    ordered_subjects = sorted(list(subjects or []), key=workspace_subject_order)
    if strategy == "per_bucket":
        if not fields:
            raise ValueError("bucket_fields invalid")
        return list(_partition_subjects(ordered_subjects, fields).values())

    sizes, _meta = sizes_for_strategy(
        len(ordered_subjects),
        strategy,
        _strategy_payload(data),
        fallback_mode=str(data.get("fallback_mode") or "strict"),
    )
    groups = []
    offset = 0
    for index, size in enumerate(sizes, start=1):
        rows = ordered_subjects[offset:offset + size]
        offset += size
        if rows:
            groups.append({"key": f"strategy:{strategy}:{index}", "label": "", "subjects": rows})
    return groups


def _series_names(groups: Sequence[dict], start_display_num: int, strategy: str) -> List[str]:
    names = []
    for index, group in enumerate(list(groups or [])):
        display_num = int(start_display_num) + index
        bucket_label = str(group.get("label") or "").strip()
        if strategy == "per_bucket" and bucket_label:
            names.append(bucket_label)
        else:
            names.append(f"Serie {display_num}")
    return names


def series_creation_plan_signature(plan: dict) -> str:
    payload = {
        "strategy": str(plan.get("strategy") or ""),
        "bucket_fields": list(plan.get("bucket_fields") or []),
        "requested_ids": [int(value) for value in list(plan.get("requested_ids") or [])],
        "effective_subject_ids": [int(value) for value in list(plan.get("effective_subject_ids") or [])],
        "invalid_selection_ids": [int(value) for value in list(plan.get("invalid_selection_ids") or [])],
        "invalid_subject_ids": [int(value) for value in list(plan.get("invalid_subject_ids") or [])],
        "source_assignments": [
            [int(subject_id), int(serie_id or 0)]
            for subject_id, serie_id in list(plan.get("source_assignments") or [])
        ],
        "planned_series": [
            {
                "display_num": int(row.get("display_num") or 0),
                "name": str(row.get("name") or ""),
                "subject_ids": [int(value) for value in list(row.get("subject_ids") or [])],
            }
            for row in list(plan.get("planned_series") or [])
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_series_creation_plan(competicio, comp_aparell, payload) -> dict:
    data = dict(payload or {})
    strategy = normalize_creation_strategy(data.get("strategy"), default="count")
    if strategy == "per_bucket" and str(data.get("strategy") or "").strip().lower() != "per_bucket":
        strategy = "count"
    bucket_fields = normalize_series_bucket_fields(data.get("bucket_fields"))
    summary = summarize_subject_selection(competicio, comp_aparell, data.get("selected_ids") or [])
    invalid_subject_ids = set(int(value) for value in list(summary.get("invalid_subject_ids") or []))
    effective_ids = [
        int(value)
        for value in list(summary.get("valid_ids") or [])
        if int(value) not in invalid_subject_ids
    ]
    subject_map = summary.get("subject_map") or {}
    effective_subjects = [dict(subject_map[value]) for value in effective_ids if value in subject_map]

    reason = ""
    groups = []
    if not effective_subjects:
        reason = "no_valid_selection"
    else:
        groups = _plan_groups(effective_subjects, {**data, "strategy": strategy})
        if not groups:
            reason = "empty_plan"

    start_display_num = next_serie_display_num(competicio, comp_aparell)
    names = _series_names(groups, start_display_num, strategy)
    planned_series = []
    for index, group in enumerate(groups):
        subject_ids = [int(subject["subject_id"]) for subject in list(group.get("subjects") or [])]
        planned_series.append(
            {
                "display_num": int(start_display_num + index),
                "name": names[index],
                "label": names[index],
                "subjects_count": len(subject_ids),
                "subject_ids": subject_ids,
                "subjects": [dict(subject) for subject in list(group.get("subjects") or [])],
                "bucket_key": str(group.get("key") or ""),
                "bucket_label": str(group.get("label") or ""),
                "will_create": True,
                "impact_kind": "created",
            }
        )

    source_assignments = [
        [int(subject_id), int(subject_map.get(subject_id, {}).get("serie_id") or 0)]
        for subject_id in effective_ids
    ]
    source_series_ids = sorted({serie_id for _subject_id, serie_id in source_assignments if serie_id})
    plan = {
        "strategy": strategy,
        "bucket_fields": bucket_fields,
        "can_run": not reason and bool(planned_series),
        "reason": reason,
        "requested_ids": list(summary.get("requested_ids") or []),
        "effective_subject_ids": effective_ids,
        "invalid_selection_ids": list(summary.get("invalid_ids") or []),
        "invalid_subject_ids": sorted(invalid_subject_ids),
        "source_assignments": source_assignments,
        "source_series_ids": source_series_ids,
        "planned_series": planned_series,
        "counts": {
            "requested": len(list(summary.get("requested_ids") or [])),
            "effective": len(effective_ids),
            "invalid_selection": len(list(summary.get("invalid_ids") or [])),
            "invalid_subjects": len(invalid_subject_ids),
            "series": len(planned_series),
        },
    }
    plan["plan_signature"] = series_creation_plan_signature(plan)
    return plan


@transaction.atomic
def apply_series_creation_plan(competicio, comp_aparell, plan: dict) -> dict:
    created_series = []
    updated_ids = []
    for row in list(plan.get("planned_series") or []):
        serie = ensure_serie(
            competicio,
            comp_aparell,
            display_num=int(row.get("display_num") or 0),
            name=str(row.get("name") or ""),
        )
        result = assign_subjects_to_serie(serie, row.get("subject_ids") or [])
        created_series.append(
            {
                "id": int(serie.id),
                "display_num": int(serie.display_num),
                "label": serie_label(serie),
            }
        )
        updated_ids.extend(int(value) for value in list(result.get("updated_ids") or []))
    return {
        "created_series": created_series,
        "created_series_ids": [int(row["id"]) for row in created_series],
        "updated_ids": normalize_subject_ids(updated_ids),
    }
