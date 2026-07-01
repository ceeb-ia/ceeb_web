import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from ...models.judging import JudgeDeviceToken, JudgeScoreSubmission
from ...scoring_engine import ScoringError
from ...services.judging.submissions import approve_judge_score_submission
from ...services.judging.supervision import pending_submissions_for_supervisor
from ...services.scoring.scoring_subjects import serialize_subject_payload
from ._assignment_scope import assignment_id_from_request, resolve_assignment_scope_for_request


def _submission_payload(submission):
    return {
        "id": submission.id,
        "status": submission.status,
        "field_code": submission.field_code,
        "runtime_field_code": submission.runtime_field_code or submission.field_code,
        "exercici": submission.exercici,
        **serialize_subject_payload(submission.subject_kind, submission.subject_id),
        "judge_index": submission.judge_index,
        "item_start": submission.item_start,
        "item_count": submission.item_count,
        "inputs_patch": submission.inputs_patch or {},
        "normalized_inputs_patch": submission.normalized_inputs_patch or {},
        "submitted_by_token_id": str(submission.submitted_by_token_id),
        "submitted_by_label": getattr(submission.submitted_by_token, "label", "") or "",
        "created_at": submission.created_at.isoformat() if submission.created_at else None,
        "updated_at": submission.updated_at.isoformat() if submission.updated_at else None,
    }


@require_GET
def judge_supervision_pending(request, token):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        return JsonResponse({"ok": False, "error": "Token invalid o revocat"}, status=403)
    scope, scope_error = resolve_assignment_scope_for_request(tok, assignment_id_from_request(request))
    if scope_error is not None:
        return scope_error
    submissions = pending_submissions_for_supervisor(
        token=tok,
        assignment=scope.assignment,
        comp_aparell=scope.comp_aparell,
        phase=scope.phase,
    )
    return JsonResponse({
        "ok": True,
        "assignment_id": scope.assignment_id,
        "pending": [_submission_payload(item) for item in submissions[:300]],
    })


@require_POST
def judge_supervision_approve(request, token):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        return JsonResponse({"ok": False, "error": "Token invalid o revocat"}, status=403)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON invalid"}, status=400)
    scope, scope_error = resolve_assignment_scope_for_request(tok, assignment_id_from_request(request, payload))
    if scope_error is not None:
        return scope_error
    submission_id = payload.get("submission_id")
    if submission_id in (None, ""):
        return JsonResponse({"ok": False, "error": "Cal indicar la submissio a aprovar."}, status=400)
    submission = get_object_or_404(
        JudgeScoreSubmission,
        pk=submission_id,
        competicio=scope.competicio,
        comp_aparell=scope.comp_aparell,
    )
    try:
        approved, entry = approve_judge_score_submission(
            submission=submission,
            supervisor_token=tok,
            supervisor_assignment=scope.assignment,
            inputs_patch=payload.get("inputs_patch"),
        )
    except PermissionDenied as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=403)
    except ValidationError as exc:
        return JsonResponse({"ok": False, "error": "; ".join(exc.messages)}, status=400)
    except ScoringError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({
        "ok": True,
        "submission": _submission_payload(approved),
        "entry": {
            **serialize_subject_payload(approved.subject_kind, approved.subject_id),
            "exercici": entry.exercici,
            "comp_aparell_id": entry.comp_aparell_id,
            "fase_id": entry.fase_id,
            "inputs": entry.inputs or {},
            "outputs": entry.outputs or {},
            "total": float(entry.total),
            "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
        },
    })
