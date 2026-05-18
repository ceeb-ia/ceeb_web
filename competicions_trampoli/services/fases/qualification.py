from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ...models.classificacions import ClassificacioConfig
from ...models.competicio import (
    CompeticioAparellFase,
    FasePartitionState,
    ProgramUnit,
    ProgramUnitSlot,
    QualificationRun,
)
from ...services.classificacions.compute import compute_classificacio
from ...services.classificacions.phase_scope import (
    PHASE_SCOPE_PER_APP,
    normalize_phase_scope_payload,
)
from .program_units import SlotSubject, create_program_unit_with_empty_slots, fill_program_unit_slots


SOURCE_PHASE_READY_STATES = {
    CompeticioAparellFase.Estat.CONFIRMED,
    CompeticioAparellFase.Estat.CLOSED,
}
TIE_POLICIES = {"classification_order", "include_all_at_cut", "manual_decision"}


class QualificationError(ValueError):
    pass


@dataclass(frozen=True)
class QualificationCandidate:
    source_particio_key: str
    source_row: dict
    subject_kind: str
    subject_id: int
    status: str
    source_position: int | None = None
    source_score: Decimal | None = None

    def to_slot_subject(self, classificacio_id: int) -> SlotSubject:
        return SlotSubject(
            subject_kind=self.subject_kind,
            subject_id=self.subject_id,
            status=self.status,
            source_classificacio_id=classificacio_id,
            source_particio_key=self.source_particio_key,
            source_position=self.source_position,
            source_score=self.source_score,
            source_row=self.source_row,
        )


@dataclass(frozen=True)
class QualificationUnitPreview:
    label: str
    partition_key: str
    capacity: int
    candidates: list[QualificationCandidate] = field(default_factory=list)


@dataclass(frozen=True)
class QualificationPreview:
    fase: CompeticioAparellFase
    classificacio: ClassificacioConfig
    source_phase: CompeticioAparellFase | None
    snapshot_hash: str
    units: list[QualificationUnitPreview]
    warnings: list[str] = field(default_factory=list)
    partition_warnings: dict[str, list[str]] = field(default_factory=dict)

    @property
    def candidate_count(self) -> int:
        return sum(len(unit.candidates) for unit in self.units)

    @property
    def reserve_count(self) -> int:
        return sum(
            1
            for unit in self.units
            for candidate in unit.candidates
            if candidate.status == ProgramUnitSlot.Status.RESERVE
        )

    @property
    def pending_decision_count(self) -> int:
        return sum(
            1
            for unit in self.units
            for candidate in unit.candidates
            if candidate.status == ProgramUnitSlot.Status.PENDING_DECISION
        )

    @property
    def slot_count(self) -> int:
        return sum(unit.capacity for unit in self.units)

    def summary(self) -> dict:
        return {
            "units": len(self.units),
            "slots": self.slot_count,
            "candidates": self.candidate_count,
            "reserves": self.reserve_count,
            "pending_decision": self.pending_decision_count,
            "warnings": len(self.warnings),
            "partitions": len({unit.partition_key for unit in self.units}),
        }

    def payload(self) -> dict:
        return {
            "summary": self.summary(),
            "units": [
                {
                    "label": unit.label,
                    "partition_key": unit.partition_key,
                    "capacity": unit.capacity,
                    "candidates": [
                        {
                            "subject_kind": candidate.subject_kind,
                            "subject_id": candidate.subject_id,
                            "status": candidate.status,
                            "source_particio_key": candidate.source_particio_key,
                            "source_position": candidate.source_position,
                            "source_score": str(candidate.source_score) if candidate.source_score is not None else None,
                            "source_row": candidate.source_row,
                        }
                        for candidate in unit.candidates
                    ],
                }
                for unit in self.units
            ],
            "partition_warnings": self.partition_warnings,
        }


def _positive_int(value, *, default=0) -> int:
    try:
        clean = int(value)
    except (TypeError, ValueError):
        return default
    return clean if clean > 0 else default


def _decimal_or_none(value) -> Decimal | None:
    try:
        if value in (None, ""):
            return None
        return Decimal(str(value))
    except Exception:
        return None


def _phase_config(fase: CompeticioAparellFase) -> tuple[dict, dict]:
    config = fase.config if isinstance(fase.config, dict) else {}
    source = config.get("source") if isinstance(config.get("source"), dict) else {}
    cut = config.get("cut") if isinstance(config.get("cut"), dict) else {}
    return source, cut


def _source_classificacio(fase: CompeticioAparellFase) -> ClassificacioConfig:
    source, _cut = _phase_config(fase)
    classificacio_id = _positive_int(source.get("classificacio_id") or source.get("id"))
    if not classificacio_id:
        raise QualificationError("Cal configurar una classificacio origen abans de generar la fase.")
    classificacio = (
        ClassificacioConfig.objects
        .filter(competicio=fase.competicio, id=classificacio_id, activa=True)
        .first()
    )
    if classificacio is None:
        raise QualificationError("La classificacio origen configurada no existeix o no esta activa.")
    return classificacio


def _source_phase_for_classificacio(
    classificacio: ClassificacioConfig,
    *,
    comp_aparell_id: int,
) -> CompeticioAparellFase | None:
    schema = classificacio.schema if isinstance(classificacio.schema, dict) else {}
    scope = normalize_phase_scope_payload(schema.get("scope") or {})
    phase_id = None
    if scope.get("mode") == PHASE_SCOPE_PER_APP:
        app_scope = (scope.get("apps") or {}).get(str(comp_aparell_id)) or {}
        phase_id = _positive_int(app_scope.get("fase_id"))
    else:
        phase_id = _positive_int(scope.get("fase_id"))
    if not phase_id:
        return None
    return (
        CompeticioAparellFase.objects
        .filter(competicio=classificacio.competicio, id=phase_id)
        .select_related("comp_aparell")
        .first()
    )


def _source_phase_warning(source_phase: CompeticioAparellFase | None) -> str:
    if source_phase is None or source_phase.estat in SOURCE_PHASE_READY_STATES:
        return ""
    return (
        f"La fase origen '{source_phase.nom}' encara esta en estat "
        f"'{source_phase.estat}'. Cal confirmar-la o tancar-la abans de congelar el tall."
    )


def _subject_from_row(row: dict) -> tuple[str, int] | None:
    inscripcio_id = _positive_int(row.get("inscripcio_id"))
    if inscripcio_id:
        return "inscripcio", inscripcio_id
    team_subject_id = _positive_int(row.get("team_subject_id"))
    if team_subject_id:
        return "team_unit", team_subject_id
    equip_id = _positive_int(row.get("equip_id") or row.get("team_id"))
    if equip_id:
        return "equip", equip_id
    return None


def _clean_source_row(row: dict) -> dict:
    out = {}
    for key, value in (row or {}).items():
        if key == "source_row":
            continue
        try:
            json.dumps(value)
            out[key] = value
        except TypeError:
            out[key] = str(value)
    return out


def _candidate_from_row(
    row: dict,
    *,
    particio_key: str,
    status: str,
) -> QualificationCandidate | None:
    subject = _subject_from_row(row)
    if subject is None:
        return None
    subject_kind, subject_id = subject
    return QualificationCandidate(
        source_particio_key=particio_key,
        source_row=_clean_source_row(row),
        subject_kind=subject_kind,
        subject_id=subject_id,
        status=status,
        source_position=_positive_int(row.get("posicio")) or None,
        source_score=_decimal_or_none(row.get("punts", row.get("score"))),
    )


def _rows_for_cut(result: dict, partition_mode: str) -> list[tuple[str, list[dict]]]:
    if partition_mode == "source_partitions":
        return [(str(key or "global"), list(rows or [])) for key, rows in (result or {}).items()]
    if "global" in (result or {}):
        return [("global", list((result or {}).get("global") or []))]
    rows = []
    for part_rows in (result or {}).values():
        rows.extend(list(part_rows or []))
    rows.sort(key=lambda row: (_positive_int(row.get("posicio"), default=10**9), -float(row.get("punts", row.get("score")) or 0)))
    return [("global", rows)]


def _format_unit_label(template: str, *, fase: CompeticioAparellFase, partition_key: str, index: int, total: int) -> str:
    particio = partition_key if partition_key != "global" else "Global"
    try:
        label = template.format(fase=fase.nom, particio=particio, index=index, total=total)
    except Exception:
        label = ""
    label = str(label or "").strip()
    if not label:
        label = f"{fase.nom} - {particio}"
    if total > 1:
        label = f"{label} {index}"
    return label


def _snapshot_hash(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _add_partition_warning(warnings: list[str], partition_warnings: dict[str, list[str]], partition_key: str, message: str) -> None:
    text = f"{partition_key}: {message}"
    warnings.append(text)
    partition_warnings.setdefault(partition_key, []).append(message)


def _position_at_cut(rows: list[dict], qualifiers_count: int):
    if not rows or qualifiers_count <= 0 or len(rows) < qualifiers_count:
        return None
    return rows[qualifiers_count - 1].get("posicio")


def _select_rows_for_tie_policy(
    rows: list[dict],
    *,
    qualifiers_count: int,
    reserve_count: int,
    tie_policy: str,
    partition_key: str,
    warnings: list[str],
    partition_warnings: dict[str, list[str]],
) -> list[tuple[dict, str]]:
    if not rows:
        return []
    cut_position = _position_at_cut(rows, qualifiers_count)
    tied_at_cut = (
        cut_position is not None
        and len(rows) > qualifiers_count
        and rows[qualifiers_count].get("posicio") == cut_position
    )
    if tied_at_cut:
        _add_partition_warning(warnings, partition_warnings, partition_key, "hi ha empat real a la zona de tall.")

    if tie_policy == "include_all_at_cut" and tied_at_cut:
        filled_rows = [row for row in rows if row.get("posicio") is not None and row.get("posicio") <= cut_position]
        reserve_rows = rows[len(filled_rows):len(filled_rows) + reserve_count]
        return (
            [(row, ProgramUnitSlot.Status.FILLED) for row in filled_rows]
            + [(row, ProgramUnitSlot.Status.RESERVE) for row in reserve_rows]
        )

    if tie_policy == "manual_decision" and tied_at_cut:
        filled_rows = [row for row in rows if row.get("posicio") is not None and row.get("posicio") < cut_position]
        pending_rows = [row for row in rows if row.get("posicio") == cut_position]
        after_tie_offset = len(filled_rows) + len(pending_rows)
        reserve_rows = rows[after_tie_offset:after_tie_offset + reserve_count]
        return (
            [(row, ProgramUnitSlot.Status.FILLED) for row in filled_rows]
            + [(row, ProgramUnitSlot.Status.PENDING_DECISION) for row in pending_rows]
            + [(row, ProgramUnitSlot.Status.RESERVE) for row in reserve_rows]
        )

    selected = []
    for index, row in enumerate(rows[:qualifiers_count + reserve_count], start=1):
        status = ProgramUnitSlot.Status.FILLED if index <= qualifiers_count else ProgramUnitSlot.Status.RESERVE
        selected.append((row, status))
    return selected


def _build_units_for_partition(
    *,
    fase: CompeticioAparellFase,
    classificacio_id: int,
    partition_key: str,
    rows: list[dict],
    qualifiers_count: int,
    reserve_count: int,
    unit_capacity: int,
    unit_name_template: str,
    tie_policy: str,
    warnings: list[str],
    partition_warnings: dict[str, list[str]],
) -> list[QualificationUnitPreview]:
    if not rows:
        _add_partition_warning(
            warnings,
            partition_warnings,
            partition_key,
            "la classificacio origen no te participants disponibles.",
        )

    selected = []
    unsupported = 0
    selected_rows = _select_rows_for_tie_policy(
        rows,
        qualifiers_count=qualifiers_count,
        reserve_count=reserve_count,
        tie_policy=tie_policy,
        partition_key=partition_key,
        warnings=warnings,
        partition_warnings=partition_warnings,
    )
    for row, status in selected_rows:
        candidate = _candidate_from_row(row, particio_key=partition_key, status=status)
        if candidate is None:
            unsupported += 1
            continue
        selected.append(candidate)
    if unsupported:
        _add_partition_warning(
            warnings,
            partition_warnings,
            partition_key,
            f"{unsupported} fila/es no tenen subjecte puntuable reconegut.",
        )
    if len(rows) < qualifiers_count:
        _add_partition_warning(
            warnings,
            partition_warnings,
            partition_key,
            f"nomes hi ha {len(rows)} participants disponibles de {qualifiers_count} places configurades.",
        )

    slot_target = max(qualifiers_count + reserve_count, len(selected), 1)
    unit_count = (slot_target + unit_capacity - 1) // unit_capacity
    units = []
    for offset in range(0, slot_target, unit_capacity):
        capacity = min(unit_capacity, slot_target - offset)
        index = (offset // unit_capacity) + 1
        label = _format_unit_label(
            unit_name_template,
            fase=fase,
            partition_key=partition_key,
            index=index,
            total=unit_count,
        )
        units.append(
            QualificationUnitPreview(
                label=label,
                partition_key=partition_key,
                capacity=capacity,
                candidates=selected[offset:offset + capacity],
            )
        )
    return units


def preview_qualification(fase: CompeticioAparellFase) -> QualificationPreview:
    classificacio = _source_classificacio(fase)
    source_phase = _source_phase_for_classificacio(classificacio, comp_aparell_id=fase.comp_aparell_id)
    _source, cut = _phase_config(fase)
    qualifiers_count = _positive_int(cut.get("qualifiers_count"), default=0)
    reserve_count = _positive_int(cut.get("reserve_count"), default=0)
    unit_capacity = _positive_int(cut.get("unit_capacity"), default=qualifiers_count + reserve_count or 1)
    partition_mode = str(cut.get("partition_mode") or "global").strip() or "global"
    unit_name_template = str(cut.get("unit_name_template") or "{fase} - {particio}").strip()
    tie_policy = str(cut.get("tie_policy") or "classification_order").strip() or "classification_order"
    if qualifiers_count <= 0:
        raise QualificationError("Cal configurar un nombre positiu de classificats.")
    if partition_mode not in {"global", "source_partitions"}:
        raise QualificationError("El mode de particio del tall no es valid.")
    if tie_policy not in TIE_POLICIES:
        raise QualificationError("La politica d'empats del tall no es valida.")

    warnings = []
    partition_warnings = {}
    source_warning = _source_phase_warning(source_phase)
    if source_warning:
        warnings.append(source_warning)
    result = compute_classificacio(fase.competicio, classificacio)
    units = []
    for partition_key, rows in _rows_for_cut(result, partition_mode):
        units.extend(
            _build_units_for_partition(
                fase=fase,
                classificacio_id=classificacio.id,
                partition_key=partition_key,
                rows=rows,
                qualifiers_count=qualifiers_count,
                reserve_count=reserve_count,
                unit_capacity=unit_capacity,
                unit_name_template=unit_name_template,
                tie_policy=tie_policy,
                warnings=warnings,
                partition_warnings=partition_warnings,
            )
        )

    snapshot_payload = {
        "classificacio_id": classificacio.id,
        "classificacio_updated_at": classificacio.updated_at.isoformat() if classificacio.updated_at else "",
        "source_phase_id": source_phase.id if source_phase else None,
        "cut": cut,
        "units": QualificationPreview(
            fase=fase,
            classificacio=classificacio,
            source_phase=source_phase,
            snapshot_hash="",
            units=units,
            warnings=warnings,
            partition_warnings=partition_warnings,
        ).payload()["units"],
    }
    return QualificationPreview(
        fase=fase,
        classificacio=classificacio,
        source_phase=source_phase,
        snapshot_hash=_snapshot_hash(snapshot_payload),
        units=units,
        warnings=warnings,
        partition_warnings=partition_warnings,
    )


def _create_run(preview: QualificationPreview, *, status: str, applied_at=None) -> QualificationRun:
    return QualificationRun.objects.create(
        fase=preview.fase,
        source_classificacio=preview.classificacio,
        source_phase=preview.source_phase,
        status=status,
        snapshot_hash=preview.snapshot_hash,
        summary=preview.summary(),
        warnings=list(preview.warnings),
        payload=preview.payload(),
        applied_at=applied_at,
    )


def record_qualification_preview(fase: CompeticioAparellFase) -> QualificationPreview:
    preview = preview_qualification(fase)
    _create_run(preview, status=QualificationRun.Status.PREVIEWED)
    return preview


def _partition_keys_for_preview(preview: QualificationPreview) -> list[str]:
    keys = []
    seen = set()
    for unit in preview.units:
        key = str(unit.partition_key or "global").strip() or "global"
        if key not in seen:
            keys.append(key)
            seen.add(key)
    return keys


def _sync_partition_states(preview: QualificationPreview, run: QualificationRun) -> None:
    keys = _partition_keys_for_preview(preview)
    for partition_key in keys:
        state, _created = FasePartitionState.objects.get_or_create(
            fase=preview.fase,
            partition_key=partition_key,
            defaults={
                "status": FasePartitionState.Status.GENERATED,
                "qualification_run": run,
                "source_snapshot_hash": preview.snapshot_hash,
                "warnings": list(preview.partition_warnings.get(partition_key, [])),
            },
        )
        state.status = FasePartitionState.Status.GENERATED
        state.qualification_run = run
        state.source_snapshot_hash = preview.snapshot_hash
        state.warnings = list(preview.partition_warnings.get(partition_key, []))
        state.confirmed_at = None
        state.save(update_fields=[
            "status",
            "qualification_run",
            "source_snapshot_hash",
            "warnings",
            "confirmed_at",
            "updated_at",
        ])
    FasePartitionState.objects.filter(fase=preview.fase).exclude(partition_key__in=keys).update(
        status=FasePartitionState.Status.STALE,
        qualification_run=run,
        source_snapshot_hash=preview.snapshot_hash,
    )


def _protected_slots_exist(fase: CompeticioAparellFase) -> bool:
    return ProgramUnitSlot.objects.filter(unit__fase=fase, locked=True).exists() or ProgramUnitSlot.objects.filter(
        unit__fase=fase,
        status=ProgramUnitSlot.Status.MANUAL,
    ).exists()


def apply_qualification(
    fase: CompeticioAparellFase,
    *,
    replace_existing: bool = False,
    allow_replace_protected: bool = False,
) -> QualificationPreview:
    preview = preview_qualification(fase)
    source_warning = _source_phase_warning(preview.source_phase)
    if source_warning:
        raise QualificationError(source_warning)
    if fase.program_units.exists() and not replace_existing:
        raise QualificationError("La fase desti ja te unitats. Revisa-les o buida-les abans de generar el tall.")

    with transaction.atomic():
        if replace_existing:
            if _protected_slots_exist(fase) and not allow_replace_protected:
                raise QualificationError("No es poden sobreescriure slots bloquejats o manuals.")
            fase.program_units.all().delete()

        now = timezone.now()
        run = _create_run(preview, status=QualificationRun.Status.APPLIED, applied_at=now)
        for order, unit_preview in enumerate(preview.units, start=1):
            unit = create_program_unit_with_empty_slots(
                fase=fase,
                nom=unit_preview.label,
                capacity=unit_preview.capacity,
                tipus=ProgramUnit.Tipus.BLOCK,
                ordre=order,
                partition_key=unit_preview.partition_key,
                partition_values={"key": unit_preview.partition_key},
                status=ProgramUnit.Status.GENERATED,
                metadata={
                    "qualification_snapshot_hash": preview.snapshot_hash,
                    "qualification_run_id": run.id,
                    "source_classificacio_id": preview.classificacio.id,
                },
            )
            fill_program_unit_slots(
                unit,
                [
                    candidate.to_slot_subject(preview.classificacio.id)
                    for candidate in unit_preview.candidates
                ],
            )

        _sync_partition_states(preview, run)
        config = fase.config if isinstance(fase.config, dict) else {}
        config["qualification"] = {
            "run_id": run.id,
            "source_classificacio_id": preview.classificacio.id,
            "source_phase_id": preview.source_phase.id if preview.source_phase else None,
            "snapshot_hash": preview.snapshot_hash,
            "generated_at": now.isoformat(),
            "summary": preview.summary(),
            "warnings": list(preview.warnings),
            "partitions": _partition_keys_for_preview(preview),
            "stale": False,
        }
        fase.config = config
        fase.estat = CompeticioAparellFase.Estat.GENERATED
        fase.save(update_fields=["config", "estat", "updated_at"])
    return preview


def qualification_is_stale(fase: CompeticioAparellFase) -> bool:
    config = fase.config if isinstance(fase.config, dict) else {}
    qualification = config.get("qualification") if isinstance(config.get("qualification"), dict) else {}
    stored_hash = str(qualification.get("snapshot_hash") or "").strip()
    if not stored_hash:
        return False
    try:
        return preview_qualification(fase).snapshot_hash != stored_hash
    except QualificationError:
        return True


def mark_qualification_stale_if_needed(fase: CompeticioAparellFase) -> bool:
    if not qualification_is_stale(fase):
        return False
    config = fase.config if isinstance(fase.config, dict) else {}
    qualification = config.get("qualification") if isinstance(config.get("qualification"), dict) else {}
    stored_hash = str(qualification.get("snapshot_hash") or "").strip()
    with transaction.atomic():
        if stored_hash:
            QualificationRun.objects.filter(
                fase=fase,
                snapshot_hash=stored_hash,
                status=QualificationRun.Status.APPLIED,
            ).update(status=QualificationRun.Status.STALE)
        FasePartitionState.objects.filter(fase=fase).update(status=FasePartitionState.Status.STALE)
        qualification["stale"] = True
        config["qualification"] = qualification
        fase.config = config
        fase.estat = CompeticioAparellFase.Estat.STALE
        fase.save(update_fields=["config", "estat", "updated_at"])
    return True


def confirm_qualification_partition(fase: CompeticioAparellFase, partition_key: str) -> FasePartitionState:
    key = str(partition_key or "").strip() or "global"
    if qualification_is_stale(fase):
        mark_qualification_stale_if_needed(fase)
        raise QualificationError("La font ha canviat. Regenera la proposta abans de confirmar particions.")

    with transaction.atomic():
        try:
            state = FasePartitionState.objects.select_for_update().get(fase=fase, partition_key=key)
        except FasePartitionState.DoesNotExist as exc:
            raise QualificationError("Aquesta particio encara no esta generada.") from exc
        if state.status == FasePartitionState.Status.STALE:
            raise QualificationError("Aquesta particio esta obsoleta. Regenera la proposta abans de confirmar-la.")
        state.status = FasePartitionState.Status.CONFIRMED
        state.confirmed_at = timezone.now()
        state.save(update_fields=["status", "confirmed_at", "updated_at"])
        ProgramUnit.objects.filter(fase=fase, partition_key=key).update(status=ProgramUnit.Status.CONFIRMED)
        remaining_generated = FasePartitionState.objects.filter(
            fase=fase,
            status=FasePartitionState.Status.GENERATED,
        ).exists()
        stale_exists = FasePartitionState.objects.filter(
            fase=fase,
            status=FasePartitionState.Status.STALE,
        ).exists()
        if stale_exists:
            fase.estat = CompeticioAparellFase.Estat.STALE
        elif remaining_generated:
            fase.estat = CompeticioAparellFase.Estat.PARTIALLY_CONFIRMED
        else:
            fase.estat = CompeticioAparellFase.Estat.CONFIRMED
        fase.save(update_fields=["estat", "updated_at"])
    return state


def preview_as_dict(preview: QualificationPreview) -> dict:
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
                "candidates": list(unit.candidates),
            }
            for unit in preview.units
        ],
    }


__all__ = [
    "QualificationError",
    "QualificationPreview",
    "QualificationUnitPreview",
    "apply_qualification",
    "confirm_qualification_partition",
    "mark_qualification_stale_if_needed",
    "preview_as_dict",
    "preview_qualification",
    "qualification_is_stale",
    "record_qualification_preview",
]
