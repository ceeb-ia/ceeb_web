from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from ...models.classificacions import ClassificacioConfig
from ...models.scoring import TeamCompetitiveSubject
from ...services.classificacions.filters import normalize_classificacio_equips_cfg, normalize_team_mode
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
from .labels import format_partition_label
from .program_units import SlotSubject, fill_program_unit_slots


SOURCE_PHASE_READY_STATES = {
    CompeticioAparellFase.Estat.CONFIRMED,
    CompeticioAparellFase.Estat.CLOSED,
}
CIRCULAR_SOURCE_PHASE_MESSAGE = (
    "La classificacio origen seleccionada calcula notes d'aquesta mateixa fase. "
    "Tria una classificacio d'una fase anterior o una classificacio global abans de congelar el tall."
)
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
    unit_id: int | None = None
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
    reserves: dict[str, list[QualificationCandidate]] = field(default_factory=dict)
    partition_hashes: dict[str, str] = field(default_factory=dict)
    scope: dict = field(default_factory=dict)

    @property
    def candidate_count(self) -> int:
        return sum(len(unit.candidates) for unit in self.units) + sum(
            len(items) for items in self.reserves.values()
        )

    @property
    def reserve_count(self) -> int:
        return sum(len(items) for items in self.reserves.values())

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
                    "unit_id": unit.unit_id,
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
            "reserves": {
                key: [
                    {
                        "subject_kind": candidate.subject_kind,
                        "subject_id": candidate.subject_id,
                        "status": candidate.status,
                        "source_particio_key": candidate.source_particio_key,
                        "source_position": candidate.source_position,
                        "source_score": str(candidate.source_score) if candidate.source_score is not None else None,
                        "source_row": candidate.source_row,
                    }
                    for candidate in items
                ]
                for key, items in self.reserves.items()
            },
            "partition_warnings": self.partition_warnings,
            "partition_hashes": dict(self.partition_hashes),
            "scope": dict(self.scope or {"kind": "global"}),
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
    validate_classificacio_subject_contract(fase, classificacio)
    return classificacio


def _classificacio_selected_app_ids(classificacio: ClassificacioConfig) -> set[int]:
    schema = classificacio.schema if isinstance(classificacio.schema, dict) else {}
    puntuacio = schema.get("puntuacio") if isinstance(schema.get("puntuacio"), dict) else {}
    aparells = puntuacio.get("aparells") if isinstance(puntuacio.get("aparells"), dict) else {}
    if str(aparells.get("mode") or "").strip().lower() != "seleccionar":
        return set()
    ids = set()
    for raw_id in aparells.get("ids") or []:
        clean = _positive_int(raw_id)
        if clean:
            ids.add(clean)
    return ids


def classificacio_is_native_team_source(classificacio: ClassificacioConfig) -> bool:
    schema = classificacio.schema if isinstance(classificacio.schema, dict) else {}
    equips_cfg = normalize_classificacio_equips_cfg(schema.get("equips") or {})
    return (
        str(classificacio.tipus or "").strip().lower() == "equips"
        and normalize_team_mode(equips_cfg.get("team_mode")) == "native_team"
    )


def classificacio_is_valid_source_for_phase(
    fase: CompeticioAparellFase,
    classificacio: ClassificacioConfig,
) -> bool:
    selected_app_ids = _classificacio_selected_app_ids(classificacio)
    if selected_app_ids and int(fase.comp_aparell_id) not in selected_app_ids:
        return False
    is_team_phase = bool(getattr(fase.comp_aparell, "is_team_competition_unit", False))
    if is_team_phase:
        return classificacio_is_native_team_source(classificacio)
    return not classificacio_is_native_team_source(classificacio)


def validate_classificacio_subject_contract(
    fase: CompeticioAparellFase,
    classificacio: ClassificacioConfig,
) -> None:
    selected_app_ids = _classificacio_selected_app_ids(classificacio)
    if selected_app_ids and int(fase.comp_aparell_id) not in selected_app_ids:
        raise QualificationError("La classificacio origen no calcula aquest aparell.")
    is_team_phase = bool(getattr(fase.comp_aparell, "is_team_competition_unit", False))
    if is_team_phase and not classificacio_is_native_team_source(classificacio):
        raise QualificationError(
            "Un aparell d'equip nomes pot congelar el tall des d'una classificacio d'equips nativa."
        )
    if not is_team_phase and classificacio_is_native_team_source(classificacio):
        raise QualificationError(
            "Una fase individual no pot congelar el tall des d'una classificacio nativa d'equip."
        )


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


def validate_classificacio_not_circular_source(
    fase: CompeticioAparellFase,
    classificacio: ClassificacioConfig,
    *,
    source_phase: CompeticioAparellFase | None = None,
) -> CompeticioAparellFase | None:
    resolved_source_phase = source_phase
    if resolved_source_phase is None:
        resolved_source_phase = _source_phase_for_classificacio(
            classificacio,
            comp_aparell_id=fase.comp_aparell_id,
        )
    if resolved_source_phase is not None and int(resolved_source_phase.id) == int(fase.id):
        raise QualificationError(CIRCULAR_SOURCE_PHASE_MESSAGE)
    return resolved_source_phase


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


def _team_subject_id_for_equip(fase: CompeticioAparellFase, equip_id: int) -> int | None:
    if not equip_id:
        return None
    subject = (
        TeamCompetitiveSubject.objects
        .filter(
            competicio=fase.competicio,
            comp_aparell=fase.comp_aparell,
            equip_id=equip_id,
        )
        .order_by("id")
        .first()
    )
    return int(subject.id) if subject is not None else None


def _subject_from_row_for_phase(fase: CompeticioAparellFase, row: dict) -> tuple[str, int] | None:
    is_team_phase = bool(getattr(fase.comp_aparell, "is_team_competition_unit", False))
    if is_team_phase:
        team_subject_id = _positive_int(row.get("team_subject_id") or row.get("subject_id"))
        if team_subject_id:
            exists = TeamCompetitiveSubject.objects.filter(
                competicio=fase.competicio,
                comp_aparell=fase.comp_aparell,
                id=team_subject_id,
            ).exists()
            if not exists:
                raise QualificationError("La classificacio origen referencia una unitat d'equip que no pertany a aquest aparell.")
            return "team_unit", team_subject_id
        equip_id = _positive_int(row.get("equip_id") or row.get("team_id"))
        team_subject_id = _team_subject_id_for_equip(fase, equip_id)
        if team_subject_id:
            return "team_unit", team_subject_id
        if equip_id:
            raise QualificationError(
                "La classificacio origen conte un equip que no es pot resoldre com a unitat competitiva d'aquest aparell."
            )
        if _positive_int(row.get("inscripcio_id")):
            raise QualificationError("El tall d'un aparell d'equip no pot omplir places amb inscripcions individuals.")
        return None

    subject = _subject_from_row(row)
    if subject is None:
        return None
    subject_kind, subject_id = subject
    if subject_kind != "inscripcio":
        raise QualificationError("El tall d'una fase individual no pot omplir places amb equips.")
    return subject_kind, subject_id


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
    fase: CompeticioAparellFase,
    row: dict,
    *,
    particio_key: str,
    status: str,
    seed_position: int | None = None,
) -> QualificationCandidate | None:
    subject = _subject_from_row_for_phase(fase, row)
    if subject is None:
        return None
    subject_kind, subject_id = subject
    source_row = _clean_source_row(row)
    if subject_kind == "team_unit":
        source_row.setdefault("team_subject_id", subject_id)
    if seed_position:
        source_row["phase_seed_position"] = seed_position
    return QualificationCandidate(
        source_particio_key=particio_key,
        source_row=source_row,
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


def _format_partition_label(partition_key: str) -> str:
    return format_partition_label(partition_key)


def _format_unit_label(template: str, *, fase: CompeticioAparellFase, partition_key: str, index: int, total: int) -> str:
    particio = _format_partition_label(partition_key)
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


def _normalize_partition_key(value) -> str:
    return str(value or "").strip() or "global"


def _normalize_partition_keys(partition_keys=None) -> list[str] | None:
    if partition_keys is None:
        return None
    if isinstance(partition_keys, str):
        raw_items = [partition_keys]
    else:
        raw_items = list(partition_keys or [])
    keys: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        key = _normalize_partition_key(raw)
        if key not in seen:
            keys.append(key)
            seen.add(key)
    return keys


def _scope_payload(partition_keys=None) -> dict:
    keys = _normalize_partition_keys(partition_keys)
    if keys is None:
        return {"kind": "global"}
    return {"kind": "partition", "partition_keys": keys}


def _candidate_payload(candidate: QualificationCandidate) -> dict:
    return {
        "subject_kind": candidate.subject_kind,
        "subject_id": candidate.subject_id,
        "status": candidate.status,
        "source_particio_key": candidate.source_particio_key,
        "source_position": candidate.source_position,
        "source_score": str(candidate.source_score) if candidate.source_score is not None else None,
        "source_row": candidate.source_row,
    }


def _unit_payload(unit: QualificationUnitPreview) -> dict:
    return {
        "unit_id": unit.unit_id,
        "label": unit.label,
        "partition_key": unit.partition_key,
        "capacity": unit.capacity,
        "candidates": [_candidate_payload(candidate) for candidate in unit.candidates],
    }


def _preview_partition_payload(
    *,
    classificacio: ClassificacioConfig,
    source_phase: CompeticioAparellFase | None,
    cut: dict,
    partition_key: str,
    units: list[QualificationUnitPreview],
    reserves: list[QualificationCandidate],
    warnings: list[str],
) -> dict:
    return {
        "classificacio_id": classificacio.id,
        "classificacio_updated_at": classificacio.updated_at.isoformat() if classificacio.updated_at else "",
        "source_phase_id": source_phase.id if source_phase else None,
        "cut": cut,
        "partition_key": _normalize_partition_key(partition_key),
        "units": [_unit_payload(unit) for unit in units],
        "reserves": [_candidate_payload(candidate) for candidate in reserves],
        "warnings": list(warnings or []),
    }


def _aggregate_snapshot_hash(scope: dict, partition_hashes: dict[str, str]) -> str:
    return _snapshot_hash({
        "scope": scope or {"kind": "global"},
        "partition_hashes": {
            key: partition_hashes[key]
            for key in sorted(partition_hashes)
        },
    })


def _legacy_global_preview_snapshot_hash(preview: QualificationPreview) -> str:
    """
    Hash compatible with the pre-partition-scope global snapshot payload.

    New snapshots store per-partition hashes and an aggregate hash, but existing
    global snapshots in phase.config only know this legacy digest. Accepting it
    avoids marking old valid snapshots stale solely because the hash format was
    upgraded.
    """

    payload = preview.payload()
    return _snapshot_hash({
        "classificacio_id": preview.classificacio.id,
        "classificacio_updated_at": preview.classificacio.updated_at.isoformat() if preview.classificacio.updated_at else "",
        "source_phase_id": preview.source_phase.id if preview.source_phase else None,
        "cut": _phase_config(preview.fase)[1],
        "units": payload.get("units") or [],
        "reserves": payload.get("reserves") or {},
    })


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
    strategy: str = "classification_order",
) -> list[QualificationUnitPreview]:
    selected = _select_candidates_for_partition(
        fase=fase,
        partition_key=partition_key,
        rows=rows,
        qualifiers_count=qualifiers_count,
        reserve_count=reserve_count,
        tie_policy=tie_policy,
        warnings=warnings,
        partition_warnings=partition_warnings,
    )
    competitive = [candidate for candidate in selected if candidate.status != ProgramUnitSlot.Status.RESERVE]
    slot_target = max(qualifiers_count, len(competitive), 1)
    unit_count = (slot_target + unit_capacity - 1) // unit_capacity
    capacities = [
        min(unit_capacity, slot_target - offset)
        for offset in range(0, slot_target, unit_capacity)
    ]
    chunks, unassigned = _chunks_by_strategy(
        competitive,
        capacities,
        strategy=str(strategy or "classification_order"),
        seed_material={
            "phase_id": fase.id,
            "partition_key": partition_key,
            "strategy": str(strategy or "classification_order"),
            "capacities": capacities,
            "subjects": [
                {
                    "kind": candidate.subject_kind,
                    "id": candidate.subject_id,
                    "status": candidate.status,
                    "source_position": candidate.source_position,
                }
                for candidate in competitive
            ],
        },
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
            QualificationUnitPreview(
                label=label,
                partition_key=partition_key,
                capacity=capacity,
                candidates=_slot_order_candidates(chunk, strategy=str(strategy or "classification_order")),
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


def _split_reserve_candidates(
    selected: list[QualificationCandidate],
) -> tuple[list[QualificationCandidate], list[QualificationCandidate]]:
    competitive = []
    reserves = []
    for candidate in selected:
        if candidate.status == ProgramUnitSlot.Status.RESERVE:
            reserves.append(candidate)
        else:
            competitive.append(candidate)
    return competitive, reserves


def _select_candidates_for_partition(
    *,
    fase: CompeticioAparellFase,
    partition_key: str,
    rows: list[dict],
    qualifiers_count: int,
    reserve_count: int,
    tie_policy: str,
    warnings: list[str],
    partition_warnings: dict[str, list[str]],
) -> list[QualificationCandidate]:
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
    for seed_position, (row, status) in enumerate(selected_rows, start=1):
        candidate = _candidate_from_row(
            fase,
            row,
            particio_key=partition_key,
            status=status,
            seed_position=seed_position,
        )
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
    return selected


def _partition_key_for_unit(unit: ProgramUnit, partition_mode: str) -> str:
    key = str(unit.partition_key or "").strip()
    if partition_mode == "global" and not key:
        return "global"
    return key or "global"


def _candidate_units_for_partition(
    existing_units: list[ProgramUnit],
    *,
    partition_mode: str,
    partition_key: str,
) -> list[ProgramUnit]:
    key = str(partition_key or "").strip() or "global"
    if partition_mode == "global":
        return [
            unit for unit in existing_units
            if _partition_key_for_unit(unit, partition_mode) == "global"
        ]
    return [
        unit for unit in existing_units
        if _partition_key_for_unit(unit, partition_mode) == key
    ]


def _slots_for_unit(unit: ProgramUnit) -> list[ProgramUnitSlot]:
    prefetched = getattr(unit, "_prefetched_objects_cache", {}).get("slots")
    if prefetched is not None:
        return sorted(prefetched, key=lambda slot: (slot.ordre, slot.slot_index, slot.id or 0))
    return list(unit.slots.order_by("ordre", "slot_index", "id"))


def _qualification_group_settings(fase: CompeticioAparellFase) -> dict:
    config = fase.config if isinstance(fase.config, dict) else {}
    group_plan = config.get("group_plan") if isinstance(config.get("group_plan"), dict) else {}
    settings = config.get("group_plan_settings") if isinstance(config.get("group_plan_settings"), dict) else {}
    return {
        "formation_strategy": (
            group_plan.get("formation_strategy")
            or settings.get("formation_strategy")
            or "classification_order"
        )
    }


def _chunks_by_strategy(
    selected: list[QualificationCandidate],
    capacities: list[int],
    *,
    strategy: str,
    seed_material: dict | None = None,
) -> tuple[list[list[QualificationCandidate]], int]:
    chunks = [[] for _ in capacities]
    if not selected or not capacities:
        return chunks, len(selected)

    def next_open(start: int, step: int = 1):
        total = len(capacities)
        for offset in range(total):
            index = (start + offset * step) % total
            if len(chunks[index]) < capacities[index]:
                return index
        return None

    if strategy == "serpentine":
        direction = 1
        index = 0
        for candidate in selected:
            target = next_open(index, direction)
            if target is None:
                return chunks, len(selected) - sum(len(chunk) for chunk in chunks)
            chunks[target].append(candidate)
            if direction == 1:
                if target >= len(capacities) - 1:
                    direction = -1
                    index = target
                else:
                    index = target + 1
            else:
                if target <= 0:
                    direction = 1
                    index = target
                else:
                    index = target - 1
        return chunks, 0

    if strategy == "first_last":
        left = 0
        right = len(selected) - 1
        unit_index = 0
        while left <= right:
            target = next_open(unit_index)
            if target is None:
                return chunks, right - left + 1
            chunks[target].append(selected[left])
            left += 1
            if left <= right and len(chunks[target]) < capacities[target]:
                chunks[target].append(selected[right])
                right -= 1
            unit_index = target + 1
        return chunks, 0

    if strategy == "random":
        shuffled = list(selected)
        seed = _snapshot_hash(seed_material or {
            "strategy": strategy,
            "capacities": capacities,
            "subjects": [
                {
                    "kind": candidate.subject_kind,
                    "id": candidate.subject_id,
                    "status": candidate.status,
                    "source_particio_key": candidate.source_particio_key,
                    "source_position": candidate.source_position,
                }
                for candidate in shuffled
            ],
        })
        random.Random(seed).shuffle(shuffled)
        offset = 0
        for index, capacity in enumerate(capacities):
            chunks[index] = shuffled[offset:offset + capacity]
            offset += capacity
        return chunks, max(0, len(shuffled) - offset)

    offset = 0
    for index, capacity in enumerate(capacities):
        chunks[index] = selected[offset:offset + capacity]
        offset += capacity
    return chunks, max(0, len(selected) - offset)


def _slot_order_candidates(
    candidates: list[QualificationCandidate],
    *,
    strategy: str,
) -> list[QualificationCandidate]:
    if str(strategy or "").strip() == "serpentine":
        return list(reversed(candidates))
    return list(candidates)


def _build_existing_unit_previews(
    *,
    fase: CompeticioAparellFase,
    existing_units: list[ProgramUnit],
    partition_mode: str,
    partition_key: str,
    selected: list[QualificationCandidate],
    warnings: list[str],
    partition_warnings: dict[str, list[str]],
) -> list[QualificationUnitPreview]:
    units = _candidate_units_for_partition(
        existing_units,
        partition_mode=partition_mode,
        partition_key=partition_key,
    )
    if not units:
        _add_partition_warning(
            warnings,
            partition_warnings,
            partition_key,
            "no hi ha unitats de programa per a aquesta particio. Genera-les a Grups abans de congelar.",
        )
        return []

    previews = []
    capacities = []
    for unit in units:
        capacity = len(_slots_for_unit(unit))
        if capacity <= 0:
            capacity = _positive_int(unit.capacity, default=0)
        capacities.append(capacity)
    settings = _qualification_group_settings(fase)
    strategy = str(settings.get("formation_strategy") or "classification_order")
    chunks, unassigned = _chunks_by_strategy(
        selected,
        capacities,
        strategy=strategy,
        seed_material={
            "phase_id": fase.id,
            "partition_key": partition_key,
            "strategy": strategy,
            "capacities": capacities,
            "unit_ids": [unit.id for unit in units],
            "subjects": [
                {
                    "kind": candidate.subject_kind,
                    "id": candidate.subject_id,
                    "status": candidate.status,
                    "source_position": candidate.source_position,
                }
                for candidate in selected
            ],
        },
    )
    for unit, capacity, chunk in zip(units, capacities, chunks):
        previews.append(
            QualificationUnitPreview(
                unit_id=unit.id,
                label=unit.nom,
                partition_key=_partition_key_for_unit(unit, partition_mode),
                capacity=capacity,
                candidates=_slot_order_candidates(chunk, strategy=strategy),
            )
        )
    if unassigned:
        _add_partition_warning(
            warnings,
            partition_warnings,
            partition_key,
            f"no hi ha prou slots per assignar {unassigned} classificat/s o reserva/es.",
        )
    return previews


def preview_qualification(
    fase: CompeticioAparellFase,
    partition_keys=None,
) -> QualificationPreview:
    classificacio = _source_classificacio(fase)
    source_phase = _source_phase_for_classificacio(classificacio, comp_aparell_id=fase.comp_aparell_id)
    validate_classificacio_not_circular_source(fase, classificacio, source_phase=source_phase)
    _source, cut = _phase_config(fase)
    qualifiers_count = _positive_int(cut.get("qualifiers_count"), default=0)
    reserve_count = _positive_int(cut.get("reserve_count"), default=0)
    partition_mode = str(cut.get("partition_mode") or "global").strip() or "global"
    tie_policy = str(cut.get("tie_policy") or "classification_order").strip() or "classification_order"
    if qualifiers_count <= 0:
        raise QualificationError("Cal configurar un nombre positiu de classificats.")
    if partition_mode not in {"global", "source_partitions"}:
        raise QualificationError("El mode de particio del tall no es valid.")
    if tie_policy not in TIE_POLICIES:
        raise QualificationError("La politica d'empats del tall no es valida.")
    existing_units = list(
        ProgramUnit.objects
        .filter(fase=fase)
        .prefetch_related("slots")
        .order_by("ordre", "id")
    )
    if not existing_units:
        raise QualificationError("Primer genera les unitats buides de la fase a Grups.")

    warnings = []
    partition_warnings = {}
    source_warning = _source_phase_warning(source_phase)
    if source_warning:
        warnings.append(source_warning)
    result = compute_classificacio(fase.competicio, classificacio)
    units = []
    reserves = {}
    requested_keys = _normalize_partition_keys(partition_keys)
    rows_by_key = {
        _normalize_partition_key(partition_key): list(rows or [])
        for partition_key, rows in _rows_for_cut(result, partition_mode)
    }
    if requested_keys is None:
        partition_items = list(rows_by_key.items())
    else:
        partition_items = [(key, rows_by_key.get(key, [])) for key in requested_keys]
    partition_hashes: dict[str, str] = {}
    for partition_key, rows in partition_items:
        selected = _select_candidates_for_partition(
            fase=fase,
            partition_key=partition_key,
            rows=rows,
            qualifiers_count=qualifiers_count,
            reserve_count=reserve_count,
            tie_policy=tie_policy,
            warnings=warnings,
            partition_warnings=partition_warnings,
        )
        competitive, reserve_candidates = _split_reserve_candidates(selected)
        if reserve_candidates:
            reserves[partition_key] = reserve_candidates
        partition_units = _build_existing_unit_previews(
            fase=fase,
            existing_units=existing_units,
            partition_mode=partition_mode,
            partition_key=partition_key,
            selected=competitive,
            warnings=warnings,
            partition_warnings=partition_warnings,
        )
        units.extend(partition_units)
        partition_hashes[partition_key] = _snapshot_hash(
            _preview_partition_payload(
                classificacio=classificacio,
                source_phase=source_phase,
                cut=cut,
                partition_key=partition_key,
                units=partition_units,
                reserves=reserve_candidates,
                warnings=partition_warnings.get(partition_key, []),
            )
        )

    scope = _scope_payload(requested_keys)
    return QualificationPreview(
        fase=fase,
        classificacio=classificacio,
        source_phase=source_phase,
        snapshot_hash=_aggregate_snapshot_hash(scope, partition_hashes),
        units=units,
        warnings=warnings,
        partition_warnings=partition_warnings,
        reserves=reserves,
        partition_hashes=partition_hashes,
        scope=scope,
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


def record_qualification_preview(
    fase: CompeticioAparellFase,
    partition_keys=None,
) -> QualificationPreview:
    preview = preview_qualification(fase, partition_keys=partition_keys)
    _create_run(preview, status=QualificationRun.Status.PREVIEWED)
    return preview


def _partition_keys_for_preview(preview: QualificationPreview) -> list[str]:
    keys = []
    seen = set()
    for raw_key in (getattr(preview, "partition_hashes", None) or {}).keys():
        key = _normalize_partition_key(raw_key)
        if key not in seen:
            keys.append(key)
            seen.add(key)
    for unit in getattr(preview, "units", []) or []:
        key = _normalize_partition_key(unit.partition_key)
        if key not in seen:
            keys.append(key)
            seen.add(key)
    for raw_key in (getattr(preview, "reserves", None) or {}).keys():
        key = _normalize_partition_key(raw_key)
        if key not in seen:
            keys.append(key)
            seen.add(key)
    return keys


def _sync_partition_states(
    preview: QualificationPreview,
    run: QualificationRun,
    *,
    mark_missing_stale: bool = False,
) -> None:
    keys = _partition_keys_for_preview(preview)
    for partition_key in keys:
        partition_hash = (preview.partition_hashes or {}).get(partition_key, preview.snapshot_hash)
        state, _created = FasePartitionState.objects.get_or_create(
            fase=preview.fase,
            partition_key=partition_key,
            defaults={
                "status": FasePartitionState.Status.GENERATED,
                "qualification_run": run,
                "source_snapshot_hash": partition_hash,
                "warnings": list(preview.partition_warnings.get(partition_key, [])),
            },
        )
        state.status = FasePartitionState.Status.GENERATED
        state.qualification_run = run
        state.source_snapshot_hash = partition_hash
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
    if mark_missing_stale:
        FasePartitionState.objects.filter(fase=preview.fase).exclude(partition_key__in=keys).update(
            status=FasePartitionState.Status.STALE,
        )


def _unit_ids_for_preview(preview: QualificationPreview) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for unit_preview in preview.units:
        if not unit_preview.unit_id:
            continue
        unit_id = int(unit_preview.unit_id)
        if unit_id not in seen:
            ids.append(unit_id)
            seen.add(unit_id)
    return ids


def _slots_qs_for_scope(fase: CompeticioAparellFase, *, unit_ids: list[int] | None = None):
    qs = ProgramUnitSlot.objects.filter(unit__fase=fase)
    if unit_ids is not None:
        qs = qs.filter(unit_id__in=unit_ids)
    return qs


def _protected_slots_exist(fase: CompeticioAparellFase, *, unit_ids: list[int] | None = None) -> bool:
    qs = _slots_qs_for_scope(fase, unit_ids=unit_ids)
    return qs.filter(locked=True).exists() or qs.filter(
        unit__fase=fase,
        status=ProgramUnitSlot.Status.MANUAL,
    ).exists()


def _assigned_slots_exist(fase: CompeticioAparellFase, *, unit_ids: list[int] | None = None) -> bool:
    return _slots_qs_for_scope(fase, unit_ids=unit_ids).exclude(status=ProgramUnitSlot.Status.EMPTY).exists()


def _clear_qualification_slots(fase: CompeticioAparellFase, *, unit_ids: list[int] | None = None) -> None:
    _slots_qs_for_scope(fase, unit_ids=unit_ids).update(
        subject_kind="",
        subject_id=None,
        status=ProgramUnitSlot.Status.EMPTY,
        source_classificacio=None,
        source_particio_key="",
        source_position=None,
        source_score=None,
        source_row={},
    )


def _state_partition_hashes(fase: CompeticioAparellFase) -> dict[str, str]:
    return {
        _normalize_partition_key(row["partition_key"]): str(row["source_snapshot_hash"] or "").strip()
        for row in FasePartitionState.objects.filter(fase=fase).values("partition_key", "source_snapshot_hash")
    }


def _aggregate_phase_status(fase: CompeticioAparellFase) -> str:
    states = list(FasePartitionState.objects.filter(fase=fase).values_list("status", flat=True))
    if not states:
        return CompeticioAparellFase.Estat.GENERATED
    if any(status == FasePartitionState.Status.STALE for status in states):
        return CompeticioAparellFase.Estat.STALE
    if all(status == FasePartitionState.Status.CONFIRMED for status in states):
        return CompeticioAparellFase.Estat.CONFIRMED
    if any(status == FasePartitionState.Status.CONFIRMED for status in states):
        return CompeticioAparellFase.Estat.PARTIALLY_CONFIRMED
    return CompeticioAparellFase.Estat.GENERATED


def _update_phase_qualification_config(
    fase: CompeticioAparellFase,
    *,
    preview: QualificationPreview,
    run: QualificationRun,
    now,
) -> None:
    config = fase.config if isinstance(fase.config, dict) else {}
    old_qualification = config.get("qualification") if isinstance(config.get("qualification"), dict) else {}
    partition_hashes = _state_partition_hashes(fase)
    stale = FasePartitionState.objects.filter(fase=fase, status=FasePartitionState.Status.STALE).exists()
    config["qualification"] = {
        **old_qualification,
        "run_id": run.id,
        "last_run_id": run.id,
        "source_classificacio_id": preview.classificacio.id,
        "source_phase_id": preview.source_phase.id if preview.source_phase else None,
        "snapshot_hash": preview.snapshot_hash,
        "generated_at": now.isoformat(),
        "summary": preview.summary(),
        "warnings": list(preview.warnings),
        "partitions": sorted(partition_hashes.keys()),
        "partition_hashes": partition_hashes,
        "scope": dict(preview.scope or {"kind": "global"}),
        "stale": stale,
    }
    fase.config = config
    fase.estat = _aggregate_phase_status(fase)
    fase.save(update_fields=["config", "estat", "updated_at"])


def apply_qualification(
    fase: CompeticioAparellFase,
    *,
    partition_keys=None,
    replace_existing: bool = False,
    allow_replace_protected: bool = False,
) -> QualificationPreview:
    preview = preview_qualification(fase, partition_keys=partition_keys)
    source_warning = _source_phase_warning(preview.source_phase)
    if source_warning:
        raise QualificationError(source_warning)
    target_unit_ids = _unit_ids_for_preview(preview)
    if _assigned_slots_exist(fase, unit_ids=target_unit_ids) and not replace_existing:
        raise QualificationError("La fase desti ja te slots omplerts. Revisa'ls o reemplaça el snapshot.")
    if replace_existing and _protected_slots_exist(fase, unit_ids=target_unit_ids) and not allow_replace_protected:
        raise QualificationError("No es poden sobreescriure slots bloquejats o manuals.")

    with transaction.atomic():
        now = timezone.now()
        run = _create_run(preview, status=QualificationRun.Status.APPLIED, applied_at=now)
        _clear_qualification_slots(fase, unit_ids=target_unit_ids)
        units_by_id = {
            unit.id: unit
            for unit in ProgramUnit.objects.filter(fase=fase, id__in=target_unit_ids).prefetch_related("slots")
        }
        for unit_preview in preview.units:
            unit = units_by_id.get(unit_preview.unit_id)
            if unit is None:
                continue
            partition_key = _normalize_partition_key(unit_preview.partition_key)
            partition_hash = (preview.partition_hashes or {}).get(partition_key, preview.snapshot_hash)
            metadata = unit.metadata if isinstance(unit.metadata, dict) else {}
            metadata.update({
                "qualification_snapshot_hash": partition_hash,
                "qualification_run_id": run.id,
                "source_classificacio_id": preview.classificacio.id,
                "qualification_scope": dict(preview.scope or {"kind": "global"}),
            })
            unit.metadata = metadata
            unit.status = ProgramUnit.Status.GENERATED
            unit.save(update_fields=["metadata", "status", "updated_at"])
            fill_program_unit_slots(
                unit,
                [
                    candidate.to_slot_subject(preview.classificacio.id)
                    for candidate in unit_preview.candidates
                ],
            )

        _sync_partition_states(
            preview,
            run,
            mark_missing_stale=_normalize_partition_keys(partition_keys) is None,
        )
        _update_phase_qualification_config(fase, preview=preview, run=run, now=now)
    return preview


def _legacy_global_snapshot_hash(fase: CompeticioAparellFase) -> str:
    config = fase.config if isinstance(fase.config, dict) else {}
    qualification = config.get("qualification") if isinstance(config.get("qualification"), dict) else {}
    return str(qualification.get("snapshot_hash") or "").strip()


def _run_has_partition_hash(run: QualificationRun | None, partition_key: str) -> bool:
    if run is None:
        return False
    payload = run.payload if isinstance(run.payload, dict) else {}
    partition_hashes = payload.get("partition_hashes") if isinstance(payload.get("partition_hashes"), dict) else {}
    return _normalize_partition_key(partition_key) in partition_hashes


def _global_qualification_is_stale(fase: CompeticioAparellFase) -> bool:
    stored_hash = _legacy_global_snapshot_hash(fase)
    if not stored_hash:
        return False
    try:
        preview = preview_qualification(fase)
    except QualificationError:
        return True
    return stored_hash not in {
        preview.snapshot_hash,
        _legacy_global_preview_snapshot_hash(preview),
    }


def qualification_partition_is_stale(fase: CompeticioAparellFase, partition_key: str) -> bool:
    key = _normalize_partition_key(partition_key)
    state = (
        FasePartitionState.objects
        .filter(fase=fase, partition_key=key)
        .select_related("qualification_run")
        .first()
    )
    if state is None:
        return False
    stored_hash = str(state.source_snapshot_hash or "").strip()
    if not stored_hash:
        return False
    if state.status == FasePartitionState.Status.STALE:
        return True
    if not _run_has_partition_hash(state.qualification_run, key):
        config = fase.config if isinstance(fase.config, dict) else {}
        qualification = config.get("qualification") if isinstance(config.get("qualification"), dict) else {}
        config_hashes = qualification.get("partition_hashes") if isinstance(qualification.get("partition_hashes"), dict) else {}
        if key not in config_hashes:
            return _global_qualification_is_stale(fase)
    try:
        preview = preview_qualification(fase, partition_keys=[key])
    except QualificationError:
        return True
    current_hash = str((preview.partition_hashes or {}).get(key) or preview.snapshot_hash or "").strip()
    return current_hash != stored_hash


def qualification_stale_partitions(fase: CompeticioAparellFase) -> dict[str, bool]:
    states = list(FasePartitionState.objects.filter(fase=fase).values_list("partition_key", flat=True))
    if not states:
        return {"global": _global_qualification_is_stale(fase)}
    return {
        _normalize_partition_key(partition_key): qualification_partition_is_stale(fase, partition_key)
        for partition_key in states
    }


def qualification_is_stale(fase: CompeticioAparellFase) -> bool:
    return any(qualification_stale_partitions(fase).values())


def qualification_source_changed(fase: CompeticioAparellFase) -> bool:
    config = fase.config if isinstance(fase.config, dict) else {}
    qualification = config.get("qualification") if isinstance(config.get("qualification"), dict) else {}
    source_classificacio_id = qualification.get("source_classificacio_id")
    generated_at_raw = str(qualification.get("generated_at") or "").strip()
    if not source_classificacio_id or not generated_at_raw:
        return False
    generated_at = parse_datetime(generated_at_raw)
    if generated_at is None:
        return False
    classificacio = ClassificacioConfig.objects.filter(id=source_classificacio_id).only("id", "updated_at").first()
    if classificacio is None:
        return True
    return bool(classificacio.updated_at and classificacio.updated_at > generated_at)


def accept_current_qualification_snapshot(fase: CompeticioAparellFase) -> QualificationPreview:
    if qualification_source_changed(fase):
        raise QualificationError("La classificacio font ha canviat. Recalcula el snapshot abans de validar-lo.")
    preview = preview_qualification(fase)
    now = timezone.now()
    with transaction.atomic():
        run = _create_run(preview, status=QualificationRun.Status.APPLIED, applied_at=now)
        _sync_partition_states(preview, run, mark_missing_stale=True)
        _update_phase_qualification_config(fase, preview=preview, run=run, now=now)
        config = fase.config if isinstance(fase.config, dict) else {}
        qualification = config.get("qualification") if isinstance(config.get("qualification"), dict) else {}
        qualification["validated_at"] = now.isoformat()
        qualification["manual_validated"] = True
        config["qualification"] = qualification
        fase.config = config
        fase.save(update_fields=["config", "updated_at"])
    return preview


def mark_qualification_stale_if_needed(fase: CompeticioAparellFase) -> bool:
    stale_map = qualification_stale_partitions(fase)
    stale_keys = [key for key, is_stale in stale_map.items() if is_stale]
    if not stale_keys:
        return False
    config = fase.config if isinstance(fase.config, dict) else {}
    qualification = config.get("qualification") if isinstance(config.get("qualification"), dict) else {}
    with transaction.atomic():
        if FasePartitionState.objects.filter(fase=fase).exists():
            FasePartitionState.objects.filter(fase=fase, partition_key__in=stale_keys).update(
                status=FasePartitionState.Status.STALE,
            )
        qualification["stale"] = bool(stale_keys)
        qualification["stale_partitions"] = stale_keys
        config["qualification"] = qualification
        fase.config = config
        fase.estat = _aggregate_phase_status(fase) if FasePartitionState.objects.filter(fase=fase).exists() else CompeticioAparellFase.Estat.STALE
        fase.save(update_fields=["config", "estat", "updated_at"])
    return True


def confirm_qualification_partition(fase: CompeticioAparellFase, partition_key: str) -> FasePartitionState:
    key = _normalize_partition_key(partition_key)
    with transaction.atomic():
        try:
            state = FasePartitionState.objects.select_for_update().get(fase=fase, partition_key=key)
        except FasePartitionState.DoesNotExist as exc:
            raise QualificationError("Aquesta particio encara no esta generada.") from exc
        state.status = FasePartitionState.Status.CONFIRMED
        state.confirmed_at = timezone.now()
        state.save(update_fields=["status", "confirmed_at", "updated_at"])
        if key == "global":
            ProgramUnit.objects.filter(fase=fase, partition_key__in=["", "global"]).update(status=ProgramUnit.Status.CONFIRMED)
        else:
            ProgramUnit.objects.filter(fase=fase, partition_key=key).update(status=ProgramUnit.Status.CONFIRMED)
        fase.estat = _aggregate_phase_status(fase)
        fase.save(update_fields=["estat", "updated_at"])
    return state


def preview_as_dict(preview: QualificationPreview) -> dict:
    return {
        "classificacio": preview.classificacio,
        "source_phase": preview.source_phase,
        "summary": preview.summary(),
        "warnings": list(preview.warnings),
        "partition_warnings": dict(preview.partition_warnings),
        "reserves": dict(preview.reserves),
        "units": [
            {
                "unit_id": unit.unit_id,
                "label": unit.label,
                "partition_key": unit.partition_key,
                "capacity": unit.capacity,
                "candidates": list(unit.candidates),
            }
            for unit in preview.units
        ],
    }


__all__ = [
    "CIRCULAR_SOURCE_PHASE_MESSAGE",
    "QualificationError",
    "QualificationPreview",
    "QualificationUnitPreview",
    "accept_current_qualification_snapshot",
    "apply_qualification",
    "classificacio_is_valid_source_for_phase",
    "confirm_qualification_partition",
    "mark_qualification_stale_if_needed",
    "preview_as_dict",
    "preview_qualification",
    "qualification_partition_is_stale",
    "qualification_source_changed",
    "qualification_is_stale",
    "qualification_stale_partitions",
    "record_qualification_preview",
    "validate_classificacio_subject_contract",
    "validate_classificacio_not_circular_source",
]
