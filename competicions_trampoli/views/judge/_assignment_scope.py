from __future__ import annotations

from dataclasses import dataclass

from django.http import JsonResponse

from ...models.competicio import CompeticioAparell, CompeticioAparellFase
from ...services.judging.assignments import EffectiveJudgeAssignment, resolve_effective_assignment
from ...services.scoring.notes_units import effective_exercise_count
from ...services.scoring.phase_eligibility import phase_subject_is_scoreable


@dataclass(frozen=True)
class JudgeAssignmentScope:
    assignment: EffectiveJudgeAssignment
    competicio: object
    comp_aparell: CompeticioAparell
    phase: CompeticioAparellFase | None

    @property
    def assignment_id(self) -> int | None:
        return self.assignment.id

    @property
    def permissions(self) -> list:
        return list(self.assignment.permissions or [])


def assignment_id_from_request(request, payload: dict | None = None):
    if payload and payload.get("assignment_id") not in (None, ""):
        return payload.get("assignment_id")
    if request.method == "GET":
        return request.GET.get("assignment_id")
    return request.POST.get("assignment_id") or request.GET.get("assignment_id")


def resolve_assignment_scope_for_request(token_obj, assignment_id):
    assignment = resolve_effective_assignment(token_obj, assignment_id)
    if assignment is None:
        return None, JsonResponse(
            {
                "ok": False,
                "error": "Assignacio de jutge no trobada o ambigua.",
                "reason": "assignment_not_found",
            },
            status=404,
        )
    if not assignment.is_active:
        return None, JsonResponse(
            {"ok": False, "error": "Assignacio de jutge inactiva.", "reason": "assignment_inactive"},
            status=403,
        )

    comp_aparell = (
        CompeticioAparell.objects
        .filter(pk=assignment.comp_aparell_id, competicio=token_obj.competicio)
        .select_related("aparell")
        .first()
    )
    if comp_aparell is None:
        return None, JsonResponse(
            {"ok": False, "error": "Aparell d'assignacio no trobat.", "reason": "assignment_app_missing"},
            status=404,
        )

    phase = None
    if assignment.fase_id:
        phase = (
            CompeticioAparellFase.objects
            .filter(
                pk=assignment.fase_id,
                competicio=token_obj.competicio,
                comp_aparell=comp_aparell,
            )
            .first()
        )
        if phase is None:
            return None, JsonResponse(
                {"ok": False, "error": "Fase d'assignacio no trobada.", "reason": "assignment_phase_missing"},
                status=404,
            )

    return JudgeAssignmentScope(
        assignment=assignment,
        competicio=token_obj.competicio,
        comp_aparell=comp_aparell,
        phase=phase,
    ), None


def clamp_exercici_for_scope(scope: JudgeAssignmentScope, exercici_raw):
    try:
        exercici = int(exercici_raw or 1)
    except Exception:
        exercici = 1
    max_ex = max(1, int(effective_exercise_count(scope.comp_aparell, phase=scope.phase) or 1))
    return max(1, min(max_ex, exercici))


def ensure_subject_scoreable_for_scope(scope: JudgeAssignmentScope, subject):
    if phase_subject_is_scoreable(
        scope.phase,
        comp_aparell=scope.comp_aparell,
        subject_kind=subject.get("subject_kind"),
        subject_id=subject.get("subject_id"),
    ):
        return None
    return JsonResponse(
        {
            "ok": False,
            "error": "Aquest subjecte no esta publicat o no es puntuable en aquesta fase.",
            "reason": "subject_not_scoreable_in_phase",
        },
        status=403,
    )


def entry_phase_filter(scope: JudgeAssignmentScope) -> dict:
    if scope.phase is None:
        return {"fase__isnull": True}
    return {"fase": scope.phase}
