from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from ...models.competicio import InscripcioAparellExclusio
from ...models.judging import JudgeDeviceToken
from ...models.scoring import ScoreEntry, TeamScoreEntry
from ...services.shared.incremental_feeds import (
    apply_single_model_cursor,
    build_single_model_feed_meta,
    parse_feed_cursor,
)
from ...services.rotacions.rotacions_ordering import unique_ordered
from ...services.scoring.schema_resolution import resolve_scoring_schema_for_comp_aparell
from ...services.scoring.team_scoring import is_team_context_app, logical_team_inputs_to_runtime_inputs
from ...services.scoring.team_subject_contract import (
    build_team_subject_registry,
    filter_team_subject_ids_for_serie,
)
from ...services.scoring.update_payloads import build_score_update_payload
from ._shared import _clamp_exercici_for_aparell, _filter_inputs_for_allowed_codes
from .permissions import (
    _allowed_input_codes_from_permissions,
    _normalize_permissions,
    _resolve_permissions_for_subject,
)

JUDGE_UPDATES_LIMIT = 500


@require_http_methods(["GET"])
def judge_updates(request, token):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        return JsonResponse({"ok": False, "error": "Token invàlid o revocat"}, status=403)

    cursor = parse_feed_cursor(request)
    if cursor.dt is None:
        return JsonResponse(
            {
                "ok": True,
                "now": None,
                "updates": [],
                "next_since": None,
                "next_after_id": "",
                "has_more": False,
            }
        )

    competicio = tok.competicio
    comp_aparell = tok.comp_aparell
    raw_exercicis = request.GET.getlist("exercici")
    serie_id = request.GET.get("serie_id")
    if not raw_exercicis:
        single_exercici = request.GET.get("exercici") or request.GET.get("ex")
        raw_exercicis = [single_exercici] if single_exercici not in (None, "") else []
    if raw_exercicis:
        exercicis = unique_ordered(
            _clamp_exercici_for_aparell(comp_aparell, raw_exercici)
            for raw_exercici in raw_exercicis
        )
    else:
        exercicis = [_clamp_exercici_for_aparell(comp_aparell, request.GET.get("exercici") or request.GET.get("ex"))]
    permissions = _normalize_permissions(tok.permissions)
    _schema_obj, base_schema = resolve_scoring_schema_for_comp_aparell(comp_aparell)

    if is_team_context_app(comp_aparell):
        registry = build_team_subject_registry(competicio, comp_aparell)
        subject_map = registry["all_by_id"]
        allowed_team_ids = filter_team_subject_ids_for_serie(subject_map, serie_id)
        qs = (
            TeamScoreEntry.objects
            .filter(
                competicio=competicio,
                comp_aparell=comp_aparell,
                exercici__in=exercicis,
                team_subject_id__in=allowed_team_ids,
                fase__isnull=True,
            )
            .select_related("team_subject")
            .order_by("updated_at", "id")
        )
    else:
        excluded_ins_ids = (
            InscripcioAparellExclusio.objects
            .filter(comp_aparell=comp_aparell)
            .values_list("inscripcio_id", flat=True)
        )

        qs = (
            ScoreEntry.objects
            .filter(
                competicio=competicio,
                comp_aparell=comp_aparell,
                exercici__in=exercicis,
                fase__isnull=True,
            )
            .exclude(inscripcio_id__in=excluded_ins_ids)
            .order_by("updated_at", "id")
        )

    qs = apply_single_model_cursor(qs, cursor)
    updates = []
    rows = list(qs[: JUDGE_UPDATES_LIMIT + 1])
    for s in rows[:JUDGE_UPDATES_LIMIT]:
        subject_kind = "team_unit" if is_team_context_app(comp_aparell) else "inscripcio"
        subject_id = s.team_subject_id if subject_kind == "team_unit" else s.inscripcio_id
        if subject_kind == "team_unit":
            subject_meta = dict(subject_map.get(int(subject_id), {}))
            subject_meta["team_subject"] = getattr(s, "team_subject", None)
            resolved_permissions = _resolve_permissions_for_subject(permissions, comp_aparell, subject_meta)
            runtime_inputs = (
                logical_team_inputs_to_runtime_inputs(s.inputs, s.team_subject, base_schema)
                if isinstance(s.inputs, dict)
                else {}
            )
        else:
            subject_meta = {}
            resolved_permissions = _resolve_permissions_for_subject(permissions, comp_aparell, None)
            runtime_inputs = s.inputs if isinstance(s.inputs, dict) else {}
        allowed_input_codes = _allowed_input_codes_from_permissions(resolved_permissions)
        updates.append(
            build_score_update_payload(
                subject_kind=subject_kind,
                subject_id=subject_id,
                exercici=s.exercici,
                comp_aparell_id=s.comp_aparell_id,
                fase_id=s.fase_id,
                inputs=_filter_inputs_for_allowed_codes(runtime_inputs, allowed_input_codes),
                outputs=s.outputs or {},
                total=s.total,
                updated_at=s.updated_at,
                subject_meta=subject_meta if subject_kind == "team_unit" else None,
            )
        )

    feed_meta = build_single_model_feed_meta(rows, limit=JUDGE_UPDATES_LIMIT, cursor=cursor)
    return JsonResponse(
        {
            "ok": True,
            "now": feed_meta["next_since"],
            "updates": updates,
            "next_since": feed_meta["next_since"],
            "next_after_id": feed_meta["next_after_id"],
            "has_more": feed_meta["has_more"],
        }
    )

