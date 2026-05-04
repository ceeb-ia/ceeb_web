from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Count, Prefetch

from ...models.competicio import CompeticioAparell, CompeticioAparellFase, ProgramUnit, ProgramUnitSlot
from .defaults import ensure_default_phase_for_comp_aparell
from .program_units import (
    create_program_unit_with_empty_slots,
    create_units_from_base_groups,
    create_units_one_per_partition,
)


@dataclass(frozen=True)
class PlannerActionResult:
    ok: bool
    message: str


def phase_planner_context(comp_aparell: CompeticioAparell) -> dict:
    ensure_default_phase_for_comp_aparell(comp_aparell)
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
                            queryset=ProgramUnitSlot.objects.order_by("slot_index", "id"),
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


def create_phase_for_comp_aparell(comp_aparell: CompeticioAparell, form) -> CompeticioAparellFase:
    phase = form.save(commit=False)
    phase.competicio = comp_aparell.competicio
    phase.comp_aparell = comp_aparell
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


def generate_base_group_units_for_phase(fase: CompeticioAparellFase) -> list[ProgramUnit]:
    return create_units_from_base_groups(fase)
