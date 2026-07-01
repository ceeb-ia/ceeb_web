import json

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from ...models.judging import JudgeDeviceToken
from ...scoring_engine import ScoringError
from ...services.judging.submissions import persist_subject_score_patch
from ...services.judging.supervision import (
    PendingSubmissionSpec,
    approve_pending_submissions_for_published_fields,
    create_or_update_pending_submission,
    field_requires_supervision,
    token_is_supervisor_for_field,
)
from ...services.scoring.schema_resolution import resolve_scoring_schema_for_comp_aparell
from ...services.scoring.scoring_subjects import (
    resolve_scoring_subject,
    serialize_subject_payload,
    subject_entry_model,
)
from ...services.scoring.team_scoring import (
    build_team_subjects_for_comp_aparell,
    is_team_context_app,
    logical_team_inputs_to_runtime_inputs,
    runtime_schema_for_comp_aparell,
)
from ._assignment_scope import (
    assignment_id_from_request,
    clamp_exercici_for_scope,
    ensure_subject_allowed_for_assignment,
    ensure_subject_scoreable_for_scope,
    resolve_assignment_scope_for_request,
)
from ._shared import _filter_inputs_for_allowed_codes
from .permissions import (
    _allowed_input_codes_from_permissions,
    _normalize_permissions,
    _resolve_permissions_for_subject,
    _sanitize_patch_by_permissions,
)


def _patch_base_code(code: str) -> str:
    code = str(code or "")
    return code[len("__crash__"):] if code.startswith("__crash__") else code


def _group_patch_by_field(patch: dict) -> dict:
    grouped = {}
    for code, value in (patch or {}).items():
        grouped.setdefault(_patch_base_code(code), {})[code] = value
    return grouped


def _permission_meta_for_runtime_code(permissions: list, runtime_code: str) -> dict:
    runtime_code = str(runtime_code or "").strip()
    for perm in permissions or []:
        candidate = str(perm.get("runtime_field_code") or perm.get("field_code") or "").strip()
        if candidate == runtime_code:
            return {
                "field_code": str(perm.get("field_code") or runtime_code),
                "runtime_field_code": runtime_code,
                "judge_index": int(perm.get("judge_index") or 1),
                "item_start": int(perm.get("item_start") or 1),
                "item_count": perm.get("item_count"),
            }
    return {
        "field_code": runtime_code,
        "runtime_field_code": runtime_code,
        "judge_index": 1,
        "item_start": 1,
        "item_count": None,
    }


def _existing_entry_for_subject(competicio, comp_aparell, exercici, subject, phase):
    model = subject_entry_model(comp_aparell)
    filters = {
        "competicio": competicio,
        "comp_aparell": comp_aparell,
        "exercici": exercici,
        "fase": phase,
    }
    if str(subject.get("subject_kind")) == "team_unit":
        filters["team_subject"] = subject["team_subject"]
    else:
        filters["inscripcio"] = subject["inscripcio"]
    return model.objects.filter(**filters).first()


@require_POST
@transaction.atomic
def judge_save_partial(request, token):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        return JsonResponse({"ok": False, "error": "Token invalid o revocat"}, status=403)

    tok.touch()

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON invalid"}, status=400)

    scope, scope_error = resolve_assignment_scope_for_request(tok, assignment_id_from_request(request, payload))
    if scope_error is not None:
        return scope_error

    subject_payload = {
        "subject_kind": payload.get("subject_kind"),
        "subject_id": payload.get("subject_id"),
        "inscripcio_id": payload.get("inscripcio_id"),
    }
    exercici_raw = payload.get("exercici")
    inputs_patch = payload.get("inputs_patch", {})
    competicio = scope.competicio
    comp_aparell = scope.comp_aparell
    exercici = clamp_exercici_for_scope(scope, exercici_raw)

    if not subject_payload.get("subject_id") and not subject_payload.get("inscripcio_id"):
        return JsonResponse({"ok": False, "error": "Falta subject_id/inscripcio_id"}, status=400)
    if not isinstance(inputs_patch, dict):
        return JsonResponse({"ok": False, "error": "inputs_patch ha de ser objecte JSON"}, status=400)

    permissions = _normalize_permissions(scope.permissions)

    team_ids = None
    if is_team_context_app(comp_aparell):
        team_ids = [
            int(item["subject_id"])
            for item in build_team_subjects_for_comp_aparell(competicio, comp_aparell)[0]
            if int(comp_aparell.id) in (item.get("allowed_app_ids") or [])
        ]
    subject, error_response = resolve_scoring_subject(
        competicio,
        comp_aparell,
        subject_payload,
        eligible_team_ids=team_ids,
    )
    if error_response is not None:
        return error_response
    scope_subject_error = ensure_subject_scoreable_for_scope(scope, subject)
    if scope_subject_error is not None:
        return scope_subject_error
    assignment_subject_error = ensure_subject_allowed_for_assignment(scope, subject)
    if assignment_subject_error is not None:
        return assignment_subject_error

    _schema_obj, base_schema = resolve_scoring_schema_for_comp_aparell(comp_aparell)
    team_subject = subject.get("team_subject") if str(subject.get("subject_kind")) == "team_unit" else None
    team_member_count = len(getattr(team_subject, "member_ids", []) or []) if team_subject is not None else 0
    resolved_permissions = _resolve_permissions_for_subject(permissions, comp_aparell, subject)
    allowed_codes = {str(p.get("runtime_field_code") or p.get("field_code") or "") for p in resolved_permissions}
    allowed_codes.discard("")
    allowed_input_codes = _allowed_input_codes_from_permissions(resolved_permissions)
    allowed_patch_codes = set(allowed_codes)
    allowed_patch_codes.update({f"__crash__{code}" for code in allowed_codes})
    patch_codes = set(inputs_patch.keys())
    if not patch_codes.issubset(allowed_patch_codes):
        return JsonResponse({"ok": False, "error": "Intentes editar un camp no autoritzat per aquest QR"}, status=403)
    schema = runtime_schema_for_comp_aparell(base_schema, comp_aparell, member_count=team_member_count)

    sanitized = _sanitize_patch_by_permissions(schema, resolved_permissions, inputs_patch)
    sanitized_by_field = _group_patch_by_field(sanitized)
    raw_by_field = _group_patch_by_field(inputs_patch)
    immediate_patch = {}
    pending_submissions = []
    supervisor_published_codes = []

    for runtime_code, field_patch in sanitized_by_field.items():
        requires_supervision = field_requires_supervision(
            competicio=competicio,
            comp_aparell=comp_aparell,
            phase=scope.phase,
            runtime_field_code=runtime_code,
        )
        is_supervisor = token_is_supervisor_for_field(
            token=tok,
            assignment=scope.assignment,
            comp_aparell=comp_aparell,
            runtime_field_code=runtime_code,
        )
        if requires_supervision and not is_supervisor:
            meta = _permission_meta_for_runtime_code(resolved_permissions, runtime_code)
            submission = create_or_update_pending_submission(
                scope=scope,
                token=tok,
                subject=subject,
                spec=PendingSubmissionSpec(
                    subject_kind=str(subject["subject_kind"]),
                    subject_id=int(subject["subject_id"]),
                    exercici=exercici,
                    field_code=meta["field_code"],
                    runtime_field_code=meta["runtime_field_code"],
                    judge_index=meta["judge_index"],
                    item_start=meta["item_start"],
                    item_count=meta["item_count"],
                ),
                inputs_patch=raw_by_field.get(runtime_code, {}),
                normalized_inputs_patch=raw_by_field.get(runtime_code, {}),
            )
            pending_submissions.append(submission)
        else:
            immediate_patch.update(field_patch)
            if is_supervisor:
                supervisor_published_codes.append(runtime_code)

    try:
        if immediate_patch:
            entry = persist_subject_score_patch(
                competicio=competicio,
                comp_aparell=comp_aparell,
                exercici=exercici,
                subject=subject,
                phase=scope.phase,
                patch=immediate_patch,
            )
            approve_pending_submissions_for_published_fields(
                competicio=competicio,
                comp_aparell=comp_aparell,
                phase=scope.phase,
                subject_kind=str(subject["subject_kind"]),
                subject_id=int(subject["subject_id"]),
                exercici=exercici,
                runtime_field_codes=supervisor_published_codes,
                token=tok,
                assignment=scope.assignment,
            )
        else:
            entry = _existing_entry_for_subject(competicio, comp_aparell, exercici, subject, scope.phase)
    except ScoringError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Error inesperat calculant puntuacio"}, status=500)

    if entry is not None and team_subject is not None and isinstance(entry.inputs, dict):
        response_inputs = logical_team_inputs_to_runtime_inputs(entry.inputs, team_subject, base_schema)
    elif entry is not None and isinstance(entry.inputs, dict):
        response_inputs = dict(entry.inputs)
    else:
        response_inputs = {}
    if pending_submissions and not immediate_patch:
        response_inputs.update(dict(inputs_patch))

    return JsonResponse({
        "ok": True,
        **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
        "inputs": _filter_inputs_for_allowed_codes(response_inputs, allowed_input_codes),
        "outputs": (entry.outputs if entry is not None else {}) or {},
        "total": float(entry.total if entry is not None else 0),
        "assignment_id": scope.assignment_id,
        "fase_id": entry.fase_id if entry is not None else (scope.phase.id if scope.phase is not None else None),
        "updated_at": entry.updated_at.isoformat() if entry is not None else None,
        "publication_status": (
            "partial_pending"
            if pending_submissions and immediate_patch
            else "pending"
            if pending_submissions
            else "published"
        ),
        "requires_supervision": bool(pending_submissions),
        "pending_submission_ids": [item.id for item in pending_submissions],
    })
