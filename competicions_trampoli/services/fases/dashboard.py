from __future__ import annotations

from collections import defaultdict

from django.db.models import Count, Prefetch

from ...models.competicio import (
    CompeticioAparell,
    CompeticioAparellFase,
    FasePartitionState,
    ProgramUnit,
    ProgramUnitSlot,
)
from ...models.rotacions import RotacioAssignacioProgramUnit
from .qualification import QualificationError, qualification_is_stale


def _time_label(value) -> str:
    if value is None:
        return ""
    try:
        return value.strftime("%H:%M")
    except Exception:
        return str(value)


def _rotacio_label(link: RotacioAssignacioProgramUnit) -> str:
    assignacio = link.assignacio
    franja = assignacio.franja
    estacio = assignacio.estacio
    interval = f"{_time_label(franja.hora_inici)}-{_time_label(franja.hora_fi)}"
    franja_label = str(getattr(franja, "display_label", "") or "Franja").strip()
    estacio_label = str(getattr(estacio, "nom", "") or "Estacio").strip()
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
                            queryset=ProgramUnitSlot.objects.order_by("slot_index", "id"),
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
        phase_config = phase.config if isinstance(phase.config, dict) else {}
        source_config = phase_config.get("source") if isinstance(phase_config.get("source"), dict) else {}
        cut_config = phase_config.get("cut") if isinstance(phase_config.get("cut"), dict) else {}
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
        if phase.ui_qualification_snapshot_hash:
            try:
                phase.ui_qualification_stale = qualification_is_stale(phase)
            except QualificationError:
                phase.ui_qualification_stale = True
        partition_states = list(phase.partition_states.all())
        phase.ui_partition_states = partition_states
        phase.ui_generated_partitions = [
            {
                "key": state.partition_key,
                "status": state.status,
                "status_label": state.get_status_display(),
                "confirmed_at": state.confirmed_at,
                "warnings": list(state.warnings or []),
                "is_stale": phase.ui_qualification_stale or state.status == FasePartitionState.Status.STALE,
                "can_confirm": (
                    not phase.ui_qualification_stale
                    and state.status == FasePartitionState.Status.GENERATED
                ),
            }
            for state in partition_states
        ]
        for unit in units:
            slots = list(unit.slots.all())
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
            unit.ui_has_generated_slots = any(slot.source_classificacio_id for slot in slots)
        phase.ui_units = units
        phase.ui_unit_count = len(units)
        phase.ui_programmed_unit_count = sum(1 for unit in units if unit.ui_is_programmed)
        phase.ui_pending_unit_count = max(0, phase.ui_unit_count - phase.ui_programmed_unit_count)
        phase.ui_filled_slot_count = sum(unit.ui_filled_slots_count for unit in units)
        phase.ui_competitive_slot_count = sum(unit.ui_competitive_slots_count for unit in units)
        phase.ui_slot_count = sum(unit.ui_slot_count for unit in units)
        phase.ui_has_generated_slots = any(unit.ui_has_generated_slots for unit in units)
        phase.ui_generation_mode = "classification" if phase.ui_has_generated_slots else ("manual" if units else "none")
        phase.ui_child_count = child_counts.get(int(phase.id), 0)
        phase.ui_can_delete = phase.ui_unit_count == 0 and phase.ui_child_count == 0
        phase.ui_setup_steps = [
            {
                "label": "Fase creada",
                "state": "done",
                "detail": "Contenidor de la ronda definit per aquest aparell.",
            },
            {
                "label": "Origen i tall",
                "state": "done" if phase.ui_source_configured and phase.ui_cut_configured else "todo",
                "detail": (
                    "Encara no hi ha classificacio origen ni regla de tall desades."
                    if not (phase.ui_source_configured and phase.ui_cut_configured)
                    else (
                        f"{phase.ui_source_label} · {phase.ui_cut_label} · "
                        f"{phase.ui_partition_label} · {phase.ui_tie_policy_label}"
                    )
                ),
            },
            {
                "label": "Unitats i places",
                "state": "done" if phase.ui_unit_count and phase.ui_competitive_slot_count else ("partial" if phase.ui_unit_count else "todo"),
                "detail": (
                    f"{phase.ui_competitive_slot_count}/{phase.ui_slot_count} places amb participant o equip."
                    if phase.ui_unit_count
                    else "Cap unitat competitiva creada encara."
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


def _app_summary(comp_aparell: CompeticioAparell, phases: list[CompeticioAparellFase]) -> dict:
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

    assign_depth(roots)
    return roots


def _positive_int_or_none(value):
    try:
        clean = int(value)
    except (TypeError, ValueError):
        return None
    return clean if clean > 0 else None


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

    programming_by_unit = _programming_by_unit(competicio)
    phases_by_app: dict[int, list[CompeticioAparellFase]] = {}
    app_summaries = []
    for comp_aparell in comp_aparells:
        phases = _phases_for_comp_aparell(comp_aparell)
        _decorate_phase_units(phases, programming_by_unit)
        phases_by_app[int(comp_aparell.id)] = phases
        app_summaries.append(_app_summary(comp_aparell, phases))

    selected_phases = phases_by_app.get(int(selected.id), []) if selected else []
    requested_phase_id = _positive_int_or_none(selected_phase_id)
    selected_phase = next(
        (phase for phase in selected_phases if requested_phase_id and int(phase.id) == requested_phase_id),
        None,
    )
    selected_phase_id = int(selected_phase.id) if selected_phase is not None else None
    root_phases = _attach_phase_tree(selected_phases, selected_phase_id)
    selected_units = [unit for phase in selected_phases for unit in getattr(phase, "ui_units", [])]
    return {
        "competicio": competicio,
        "comp_aparells": comp_aparells,
        "comp_aparell": selected,
        "selected_app_id": int(selected.id) if selected else None,
        "app_summaries": app_summaries,
        "phases": selected_phases,
        "root_phases": root_phases,
        "selected_phase": selected_phase,
        "selected_phase_id": selected_phase_id,
        "phase_count": len(selected_phases),
        "unit_count": len(selected_units),
        "programmed_unit_count": sum(1 for unit in selected_units if getattr(unit, "ui_is_programmed", False)),
        "pending_unit_count": sum(1 for unit in selected_units if not getattr(unit, "ui_is_programmed", False)),
        "total_phase_count": sum(item["phase_count"] for item in app_summaries),
        "total_unit_count": sum(item["unit_count"] for item in app_summaries),
        "total_pending_unit_count": sum(item["pending_unit_count"] for item in app_summaries),
    }


__all__ = ["phase_dashboard_context"]
