from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max
from django.core.exceptions import ObjectDoesNotExist

from ...models.competicio import (
    CompeticioAparellFase,
    Inscripcio,
    InscripcioAparellExclusio,
    ProgramUnit,
    ProgramUnitSlot,
    QualificationRun,
)


class SlotOverrideError(ValueError):
    pass


@dataclass(frozen=True)
class ReserveOption:
    key: str
    partition_key: str
    subject_kind: str
    subject_id: int
    label: str
    meta: str
    source_particio_key: str
    source_position: int | None
    source_score: Decimal | None
    source_row: dict
    source_classificacio_id: int | None

    @property
    def subject_ref(self) -> tuple[str, int]:
        return (self.subject_kind, self.subject_id)


@dataclass(frozen=True)
class SnapshotOption:
    key: str
    partition_key: str
    subject_kind: str
    subject_id: int
    label: str
    meta: str
    source_particio_key: str
    source_position: int | None
    source_score: Decimal | None
    source_row: dict
    source_classificacio_id: int | None

    @property
    def subject_ref(self) -> tuple[str, int]:
        return (self.subject_kind, self.subject_id)


@dataclass(frozen=True)
class ManualInscripcioOption:
    inscripcio_id: int
    label: str
    meta: str
    assigned: bool
    excluded_from_app: bool


def _source_row_text(source_row: dict, *keys: str) -> str:
    for key in keys:
        value = source_row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    cells = source_row.get("cells")
    if isinstance(cells, dict):
        for key in keys:
            value = cells.get(key)
            if value not in (None, ""):
                return str(value).strip()
    return ""


def _to_decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def applied_qualification_run(fase: CompeticioAparellFase) -> QualificationRun | None:
    config = fase.config if isinstance(fase.config, dict) else {}
    qualification = config.get("qualification") if isinstance(config.get("qualification"), dict) else {}
    run_id = _to_int(qualification.get("run_id"))
    if not run_id:
        return None
    return (
        QualificationRun.objects
        .filter(id=run_id, fase=fase, status=QualificationRun.Status.APPLIED)
        .first()
    )


def reserve_options_for_phase(fase: CompeticioAparellFase) -> list[ReserveOption]:
    run = applied_qualification_run(fase)
    if run is None:
        return []
    payload = run.payload if isinstance(run.payload, dict) else {}
    reserves = payload.get("reserves") if isinstance(payload.get("reserves"), dict) else {}
    options: list[ReserveOption] = []
    index = 0
    for partition_key, items in reserves.items():
        for item in items or []:
            if not isinstance(item, dict):
                continue
            subject_kind = str(item.get("subject_kind") or "").strip().lower()
            subject_id = _to_int(item.get("subject_id"))
            if not subject_kind or not subject_id:
                continue
            source_row = deepcopy(item.get("source_row") if isinstance(item.get("source_row"), dict) else {})
            label = _source_row_text(source_row, "participant", "nom", "name", "label", "equip_nom")
            if not label:
                label = f"{subject_kind}:{subject_id}"
            meta = _source_row_text(source_row, "entitat_nom", "entitat", "club", "categoria", "subcategoria")
            index += 1
            key = f"{index}:{partition_key}:{subject_kind}:{subject_id}"
            options.append(
                ReserveOption(
                    key=key,
                    partition_key=str(partition_key or "global").strip() or "global",
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    label=label,
                    meta=meta,
                    source_particio_key=str(item.get("source_particio_key") or partition_key or "global").strip() or "global",
                    source_position=_to_int(item.get("source_position")),
                    source_score=_to_decimal(item.get("source_score")),
                    source_row=source_row,
                    source_classificacio_id=run.source_classificacio_id,
                )
            )
    return options


def active_subject_refs_for_phase(fase: CompeticioAparellFase, *, exclude_slot_id: int | None = None) -> set[tuple[str, int]]:
    qs = ProgramUnitSlot.objects.filter(
        unit__fase=fase,
        status__in=[ProgramUnitSlot.Status.FILLED, ProgramUnitSlot.Status.MANUAL],
        subject_id__isnull=False,
    )
    if exclude_slot_id:
        qs = qs.exclude(id=exclude_slot_id)
    return {
        (str(row["subject_kind"] or "").strip().lower(), int(row["subject_id"]))
        for row in qs.values("subject_kind", "subject_id")
        if row["subject_kind"] and row["subject_id"]
    }


def reserve_matches_slot(option: ReserveOption, slot: ProgramUnitSlot, unit: ProgramUnit | None = None) -> bool:
    resolved_unit = unit or slot.unit
    slot_partition = (
        str(slot.source_particio_key or "").strip()
        or str(getattr(resolved_unit, "partition_key", "") or "").strip()
        or "global"
    )
    return option.partition_key == slot_partition


def available_reserve_options_for_slot(
    slot: ProgramUnitSlot,
    options: list[ReserveOption],
    active_refs: set[tuple[str, int]],
) -> list[ReserveOption]:
    unit = slot.unit
    return [
        option
        for option in options
        if option.subject_ref not in active_refs and reserve_matches_slot(option, slot, unit)
    ]


def _slot_metadata_source_row(source_row: dict, *, override_type: str, previous_slot: ProgramUnitSlot | None = None) -> dict:
    row = deepcopy(source_row)
    manual = row.get("manual_override") if isinstance(row.get("manual_override"), dict) else {}
    manual["type"] = override_type
    if previous_slot is not None and previous_slot.subject_id:
        manual["previous_subject_kind"] = previous_slot.subject_kind
        manual["previous_subject_id"] = previous_slot.subject_id
        manual["previous_status"] = previous_slot.status
    row["manual_override"] = manual
    return row


def _reserve_by_key(fase: CompeticioAparellFase, reserve_key: str) -> ReserveOption:
    for option in reserve_options_for_phase(fase):
        if option.key == reserve_key:
            return option
    raise SlotOverrideError("Reserva no valida per aquest snapshot.")


def _snapshot_option_from_item(
    *,
    index: int,
    partition_key: str,
    item: dict,
    source_classificacio_id: int | None,
) -> SnapshotOption | None:
    if not isinstance(item, dict):
        return None
    subject_kind = str(item.get("subject_kind") or "").strip().lower()
    subject_id = _to_int(item.get("subject_id"))
    if not subject_kind or not subject_id:
        return None
    source_row = deepcopy(item.get("source_row") if isinstance(item.get("source_row"), dict) else {})
    label = _source_row_text(source_row, "participant", "nom", "name", "label", "equip_nom")
    if not label:
        label = f"{subject_kind}:{subject_id}"
    meta = _source_row_text(source_row, "entitat_nom", "entitat", "club", "categoria", "subcategoria")
    clean_partition = str(item.get("source_particio_key") or partition_key or "global").strip() or "global"
    return SnapshotOption(
        key=f"{index}:{clean_partition}:{subject_kind}:{subject_id}",
        partition_key=clean_partition,
        subject_kind=subject_kind,
        subject_id=subject_id,
        label=label,
        meta=meta,
        source_particio_key=clean_partition,
        source_position=_to_int(item.get("source_position")),
        source_score=_to_decimal(item.get("source_score")),
        source_row=source_row,
        source_classificacio_id=source_classificacio_id,
    )


def recoverable_snapshot_options_for_phase(fase: CompeticioAparellFase) -> list[SnapshotOption]:
    run = applied_qualification_run(fase)
    if run is None:
        return []
    payload = run.payload if isinstance(run.payload, dict) else {}
    options: list[SnapshotOption] = []
    seen: set[tuple[str, int]] = set()
    index = 0
    for unit in payload.get("units") or []:
        if not isinstance(unit, dict):
            continue
        partition_key = str(unit.get("partition_key") or "global").strip() or "global"
        for item in unit.get("candidates") or []:
            index += 1
            option = _snapshot_option_from_item(
                index=index,
                partition_key=partition_key,
                item=item,
                source_classificacio_id=run.source_classificacio_id,
            )
            if option is None or option.subject_ref in seen:
                continue
            seen.add(option.subject_ref)
            options.append(option)
    return options


def available_recoverable_options_for_slot(
    slot: ProgramUnitSlot,
    options: list[SnapshotOption],
    active_refs: set[tuple[str, int]],
) -> list[SnapshotOption]:
    return [
        option
        for option in options
        if option.subject_ref not in active_refs and reserve_matches_slot(option, slot, slot.unit)
    ]


def _snapshot_by_key(fase: CompeticioAparellFase, candidate_key: str) -> SnapshotOption:
    for option in recoverable_snapshot_options_for_phase(fase):
        if option.key == candidate_key:
            return option
    raise SlotOverrideError("Candidat del snapshot no valid.")


def manual_inscripcio_options_for_phase(fase: CompeticioAparellFase) -> list[ManualInscripcioOption]:
    comp_aparell = fase.comp_aparell
    active_inscripcio_ids = {
        subject_id
        for subject_kind, subject_id in active_subject_refs_for_phase(fase)
        if subject_kind == "inscripcio"
    }
    excluded_ids = set(
        InscripcioAparellExclusio.objects
        .filter(comp_aparell=comp_aparell)
        .values_list("inscripcio_id", flat=True)
    )
    options: list[ManualInscripcioOption] = []
    qs = (
        Inscripcio.objects
        .filter(competicio=fase.competicio)
        .select_related("equip")
        .order_by("categoria", "subcategoria", "entitat", "nom_i_cognoms", "id")
    )
    for inscripcio in qs:
        meta_parts = [
            str(getattr(inscripcio, "entitat", "") or "").strip(),
            str(getattr(inscripcio, "categoria", "") or "").strip(),
            str(getattr(inscripcio, "subcategoria", "") or "").strip(),
        ]
        equip = getattr(inscripcio, "equip", None)
        if equip is not None:
            meta_parts.append(str(getattr(equip, "nom", "") or "").strip())
        options.append(
            ManualInscripcioOption(
                inscripcio_id=int(inscripcio.id),
                label=str(inscripcio.nom_i_cognoms or "").strip() or f"Inscripcio {inscripcio.id}",
                meta=" / ".join(part for part in meta_parts if part),
                assigned=int(inscripcio.id) in active_inscripcio_ids,
                excluded_from_app=int(inscripcio.id) in excluded_ids,
            )
        )
    return options


def add_extra_slot_to_unit(fase: CompeticioAparellFase, unit_id: int) -> ProgramUnitSlot:
    try:
        unit = ProgramUnit.objects.get(fase=fase, id=unit_id)
    except ObjectDoesNotExist as exc:
        raise SlotOverrideError("Unitat no valida per aquesta fase.") from exc
    with transaction.atomic():
        stats = unit.slots.aggregate(max_slot_index=Max("slot_index"), max_ordre=Max("ordre"))
        slot = ProgramUnitSlot.objects.create(
            unit=unit,
            slot_index=int(stats.get("max_slot_index") or 0) + 1,
            ordre=int(stats.get("max_ordre") or 0) + 1,
            status=ProgramUnitSlot.Status.EMPTY,
        )
        unit.capacity = unit.slots.count()
        unit.save(update_fields=["capacity", "updated_at"])
    return slot


def reorder_program_unit_slots(fase: CompeticioAparellFase, unit_id: int, ordered_slot_ids: list[int]) -> ProgramUnit:
    try:
        unit = ProgramUnit.objects.get(fase=fase, id=unit_id)
    except ObjectDoesNotExist as exc:
        raise SlotOverrideError("Unitat no valida per aquesta fase.") from exc
    slots = list(ProgramUnitSlot.objects.filter(unit=unit).order_by("ordre", "slot_index", "id"))
    if not slots:
        raise SlotOverrideError("Aquesta unitat no te places per ordenar.")
    if any(slot.locked for slot in slots):
        raise SlotOverrideError("No es pot reordenar una unitat amb places bloquejades.")

    current_ids = [int(slot.id) for slot in slots]
    clean_ids: list[int] = []
    seen: set[int] = set()
    for raw_id in ordered_slot_ids or []:
        slot_id = _to_int(raw_id)
        if not slot_id or slot_id in seen:
            continue
        clean_ids.append(slot_id)
        seen.add(slot_id)
    if set(clean_ids) != set(current_ids):
        raise SlotOverrideError("L'ordre rebut no coincideix amb les places actuals de la unitat.")

    slots_by_id = {int(slot.id): slot for slot in slots}
    ordered_slots = [slots_by_id[slot_id] for slot_id in clean_ids]
    with transaction.atomic():
        offset = max([int(slot.ordre or 0) for slot in slots] or [0]) + len(slots) + 10
        for index, slot in enumerate(ordered_slots, start=1):
            slot.ordre = offset + index
        ProgramUnitSlot.objects.bulk_update(ordered_slots, ["ordre"], batch_size=500)

        for index, slot in enumerate(ordered_slots, start=1):
            slot.ordre = index
        ProgramUnitSlot.objects.bulk_update(ordered_slots, ["ordre"], batch_size=500)
    return unit


def assign_reserve_to_slot(fase: CompeticioAparellFase, slot_id: int, reserve_key: str) -> ProgramUnitSlot:
    option = _reserve_by_key(fase, reserve_key)
    try:
        slot = ProgramUnitSlot.objects.select_related("unit").get(id=slot_id, unit__fase=fase)
    except ObjectDoesNotExist as exc:
        raise SlotOverrideError("Slot no valid per aquesta fase.") from exc
    if slot.locked:
        raise SlotOverrideError("Aquest slot esta bloquejat.")
    if not reserve_matches_slot(option, slot, slot.unit):
        raise SlotOverrideError("Aquesta reserva no correspon a la particio de la unitat.")
    if option.subject_ref in active_subject_refs_for_phase(fase, exclude_slot_id=slot.id):
        raise SlotOverrideError("Aquesta reserva ja esta assignada a una altra plaça activa.")

    slot.subject_kind = option.subject_kind
    slot.subject_id = option.subject_id
    slot.status = ProgramUnitSlot.Status.MANUAL
    slot.source_classificacio_id = option.source_classificacio_id
    slot.source_particio_key = option.source_particio_key
    slot.source_position = option.source_position
    slot.source_score = option.source_score
    slot.source_row = _slot_metadata_source_row(
        option.source_row,
        override_type="reserve_promotion",
        previous_slot=slot,
    )
    slot.full_clean()
    slot.save(update_fields=[
        "subject_kind",
        "subject_id",
        "status",
        "source_classificacio",
        "source_particio_key",
        "source_position",
        "source_score",
        "source_row",
        "updated_at",
    ])
    return slot


def _assign_option_to_slot(
    fase: CompeticioAparellFase,
    slot_id: int,
    option: ReserveOption | SnapshotOption,
    *,
    override_type: str,
) -> ProgramUnitSlot:
    try:
        slot = ProgramUnitSlot.objects.select_related("unit").get(id=slot_id, unit__fase=fase)
    except ObjectDoesNotExist as exc:
        raise SlotOverrideError("Slot no valid per aquesta fase.") from exc
    if slot.locked:
        raise SlotOverrideError("Aquest slot esta bloquejat.")
    if not reserve_matches_slot(option, slot, slot.unit):
        raise SlotOverrideError("Aquest candidat no correspon a la particio de la unitat.")
    if option.subject_ref in active_subject_refs_for_phase(fase, exclude_slot_id=slot.id):
        raise SlotOverrideError("Aquest candidat ja esta assignat a una altra placa activa.")

    slot.subject_kind = option.subject_kind
    slot.subject_id = option.subject_id
    slot.status = ProgramUnitSlot.Status.MANUAL
    slot.source_classificacio_id = option.source_classificacio_id
    slot.source_particio_key = option.source_particio_key
    slot.source_position = option.source_position
    slot.source_score = option.source_score
    slot.source_row = _slot_metadata_source_row(
        option.source_row,
        override_type=override_type,
        previous_slot=slot,
    )
    slot.full_clean()
    slot.save(update_fields=[
        "subject_kind",
        "subject_id",
        "status",
        "source_classificacio",
        "source_particio_key",
        "source_position",
        "source_score",
        "source_row",
        "updated_at",
    ])
    return slot


def assign_snapshot_candidate_to_slot(fase: CompeticioAparellFase, slot_id: int, candidate_key: str) -> ProgramUnitSlot:
    return _assign_option_to_slot(
        fase,
        slot_id,
        _snapshot_by_key(fase, candidate_key),
        override_type="snapshot_recovery",
    )


def assign_inscripcio_to_slot(fase: CompeticioAparellFase, slot_id: int, inscripcio_id: int) -> ProgramUnitSlot:
    try:
        slot = ProgramUnitSlot.objects.select_related("unit").get(id=slot_id, unit__fase=fase)
    except ObjectDoesNotExist as exc:
        raise SlotOverrideError("Slot no valid per aquesta fase.") from exc
    if slot.locked:
        raise SlotOverrideError("Aquest slot esta bloquejat.")
    try:
        inscripcio = Inscripcio.objects.select_related("equip").get(id=inscripcio_id, competicio=fase.competicio)
    except ObjectDoesNotExist as exc:
        raise SlotOverrideError("Inscripcio no valida per aquesta competicio.") from exc
    subject_ref = ("inscripcio", int(inscripcio.id))
    if subject_ref in active_subject_refs_for_phase(fase, exclude_slot_id=slot.id):
        raise SlotOverrideError("Aquesta inscripcio ja esta assignada a una altra placa activa.")

    excluded = InscripcioAparellExclusio.objects.filter(
        inscripcio=inscripcio,
        comp_aparell=fase.comp_aparell,
    ).exists()
    source_row = {
        "participant": str(inscripcio.nom_i_cognoms or "").strip(),
        "entitat": str(inscripcio.entitat or "").strip(),
        "categoria": str(inscripcio.categoria or "").strip(),
        "subcategoria": str(inscripcio.subcategoria or "").strip(),
        "manual_assignment": {
            "from_workspace": True,
            "excluded_from_app": bool(excluded),
        },
    }
    equip = getattr(inscripcio, "equip", None)
    if equip is not None:
        source_row["equip_nom"] = str(getattr(equip, "nom", "") or "").strip()

    slot.subject_kind = "inscripcio"
    slot.subject_id = int(inscripcio.id)
    slot.status = ProgramUnitSlot.Status.MANUAL
    slot.source_classificacio = None
    slot.source_particio_key = str(slot.source_particio_key or slot.unit.partition_key or "global").strip() or "global"
    slot.source_position = None
    slot.source_score = None
    slot.source_row = _slot_metadata_source_row(
        source_row,
        override_type="manual_inscripcio",
        previous_slot=slot,
    )
    slot.full_clean()
    slot.save(update_fields=[
        "subject_kind",
        "subject_id",
        "status",
        "source_classificacio",
        "source_particio_key",
        "source_position",
        "source_score",
        "source_row",
        "updated_at",
    ])
    return slot


def mark_slot_withdrawn(fase: CompeticioAparellFase, slot_id: int) -> ProgramUnitSlot:
    try:
        slot = ProgramUnitSlot.objects.get(id=slot_id, unit__fase=fase)
    except ObjectDoesNotExist as exc:
        raise SlotOverrideError("Slot no valid per aquesta fase.") from exc
    if slot.locked:
        raise SlotOverrideError("Aquest slot esta bloquejat.")
    if not slot.subject_id:
        raise SlotOverrideError("No es pot marcar baixa en un slot buit.")
    slot.status = ProgramUnitSlot.Status.WITHDRAWN
    slot.source_row = _slot_metadata_source_row(
        slot.source_row if isinstance(slot.source_row, dict) else {},
        override_type="withdrawn",
    )
    slot.full_clean()
    slot.save(update_fields=["status", "source_row", "updated_at"])
    return slot


def clear_slot_assignment(fase: CompeticioAparellFase, slot_id: int) -> ProgramUnitSlot:
    try:
        slot = ProgramUnitSlot.objects.get(id=slot_id, unit__fase=fase)
    except ObjectDoesNotExist as exc:
        raise SlotOverrideError("Slot no valid per aquesta fase.") from exc
    if slot.locked:
        raise SlotOverrideError("Aquest slot esta bloquejat.")
    slot.subject_kind = ""
    slot.subject_id = None
    slot.status = ProgramUnitSlot.Status.EMPTY
    slot.source_classificacio = None
    slot.source_particio_key = ""
    slot.source_position = None
    slot.source_score = None
    slot.source_row = {}
    slot.full_clean()
    slot.save(update_fields=[
        "subject_kind",
        "subject_id",
        "status",
        "source_classificacio",
        "source_particio_key",
        "source_position",
        "source_score",
        "source_row",
        "updated_at",
    ])
    return slot


def delete_program_slot(fase: CompeticioAparellFase, slot_id: int) -> tuple[ProgramUnit, int]:
    try:
        slot = ProgramUnitSlot.objects.select_related("unit").get(id=slot_id, unit__fase=fase)
    except ObjectDoesNotExist as exc:
        raise SlotOverrideError("Slot no valid per aquesta fase.") from exc
    if slot.locked:
        raise SlotOverrideError("Aquest slot esta bloquejat.")
    unit = slot.unit
    ordre = int(slot.ordre or slot.slot_index or 0)
    with transaction.atomic():
        slot.delete()
        unit.capacity = unit.slots.count()
        unit.save(update_fields=["capacity", "updated_at"])
    return unit, ordre
