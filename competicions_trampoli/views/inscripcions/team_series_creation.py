__all__ = [
    "series_create_many",
    "series_creation_preview",
]


from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from ...models import Competicio
from ...services.inscripcions.history import (
    capture_inscripcions_history_snapshot,
    record_inscripcions_history_entry,
    with_inscripcions_history_payload,
)
from ...services.teams.series_creation_plans import (
    apply_series_creation_plan,
    build_series_creation_plan,
)
from ...services.teams.team_series import get_series_summary_payload
from .team_series import (
    _active_series_card_maps,
    _parse_payload,
    _preview_card_from_row,
    _preview_card_from_subjects,
    _resolve_team_comp_aparell,
    _visible_subject_maps,
)


def _selection_payload(plan):
    counts = dict(plan.get("counts") or {})
    effective = int(counts.get("effective") or 0)
    requested = int(counts.get("requested") or 0)
    return {
        "count": effective,
        "requested_count": requested,
        "valid_count": effective,
        "invalid_selection_count": int(counts.get("invalid_selection") or 0),
        "invalid_subject_count": int(counts.get("invalid_subjects") or 0),
        "assigned_count": sum(
            1 for _subject_id, serie_id in list(plan.get("source_assignments") or []) if int(serie_id or 0) > 0
        ),
        "unassigned_count": sum(
            1 for _subject_id, serie_id in list(plan.get("source_assignments") or []) if int(serie_id or 0) <= 0
        ),
        "label": f"{effective} unitat{'s' if effective != 1 else ''} valida{'s' if effective != 1 else ''}",
    }


def _blocked_reason_message(reason):
    if reason == "no_valid_selection":
        return "Selecciona almenys una unitat competitiva valida."
    if reason == "empty_plan":
        return "Aquesta configuracio no genera cap serie."
    return "No s'ha pogut construir el pla de series."


def _preview_payload(competicio, comp_aparell, plan):
    subjects, _subject_map = _visible_subject_maps(competicio, comp_aparell)
    _current_rows, current_row_map = _active_series_card_maps(competicio, comp_aparell, subjects)
    existing_series = [
        _preview_card_from_row(current_row_map[serie_id], status_note="Estat actual")
        for serie_id in list(plan.get("source_series_ids") or [])
        if serie_id in current_row_map
    ]
    planned_series = [
        _preview_card_from_subjects(
            label=row.get("label"),
            display_num=row.get("display_num"),
            subjects=row.get("subjects") or [],
            impact_kind="created",
            incoming_count=row.get("subjects_count"),
            will_create=True,
        )
        for row in list(plan.get("planned_series") or [])
    ]
    reason = str(plan.get("reason") or "")
    current_summary = get_series_summary_payload(competicio, comp_aparell, subjects)
    counts = dict(plan.get("counts") or {})
    series_count = int(counts.get("series") or 0)
    effective = int(counts.get("effective") or 0)
    message = (
        f"Crear {series_count} serie{'s' if series_count != 1 else ''} "
        f"amb {effective} unitat{'s' if effective != 1 else ''} competitiva{'s' if effective != 1 else ''}?"
    )
    blocked_reasons = [_blocked_reason_message(reason)] if reason else []
    return {
        **dict(plan or {}),
        "action": "create_many",
        "selection": _selection_payload(plan),
        "summary": {
            **current_summary,
            "affected_subjects_count": effective,
            "existing_series_total": len(existing_series),
            "planned_series_total": len(planned_series),
        },
        "existing_series": existing_series,
        "planned_series": planned_series,
        "message": message,
        "blocked": bool(reason),
        "blocked_reasons": blocked_reasons,
    }


def _build_plan_or_error(competicio, comp_aparell, payload):
    try:
        return build_series_creation_plan(competicio, comp_aparell, payload), None
    except ValueError as exc:
        return None, HttpResponseBadRequest(str(exc) or "strategy invalid")


@require_POST
@csrf_protect
def series_creation_preview(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    comp_aparell = _resolve_team_comp_aparell(competicio, payload)
    if comp_aparell is None:
        return HttpResponseBadRequest("comp_aparell_id invalid")
    plan, error = _build_plan_or_error(competicio, comp_aparell, payload)
    if error is not None:
        return error
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "preview": _preview_payload(competicio, comp_aparell, plan)},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def series_create_many(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    comp_aparell = _resolve_team_comp_aparell(competicio, payload)
    if comp_aparell is None:
        return HttpResponseBadRequest("comp_aparell_id invalid")
    expected_signature = str(payload.get("plan_signature") or "").strip()
    if not expected_signature:
        return HttpResponseBadRequest("preview required")
    plan, error = _build_plan_or_error(competicio, comp_aparell, payload)
    if error is not None:
        return error
    if not plan.get("can_run"):
        return HttpResponseBadRequest(str(plan.get("reason") or "preview stale"))
    if str(plan.get("plan_signature") or "") != expected_signature:
        return HttpResponseBadRequest("preview stale")

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    result = apply_series_creation_plan(competicio, comp_aparell, plan)
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="series_equip_create_many",
        action_label="Crear series d'equips",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "created": len(result.get("created_series_ids") or []),
                **result,
            },
            request,
            competicio.id,
        )
    )
