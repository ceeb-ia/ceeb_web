from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from .team_scoring import build_team_subjects_for_comp_aparell, runtime_schema_for_comp_aparell


def build_team_subject_registry(competicio, comp_aparell) -> dict:
    subjects, issues = build_team_subjects_for_comp_aparell(competicio, comp_aparell)
    all_by_id: Dict[int, dict] = {}
    eligible_by_id: Dict[int, dict] = {}
    invalid_by_id: Dict[int, dict] = {}
    for raw_subject in subjects:
        subject = dict(raw_subject or {})
        subject_id = int(subject.get("subject_id") or 0)
        if subject_id <= 0:
            continue
        all_by_id[subject_id] = subject
        if int(comp_aparell.id) in (subject.get("allowed_app_ids") or []) and not subject.get("invalid_reasons"):
            eligible_by_id[subject_id] = subject
        if subject.get("invalid_reasons") or str(subject.get("series_state") or "") == "invalid":
            invalid_by_id[subject_id] = subject
    return {
        "subjects": list(all_by_id.values()),
        "issues": issues,
        "all_by_id": all_by_id,
        "eligible_by_id": eligible_by_id,
        "invalid_by_id": invalid_by_id,
    }


def filter_team_subject_ids_for_serie(subject_map: Dict[int, dict], raw_serie_id) -> List[int]:
    clean_map = {int(subject_id): dict(subject or {}) for subject_id, subject in (subject_map or {}).items()}
    if raw_serie_id in (None, ""):
        return list(clean_map.keys())
    try:
        clean_serie_id = int(raw_serie_id)
    except Exception:
        clean_serie_id = None
    if clean_serie_id:
        return [
            subject_id
            for subject_id, subject in clean_map.items()
            if int(subject.get("serie_id") or 0) == clean_serie_id
        ]
    return [
        subject_id
        for subject_id, subject in clean_map.items()
        if not subject.get("serie_id")
    ]


def max_team_member_count(subjects: Iterable[dict]) -> int:
    max_count = 0
    for subject in list(subjects or []):
        members = list(subject.get("members") or [])
        max_count = max(max_count, len(members))
    return max_count


def runtime_schema_for_team_subjects(schema: dict, comp_aparell, subjects: Iterable[dict]) -> dict:
    return runtime_schema_for_comp_aparell(
        schema or {},
        comp_aparell,
        member_count=max_team_member_count(subjects),
    )


def team_subject_meta(subject: Optional[dict]) -> dict:
    subject = dict(subject or {})
    return {
        "serie_id": subject.get("serie_id"),
        "serie_label": subject.get("serie_label"),
        "serie_order": subject.get("serie_order"),
        "series_state": subject.get("series_state"),
    }
