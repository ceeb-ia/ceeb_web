from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Sequence, Tuple

from django.apps import apps
from django.db import transaction
from django.db.models import Max

from ..models import Competicio, Inscripcio
from ..models_rotacions import RotacioAssignacioSerieEquip
from ..models_trampoli import CompeticioAparell

if TYPE_CHECKING:
    from ..models_scoring import SerieEquip, SerieEquipItem, TeamCompetitiveSubject


UNASSIGNED_SERIE_KEY = "series-unassigned"


def _serie_equip_model():
    return apps.get_model("competicions_trampoli", "SerieEquip")


def _serie_equip_item_model():
    return apps.get_model("competicions_trampoli", "SerieEquipItem")


def _team_subject_model():
    return apps.get_model("competicions_trampoli", "TeamCompetitiveSubject")


def normalize_subject_ids(values) -> List[int]:
    if values is None:
        return []
    raw_values = list(values) if isinstance(values, (list, tuple, set)) else [values]
    out: List[int] = []
    seen = set()
    for raw in raw_values:
        try:
            value = int(raw)
        except Exception:
            continue
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def serie_label(serie: Optional[SerieEquip]) -> str:
    if serie is None:
        return "Sense serie"
    name = str(getattr(serie, "nom", "") or "").strip()
    if name:
        return name
    display_num = int(getattr(serie, "display_num", 0) or 0)
    return f"Serie {display_num}" if display_num > 0 else "Sense serie"


def next_serie_display_num(competicio: Competicio, comp_aparell: CompeticioAparell) -> int:
    serie_model = _serie_equip_model()
    return (
        serie_model.objects
        .filter(competicio=competicio, comp_aparell=comp_aparell)
        .aggregate(Max("display_num"))["display_num__max"]
        or 0
    ) + 1


def get_series_queryset(competicio: Competicio, comp_aparell: CompeticioAparell, *, include_inactive=True):
    qs = _serie_equip_model().objects.filter(competicio=competicio, comp_aparell=comp_aparell)
    if not include_inactive:
        qs = qs.filter(actiu=True)
    return qs.order_by("display_num", "id")


def get_series_maps(
    competicio: Competicio,
    comp_aparell: CompeticioAparell,
    *,
    include_inactive=True,
) -> Dict[str, object]:
    series = list(get_series_queryset(competicio, comp_aparell, include_inactive=include_inactive))
    by_id = {int(serie.id): serie for serie in series}
    labels = {str(serie.id): serie_label(serie) for serie in series}
    return {
        "series": series,
        "by_id": by_id,
        "label_by_id": labels,
    }


def get_series_assignment_map(
    competicio: Competicio,
    comp_aparell: CompeticioAparell,
    *,
    include_inactive=True,
) -> Dict[int, Dict[str, object]]:
    serie_item_model = _serie_equip_item_model()
    qs = (
        serie_item_model.objects
        .filter(
            serie__competicio=competicio,
            serie__comp_aparell=comp_aparell,
        )
        .select_related("serie")
        .order_by("serie__display_num", "ordre", "id")
    )
    if not include_inactive:
        qs = qs.filter(serie__actiu=True)
    out: Dict[int, Dict[str, object]] = {}
    for row in qs:
        out[int(row.team_subject_id)] = {
            "serie_id": int(row.serie_id),
            "serie_order": int(row.ordre or 0),
            "serie_display_num": int(getattr(row.serie, "display_num", 0) or 0),
            "serie_label": serie_label(row.serie),
            "serie_active": bool(getattr(row.serie, "actiu", True)),
        }
    return out


def enrich_team_subjects_with_series(
    competicio: Competicio,
    comp_aparell: CompeticioAparell,
    subjects: Sequence[dict],
) -> List[dict]:
    assignment_map = get_series_assignment_map(competicio, comp_aparell, include_inactive=True)
    enriched = []
    for raw in list(subjects or []):
        subject = dict(raw or {})
        subject_id = int(subject.get("subject_id") or 0)
        meta = assignment_map.get(subject_id) or {}
        invalid = bool(subject.get("invalid_reasons"))
        assigned = bool(meta.get("serie_id"))
        state = "invalid" if invalid else ("assigned" if assigned else "unassigned")
        subject["serie_id"] = int(meta.get("serie_id") or 0) or None
        subject["serie_label"] = str(meta.get("serie_label") or "")
        subject["serie_order"] = int(meta.get("serie_order") or 0) or None
        subject["serie_display_num"] = int(meta.get("serie_display_num") or 0) or None
        subject["series_state"] = state
        enriched.append(subject)
    return enriched


def team_subject_bucket_key(subject: dict, app_id: Optional[int] = None) -> str:
    serie_id = int(subject.get("serie_id") or 0)
    if serie_id > 0:
        if app_id:
            return f"app-{int(app_id)}-serie-{serie_id}"
        return f"serie-{serie_id}"
    if app_id:
        return f"app-{int(app_id)}-{UNASSIGNED_SERIE_KEY}"
    return UNASSIGNED_SERIE_KEY


def team_subject_bucket_label(subject: dict, app_name: str = "") -> str:
    base = str(subject.get("serie_label") or "").strip() or "Sense serie"
    app_name = str(app_name or "").strip()
    return f"{app_name} · {base}" if app_name else base


def get_programmed_series_ids(competicio: Competicio, comp_aparell: Optional[CompeticioAparell] = None) -> List[int]:
    qs = RotacioAssignacioSerieEquip.objects.filter(assignacio__competicio=competicio)
    if comp_aparell is not None:
        qs = qs.filter(serie__comp_aparell=comp_aparell)
    return list(qs.values_list("serie_id", flat=True).distinct())


def get_series_summary_payload(competicio: Competicio, comp_aparell: CompeticioAparell, subjects: Sequence[dict]) -> dict:
    series = list(get_series_queryset(competicio, comp_aparell, include_inactive=False))
    assigned = 0
    invalid = 0
    for subject in list(subjects or []):
        if str(subject.get("series_state") or "") == "invalid":
            invalid += 1
        if subject.get("serie_id"):
            assigned += 1
    programmed_ids = set(int(x) for x in get_programmed_series_ids(competicio, comp_aparell))
    return {
        "series_total": len(series),
        "series_with_subjects": len({int(subject.get("serie_id") or 0) for subject in subjects if subject.get("serie_id")}),
        "empty_series": max(0, len(series) - len({int(subject.get("serie_id") or 0) for subject in subjects if subject.get("serie_id")})),
        "assigned_count": assigned,
        "unassigned_count": max(0, len(list(subjects or [])) - assigned),
        "invalid_count": invalid,
        "programmed_series": sum(1 for serie in series if int(serie.id) in programmed_ids),
        "out_of_program_series": sum(1 for serie in series if int(serie.id) not in programmed_ids),
    }


def default_subject_order(subject: dict) -> Tuple[int, str, int]:
    return (
        int(subject.get("order") or 10**9),
        str(subject.get("context_name") or "").lower(),
        int(subject.get("subject_id") or 0),
    )


def workspace_subject_order(subject: dict) -> Tuple[int, int, int, str, int]:
    serie_id = int(subject.get("serie_id") or 0)
    if serie_id > 0:
        return (
            1,
            int(subject.get("serie_display_num") or 10**9),
            int(subject.get("serie_order") or 10**9),
            str(subject.get("context_name") or "").lower(),
            int(subject.get("subject_id") or 0),
        )
    order, context_name, subject_id = default_subject_order(subject)
    return (0, order, 0, context_name, subject_id)


def assigned_subject_order(subject: dict) -> Tuple[int, int]:
    return (
        int(subject.get("serie_order") or 10**9),
        int(subject.get("subject_id") or 0),
    )


def _subject_initial_order_map(subject_ids: Iterable[int]) -> Dict[int, Tuple[int, str, int]]:
    clean_ids = normalize_subject_ids(subject_ids)
    if not clean_ids:
        return {}
    subjects = list(
        _team_subject_model().objects
        .filter(id__in=clean_ids)
        .select_related("context")
        .only("id", "member_ids", "context__nom")
    )
    member_ids = sorted({
        int(member_id)
        for subject in subjects
        for member_id in list(getattr(subject, "member_ids", []) or [])
        if str(member_id).isdigit() and int(member_id) > 0
    })
    order_by_member_id = {
        int(row["id"]): int(row["ordre_competicio"] or 10**9)
        for row in (
            Inscripcio.objects
            .filter(id__in=member_ids)
            .values("id", "ordre_competicio")
        )
    }
    out: Dict[int, Tuple[int, str, int]] = {}
    for subject in subjects:
        member_orders = [
            int(order_by_member_id.get(int(member_id), 10**9))
            for member_id in list(getattr(subject, "member_ids", []) or [])
            if str(member_id).isdigit() and int(member_id) > 0
        ]
        out[int(subject.id)] = (
            min(member_orders or [10**9]),
            str(getattr(getattr(subject, "context", None), "nom", "") or "").lower(),
            int(subject.id),
        )
    return out


def subject_ids_for_serie_filter(subject_map: Dict[int, dict], raw_serie_id) -> List[int]:
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


def get_series_cards_payload(
    competicio: Competicio,
    comp_aparell: CompeticioAparell,
    subjects: Sequence[dict],
    *,
    include_inactive=True,
) -> List[dict]:
    series = list(get_series_queryset(competicio, comp_aparell, include_inactive=include_inactive))
    series_by_id = {int(serie.id): serie for serie in series}
    members = defaultdict(list)
    for subject in list(subjects or []):
        serie_id = int(subject.get("serie_id") or 0)
        if serie_id > 0:
            members[serie_id].append(subject)
    programmed_ids = set(int(x) for x in get_programmed_series_ids(competicio, comp_aparell))
    rows = []
    for serie in series:
        items = sorted(members.get(int(serie.id), []), key=assigned_subject_order)
        rows.append({
            "id": int(serie.id),
            "display_num": int(serie.display_num),
            "label": serie_label(serie),
            "name": str(serie.nom or "").strip(),
            "actiu": bool(serie.actiu),
            "subjects_count": len(items),
            "subjects": items,
            "is_empty": not items,
            "is_programmed": int(serie.id) in programmed_ids,
            "is_out_of_program": int(serie.id) not in programmed_ids,
        })
    return rows


def ensure_serie(
    competicio: Competicio,
    comp_aparell: CompeticioAparell,
    *,
    display_num: Optional[int] = None,
    name: str = "",
) -> SerieEquip:
    serie_model = _serie_equip_model()
    clean_name = str(name or "").strip()
    display_num = int(display_num or next_serie_display_num(competicio, comp_aparell))
    serie, _created = serie_model.objects.get_or_create(
        competicio=competicio,
        comp_aparell=comp_aparell,
        display_num=display_num,
        defaults={"nom": clean_name, "actiu": True},
    )
    updates = []
    if not serie.actiu:
        serie.actiu = True
        updates.append("actiu")
    if clean_name and serie.nom != clean_name:
        serie.nom = clean_name
        updates.append("nom")
    if updates:
        updates.append("updated_at")
        serie.save(update_fields=updates)
    return serie


def _bulk_resequence_items(items: Sequence[SerieEquipItem]):
    updates = []
    for idx, row in enumerate(list(items or []), start=1):
        if int(row.ordre or 0) != idx:
            row.ordre = idx
            updates.append(row)
    if updates:
        _serie_equip_item_model().objects.bulk_update(updates, ["ordre"], batch_size=200)


def _validate_item_or_raise(row: SerieEquipItem):
    row.full_clean()


@transaction.atomic
def assign_subjects_to_serie(
    serie: SerieEquip,
    subject_ids: Iterable[int],
) -> Dict[str, List[int]]:
    team_subject_model = _team_subject_model()
    serie_item_model = _serie_equip_item_model()
    clean_ids = normalize_subject_ids(subject_ids)
    if not clean_ids:
        return {"updated_ids": [], "skipped_ids": []}

    valid_subject_ids = set(
        team_subject_model.objects
        .select_for_update()
        .filter(
            competicio=serie.competicio,
            comp_aparell=serie.comp_aparell,
            id__in=clean_ids,
        )
        .values_list("id", flat=True)
    )
    target_ids = [subject_id for subject_id in clean_ids if subject_id in valid_subject_ids]
    skipped_ids = [subject_id for subject_id in clean_ids if subject_id not in valid_subject_ids]
    if not target_ids:
        return {"updated_ids": [], "skipped_ids": skipped_ids}

    existing_rows = list(
        serie_item_model.objects
        .select_for_update()
        .select_related("serie")
        .filter(team_subject_id__in=target_ids, serie__comp_aparell=serie.comp_aparell)
        .order_by("serie_id", "ordre", "id")
    )
    stale_ids = [row.id for row in existing_rows if int(row.serie_id) != int(serie.id)]
    if stale_ids:
        serie_item_model.objects.filter(id__in=stale_ids).delete()

    already_in_target = {
        int(row.team_subject_id)
        for row in existing_rows
        if int(row.serie_id) == int(serie.id)
    }
    next_order = (
        serie_item_model.objects
        .filter(serie=serie)
        .aggregate(Max("ordre"))["ordre__max"]
        or 0
    )
    subject_order_map = _subject_initial_order_map(target_ids)
    creates = []
    updated_ids = []
    ordered_target_ids = sorted(
        target_ids,
        key=lambda subject_id: subject_order_map.get(
            int(subject_id),
            (10**9, "", int(subject_id)),
        ),
    )
    for subject_id in ordered_target_ids:
        if subject_id in already_in_target:
            continue
        next_order += 1
        row = serie_item_model(serie=serie, team_subject_id=subject_id, ordre=next_order)
        _validate_item_or_raise(row)
        creates.append(row)
        updated_ids.append(subject_id)
    if creates:
        serie_item_model.objects.bulk_create(creates, batch_size=200)

    touched_series_ids = {int(serie.id)} | {
        int(getattr(row, "serie_id", 0) or 0)
        for row in existing_rows
        if getattr(row, "serie_id", None)
    }
    for serie_id in touched_series_ids:
        rows = list(serie_item_model.objects.filter(serie_id=serie_id).order_by("ordre", "id"))
        _bulk_resequence_items(rows)

    return {"updated_ids": updated_ids, "skipped_ids": skipped_ids}


@transaction.atomic
def unassign_subjects_from_series(competicio: Competicio, comp_aparell: CompeticioAparell, subject_ids: Iterable[int]) -> Dict[str, List[int]]:
    serie_item_model = _serie_equip_item_model()
    clean_ids = normalize_subject_ids(subject_ids)
    if not clean_ids:
        return {"updated_ids": []}
    existing = list(
        serie_item_model.objects
        .filter(team_subject_id__in=clean_ids, serie__competicio=competicio, serie__comp_aparell=comp_aparell)
        .order_by("serie_id", "ordre", "id")
    )
    if not existing:
        return {"updated_ids": []}
    serie_ids = {int(row.serie_id) for row in existing}
    updated_ids = [int(row.team_subject_id) for row in existing]
    serie_item_model.objects.filter(id__in=[row.id for row in existing]).delete()
    for serie_id in serie_ids:
        rows = list(serie_item_model.objects.filter(serie_id=serie_id).order_by("ordre", "id"))
        _bulk_resequence_items(rows)
    return {"updated_ids": updated_ids}


@transaction.atomic
def reorder_serie_subjects(serie: SerieEquip, subject_ids: Iterable[int]) -> List[int]:
    clean_ids = normalize_subject_ids(subject_ids)
    rows = list(_serie_equip_item_model().objects.filter(serie=serie).order_by("ordre", "id"))
    by_subject_id = {int(row.team_subject_id): row for row in rows}
    desired = [subject_id for subject_id in clean_ids if subject_id in by_subject_id]
    desired.extend([int(row.team_subject_id) for row in rows if int(row.team_subject_id) not in desired])
    ordered_rows = [by_subject_id[subject_id] for subject_id in desired]
    _bulk_resequence_items(ordered_rows)
    return desired


@transaction.atomic
def safe_deactivate_empty_serie(serie: SerieEquip) -> Tuple[bool, str]:
    serie_model = _serie_equip_model()
    locked = (
        serie_model.objects
        .select_for_update()
        .filter(pk=getattr(serie, "pk", None))
        .first()
    )
    if locked is None:
        return False, "serie_invalid"
    has_items = _serie_equip_item_model().objects.select_for_update().filter(serie=locked).exists()
    if has_items:
        return False, "serie_not_empty"
    is_programmed = RotacioAssignacioSerieEquip.objects.select_for_update().filter(serie=locked).exists()
    if is_programmed:
        return False, "serie_programmed"
    if not locked.actiu:
        return True, "already_inactive"
    locked.actiu = False
    locked.save(update_fields=["actiu", "updated_at"])
    return True, "deactivated"


def series_plan_signature(preview: dict) -> str:
    payload = {
        "action": str(preview.get("action") or ""),
        "serie_id": int(preview.get("serie_id") or 0),
        "serie_label": str(preview.get("serie_label") or ""),
        "can_run": bool(preview.get("can_run")),
        "reason": str(preview.get("reason") or ""),
        "counts": dict(preview.get("counts") or {}),
        "requested_ids": [int(x) for x in list(preview.get("requested_ids") or [])],
        "effective_subject_ids": [int(x) for x in list(preview.get("effective_subject_ids") or [])],
        "invalid_selection_ids": [int(x) for x in list(preview.get("invalid_selection_ids") or [])],
        "invalid_subject_ids": [int(x) for x in list(preview.get("invalid_subject_ids") or [])],
        "source_series_ids": [int(x) for x in list(preview.get("source_series_ids") or [])],
        "touched_series_ids": [int(x) for x in list(preview.get("touched_series_ids") or [])],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def summarize_subject_selection(
    competicio: Competicio,
    comp_aparell: CompeticioAparell,
    subject_ids: Iterable[int],
) -> Dict[str, object]:
    from .team_scoring import build_team_subjects_for_comp_aparell

    team_subject_model = _team_subject_model()
    clean_ids = normalize_subject_ids(subject_ids)
    if not clean_ids:
        return {
            "requested_ids": [],
            "valid_ids": [],
            "invalid_ids": [],
            "assigned_ids": [],
            "unassigned_ids": [],
            "invalid_subject_ids": [],
        }

    valid_subject_ids = set(
        team_subject_model.objects
        .filter(
            competicio=competicio,
            comp_aparell=comp_aparell,
            id__in=clean_ids,
        )
        .values_list("id", flat=True)
    )
    subjects, _issues = build_team_subjects_for_comp_aparell(competicio, comp_aparell)
    subject_map = {
        int(subject["subject_id"]): dict(subject)
        for subject in subjects
        if int(subject["subject_id"]) in valid_subject_ids
    }
    valid_ids = [subject_id for subject_id in clean_ids if subject_id in valid_subject_ids]
    invalid_ids = [subject_id for subject_id in clean_ids if subject_id not in valid_subject_ids]
    assigned_ids = [subject_id for subject_id in valid_ids if subject_map.get(subject_id, {}).get("serie_id")]
    unassigned_ids = [subject_id for subject_id in valid_ids if not subject_map.get(subject_id, {}).get("serie_id")]
    invalid_subject_ids = [
        subject_id
        for subject_id in valid_ids
        if str(subject_map.get(subject_id, {}).get("series_state") or "") == "invalid"
    ]
    return {
        "requested_ids": clean_ids,
        "valid_ids": valid_ids,
        "invalid_ids": invalid_ids,
        "assigned_ids": assigned_ids,
        "unassigned_ids": unassigned_ids,
        "invalid_subject_ids": invalid_subject_ids,
        "subject_map": subject_map,
    }
