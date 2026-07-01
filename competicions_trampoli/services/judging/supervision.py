from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from ...models.judging import JudgePortalAssignment, JudgeScoreSubmission
from ...services.scoring.team_scoring import normalize_permission_target, resolve_permission_runtime_entries

ROLE_STANDARD = "standard"
ROLE_SUPERVISOR = "supervisor"
JUDGE_ROLE_CHOICES = (
    (ROLE_STANDARD, "Jutge"),
    (ROLE_SUPERVISOR, "Supervisor"),
)


def normalize_judge_role(value) -> str:
    role = str(value or ROLE_STANDARD).strip().lower()
    if role not in {ROLE_STANDARD, ROLE_SUPERVISOR}:
        return ROLE_STANDARD
    return role


def permission_with_role(permission: dict) -> dict:
    row = normalize_permission_target(permission or {})
    row["role"] = normalize_judge_role(row.get("role"))
    return row


def permission_is_supervisor(permission: dict) -> bool:
    return normalize_judge_role((permission or {}).get("role")) == ROLE_SUPERVISOR


def _phase_filter(phase):
    return {"fase__isnull": True} if phase is None else {"fase": phase}


def _supervision_runtime_entries(permission: dict, comp_aparell):
    clean = permission_with_role(permission)
    entries = list(resolve_permission_runtime_entries(clean, comp_aparell, member_count=0))
    if entries:
        return entries
    code = str(clean.get("runtime_field_code") or clean.get("field_code") or "").strip()
    if not code:
        return []
    fallback = dict(clean)
    fallback["runtime_field_code"] = code
    return [fallback]


def active_supervisor_assignments_for_field(*, competicio, comp_aparell, phase, runtime_field_code: str):
    runtime_field_code = str(runtime_field_code or "").strip()
    if not runtime_field_code:
        return []
    qs = (
        JudgePortalAssignment.objects
        .filter(
            competicio=competicio,
            comp_aparell=comp_aparell,
            is_active=True,
            judge_token__is_active=True,
            judge_token__revoked_at__isnull=True,
            **_phase_filter(phase),
        )
        .select_related("judge_token", "comp_aparell")
        .order_by("ordre", "id")
    )
    out = []
    for assignment in qs:
        for permission in assignment.permissions or []:
            clean = permission_with_role(permission)
            if not permission_is_supervisor(clean):
                continue
            for resolved in _supervision_runtime_entries(clean, comp_aparell):
                candidate = str(resolved.get("runtime_field_code") or resolved.get("field_code") or "").strip()
                if candidate == runtime_field_code:
                    out.append(assignment)
                    break
    return out


def field_requires_supervision(*, competicio, comp_aparell, phase, runtime_field_code: str) -> bool:
    return bool(
        active_supervisor_assignments_for_field(
            competicio=competicio,
            comp_aparell=comp_aparell,
            phase=phase,
            runtime_field_code=runtime_field_code,
        )
    )


def token_is_supervisor_for_field(*, token, assignment, comp_aparell, runtime_field_code: str) -> bool:
    runtime_field_code = str(runtime_field_code or "").strip()
    if not runtime_field_code:
        return False
    assignment_token_id = getattr(assignment, "judge_token_id", None)
    if assignment_token_id is None and getattr(assignment, "token", None) is not None:
        assignment_token_id = getattr(assignment.token, "id", None)
    if assignment is None or assignment_token_id != getattr(token, "id", None):
        return False
    for permission in assignment.permissions or []:
        clean = permission_with_role(permission)
        if not permission_is_supervisor(clean):
            continue
        for resolved in _supervision_runtime_entries(clean, comp_aparell):
            candidate = str(resolved.get("runtime_field_code") or resolved.get("field_code") or "").strip()
            if candidate == runtime_field_code:
                return True
    return False


@dataclass(frozen=True)
class PendingSubmissionSpec:
    subject_kind: str
    subject_id: int
    exercici: int
    field_code: str
    runtime_field_code: str
    judge_index: int = 1
    item_start: int = 1
    item_count: int | None = None


@transaction.atomic
def create_or_update_pending_submission(
    *,
    scope,
    token,
    subject,
    spec: PendingSubmissionSpec,
    inputs_patch: dict,
    normalized_inputs_patch: dict,
) -> JudgeScoreSubmission:
    lookup = {
        "competicio": scope.competicio,
        "comp_aparell": scope.comp_aparell,
        "fase": scope.phase,
        "submitted_by_token": token,
        "submitted_by_assignment_id": scope.assignment_id,
        "subject_kind": spec.subject_kind,
        "subject_id": int(spec.subject_id),
        "exercici": int(spec.exercici),
        "field_code": str(spec.field_code),
        "runtime_field_code": str(spec.runtime_field_code or spec.field_code),
        "judge_index": int(spec.judge_index or 1),
        "item_start": int(spec.item_start or 1),
        "item_count": spec.item_count,
        "status": JudgeScoreSubmission.Status.PENDING,
    }
    existing = JudgeScoreSubmission.objects.select_for_update().filter(**lookup).order_by("-updated_at", "-id").first()
    if existing is None:
        return JudgeScoreSubmission.objects.create(
            **lookup,
            inputs_patch=dict(inputs_patch or {}),
            normalized_inputs_patch=dict(normalized_inputs_patch or {}),
        )
    existing.inputs_patch = dict(inputs_patch or {})
    existing.normalized_inputs_patch = dict(normalized_inputs_patch or {})
    existing.save(update_fields=["inputs_patch", "normalized_inputs_patch", "updated_at"])
    return existing


def pending_submissions_for_supervisor(*, token, assignment, comp_aparell, phase):
    supervisor_codes = set()
    for permission in assignment.permissions or []:
        clean = permission_with_role(permission)
        if not permission_is_supervisor(clean):
            continue
        for resolved in _supervision_runtime_entries(clean, comp_aparell):
            code = str(resolved.get("runtime_field_code") or resolved.get("field_code") or "").strip()
            if code:
                supervisor_codes.add(code)
    if not supervisor_codes:
        return JudgeScoreSubmission.objects.none()
    return (
        JudgeScoreSubmission.objects
        .filter(
            competicio=token.competicio,
            comp_aparell=comp_aparell,
            status=JudgeScoreSubmission.Status.PENDING,
            runtime_field_code__in=supervisor_codes,
            **_phase_filter(phase),
        )
        .exclude(submitted_by_token=token)
        .select_related("submitted_by_token", "submitted_by_assignment")
        .order_by("created_at", "id")
    )


def validate_single_supervisor_per_field(*, competicio, comp_aparell, phase, permissions: list, excluding_assignment_id=None):
    conflicts = []
    requested_codes = []
    for permission in permissions or []:
        clean = permission_with_role(permission)
        if not permission_is_supervisor(clean):
            continue
        for resolved in _supervision_runtime_entries(clean, comp_aparell):
            code = str(resolved.get("runtime_field_code") or resolved.get("field_code") or "").strip()
            if not code:
                continue
            requested_codes.append(code)
            assignments = active_supervisor_assignments_for_field(
                competicio=competicio,
                comp_aparell=comp_aparell,
                phase=phase,
                runtime_field_code=code,
            )
            if excluding_assignment_id is not None:
                assignments = [item for item in assignments if int(item.id) != int(excluding_assignment_id)]
            if assignments:
                conflicts.append(code)
    duplicates = {
        code
        for code in requested_codes
        if requested_codes.count(code) > 1
    }
    if duplicates:
        unique = ", ".join(sorted(duplicates))
        raise ValueError(f"No es pot assignar mes d'un supervisor al mateix camp: {unique}.")
    if conflicts:
        unique = ", ".join(sorted(set(conflicts)))
        raise ValueError(f"Ja hi ha un supervisor actiu per aquests camps: {unique}.")


def mark_submission_approved(submission, *, token, assignment):
    submission.status = JudgeScoreSubmission.Status.APPROVED
    submission.reviewed_by_token = token
    submission.reviewed_by_assignment_id = getattr(assignment, "id", None)
    submission.reviewed_at = timezone.now()
    submission.save(update_fields=["status", "reviewed_by_token", "reviewed_by_assignment", "reviewed_at", "updated_at"])
    return submission


def mark_submission_rejected(submission, *, token, assignment):
    submission.status = JudgeScoreSubmission.Status.REJECTED
    submission.reviewed_by_token = token
    submission.reviewed_by_assignment_id = getattr(assignment, "id", None)
    submission.reviewed_at = timezone.now()
    submission.save(update_fields=["status", "reviewed_by_token", "reviewed_by_assignment", "reviewed_at", "updated_at"])
    return submission


def approve_pending_submissions_for_published_fields(
    *,
    competicio,
    comp_aparell,
    phase,
    subject_kind: str,
    subject_id: int,
    exercici: int,
    runtime_field_codes: list[str],
    token,
    assignment,
) -> int:
    codes = [str(code or "").strip() for code in runtime_field_codes or [] if str(code or "").strip()]
    if not codes:
        return 0
    rows = (
        JudgeScoreSubmission.objects
        .filter(
            competicio=competicio,
            comp_aparell=comp_aparell,
            subject_kind=str(subject_kind or "").strip().lower(),
            subject_id=int(subject_id),
            exercici=int(exercici),
            runtime_field_code__in=sorted(set(codes)),
            status=JudgeScoreSubmission.Status.PENDING,
            **_phase_filter(phase),
        )
        .exclude(submitted_by_token=token)
        .select_for_update()
        .order_by("id")
    )
    count = 0
    for submission in rows:
        mark_submission_approved(submission, token=token, assignment=assignment)
        count += 1
    return count
