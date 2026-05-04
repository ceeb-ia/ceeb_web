from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from django.db import transaction

from ...models.inscripcions import GrupCompeticio, Inscripcio
from ...models.competicio import CompeticioAparellFase, ProgramUnit, ProgramUnitSlot
from ...services.shared.competition_groups import group_label


@dataclass(frozen=True)
class SlotSubject:
    subject_kind: str
    subject_id: int
    status: str = ProgramUnitSlot.Status.FILLED
    source_position: Optional[int] = None
    source_row: Optional[dict] = None


def create_program_unit_with_empty_slots(
    *,
    fase: CompeticioAparellFase,
    nom: str,
    capacity: int,
    tipus: str = ProgramUnit.Tipus.CUSTOM,
    ordre: Optional[int] = None,
    partition_key: str = "",
    partition_values: Optional[dict] = None,
    metadata: Optional[dict] = None,
    status: str = ProgramUnit.Status.PLANNED,
) -> ProgramUnit:
    if fase is None or not getattr(fase, "id", None):
        raise ValueError("Cal una fase desada.")
    try:
        clean_capacity = int(capacity)
    except Exception as exc:
        raise ValueError("La capacitat ha de ser un enter positiu.") from exc
    if clean_capacity <= 0:
        raise ValueError("La capacitat ha de ser positiva.")

    resolved_order = ordre if ordre is not None else next_program_unit_order(fase)
    with transaction.atomic():
        unit = ProgramUnit.objects.create(
            fase=fase,
            nom=nom,
            tipus=tipus,
            ordre=resolved_order,
            partition_key=partition_key,
            partition_values=partition_values or {},
            capacity=clean_capacity,
            metadata=metadata or {},
            status=status,
        )
        ProgramUnitSlot.objects.bulk_create(
            [
                ProgramUnitSlot(
                    unit=unit,
                    slot_index=index,
                    ordre=index,
                    status=ProgramUnitSlot.Status.EMPTY,
                )
                for index in range(1, clean_capacity + 1)
            ]
        )
    return unit


def next_program_unit_order(fase: CompeticioAparellFase) -> int:
    last = ProgramUnit.objects.filter(fase=fase).order_by("-ordre").values_list("ordre", flat=True).first()
    return int(last or 0) + 1


def fill_program_unit_slots(
    unit: ProgramUnit,
    subjects: Sequence[SlotSubject],
) -> ProgramUnit:
    if unit is None or not getattr(unit, "id", None):
        raise ValueError("Cal una unitat programable desada.")
    slots = list(unit.slots.order_by("slot_index", "id"))
    if len(subjects or []) > len(slots):
        raise ValueError("Hi ha mes subjectes que slots disponibles.")

    updates = []
    for slot, subject in zip(slots, subjects or []):
        slot.subject_kind = str(subject.subject_kind or "").strip().lower()
        slot.subject_id = int(subject.subject_id)
        slot.status = subject.status
        slot.source_position = subject.source_position
        slot.source_row = subject.source_row or {}
        slot.full_clean()
        updates.append(slot)
    if updates:
        ProgramUnitSlot.objects.bulk_update(
            updates,
            ["subject_kind", "subject_id", "status", "source_position", "source_row", "updated_at"],
        )
    return unit


def create_program_unit_from_subjects(
    *,
    fase: CompeticioAparellFase,
    nom: str,
    subjects: Sequence[SlotSubject],
    tipus: str = ProgramUnit.Tipus.CUSTOM,
    ordre: Optional[int] = None,
    partition_key: str = "",
    partition_values: Optional[dict] = None,
    metadata: Optional[dict] = None,
    status: str = ProgramUnit.Status.GENERATED,
) -> ProgramUnit:
    clean_subjects = list(subjects or [])
    capacity = max(1, len(clean_subjects))
    unit = create_program_unit_with_empty_slots(
        fase=fase,
        nom=nom,
        capacity=capacity,
        tipus=tipus,
        ordre=ordre,
        partition_key=partition_key,
        partition_values=partition_values,
        metadata=metadata,
        status=status,
    )
    fill_program_unit_slots(unit, clean_subjects)
    return unit


def create_units_one_per_partition(
    *,
    fase: CompeticioAparellFase,
    partitions: Iterable[dict],
    default_capacity: int,
    tipus: str = ProgramUnit.Tipus.CUSTOM,
) -> list[ProgramUnit]:
    units = []
    for index, partition in enumerate(partitions or [], start=1):
        key = str((partition or {}).get("key") or f"partition-{index}").strip()
        label = str((partition or {}).get("label") or key or f"Particio {index}").strip()
        values = (partition or {}).get("values") if isinstance(partition, dict) else {}
        capacity = int((partition or {}).get("capacity") or default_capacity)
        units.append(
            create_program_unit_with_empty_slots(
                fase=fase,
                nom=label,
                capacity=capacity,
                tipus=tipus,
                ordre=next_program_unit_order(fase),
                partition_key=key,
                partition_values=values if isinstance(values, dict) else {},
                status=ProgramUnit.Status.GENERATED,
            )
        )
    return units


def create_units_split_by_capacity(
    *,
    fase: CompeticioAparellFase,
    label: str,
    subjects: Sequence[SlotSubject],
    max_capacity: int,
    tipus: str = ProgramUnit.Tipus.CUSTOM,
    partition_key: str = "",
    partition_values: Optional[dict] = None,
) -> list[ProgramUnit]:
    try:
        clean_capacity = int(max_capacity)
    except Exception as exc:
        raise ValueError("La capacitat maxima ha de ser un enter positiu.") from exc
    if clean_capacity <= 0:
        raise ValueError("La capacitat maxima ha de ser positiva.")

    clean_subjects = list(subjects or [])
    if not clean_subjects:
        return [
            create_program_unit_with_empty_slots(
                fase=fase,
                nom=label,
                capacity=clean_capacity,
                tipus=tipus,
                partition_key=partition_key,
                partition_values=partition_values or {},
                status=ProgramUnit.Status.GENERATED,
            )
        ]

    units = []
    for offset in range(0, len(clean_subjects), clean_capacity):
        chunk = clean_subjects[offset:offset + clean_capacity]
        suffix = (offset // clean_capacity) + 1
        unit_label = label if len(clean_subjects) <= clean_capacity else f"{label} {suffix}"
        units.append(
            create_program_unit_from_subjects(
                fase=fase,
                nom=unit_label,
                subjects=chunk,
                tipus=tipus,
                partition_key=partition_key,
                partition_values=partition_values or {},
            )
        )
    return units


def create_units_from_base_groups(fase: CompeticioAparellFase) -> list[ProgramUnit]:
    if fase is None or not getattr(fase, "id", None):
        raise ValueError("Cal una fase desada.")
    competicio = fase.competicio
    groups = list(GrupCompeticio.objects.filter(competicio=competicio, actiu=True).order_by("display_num", "id"))
    units = []
    for group in groups:
        inscripcions = list(
            Inscripcio.objects
            .filter(competicio=competicio, grup_competicio=group)
            .order_by("ordre_competicio", "ordre_sortida", "id")
        )
        subjects = [
            SlotSubject(
                subject_kind="inscripcio",
                subject_id=int(inscripcio.id),
                source_position=index,
                source_row={
                    "grup_competicio_id": int(group.id),
                    "group_display_num": int(group.display_num),
                },
            )
            for index, inscripcio in enumerate(inscripcions, start=1)
        ]
        capacity = max(1, len(subjects))
        unit = create_program_unit_with_empty_slots(
            fase=fase,
            nom=group_label(group),
            capacity=capacity,
            tipus=ProgramUnit.Tipus.GROUP,
            partition_key=f"group:{group.display_num}",
            partition_values={
                "group_id": int(group.id),
                "display_num": int(group.display_num),
            },
            metadata={
                "source": "base_group",
                "grup_competicio_id": int(group.id),
            },
            status=ProgramUnit.Status.GENERATED,
        )
        fill_program_unit_slots(unit, subjects)
        units.append(unit)
    return units
