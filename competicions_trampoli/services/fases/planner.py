from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from django.db.models import Count, Max, Prefetch

from ...models.competicio import CompeticioAparell, CompeticioAparellFase, ProgramUnit, ProgramUnitSlot
from .group_plan import structural_cut_signature
from .program_units import (
    create_program_unit_with_empty_slots,
    create_units_one_per_partition,
)


@dataclass(frozen=True)
class PlannerActionResult:
    ok: bool
    message: str


def phase_planner_context(comp_aparell: CompeticioAparell) -> dict:
    phases = list(
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
                            queryset=ProgramUnitSlot.objects.order_by("ordre", "slot_index", "id"),
                        )
                    )
                    .order_by("ordre", "id")
                ),
            )
        )
        .order_by("ordre", "id")
    )
    return {
        "phases": phases,
        "phase_count": len(phases),
        "unit_count": sum(len(list(phase.program_units.all())) for phase in phases),
    }


def _next_sibling_phase_order(comp_aparell: CompeticioAparell, parent) -> int:
    siblings = CompeticioAparellFase.objects.filter(
        competicio=comp_aparell.competicio,
        comp_aparell=comp_aparell,
    )
    if parent is None:
        siblings = siblings.filter(parent__isnull=True)
    else:
        siblings = siblings.filter(parent=parent)
    max_order = siblings.aggregate(max_order=Max("ordre")).get("max_order") or 0
    return int(max_order) + 1


def create_phase_for_comp_aparell(comp_aparell: CompeticioAparell, form) -> CompeticioAparellFase:
    phase = form.save(commit=False)
    phase.competicio = comp_aparell.competicio
    phase.comp_aparell = comp_aparell
    explicit_order = form.cleaned_data.get("ordre")
    if explicit_order in (None, ""):
        phase.ordre = _next_sibling_phase_order(comp_aparell, phase.parent)
    else:
        phase.ordre = explicit_order
    phase.full_clean()
    phase.save()
    return phase


def create_manual_unit_for_phase(fase: CompeticioAparellFase, form) -> ProgramUnit:
    unit = create_program_unit_with_empty_slots(
        fase=fase,
        nom=form.cleaned_data["nom"],
        capacity=form.cleaned_data["capacity"],
        tipus=form.cleaned_data["tipus"],
        partition_key=form.cleaned_data.get("partition_key") or "",
        status=ProgramUnit.Status.PLANNED,
    )
    return unit


def create_partition_unit_for_phase(fase: CompeticioAparellFase, form) -> list[ProgramUnit]:
    return create_units_one_per_partition(
        fase=fase,
        default_capacity=form.cleaned_data["capacity"],
        partitions=[
            {
                "key": form.cleaned_data["key"],
                "label": form.cleaned_data["label"],
                "capacity": form.cleaned_data["capacity"],
                "values": {"key": form.cleaned_data["key"]},
            }
        ],
    )


def configure_phase_source_cut(fase: CompeticioAparellFase, form) -> CompeticioAparellFase:
    classificacio = form.cleaned_data["classificacio"]
    config = deepcopy(fase.config if isinstance(fase.config, dict) else {})
    old_group_plan = config.get("group_plan") if isinstance(config.get("group_plan"), dict) else {}
    old_cut_signature = structural_cut_signature(config.get("cut") if isinstance(config.get("cut"), dict) else {})
    config["source"] = {
        "classificacio_id": int(classificacio.id),
        "classificacio_nom": classificacio.nom,
        "tipus": classificacio.tipus,
    }
    config["cut"] = {
        "mode": form.cleaned_data["cut_mode"],
        "qualifiers_count": int(form.cleaned_data["qualifiers_count"]),
        "reserve_count": int(form.cleaned_data.get("reserve_count") or 0),
        "partition_mode": form.cleaned_data["partition_mode"],
        "tie_policy": form.cleaned_data["tie_policy"],
        "unit_capacity": int(form.cleaned_data["unit_capacity"]),
        "unit_name_template": form.cleaned_data["unit_name_template"],
    }
    new_cut_signature = structural_cut_signature(config["cut"])
    if (old_group_plan or fase.program_units.exists()) and old_cut_signature != new_cut_signature:
        old_group_plan["stale"] = True
        old_group_plan["stale_reason"] = "La recepta d'origen i tall ha canviat."
        old_group_plan["current_cut_signature"] = new_cut_signature
        config["group_plan"] = old_group_plan
    fase.config = config
    fase.full_clean()
    fase.save(update_fields=["config", "updated_at"])
    return fase


def configure_phase_group_plan(fase: CompeticioAparellFase, form) -> CompeticioAparellFase:
    config = deepcopy(fase.config if isinstance(fase.config, dict) else {})
    config["group_plan_settings"] = {
        "split_mode": form.cleaned_data["split_mode"],
        "units_per_partition": int(form.cleaned_data["units_per_partition"]),
        "unit_capacity": int(form.cleaned_data["unit_capacity"]),
        "formation_strategy": form.cleaned_data["formation_strategy"],
        "unit_name_template": form.cleaned_data["unit_name_template"],
    }
    fase.config = config
    fase.full_clean()
    fase.save(update_fields=["config", "updated_at"])
    return fase


def configure_phase_scoring_settings(fase: CompeticioAparellFase, form) -> CompeticioAparellFase:
    config = deepcopy(fase.config if isinstance(fase.config, dict) else {})
    scoring = deepcopy(config.get("scoring") if isinstance(config.get("scoring"), dict) else {})
    scoring["nombre_exercicis"] = int(form.cleaned_data["nombre_exercicis"])
    config["scoring"] = scoring
    fase.config = config
    fase.full_clean()
    fase.save(update_fields=["config", "updated_at"])
    return fase


def update_program_unit_for_phase(fase: CompeticioAparellFase, form) -> ProgramUnit:
    unit_id = int(form.cleaned_data["unit_id"])
    unit = ProgramUnit.objects.get(fase=fase, id=unit_id)
    new_capacity = int(form.cleaned_data["capacity"])
    old_slots = list(unit.slots.order_by("ordre", "slot_index", "id"))
    old_capacity = len(old_slots)
    if new_capacity < old_capacity:
        removable = [
            slot for slot in reversed(old_slots)
            if not slot.locked and slot.status == ProgramUnitSlot.Status.EMPTY
        ]
        to_remove = old_capacity - new_capacity
        if len(removable) < to_remove:
            raise ValueError("No es poden eliminar places ja omplertes, manuals o bloquejades.")
        for slot in removable[:to_remove]:
            slot.delete()
    elif new_capacity > old_capacity:
        max_slot_index = max([slot.slot_index for slot in old_slots] or [0])
        max_ordre = max([slot.ordre for slot in old_slots] or [0])
        ProgramUnitSlot.objects.bulk_create(
            [
                ProgramUnitSlot(
                    unit=unit,
                    slot_index=index,
                    ordre=max_ordre + offset,
                    status=ProgramUnitSlot.Status.EMPTY,
                )
                for offset, index in enumerate(
                    range(max_slot_index + 1, max_slot_index + (new_capacity - old_capacity) + 1),
                    start=1,
                )
            ]
        )

    metadata = unit.metadata if isinstance(unit.metadata, dict) else {}
    metadata["formation_strategy"] = form.cleaned_data["formation_strategy"]
    unit.nom = form.cleaned_data["nom"]
    unit.capacity = new_capacity
    unit.metadata = metadata
    unit.full_clean()
    unit.save(update_fields=["nom", "capacity", "metadata", "updated_at"])
    return unit
