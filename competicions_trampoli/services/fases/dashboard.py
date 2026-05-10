from __future__ import annotations

from collections import defaultdict

from django.db.models import Count, Prefetch

from ...models.competicio import CompeticioAparell, CompeticioAparellFase, ProgramUnit, ProgramUnitSlot
from ...models.rotacions import RotacioAssignacioProgramUnit


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
        for unit in units:
            slots = list(unit.slots.all())
            programmed_labels = programming_by_unit.get(int(unit.id), [])
            unit.ui_programmed_labels = programmed_labels
            unit.ui_is_programmed = bool(programmed_labels)
            unit.ui_filled_slots_count = sum(1 for slot in slots if slot.status != ProgramUnitSlot.Status.EMPTY)
            unit.ui_empty_slots_count = sum(1 for slot in slots if slot.status == ProgramUnitSlot.Status.EMPTY)
        phase.ui_units = units
        phase.ui_unit_count = len(units)
        phase.ui_programmed_unit_count = sum(1 for unit in units if unit.ui_is_programmed)
        phase.ui_pending_unit_count = max(0, phase.ui_unit_count - phase.ui_programmed_unit_count)
        phase.ui_child_count = child_counts.get(int(phase.id), 0)
        phase.ui_can_delete = phase.ui_unit_count == 0 and phase.ui_child_count == 0


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
        state_label = "Fases sense blocs"
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


def _positive_int_or_none(value):
    try:
        clean = int(value)
    except (TypeError, ValueError):
        return None
    return clean if clean > 0 else None


def phase_dashboard_context(competicio, *, selected_app_id=None) -> dict:
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
    selected_units = [unit for phase in selected_phases for unit in getattr(phase, "ui_units", [])]
    return {
        "competicio": competicio,
        "comp_aparells": comp_aparells,
        "comp_aparell": selected,
        "selected_app_id": int(selected.id) if selected else None,
        "app_summaries": app_summaries,
        "phases": selected_phases,
        "phase_count": len(selected_phases),
        "unit_count": len(selected_units),
        "programmed_unit_count": sum(1 for unit in selected_units if getattr(unit, "ui_is_programmed", False)),
        "pending_unit_count": sum(1 for unit in selected_units if not getattr(unit, "ui_is_programmed", False)),
        "total_phase_count": sum(item["phase_count"] for item in app_summaries),
        "total_unit_count": sum(item["unit_count"] for item in app_summaries),
        "total_pending_unit_count": sum(item["pending_unit_count"] for item in app_summaries),
    }


__all__ = ["phase_dashboard_context"]
