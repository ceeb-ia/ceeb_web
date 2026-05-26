from __future__ import annotations

from dataclasses import dataclass

from ...models.judging import JudgeDeviceToken, JudgePortalAssignment


@dataclass(frozen=True)
class EffectiveJudgeAssignment:
    id: int | None
    token: JudgeDeviceToken
    competicio_id: int
    comp_aparell_id: int
    fase_id: int | None
    permissions: list
    label: str
    ordre: int
    is_active: bool
    is_legacy: bool = False

    @property
    def is_preliminary(self) -> bool:
        return self.fase_id is None

    @property
    def can_record_video(self) -> bool:
        return bool(getattr(self.token, "can_record_video", False))


def _legacy_assignment_for_token(token: JudgeDeviceToken) -> EffectiveJudgeAssignment:
    return EffectiveJudgeAssignment(
        id=None,
        token=token,
        competicio_id=int(token.competicio_id),
        comp_aparell_id=int(token.comp_aparell_id),
        fase_id=None,
        permissions=list(token.permissions or []),
        label=str(token.label or "").strip(),
        ordre=1,
        is_active=bool(token.is_valid()),
        is_legacy=True,
    )


def _assignment_from_model(assignment: JudgePortalAssignment) -> EffectiveJudgeAssignment:
    token_is_valid = bool(assignment.judge_token.is_valid())
    return EffectiveJudgeAssignment(
        id=int(assignment.id),
        token=assignment.judge_token,
        competicio_id=int(assignment.competicio_id),
        comp_aparell_id=int(assignment.comp_aparell_id),
        fase_id=int(assignment.fase_id) if assignment.fase_id else None,
        permissions=list(assignment.permissions or []),
        label=str(assignment.label or "").strip(),
        ordre=int(assignment.ordre or 1),
        is_active=bool(assignment.is_active and token_is_valid),
        is_legacy=False,
    )


def effective_assignments_for_token(
    token: JudgeDeviceToken,
    *,
    include_inactive: bool = False,
) -> list[EffectiveJudgeAssignment]:
    base_qs = (
        JudgePortalAssignment.objects
        .filter(judge_token=token)
        .select_related("judge_token", "competicio", "comp_aparell", "fase")
        .order_by("ordre", "id")
    )
    has_explicit_assignments = base_qs.exists()
    if not token.is_valid() and not include_inactive:
        return []
    qs = base_qs if include_inactive else base_qs.filter(is_active=True)
    assignments = [_assignment_from_model(item) for item in qs]
    if assignments or has_explicit_assignments:
        return assignments
    legacy = _legacy_assignment_for_token(token)
    if include_inactive or legacy.is_active:
        return [legacy]
    return []


def resolve_effective_assignment(
    token: JudgeDeviceToken,
    assignment_id: int | str | None = None,
    *,
    include_inactive: bool = False,
) -> EffectiveJudgeAssignment | None:
    assignments = effective_assignments_for_token(token, include_inactive=include_inactive)
    if assignment_id in (None, "", 0, "0"):
        return assignments[0] if len(assignments) == 1 else None
    try:
        clean_id = int(assignment_id)
    except (TypeError, ValueError):
        return None
    for assignment in assignments:
        if assignment.id == clean_id:
            return assignment
    return None


__all__ = [
    "EffectiveJudgeAssignment",
    "effective_assignments_for_token",
    "resolve_effective_assignment",
]
