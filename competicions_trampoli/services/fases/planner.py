from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from django.db.models import Count, Max, Prefetch

from ...models.competicio import CompeticioAparell, CompeticioAparellFase, ProgramUnit, ProgramUnitSlot
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
    fase.config = config
    fase.full_clean()
    fase.save(update_fields=["config", "updated_at"])
    return fase
