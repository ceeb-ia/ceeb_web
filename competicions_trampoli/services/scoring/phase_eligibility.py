from __future__ import annotations

from ...models.competicio import CompeticioAparellFase, ProgramUnit, ProgramUnitSlot


SCOREABLE_SLOT_STATUSES = {
    ProgramUnitSlot.Status.FILLED,
    ProgramUnitSlot.Status.MANUAL,
}


def is_phase_published(fase: CompeticioAparellFase | None) -> bool:
    if fase is None:
        return True
    return fase.estat == CompeticioAparellFase.Estat.PUBLISHED


def is_program_unit_published(unit: ProgramUnit) -> bool:
    return unit.status == ProgramUnit.Status.PUBLISHED


def is_program_unit_scoreable(unit: ProgramUnit) -> bool:
    fase = getattr(unit, "fase", None)
    return is_phase_published(fase) or is_program_unit_published(unit)


def scoreable_slot_statuses() -> set[str]:
    return set(SCOREABLE_SLOT_STATUSES)


def scoreable_slots_qs():
    return ProgramUnitSlot.objects.filter(status__in=SCOREABLE_SLOT_STATUSES, subject_id__isnull=False)


def scoreable_slots_for_program_unit(unit: ProgramUnit):
    qs = scoreable_slots_qs().filter(unit=unit)
    if not is_program_unit_scoreable(unit):
        return qs.none()
    return qs


def phase_subject_is_scoreable(
    fase: CompeticioAparellFase | None,
    *,
    comp_aparell,
    subject_kind: str,
    subject_id,
) -> bool:
    if fase is None:
        return True
    try:
        clean_subject_id = int(subject_id)
    except (TypeError, ValueError):
        return False
    kind = str(subject_kind or "").strip().lower()
    if not kind:
        return False
    if fase.comp_aparell_id != getattr(comp_aparell, "id", None):
        return False

    qs = scoreable_slots_qs().filter(
        unit__fase=fase,
        unit__fase__comp_aparell=comp_aparell,
        subject_kind=kind,
        subject_id=clean_subject_id,
    )
    if is_phase_published(fase):
        return qs.exists()
    return qs.filter(unit__status=ProgramUnit.Status.PUBLISHED).exists()


__all__ = [
    "SCOREABLE_SLOT_STATUSES",
    "is_phase_published",
    "is_program_unit_published",
    "is_program_unit_scoreable",
    "phase_subject_is_scoreable",
    "scoreable_slot_statuses",
    "scoreable_slots_for_program_unit",
    "scoreable_slots_qs",
]
