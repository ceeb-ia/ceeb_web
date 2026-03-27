import json

from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .models import Competicio
from .models_scoring import SerieEquip
from .models_trampoli import CompeticioAparell
from .services.team_scoring import build_team_subjects_for_comp_aparell, is_team_context_app
from .services.team_series import (
    assign_subjects_to_serie,
    default_subject_order,
    ensure_serie,
    get_programmed_series_ids,
    get_series_cards_payload,
    get_series_maps,
    get_series_summary_payload,
    normalize_subject_ids,
    reorder_serie_subjects,
    safe_deactivate_empty_serie,
    unassign_subjects_from_series,
)
from .views import (
    capture_inscripcions_history_snapshot,
    record_inscripcions_history_entry,
    with_inscripcions_history_payload,
)


def _parse_payload(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return {}


def _resolve_team_comp_aparell(competicio, payload):
    app_id = payload.get("comp_aparell_id")
    if not str(app_id).isdigit():
        return None
    comp_aparell = (
        CompeticioAparell.objects
        .filter(pk=int(app_id), competicio=competicio)
        .select_related("aparell")
        .first()
    )
    if comp_aparell is None or not is_team_context_app(comp_aparell):
        return None
    return comp_aparell


def _serialize_candidate(subject):
    return {
        "id": int(subject["subject_id"]),
        "subject_id": int(subject["subject_id"]),
        "subject_kind": "team_unit",
        "label": str(subject.get("name") or "").strip(),
        "context_name": str(subject.get("context_name") or "").strip(),
        "members_text": str(subject.get("members_text") or "").strip(),
        "meta": str(subject.get("meta") or "").strip(),
        "series_state": str(subject.get("series_state") or "unassigned"),
        "serie_id": int(subject.get("serie_id") or 0) or None,
        "serie_label": str(subject.get("serie_label") or "").strip(),
        "serie_order": int(subject.get("serie_order") or 0) or None,
        "invalid_reasons": list(subject.get("invalid_reasons") or []),
    }


def _subject_matches_filters(subject, filters):
    filters = filters if isinstance(filters, dict) else {}
    q = str(filters.get("q") or "").strip().lower()
    context_name = str(filters.get("context_name") or "").strip().lower()
    series_state = str(filters.get("series_state") or "all").strip().lower() or "all"
    serie_id = str(filters.get("serie_id") or "").strip()

    if q:
        hay = " ".join([
            str(subject.get("name") or ""),
            str(subject.get("context_name") or ""),
            str(subject.get("members_text") or ""),
            str(subject.get("meta") or ""),
        ]).lower()
        if q not in hay:
            return False
    if context_name and str(subject.get("context_name") or "").strip().lower() != context_name:
        return False
    if series_state == "assigned" and not subject.get("serie_id"):
        return False
    if series_state == "unassigned" and subject.get("serie_id"):
        return False
    if series_state == "invalid" and str(subject.get("series_state") or "") != "invalid":
        return False
    if serie_id and str(subject.get("serie_id") or "") != serie_id:
        return False
    return True


def _build_workspace_payload(competicio, comp_aparell, payload):
    page = max(1, int(payload.get("page") or 1))
    page_size = max(10, min(200, int(payload.get("page_size") or 40)))
    selected_ids = normalize_subject_ids(payload.get("selected_ids") or [])
    filters = payload.get("filters") or {}

    raw_subjects, issues = build_team_subjects_for_comp_aparell(competicio, comp_aparell)
    subjects = [
        dict(subject)
        for subject in raw_subjects
        if int(comp_aparell.id) in (subject.get("allowed_app_ids") or []) or subject.get("invalid_reasons")
    ]
    subjects.sort(key=default_subject_order)

    all_context_names = sorted({
        str(subject.get("context_name") or "").strip()
        for subject in subjects
        if str(subject.get("context_name") or "").strip()
    })
    filtered = [subject for subject in subjects if _subject_matches_filters(subject, filters)]
    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    page_rows = filtered[start:end]
    summary = get_series_summary_payload(competicio, comp_aparell, subjects)
    series_cards = get_series_cards_payload(competicio, comp_aparell, subjects, include_inactive=True)
    programmed_ids = set(int(x) for x in get_programmed_series_ids(competicio, comp_aparell))

    return {
        "summary": summary,
        "selected_ids": selected_ids,
        "filters": {
            "q": str(filters.get("q") or "").strip(),
            "context_name": str(filters.get("context_name") or "").strip(),
            "series_state": str(filters.get("series_state") or "all").strip().lower() or "all",
            "serie_id": str(filters.get("serie_id") or "").strip(),
        },
        "filter_options": {
            "context_names": all_context_names,
            "series": [
                {
                    "id": int(row["id"]),
                    "label": str(row["label"]),
                    "subjects_count": int(row["subjects_count"] or 0),
                }
                for row in series_cards
            ],
            "series_states": [
                {"id": "all", "label": "Totes"},
                {"id": "assigned", "label": "Amb serie"},
                {"id": "unassigned", "label": "Sense serie"},
                {"id": "invalid", "label": "Invalides"},
            ],
        },
        "paging": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": max(1, (total + page_size - 1) // page_size) if total else 1,
        },
        "candidates": {
            "items": [_serialize_candidate(subject) for subject in page_rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": end < total,
        },
        "series": series_cards,
        "issues": issues,
        "comp_aparell": {
            "id": int(comp_aparell.id),
            "nom": str(getattr(comp_aparell.aparell, "nom", "") or "").strip(),
            "codi": str(getattr(comp_aparell.aparell, "codi", "") or "").strip(),
        },
        "programmed_series_ids": sorted(programmed_ids),
    }


def _resolve_serie_or_400(competicio, comp_aparell, payload, *, include_inactive=True):
    serie_id = payload.get("serie_id") or payload.get("id")
    if not str(serie_id).isdigit():
        return None
    qs = SerieEquip.objects.filter(competicio=competicio, comp_aparell=comp_aparell, id=int(serie_id))
    if not include_inactive:
        qs = qs.filter(actiu=True)
    return qs.first()


@require_POST
@csrf_protect
def series_workspace(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    comp_aparell = _resolve_team_comp_aparell(competicio, payload)
    if comp_aparell is None:
        return HttpResponseBadRequest("comp_aparell_id invalid")

    workspace = _build_workspace_payload(competicio, comp_aparell, payload)
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "workspace": workspace, **workspace},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def series_detail(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    comp_aparell = _resolve_team_comp_aparell(competicio, payload)
    if comp_aparell is None:
        return HttpResponseBadRequest("comp_aparell_id invalid")
    serie = _resolve_serie_or_400(competicio, comp_aparell, payload, include_inactive=True)
    if serie is None:
        return HttpResponseBadRequest("serie invalid")

    subjects = {
        int(subject["subject_id"]): subject
        for subject in build_team_subjects_for_comp_aparell(competicio, comp_aparell)[0]
        if int(comp_aparell.id) in (subject.get("allowed_app_ids") or []) or subject.get("invalid_reasons")
    }
    detail = next(
        (row for row in get_series_cards_payload(competicio, comp_aparell, list(subjects.values()), include_inactive=True) if int(row["id"]) == int(serie.id)),
        None,
    )
    if detail is None:
        return HttpResponseBadRequest("serie invalid")

    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "serie": detail, "subjects": detail.get("subjects") or []},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def series_create(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    comp_aparell = _resolve_team_comp_aparell(competicio, payload)
    if comp_aparell is None:
        return HttpResponseBadRequest("comp_aparell_id invalid")

    selected_ids = normalize_subject_ids(payload.get("selected_ids") or [])
    name = str(payload.get("name") or "").strip()

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    serie = ensure_serie(competicio, comp_aparell, name=name)
    result = assign_subjects_to_serie(serie, selected_ids)
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="series_equip_create",
        action_label="Crear serie d'equips",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "serie_id": int(serie.id),
                "updated": len(result.get("updated_ids") or []),
                "skipped_ids": list(result.get("skipped_ids") or []),
            },
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def series_assign(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    comp_aparell = _resolve_team_comp_aparell(competicio, payload)
    if comp_aparell is None:
        return HttpResponseBadRequest("comp_aparell_id invalid")
    serie = _resolve_serie_or_400(competicio, comp_aparell, payload, include_inactive=True)
    if serie is None:
        return HttpResponseBadRequest("serie invalid")
    subject_ids = normalize_subject_ids(payload.get("selected_ids") or [])
    if not subject_ids:
        return HttpResponseBadRequest("No hi ha unitats competitives seleccionades")

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    result = assign_subjects_to_serie(serie, subject_ids)
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="series_equip_assign",
        action_label="Assignar unitats competitives a serie",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "serie_id": int(serie.id),
                "updated": len(result.get("updated_ids") or []),
                "skipped_ids": list(result.get("skipped_ids") or []),
            },
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def series_unassign(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    comp_aparell = _resolve_team_comp_aparell(competicio, payload)
    if comp_aparell is None:
        return HttpResponseBadRequest("comp_aparell_id invalid")
    subject_ids = normalize_subject_ids(payload.get("selected_ids") or [])
    if not subject_ids:
        return HttpResponseBadRequest("No hi ha unitats competitives seleccionades")

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    result = unassign_subjects_from_series(competicio, comp_aparell, subject_ids)
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="series_equip_unassign",
        action_label="Treure unitats competitives de la serie",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "updated": len(result.get("updated_ids") or [])},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def series_delete(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    comp_aparell = _resolve_team_comp_aparell(competicio, payload)
    if comp_aparell is None:
        return HttpResponseBadRequest("comp_aparell_id invalid")
    serie = _resolve_serie_or_400(competicio, comp_aparell, payload, include_inactive=True)
    if serie is None:
        return HttpResponseBadRequest("serie invalid")

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    ok, reason = safe_deactivate_empty_serie(serie)
    if not ok:
        if reason == "serie_not_empty":
            return HttpResponseBadRequest("serie not empty")
        return HttpResponseBadRequest("serie invalid")
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="series_equip_delete",
        action_label="Desactivar serie d'equips",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "deleted": True, "serie_id": int(serie.id)},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def series_rename(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    comp_aparell = _resolve_team_comp_aparell(competicio, payload)
    if comp_aparell is None:
        return HttpResponseBadRequest("comp_aparell_id invalid")
    serie = _resolve_serie_or_400(competicio, comp_aparell, payload, include_inactive=True)
    if serie is None:
        return HttpResponseBadRequest("serie invalid")

    name = str(payload.get("name") or "").strip()
    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    serie.nom = name
    serie.save(update_fields=["nom", "updated_at"])
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="series_equip_rename",
        action_label="Renombrar serie d'equips",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "serie_id": int(serie.id), "name": name},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def series_reorder(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    comp_aparell = _resolve_team_comp_aparell(competicio, payload)
    if comp_aparell is None:
        return HttpResponseBadRequest("comp_aparell_id invalid")
    serie = _resolve_serie_or_400(competicio, comp_aparell, payload, include_inactive=True)
    if serie is None:
        return HttpResponseBadRequest("serie invalid")
    subject_ids = normalize_subject_ids(payload.get("subject_ids") or [])
    if not subject_ids:
        return HttpResponseBadRequest("subject_ids invalid")

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    ordered_ids = reorder_serie_subjects(serie, subject_ids)
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="series_equip_reorder",
        action_label="Reordenar serie d'equips",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "serie_id": int(serie.id), "subject_ids": ordered_ids},
            request,
            competicio.id,
        )
    )
