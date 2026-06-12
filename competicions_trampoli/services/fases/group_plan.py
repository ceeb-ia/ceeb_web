from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from ...models.competicio import CompeticioAparellFase, ProgramUnit, ProgramUnitSlot
from ...services.classificacions.compute import compute_classificacio
from .program_units import create_program_unit_with_empty_slots
from .qualification import (
    QualificationError,
    QualificationCandidate,
    TIE_POLICIES,
    _build_units_for_partition,
    _chunks_by_strategy,
    _format_unit_label,
    _partition_keys_for_preview,
    _phase_config,
    _positive_int,
    _rows_for_cut,
    _select_candidates_for_partition,
    _slot_order_candidates,
    _snapshot_hash,
    _source_classificacio,
    _source_phase_for_classificacio,
    _source_phase_warning,
    validate_classificacio_not_circular_source,
)


@dataclass(frozen=True)
class GroupPlanUnitPreview:
    label: str
    partition_key: str
    capacity: int
    order: int
    partition_values: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    planned_candidates: list[QualificationCandidate] = field(default_factory=list)


@dataclass(frozen=True)
class GroupPlanPreview:
    fase: CompeticioAparellFase
    classificacio: object
    source_phase: CompeticioAparellFase | None
    snapshot_hash: str
    units: list[GroupPlanUnitPreview]
    warnings: list[str] = field(default_factory=list)
    partition_warnings: dict[str, list[str]] = field(default_factory=dict)
    group_config: dict = field(default_factory=dict)

    @property
    def slot_count(self) -> int:
        return sum(unit.capacity for unit in self.units)

    def summary(self) -> dict:
        return {
            "units": len(self.units),
            "slots": self.slot_count,
            "warnings": len(self.warnings),
            "partitions": len({unit.partition_key for unit in self.units}),
        }

    def payload(self) -> dict:
        return {
            "summary": self.summary(),
            "group_config": dict(self.group_config),
            "units": [
                {
                    "label": unit.label,
                    "partition_key": unit.partition_key,
                    "capacity": unit.capacity,
                    "order": unit.order,
                    "partition_values": dict(unit.partition_values),
                    "metadata": dict(unit.metadata),
                    "planned_candidates": [
                        {
                            "subject_kind": candidate.subject_kind,
                            "subject_id": candidate.subject_id,
                            "status": candidate.status,
                            "source_particio_key": candidate.source_particio_key,
                            "source_position": candidate.source_position,
                            "source_score": str(candidate.source_score) if candidate.source_score is not None else None,
                            "source_row": candidate.source_row,
                        }
                        for candidate in unit.planned_candidates
                    ],
                }
                for unit in self.units
            ],
            "partition_warnings": self.partition_warnings,
        }


def _group_plan_config(cut: dict, settings: dict | None = None) -> dict:
    settings = settings if isinstance(settings, dict) else {}
    qualifiers_count = _positive_int(cut.get("qualifiers_count"), default=0)
    reserve_count = _positive_int(cut.get("reserve_count"), default=0)
    split_mode = str(settings.get("split_mode") or "by_capacity").strip() or "by_capacity"
    units_per_partition = _positive_int(settings.get("units_per_partition"), default=1)
    unit_capacity = _positive_int(
        settings.get("unit_capacity") or cut.get("unit_capacity"),
        default=qualifiers_count or 1,
    )
    partition_mode = str(cut.get("partition_mode") or "global").strip() or "global"
    unit_name_template = str(
        settings.get("unit_name_template") or cut.get("unit_name_template") or "{fase} - {particio}"
    ).strip()
    tie_policy = str(cut.get("tie_policy") or "classification_order").strip() or "classification_order"
    formation_strategy = str(settings.get("formation_strategy") or "classification_order").strip() or "classification_order"
    if qualifiers_count <= 0:
        raise QualificationError("Cal configurar un nombre positiu de classificats.")
    if partition_mode not in {"global", "source_partitions"}:
        raise QualificationError("El mode de particio del tall no es valid.")
    if tie_policy not in TIE_POLICIES:
        raise QualificationError("La politica d'empats del tall no es valida.")
    if split_mode not in {"by_count", "by_capacity"}:
        raise QualificationError("El mode de creacio de grups no es valid.")
    if formation_strategy not in {"classification_order", "serpentine", "first_last", "random"}:
        raise QualificationError("El criteri de repartiment de grups no es valid.")
    return {
        "strategy": split_mode,
        "split_mode": split_mode,
        "partition_mode": partition_mode,
        "qualifiers_count": qualifiers_count,
        "reserve_count": reserve_count,
        "units_per_partition": units_per_partition,
        "unit_capacity": unit_capacity,
        "unit_name_template": unit_name_template,
        "formation_strategy": formation_strategy,
        "tie_policy": tie_policy,
        "hooks": {
            "formation": formation_strategy,
            "fusion_groups": [],
            "partition_overrides": {},
        },
    }


def structural_cut_signature(cut: dict) -> str:
    payload = {
        "mode": (cut or {}).get("mode"),
        "qualifiers_count": _positive_int((cut or {}).get("qualifiers_count"), default=0),
        "reserve_count": _positive_int((cut or {}).get("reserve_count"), default=0),
        "partition_mode": str((cut or {}).get("partition_mode") or "global").strip() or "global",
        "tie_policy": str((cut or {}).get("tie_policy") or "classification_order").strip() or "classification_order",
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_units_by_count(
    *,
    fase: CompeticioAparellFase,
    partition_key: str,
    rows: list[dict],
    qualifiers_count: int,
    reserve_count: int,
    units_per_partition: int,
    unit_name_template: str,
    tie_policy: str,
    formation_strategy: str,
    warnings: list[str],
    partition_warnings: dict[str, list[str]],
) -> list:
    selected = _select_candidates_for_partition(
        partition_key=partition_key,
        rows=rows,
        qualifiers_count=qualifiers_count,
        reserve_count=reserve_count,
        tie_policy=tie_policy,
        warnings=warnings,
        partition_warnings=partition_warnings,
    )
    competitive = [
        candidate for candidate in selected
        if candidate.status != ProgramUnitSlot.Status.RESERVE
    ]
    unit_count = max(1, int(units_per_partition or 1))
    slot_target = max(qualifiers_count, len(competitive), unit_count)
    base = slot_target // unit_count
    remainder = slot_target % unit_count
    capacities = [
        base + (1 if index <= remainder else 0)
        for index in range(1, unit_count + 1)
    ]
    chunks, unassigned = _chunks_by_strategy(
        competitive,
        capacities,
        strategy=formation_strategy,
    )
    units = []
    for index, (capacity, chunk) in enumerate(zip(capacities, chunks), start=1):
        label = _format_unit_label(
            unit_name_template,
            fase=fase,
            partition_key=partition_key,
            index=index,
            total=unit_count,
        )
        units.append(
            GroupPlanUnitPreview(
                label=label,
                partition_key=partition_key,
                capacity=capacity,
                order=0,
                partition_values={"key": partition_key},
                planned_candidates=_slot_order_candidates(chunk, strategy=formation_strategy),
            )
        )
    if unassigned:
        _add_partition_warning(
            warnings,
            partition_warnings,
            partition_key,
            f"no hi ha prou slots per assignar {unassigned} classificat/s o reserva/es.",
        )
    return units


def preview_group_plan(fase: CompeticioAparellFase) -> GroupPlanPreview:
    classificacio = _source_classificacio(fase)
    source_phase = _source_phase_for_classificacio(classificacio, comp_aparell_id=fase.comp_aparell_id)
    validate_classificacio_not_circular_source(fase, classificacio, source_phase=source_phase)
    _source, cut = _phase_config(fase)
    config = fase.config if isinstance(fase.config, dict) else {}
    settings = config.get("group_plan_settings") if isinstance(config.get("group_plan_settings"), dict) else {}
    group_config = _group_plan_config(cut, settings)

    warnings = []
    partition_warnings = {}
    source_warning = _source_phase_warning(source_phase)
    if source_warning:
        warnings.append(source_warning)

    result = compute_classificacio(fase.competicio, classificacio)
    units = []
    order = 1
    for partition_key, rows in _rows_for_cut(result, group_config["partition_mode"]):
        if group_config["split_mode"] == "by_count":
            partition_units = _build_units_by_count(
                fase=fase,
                partition_key=partition_key,
                rows=rows,
                qualifiers_count=group_config["qualifiers_count"],
                reserve_count=group_config["reserve_count"],
                units_per_partition=group_config["units_per_partition"],
                unit_name_template=group_config["unit_name_template"],
                tie_policy=group_config["tie_policy"],
                formation_strategy=group_config["formation_strategy"],
                warnings=warnings,
                partition_warnings=partition_warnings,
            )
        else:
            partition_units = _build_units_for_partition(
                fase=fase,
                classificacio_id=classificacio.id,
                partition_key=partition_key,
                rows=rows,
                qualifiers_count=group_config["qualifiers_count"],
                reserve_count=group_config["reserve_count"],
                unit_capacity=group_config["unit_capacity"],
                unit_name_template=group_config["unit_name_template"],
                tie_policy=group_config["tie_policy"],
                warnings=warnings,
                partition_warnings=partition_warnings,
                strategy=group_config["formation_strategy"],
            )
        for unit in partition_units:
            units.append(
                GroupPlanUnitPreview(
                    label=unit.label,
                    partition_key=unit.partition_key,
                    capacity=unit.capacity,
                    order=order,
                    partition_values={"key": unit.partition_key},
                    metadata={
                        "group_plan_strategy": group_config["strategy"],
                        "formation_strategy": group_config["formation_strategy"],
                        "group_index": order,
                        "source_classificacio_id": classificacio.id,
                    },
                    planned_candidates=list(getattr(unit, "planned_candidates", None) or getattr(unit, "candidates", [])),
                )
            )
            order += 1

    snapshot_payload = {
        "classificacio_id": classificacio.id,
        "classificacio_updated_at": classificacio.updated_at.isoformat() if classificacio.updated_at else "",
        "source_phase_id": source_phase.id if source_phase else None,
        "cut": cut,
        "group_config": group_config,
        "units": [
            {
                "label": unit.label,
                "partition_key": unit.partition_key,
                "capacity": unit.capacity,
                "order": unit.order,
                "planned_candidates": [
                    {
                        "subject_kind": candidate.subject_kind,
                        "subject_id": candidate.subject_id,
                        "status": candidate.status,
                        "source_particio_key": candidate.source_particio_key,
                        "source_position": candidate.source_position,
                        "source_score": str(candidate.source_score) if candidate.source_score is not None else None,
                        "source_row": candidate.source_row,
                    }
                    for candidate in unit.planned_candidates
                ],
            }
            for unit in units
        ],
    }
    return GroupPlanPreview(
        fase=fase,
        classificacio=classificacio,
        source_phase=source_phase,
        snapshot_hash=_snapshot_hash(snapshot_payload),
        units=units,
        warnings=warnings,
        partition_warnings=partition_warnings,
        group_config=group_config,
    )


def _protected_replacement_exists(fase: CompeticioAparellFase) -> bool:
    return (
        ProgramUnitSlot.objects.filter(unit__fase=fase, locked=True).exists()
        or ProgramUnitSlot.objects.filter(unit__fase=fase).exclude(status=ProgramUnitSlot.Status.EMPTY).exists()
        or ProgramUnit.objects.filter(
            fase=fase,
            status__in=[ProgramUnit.Status.CONFIRMED, ProgramUnit.Status.PUBLISHED],
        ).exists()
    )


def _seed_planned_slot_origins(
    unit: ProgramUnit,
    candidates: list[QualificationCandidate],
    *,
    classificacio_id: int,
) -> None:
    if not candidates:
        return
    slots = list(unit.slots.order_by("ordre", "slot_index", "id"))
    updates = []
    for slot, candidate in zip(slots, candidates):
        source_row = {"phase_seed_position": candidate.source_row.get("phase_seed_position") or candidate.source_position}
        slot.source_classificacio_id = classificacio_id
        slot.source_particio_key = candidate.source_particio_key
        slot.source_position = candidate.source_position
        slot.source_score = candidate.source_score
        slot.source_row = source_row
        updates.append(slot)
    if updates:
        ProgramUnitSlot.objects.bulk_update(
            updates,
            [
                "source_classificacio",
                "source_particio_key",
                "source_position",
                "source_score",
                "source_row",
                "updated_at",
            ],
            batch_size=500,
        )


def apply_group_plan(
    fase: CompeticioAparellFase,
    *,
    replace_existing: bool = False,
    allow_replace_protected: bool = False,
) -> GroupPlanPreview:
    preview = preview_group_plan(fase)
    has_units = fase.program_units.exists()
    if has_units and not replace_existing:
        raise QualificationError("La fase ja te unitats. Revisa-les o reemplaça el pla de grups.")
    if has_units and replace_existing and _protected_replacement_exists(fase) and not allow_replace_protected:
        raise QualificationError("No es poden reemplaçar unitats amb slots bloquejats, manuals o omplerts.")

    with transaction.atomic():
        if has_units:
            fase.program_units.all().delete()
        for unit_preview in preview.units:
            metadata = dict(unit_preview.metadata)
            metadata.update({
                "group_plan_snapshot_hash": preview.snapshot_hash,
                "source_classificacio_id": preview.classificacio.id,
            })
            unit = create_program_unit_with_empty_slots(
                fase=fase,
                nom=unit_preview.label,
                capacity=unit_preview.capacity,
                tipus=ProgramUnit.Tipus.BLOCK,
                ordre=unit_preview.order,
                partition_key=unit_preview.partition_key,
                partition_values=dict(unit_preview.partition_values),
                metadata=metadata,
                status=ProgramUnit.Status.GENERATED,
            )
            _seed_planned_slot_origins(
                unit,
                list(unit_preview.planned_candidates),
                classificacio_id=preview.classificacio.id,
            )

        config = fase.config if isinstance(fase.config, dict) else {}
        config["group_plan"] = {
            "source_classificacio_id": preview.classificacio.id,
            "source_phase_id": preview.source_phase.id if preview.source_phase else None,
            "snapshot_hash": preview.snapshot_hash,
            "cut_signature": structural_cut_signature((fase.config if isinstance(fase.config, dict) else {}).get("cut") or {}),
            "generated_at": timezone.now().isoformat(),
            "summary": preview.summary(),
            "warnings": list(preview.warnings),
            "partitions": _partition_keys_for_preview(preview),
            "stale": False,
            **preview.group_config,
        }
        fase.config = config
        fase.save(update_fields=["config", "updated_at"])
    return preview


def group_plan_as_dict(preview: GroupPlanPreview) -> dict:
    return {
        "classificacio": preview.classificacio,
        "source_phase": preview.source_phase,
        "summary": preview.summary(),
        "warnings": list(preview.warnings),
        "partition_warnings": dict(preview.partition_warnings),
        "units": [
            {
                "label": unit.label,
                "partition_key": unit.partition_key,
                "capacity": unit.capacity,
                "order": unit.order,
                "partition_values": dict(unit.partition_values),
                "planned_candidates": [
                    {
                        "source_position": candidate.source_position,
                        "source_particio_key": candidate.source_particio_key,
                        "source_score": str(candidate.source_score) if candidate.source_score is not None else None,
                    }
                    for candidate in unit.planned_candidates
                ],
            }
            for unit in preview.units
        ],
    }


__all__ = [
    "GroupPlanPreview",
    "GroupPlanUnitPreview",
    "apply_group_plan",
    "group_plan_as_dict",
    "preview_group_plan",
    "structural_cut_signature",
]
