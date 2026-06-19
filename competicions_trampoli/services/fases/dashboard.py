from __future__ import annotations

from collections import defaultdict

from django.db.models import Count, Prefetch

from ...models.competicio import (
    CompeticioAparell,
    CompeticioAparellFase,
    FasePartitionState,
    Inscripcio,
    ProgramUnit,
    ProgramUnitSlot,
)
from ...models.scoring import TeamCompetitiveSubject
from ...models.rotacions import RotacioAssignacioProgramUnit
from ..inscripcions.aparell_participation import participation_preview
from .group_plan import structural_cut_signature
from .logos import available_app_logos_for_competicio, selected_logo_path_for_app
from .labels import format_partition_label, program_unit_display_name
from .qualification import (
    QualificationError,
    qualification_is_stale,
    qualification_source_changed,
)
from .slot_overrides import (
    active_subject_refs_for_phase,
    available_recoverable_options_for_slot,
    available_reserve_options_for_slot,
    manual_inscripcio_options_for_phase,
    manual_team_unit_options_for_phase,
    recoverable_snapshot_options_for_phase,
    reserve_options_for_phase,
)


def _time_label(value) -> str:
    if value is None:
        return ""
    try:
        return value.strftime("%H:%M")
    except Exception:
        return str(value)


def _unit_display_name(unit: ProgramUnit) -> str:
    return program_unit_display_name(unit)


def _rotacio_label(link: RotacioAssignacioProgramUnit) -> str:
    assignacio = link.assignacio
    franja = assignacio.franja
    estacio = assignacio.estacio
    interval = f"{_time_label(franja.hora_inici)}-{_time_label(franja.hora_fi)}"
    franja_label = str(getattr(franja, "display_label", "") or "Franja").strip()
    estacio_label = str(getattr(estacio, "nom", "") or "Estació").strip()
    return f"{franja_label} {interval} / {estacio_label}".strip()


def _programming_by_unit(competicio) -> dict[int, list[str]]:
    labels_by_unit: dict[int, list[str]] = defaultdict(list)
    links = (
        RotacioAssignacioProgramUnit.objects
        .filter(assignacio__competicio=competicio)
        .select_related(
            "assignacio__franja",
            "assignacio__estacio",
            "assignacio__estacio__comp_aparell",
            "program_unit",
        )
        .order_by("assignacio__franja__ordre_visual", "assignacio__franja__ordre", "assignacio__estacio__ordre", "ordre", "id")
    )
    for link in links:
        labels_by_unit[int(link.program_unit_id)].append(_rotacio_label(link))
    return dict(labels_by_unit)


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _partition_key(value) -> str:
    return str(value or "").strip() or "global"


def _group_plan_is_stale_from_config(phase_config: dict) -> bool:
    group_plan = phase_config.get("group_plan") if isinstance(phase_config.get("group_plan"), dict) else {}
    cut = phase_config.get("cut") if isinstance(phase_config.get("cut"), dict) else {}
    stored = str(group_plan.get("cut_signature") or "").strip()
    return bool(group_plan.get("stale") or (stored and stored != structural_cut_signature(cut)))


def _partition_state_is_stale(
    state: FasePartitionState | None,
    *,
    phase_qualification_stale: bool,
    has_partition_states: bool,
) -> bool:
    if state is not None:
        return str(state.status or "") == FasePartitionState.Status.STALE
    if has_partition_states:
        return False
    return bool(phase_qualification_stale)


def _phase_publish_blockers(phase: CompeticioAparellFase, phase_config: dict) -> list[str]:
    blockers = []
    if _group_plan_is_stale_from_config(phase_config):
        blockers.append("revisa o regenera el pla de grups")
    if not getattr(phase, "ui_unit_count", 0):
        blockers.append("genera unitats de grups")
    elif not getattr(phase, "ui_competitive_slot_count", 0):
        blockers.append("omple almenys una unitat amb participants/equips")
    qualification = phase_config.get("qualification") if isinstance(phase_config.get("qualification"), dict) else {}
    has_partition_runs = bool(getattr(phase, "ui_partition_qualification_run_ids", []))
    if not qualification.get("run_id") and not has_partition_runs:
        blockers.append("congela el snapshot")
    elif not getattr(phase, "ui_has_partition_state_scope", False) and (
        qualification.get("stale") or getattr(phase, "ui_qualification_stale", False)
    ):
        blockers.append("recalcula el snapshot")
    stale_partitions = [
        state
        for state in getattr(phase, "ui_partition_states", [])
        if str(getattr(state, "status", "") or "") == FasePartitionState.Status.STALE
    ]
    if stale_partitions:
        blockers.append("revisa les particions obsoletes")
    return blockers


def _ordinal_ca(value: int | None) -> str:
    if not value:
        return ""
    if value == 1:
        return "1r"
    if value == 2:
        return "2n"
    if value == 3:
        return "3r"
    if value == 4:
        return "4t"
    return f"{value}e"


def _source_row_text(source_row: dict, *keys: str) -> str:
    if not isinstance(source_row, dict):
        return ""
    for key in keys:
        value = source_row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    display = source_row.get("display")
    if isinstance(display, dict):
        for key in keys:
            value = display.get(key)
            if value not in (None, ""):
                return str(value).strip()
    cells = source_row.get("cells")
    if isinstance(cells, dict):
        for key in keys:
            value = cells.get(key)
            if value not in (None, ""):
                return str(value).strip()
    return ""


def _decorate_slot_subjects(
    slots: list[ProgramUnitSlot],
    inscripcions_by_id: dict[int, Inscripcio],
    team_subjects_by_id: dict[int, TeamCompetitiveSubject] | None = None,
) -> None:
    team_subjects_by_id = team_subjects_by_id or {}
    for slot in slots:
        source_row = slot.source_row if isinstance(slot.source_row, dict) else {}
        subject_kind = str(slot.subject_kind or "").strip().lower()
        subject_id = int(slot.subject_id or 0)
        label = _source_row_text(source_row, "participant", "nom", "name", "label", "equip_nom")
        meta = _source_row_text(source_row, "entitat_nom", "entitat", "club", "categoria", "subcategoria")
        if not label and subject_kind == "inscripcio" and subject_id:
            inscripcio = inscripcions_by_id.get(subject_id)
            if inscripcio is not None:
                label = str(getattr(inscripcio, "nom_i_cognoms", "") or "").strip()
                meta = str(getattr(inscripcio, "entitat", "") or "").strip()
        if not label and subject_kind == "team_unit" and subject_id:
            team_subject = team_subjects_by_id.get(subject_id)
            if team_subject is not None:
                label = (
                    str(getattr(team_subject, "label", "") or "").strip()
                    or str(getattr(getattr(team_subject, "equip", None), "nom", "") or "").strip()
                )
                meta = str(getattr(getattr(team_subject, "context", None), "nom", "") or "").strip()
        slot.ui_subject_label = "" if slot.status == ProgramUnitSlot.Status.EMPTY else label
        slot.ui_subject_meta = "" if slot.status == ProgramUnitSlot.Status.EMPTY else meta
        slot.ui_subject_fallback = f"{slot.subject_kind}:{slot.subject_id}" if slot.subject_kind and slot.subject_id else ""
        manual = source_row.get("manual_override") if isinstance(source_row.get("manual_override"), dict) else {}
        override_type = str(manual.get("type") or "").strip()
        source_position = getattr(slot, "source_position", None)
        seed_position = _to_int(source_row.get("phase_seed_position"))
        display_position = seed_position or source_position
        source_position_label = f"#{source_position}" if source_position else ""
        display_position_label = f"#{display_position}" if display_position else ""
        if slot.status == ProgramUnitSlot.Status.EMPTY:
            origin_label = (
                f"{_ordinal_ca(display_position)} classificat previst"
                if display_position
                else "Sense origen"
            )
        elif override_type == "manual_inscripcio":
            origin_label = "Manual"
        elif override_type == "manual_team_unit":
            origin_label = "Manual"
        elif override_type == "reserve_promotion" or slot.status == ProgramUnitSlot.Status.RESERVE:
            origin_label = f"Reserva {source_position_label}".strip()
        elif display_position:
            origin_label = f"Classificat {display_position_label}"
        elif slot.source_classificacio_id:
            origin_label = "Classificat"
        elif slot.status == ProgramUnitSlot.Status.MANUAL:
            origin_label = "Manual"
        else:
            origin_label = slot.get_status_display()
        origin_parts = []
        partition = str(slot.source_particio_key or "").strip()
        if partition:
            origin_parts.append(f"Partició: {format_partition_label(partition)}")
        if slot.status != ProgramUnitSlot.Status.EMPTY:
            if seed_position and source_position and seed_position != source_position:
                origin_parts.append(f"Posició classificació: #{source_position}")
            if slot.source_score is not None:
                origin_parts.append(f"Punts: {slot.source_score}")
        slot.ui_origin_label = origin_label
        slot.ui_origin_detail = " / ".join(origin_parts)


def _phases_for_comp_aparell(comp_aparell: CompeticioAparell) -> list[CompeticioAparellFase]:
    return list(
        CompeticioAparellFase.objects
        .filter(comp_aparell=comp_aparell)
        .select_related("parent")
        .prefetch_related(
            "partition_states",
            Prefetch(
                "program_units",
                queryset=(
                    ProgramUnit.objects
                    .annotate(slots_count=Count("slots", distinct=True))
                    .prefetch_related(
                        Prefetch(
                            "slots",
                            queryset=ProgramUnitSlot.objects.order_by("ordre", "slot_index", "id"),
                        )
                    )
                    .order_by("ordre", "id")
                ),
            )
        )
        .order_by("ordre", "id")
    )


def _decorate_phase_units(phases: list[CompeticioAparellFase], programming_by_unit: dict[int, list[str]]) -> None:
    child_counts: dict[int, int] = defaultdict(int)
    for phase in phases:
        if phase.parent_id:
            child_counts[int(phase.parent_id)] += 1
    for phase in phases:
        units = list(phase.program_units.all())
        phase_slots = [slot for unit in units for slot in list(unit.slots.all())]
        inscripcio_ids = {
            int(slot.subject_id)
            for slot in phase_slots
            if str(slot.subject_kind or "").strip().lower() == "inscripcio" and slot.subject_id
        }
        team_subject_ids = {
            int(slot.subject_id)
            for slot in phase_slots
            if str(slot.subject_kind or "").strip().lower() == "team_unit" and slot.subject_id
        }
        inscripcions_by_id = {
            int(inscripcio.id): inscripcio
            for inscripcio in Inscripcio.objects.filter(id__in=inscripcio_ids).only("id", "nom_i_cognoms", "entitat")
        }
        team_subjects_by_id = {
            int(team_subject.id): team_subject
            for team_subject in (
                TeamCompetitiveSubject.objects
                .filter(id__in=team_subject_ids)
                .select_related("equip", "context")
            )
        }
        _decorate_slot_subjects(phase_slots, inscripcions_by_id, team_subjects_by_id)
        phase_config = phase.config if isinstance(phase.config, dict) else {}
        source_config = phase_config.get("source") if isinstance(phase_config.get("source"), dict) else {}
        cut_config = phase_config.get("cut") if isinstance(phase_config.get("cut"), dict) else {}
        scoring_config = phase_config.get("scoring") if isinstance(phase_config.get("scoring"), dict) else {}
        try:
            phase_exercises = int(scoring_config.get("nombre_exercicis") or phase.comp_aparell.nombre_exercicis or 1)
        except (TypeError, ValueError):
            phase_exercises = 1
        phase.ui_nombre_exercicis = max(1, min(5, phase_exercises))
        phase.ui_nombre_exercicis_is_override = bool(scoring_config.get("nombre_exercicis"))
        source_name = (
            source_config.get("classificacio_nom")
            or source_config.get("nom")
            or phase_config.get("source_classificacio_nom")
            or ""
        )
        qualifiers = cut_config.get("qualifiers_count") or cut_config.get("limit") or phase_config.get("qualifiers_count")
        reserves = cut_config.get("reserve_count") or phase_config.get("reserve_count") or 0
        unit_capacity = cut_config.get("unit_capacity") or phase_config.get("unit_capacity")
        partition_mode = cut_config.get("partition_mode") or phase_config.get("partition_mode") or "global"
        tie_policy = cut_config.get("tie_policy") or "classification_order"
        tie_policy_labels = {
            "classification_order": "Ordre de classificació",
            "include_all_at_cut": "Inclou empatats",
            "manual_decision": "Decisió manual",
        }
        qualification_config = phase_config.get("qualification") if isinstance(phase_config.get("qualification"), dict) else {}
        group_plan_config = phase_config.get("group_plan") if isinstance(phase_config.get("group_plan"), dict) else {}
        current_cut_signature = structural_cut_signature(cut_config)
        stored_cut_signature = str(group_plan_config.get("cut_signature") or "").strip()
        phase.ui_group_plan_stale = _group_plan_is_stale_from_config(phase_config)
        phase.ui_group_plan_stale_reason = (
            group_plan_config.get("stale_reason")
            or "La recepta d'origen i tall ha canviat."
        )
        phase.ui_status_form_value = (
            phase.estat
            if phase.estat in {CompeticioAparellFase.Estat.PUBLISHED, CompeticioAparellFase.Estat.CLOSED}
            else CompeticioAparellFase.Estat.PLANNED
        )
        phase.ui_user_status_value = phase.estat
        phase.ui_user_status_label = {
            CompeticioAparellFase.Estat.PLANNED: "Esborrany",
            CompeticioAparellFase.Estat.GENERATED: "Planificada",
            CompeticioAparellFase.Estat.CONFIRMED: "Planificada",
            CompeticioAparellFase.Estat.PARTIALLY_CONFIRMED: "Revisar",
            CompeticioAparellFase.Estat.STALE: "Revisar",
            CompeticioAparellFase.Estat.PUBLISHED: "Publicada",
            CompeticioAparellFase.Estat.CLOSED: "Tancada",
        }.get(phase.ui_user_status_value, "Esborrany")
        phase.ui_source_configured = bool(
            phase_config.get("source_classificacio_id")
            or phase_config.get("classificacio_id")
            or source_config.get("classificacio_id")
            or source_config.get("id")
        )
        phase.ui_cut_configured = bool(cut_config or phase_config.get("cut_rule") or phase_config.get("qualifiers"))
        phase.ui_source_label = source_name or ("Configurada" if phase.ui_source_configured else "No configurada")
        phase.ui_cut_label = (
            f"Top {qualifiers} + {reserves} reserves"
            if qualifiers
            else "No configurat"
        )
        phase.ui_partition_label = "Per partició" if partition_mode == "source_partitions" else "Global"
        phase.ui_tie_policy_label = tie_policy_labels.get(tie_policy, "Ordre de classificació")
        phase.ui_unit_capacity_label = f"màxim {unit_capacity} places/unitat" if unit_capacity else "Sense mida d'unitat"
        phase.ui_qualification_run_id = qualification_config.get("run_id")
        phase.ui_qualification_snapshot_hash = qualification_config.get("snapshot_hash") or ""
        phase.ui_qualification_stale = False
        phase.ui_qualification_source_changed = False
        phase.ui_qualification_manual_pending = False
        if phase.ui_qualification_snapshot_hash:
            try:
                phase.ui_qualification_stale = qualification_is_stale(phase)
                phase.ui_qualification_source_changed = qualification_source_changed(phase)
                phase.ui_qualification_manual_pending = bool(
                    phase.ui_qualification_stale
                    and not phase.ui_qualification_source_changed
                )
            except QualificationError:
                phase.ui_qualification_stale = True
                phase.ui_qualification_source_changed = True
        partition_states = list(phase.partition_states.all())
        partition_states_by_key = {
            _partition_key(state.partition_key): state
            for state in partition_states
        }
        phase.ui_partition_states = partition_states
        phase.ui_has_partition_state_scope = bool(partition_states)
        phase.ui_partition_qualification_run_ids = sorted({
            int(state.qualification_run_id)
            for state in partition_states
            if state.qualification_run_id
        })
        phase_reserve_options = reserve_options_for_phase(phase)
        phase_recoverable_options = recoverable_snapshot_options_for_phase(phase)
        phase_active_subject_refs = active_subject_refs_for_phase(phase)
        phase.ui_reserve_options = phase_reserve_options
        phase.ui_recoverable_snapshot_options = phase_recoverable_options
        phase.ui_manual_inscripcio_options = []
        phase.ui_manual_team_unit_options = []
        phase.ui_available_reserve_count = sum(
            1 for option in phase_reserve_options if option.subject_ref not in phase_active_subject_refs
        )
        phase.ui_generated_partitions = [
            {
                "key": state.partition_key,
                "label": format_partition_label(state.partition_key),
                "status": state.status,
                "status_label": state.get_status_display(),
                "qualification_run_id": state.qualification_run_id,
                "source_snapshot_hash": state.source_snapshot_hash,
                "confirmed_at": state.confirmed_at,
                "warnings": list(state.warnings or []),
                "is_stale": _partition_state_is_stale(
                    state,
                    phase_qualification_stale=phase.ui_qualification_stale,
                    has_partition_states=phase.ui_has_partition_state_scope,
                ),
                "stale_label": "Particio obsoleta",
                "can_confirm": (
                    not _partition_state_is_stale(
                        state,
                        phase_qualification_stale=phase.ui_qualification_stale,
                        has_partition_states=phase.ui_has_partition_state_scope,
                    )
                    and state.status == FasePartitionState.Status.GENERATED
                ),
            }
            for state in partition_states
        ]
        phase.ui_any_partition_stale = any(partition["is_stale"] for partition in phase.ui_generated_partitions)
        for unit in units:
            slots = list(unit.slots.all())
            for slot in slots:
                active_refs = set(phase_active_subject_refs)
                if slot.subject_id and slot.status in {ProgramUnitSlot.Status.FILLED, ProgramUnitSlot.Status.MANUAL}:
                    active_refs.discard((str(slot.subject_kind or "").strip().lower(), int(slot.subject_id)))
                slot.ui_reserve_options = available_reserve_options_for_slot(
                    slot,
                    phase_reserve_options,
                    active_refs,
                )
                slot.ui_recoverable_options = available_recoverable_options_for_slot(
                    slot,
                    phase_recoverable_options,
                    active_refs,
                )
            metadata = unit.metadata if isinstance(unit.metadata, dict) else {}
            programmed_labels = programming_by_unit.get(int(unit.id), [])
            unit.ui_programmed_labels = programmed_labels
            unit.ui_is_programmed = bool(programmed_labels)
            unit.ui_filled_slots_count = sum(1 for slot in slots if slot.status != ProgramUnitSlot.Status.EMPTY)
            unit.ui_competitive_slots_count = sum(
                1
                for slot in slots
                if slot.status in {ProgramUnitSlot.Status.FILLED, ProgramUnitSlot.Status.MANUAL}
            )
            unit.ui_empty_slots_count = sum(1 for slot in slots if slot.status == ProgramUnitSlot.Status.EMPTY)
            unit.ui_slot_count = len(slots)
            unit.ui_display_name = _unit_display_name(unit)
            unit.ui_has_locked_slots = any(slot.locked for slot in slots)
            unit.ui_has_generated_slots = any(slot.source_classificacio_id for slot in slots)
            unit_partition_key = _partition_key(unit.partition_key)
            unit_partition_state = partition_states_by_key.get(unit_partition_key)
            unit.ui_partition_key = unit_partition_key
            unit.ui_partition_state = unit_partition_state
            unit.ui_partition_status = str(getattr(unit_partition_state, "status", "") or "")
            unit.ui_partition_status_label = (
                unit_partition_state.get_status_display()
                if unit_partition_state is not None
                else ""
            )
            unit.ui_partition_qualification_run_id = (
                unit_partition_state.qualification_run_id
                if unit_partition_state is not None
                else None
            )
            unit.ui_partition_is_stale = _partition_state_is_stale(
                unit_partition_state,
                phase_qualification_stale=phase.ui_qualification_stale,
                has_partition_states=phase.ui_has_partition_state_scope,
            )
            unit.ui_partition_label = format_partition_label(unit_partition_key)
            unit.ui_formation_strategy = str(metadata.get("formation_strategy") or "classification_order")
            unit.ui_formation_strategy_label = {
                "classification_order": "Ordre de classificació",
                "serpentine": "Serpentina",
                "first_last": "Primer amb últim",
                "random": "Aleatori",
            }.get(unit.ui_formation_strategy, "Ordre de classificació")
            unit.ui_group_plan_strategy = str(metadata.get("group_plan_strategy") or "")
            unit.ui_status_label = {
                ProgramUnit.Status.PLANNED: "Esborrany",
                ProgramUnit.Status.GENERATED: "Planificada",
                ProgramUnit.Status.CONFIRMED: "Confirmada",
                ProgramUnit.Status.PUBLISHED: "Publicada al portal",
            }.get(unit.status, unit.get_status_display())
            unit.ui_status_badge_class = {
                ProgramUnit.Status.PLANNED: "badge-light border",
                ProgramUnit.Status.GENERATED: "badge-info",
                ProgramUnit.Status.CONFIRMED: "badge-warning",
                ProgramUnit.Status.PUBLISHED: "badge-success",
            }.get(unit.status, "badge-light border")
            unit.ui_is_confirmed = unit.status == ProgramUnit.Status.CONFIRMED
            unit.ui_is_published = unit.status == ProgramUnit.Status.PUBLISHED
            unit.ui_can_confirm = unit.status not in {ProgramUnit.Status.CONFIRMED, ProgramUnit.Status.PUBLISHED}
            unit.ui_can_publish = (
                phase.estat != CompeticioAparellFase.Estat.CLOSED
                and not unit.ui_partition_is_stale
                and unit.ui_competitive_slots_count > 0
            )
        phase.ui_units = units
        phase.ui_unit_count = len(units)
        phase.ui_generated_unit_count = sum(1 for unit in units if unit.status == ProgramUnit.Status.GENERATED)
        phase.ui_confirmed_unit_count = sum(1 for unit in units if unit.status == ProgramUnit.Status.CONFIRMED)
        phase.ui_published_unit_count = sum(1 for unit in units if unit.status == ProgramUnit.Status.PUBLISHED)
        phase.ui_programmed_unit_count = sum(1 for unit in units if unit.ui_is_programmed)
        phase.ui_pending_unit_count = max(0, phase.ui_unit_count - phase.ui_programmed_unit_count)
        phase.ui_filled_slot_count = sum(unit.ui_filled_slots_count for unit in units)
        phase.ui_competitive_slot_count = sum(unit.ui_competitive_slots_count for unit in units)
        phase.ui_slot_count = sum(unit.ui_slot_count for unit in units)
        phase.ui_has_generated_slots = any(unit.ui_has_generated_slots for unit in units)
        phase.ui_generation_mode = "classification" if phase.ui_has_generated_slots else ("manual" if units else "none")
        phase.ui_publish_blockers = _phase_publish_blockers(phase, phase_config)
        phase.ui_can_publish = (
            phase.estat in {CompeticioAparellFase.Estat.GENERATED, CompeticioAparellFase.Estat.CONFIRMED}
            and not phase.ui_publish_blockers
        )
        phase.ui_publish_blockers_label = "; ".join(phase.ui_publish_blockers)
        phase.ui_phase_alerts = []
        if phase.ui_group_plan_stale:
            phase.ui_phase_alerts.append("Grups pendents de revisar")
        if phase.ui_any_partition_stale:
            phase.ui_phase_alerts.append("Particions obsoletes")
        if not phase.ui_has_partition_state_scope and phase.ui_qualification_source_changed:
            phase.ui_phase_alerts.append("Font canviada")
        elif not phase.ui_has_partition_state_scope and phase.ui_qualification_manual_pending:
            phase.ui_phase_alerts.append("Snapshot pendent de validar")
        if phase.ui_unit_count and not phase.ui_has_generated_slots:
            phase.ui_phase_alerts.append("Snapshot pendent")
        if not phase.ui_unit_count:
            phase.ui_phase_alerts.append("Sense unitats")
        if phase.ui_pending_unit_count:
            phase.ui_phase_alerts.append("Programacio pendent")
        phase.ui_child_count = child_counts.get(int(phase.id), 0)
        phase.ui_can_delete = phase.ui_unit_count == 0 and phase.ui_child_count == 0
        phase.ui_setup_steps = [
            {
                "label": "Fase creada",
                "state": "done",
                "detail": f"Contenidor de la ronda definit amb {phase.ui_nombre_exercicis} exercici(s).",
            },
            {
                "label": "Origen i tall",
                "state": "done" if phase.ui_source_configured and phase.ui_cut_configured else "todo",
                "detail": (
                    "Encara no hi ha classificació origen ni regla de tall desades."
                    if not (phase.ui_source_configured and phase.ui_cut_configured)
                    else (
                        f"{phase.ui_source_label} · {phase.ui_cut_label} · "
                        f"{phase.ui_partition_label} · {phase.ui_tie_policy_label}"
                    )
                ),
            },
            {
                "label": "Unitats i places",
                "state": "todo" if phase.ui_group_plan_stale else ("done" if phase.ui_unit_count and phase.ui_competitive_slot_count else ("partial" if phase.ui_unit_count else "todo")),
                "detail": (
                    "La recepta ha canviat. Revisa o regenera el pla de grups."
                    if phase.ui_group_plan_stale
                    else (
                    f"{phase.ui_competitive_slot_count}/{phase.ui_slot_count} places amb participant o equip."
                    if phase.ui_unit_count
                    else "Cap unitat competitiva creada encara."
                    )
                ),
            },
            {
                "label": "Rotacions",
                "state": "done" if phase.ui_unit_count and phase.ui_pending_unit_count == 0 else ("partial" if phase.ui_programmed_unit_count else "todo"),
                "detail": (
                    f"{phase.ui_programmed_unit_count}/{phase.ui_unit_count} unitats programades."
                    if phase.ui_unit_count
                    else "Primer cal crear unitats."
                ),
            },
        ]


def _app_summary(comp_aparell: CompeticioAparell, phases: list[CompeticioAparellFase], logo_choices: list[dict]) -> dict:
    units = [unit for phase in phases for unit in getattr(phase, "ui_units", [])]
    phase_count = len(phases)
    unit_count = len(units)
    programmed_unit_count = sum(1 for unit in units if getattr(unit, "ui_is_programmed", False))
    pending_unit_count = max(0, unit_count - programmed_unit_count)
    if phase_count == 0:
        state = "simple"
        state_label = "Mode simple"
    elif unit_count == 0:
        state = "configured"
        state_label = "Fases sense unitats"
    elif pending_unit_count:
        state = "pending_rotacions"
        state_label = "Blocs pendents"
    else:
        state = "programmed"
        state_label = "Programat"
    return {
        "app": comp_aparell,
        "phase_count": phase_count,
        "unit_count": unit_count,
        "programmed_unit_count": programmed_unit_count,
        "pending_unit_count": pending_unit_count,
        "state": state,
        "state_label": state_label,
        "logo_path": selected_logo_path_for_app(comp_aparell, logo_choices),
    }


def _attach_phase_tree(phases: list[CompeticioAparellFase], selected_phase_id: int | None = None) -> list[CompeticioAparellFase]:
    by_id = {int(phase.id): phase for phase in phases}
    roots = []
    for phase in phases:
        phase.ui_children = []
        phase.ui_depth = 0
        phase.ui_is_selected = selected_phase_id is not None and int(phase.id) == selected_phase_id
    for phase in phases:
        parent = by_id.get(int(phase.parent_id or 0))
        if parent is None:
            roots.append(phase)
        else:
            parent.ui_children.append(phase)

    def assign_depth(items, depth=0):
        for item in items:
            item.ui_depth = depth
            assign_depth(getattr(item, "ui_children", []), depth + 1)

    def attach_branch_stats(items):
        for item in items:
            children = getattr(item, "ui_children", [])
            attach_branch_stats(children)
            item.ui_branch_phase_count = 1 + sum(getattr(child, "ui_branch_phase_count", 1) for child in children)
            item.ui_branch_unit_count = getattr(item, "ui_unit_count", 0) + sum(
                getattr(child, "ui_branch_unit_count", 0)
                for child in children
            )
            item.ui_branch_programmed_unit_count = getattr(item, "ui_programmed_unit_count", 0) + sum(
                getattr(child, "ui_branch_programmed_unit_count", 0)
                for child in children
            )
            item.ui_can_delete_branch = item.ui_branch_programmed_unit_count == 0

    assign_depth(roots)
    attach_branch_stats(roots)
    return roots


def _positive_int_or_none(value):
    try:
        clean = int(value)
    except (TypeError, ValueError):
        return None
    return clean if clean > 0 else None


def _is_base_phase_token(value) -> bool:
    return str(value or "").strip().lower() == "base"


def phase_dashboard_context(competicio, *, selected_app_id=None, selected_phase_id=None) -> dict:
    comp_aparells = list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("aparell", "competicio")
        .order_by("ordre", "id")
    )
    selected_id = _positive_int_or_none(selected_app_id)
    selected = None
    if comp_aparells:
        selected = next((app for app in comp_aparells if selected_id and int(app.id) == selected_id), None) or comp_aparells[0]
    app_logo_choices = available_app_logos_for_competicio(competicio)

    programming_by_unit = _programming_by_unit(competicio)
    phases_by_app: dict[int, list[CompeticioAparellFase]] = {}
    app_summaries = []
    for comp_aparell in comp_aparells:
        phases = _phases_for_comp_aparell(comp_aparell)
        _decorate_phase_units(phases, programming_by_unit)
        phases_by_app[int(comp_aparell.id)] = phases
        app_summaries.append(_app_summary(comp_aparell, phases, app_logo_choices))

    selected_phases = phases_by_app.get(int(selected.id), []) if selected else []
    selected_base_phase = _is_base_phase_token(selected_phase_id)
    requested_phase_id = _positive_int_or_none(selected_phase_id)
    selected_phase = next(
        (phase for phase in selected_phases if requested_phase_id and int(phase.id) == requested_phase_id),
        None,
    )
    if selected_phase is not None:
        selected_base_phase = False
    selected_phase_id = int(selected_phase.id) if selected_phase is not None else None
    if selected_phase is not None:
        selected_phase.ui_manual_inscripcio_options = manual_inscripcio_options_for_phase(selected_phase)
        selected_phase.ui_manual_team_unit_options = manual_team_unit_options_for_phase(selected_phase)
    root_phases = _attach_phase_tree(selected_phases, selected_phase_id)
    selected_units = [unit for phase in selected_phases for unit in getattr(phase, "ui_units", [])]
    base_participation_preview = None
    if selected is not None:
        base_participation_preview = participation_preview(
            competicio,
            selected,
            getattr(selected, "participation_config", None),
        )
    return {
        "competicio": competicio,
        "comp_aparells": comp_aparells,
        "comp_aparell": selected,
        "selected_app_id": int(selected.id) if selected else None,
        "app_summaries": app_summaries,
        "app_logo_choices": app_logo_choices,
        "phases": selected_phases,
        "root_phases": root_phases,
        "selected_phase": selected_phase,
        "selected_phase_id": selected_phase_id,
        "selected_base_phase": selected_base_phase,
        "phase_count": len(selected_phases),
        "unit_count": len(selected_units),
        "base_participation_preview": base_participation_preview,
        "programmed_unit_count": sum(1 for unit in selected_units if getattr(unit, "ui_is_programmed", False)),
        "pending_unit_count": sum(1 for unit in selected_units if not getattr(unit, "ui_is_programmed", False)),
        "total_phase_count": sum(item["phase_count"] for item in app_summaries),
        "total_unit_count": sum(item["unit_count"] for item in app_summaries),
        "total_pending_unit_count": sum(item["pending_unit_count"] for item in app_summaries),
    }


__all__ = ["phase_dashboard_context"]
