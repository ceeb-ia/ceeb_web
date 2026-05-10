from __future__ import annotations

from django.contrib import messages
from django.db import IntegrityError
from django.shortcuts import get_object_or_404

from ....forms import CompeticioAparellFaseForm, ProgramUnitManualForm, ProgramUnitPartitionForm
from ....models.competicio import CompeticioAparellFase
from ....services.fases.planner import (
    create_manual_unit_for_phase,
    create_partition_unit_for_phase,
    create_phase_for_comp_aparell,
)


def phase_for_post(competicio, request):
    phase_id = request.POST.get("fase_id")
    if not phase_id:
        return None
    return get_object_or_404(
        CompeticioAparellFase,
        pk=phase_id,
        competicio=competicio,
    )


def handle_phase_post(view, request):
    action = str(request.POST.get("action") or "").strip()
    selected_app = view.comp_aparell
    try:
        if action == "create_phase":
            if selected_app is None:
                messages.error(request, "Selecciona un aparell abans de crear fases.")
                return None, {"phase_form": CompeticioAparellFaseForm(request.POST)}
            form = CompeticioAparellFaseForm(request.POST, comp_aparell=selected_app)
            if form.is_valid():
                phase = create_phase_for_comp_aparell(selected_app, form)
                messages.success(request, f"Fase '{phase.nom}' creada.")
                return view.redirect_to_selected_app(selected_app), {}
            return None, {"phase_form": form}

        phase = phase_for_post(view.competicio, request)
        if phase is None:
            messages.error(request, "Selecciona una fase.")
            return view.redirect_to_selected_app(selected_app), {}

        view.comp_aparell = phase.comp_aparell

        if action == "delete_phase":
            if phase.children.exists():
                messages.error(request, "No es pot eliminar una fase que te fases filles.")
                return view.redirect_to_selected_app(phase.comp_aparell), {}
            if phase.program_units.exists():
                messages.error(request, "No es pot eliminar una fase que te blocs previstos.")
                return view.redirect_to_selected_app(phase.comp_aparell), {}
            phase_name = phase.nom
            phase.delete()
            messages.success(request, f"Fase '{phase_name}' eliminada.")
            return view.redirect_to_selected_app(view.comp_aparell), {}

        if action == "create_manual_unit":
            form = ProgramUnitManualForm(request.POST)
            if form.is_valid():
                unit = create_manual_unit_for_phase(phase, form)
                messages.success(request, f"Bloc '{unit.nom}' creat amb {unit.capacity} slots.")
                return view.redirect_to_selected_app(phase.comp_aparell), {}
            return None, {"manual_unit_form": form}

        if action == "create_partition_unit":
            form = ProgramUnitPartitionForm(request.POST)
            if form.is_valid():
                units = create_partition_unit_for_phase(phase, form)
                messages.success(request, f"S'ha creat {len(units)} bloc de particio.")
                return view.redirect_to_selected_app(phase.comp_aparell), {}
            return None, {"partition_unit_form": form}

        messages.error(request, "Accio no reconeguda.")
        return view.redirect_to_selected_app(selected_app), {}
    except IntegrityError:
        messages.error(request, "No s'ha pogut completar l'accio per una restriccio d'unicitat.")
        return view.redirect_to_selected_app(selected_app), {}
    except ValueError as exc:
        messages.error(request, str(exc))
        return view.redirect_to_selected_app(selected_app), {}


__all__ = ["handle_phase_post"]
