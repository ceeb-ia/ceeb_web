from __future__ import annotations

from django.contrib import messages
from django.db import IntegrityError
from django.shortcuts import get_object_or_404

from ....forms import CompeticioAparellFaseForm, PhaseSourceCutForm, ProgramUnitManualForm, ProgramUnitPartitionForm
from ....models.competicio import CompeticioAparellFase
from ....services.fases.planner import (
    create_manual_unit_for_phase,
    create_partition_unit_for_phase,
    create_phase_for_comp_aparell,
    configure_phase_source_cut,
)
from ....services.fases.qualification import (
    QualificationError,
    apply_qualification,
    confirm_qualification_partition,
    preview_as_dict,
    qualification_is_stale,
    record_qualification_preview,
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


def _apply_qualification(phase, *, replace_existing=False, allow_replace_protected=False):
    try:
        return apply_qualification(
            phase,
            replace_existing=replace_existing,
            allow_replace_protected=allow_replace_protected,
        )
    except TypeError as exc:
        if replace_existing:
            raise QualificationError("El servei encara no permet regenerar substituint unitats existents.") from exc
        raise


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
                return view.redirect_to_selected_app(selected_app, phase=phase), {}
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

        if action == "update_phase_status":
            status = str(request.POST.get("estat") or "").strip()
            valid_statuses = {choice.value for choice in CompeticioAparellFase.Estat}
            if status not in valid_statuses:
                messages.error(request, "Estat de fase no valid.")
                return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}
            phase.estat = status
            phase.full_clean()
            phase.save(update_fields=["estat", "updated_at"])
            messages.success(request, f"Estat de '{phase.nom}' actualitzat.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "configure_source_cut":
            form = PhaseSourceCutForm(request.POST, competicio=view.competicio)
            if form.is_valid():
                configure_phase_source_cut(phase, form)
                messages.success(request, f"Origen i tall de '{phase.nom}' configurats.")
                return view.redirect_to_selected_app(phase.comp_aparell), {}
            return None, {"source_cut_form": form}

        if action == "create_manual_unit":
            form = ProgramUnitManualForm(request.POST)
            if form.is_valid():
                unit = create_manual_unit_for_phase(phase, form)
                messages.success(request, f"Unitat '{unit.nom}' creada amb {unit.capacity} places.")
                return view.redirect_to_selected_app(phase.comp_aparell), {}
            return None, {"manual_unit_form": form}

        if action == "create_partition_unit":
            form = ProgramUnitPartitionForm(request.POST)
            if form.is_valid():
                units = create_partition_unit_for_phase(phase, form)
                messages.success(request, f"S'ha creat {len(units)} bloc de particio.")
                return view.redirect_to_selected_app(phase.comp_aparell), {}
            return None, {"partition_unit_form": form}

        if action == "preview_qualification":
            preview = record_qualification_preview(phase)
            summary = preview.summary()
            messages.info(
                request,
                (
                    f"Preview de '{phase.nom}': {summary['candidates']} participants/reserves, "
                    f"{summary['slots']} places i {summary['units']} unitats."
                ),
            )
            return None, {"qualification_preview": preview_as_dict(preview)}

        if action == "apply_qualification":
            preview = _apply_qualification(phase, replace_existing=False)
            summary = preview.summary()
            messages.success(
                request,
                (
                    f"Tall congelat per '{phase.nom}': {summary['candidates']} participants/reserves "
                    f"en {summary['units']} unitats."
                ),
            )
            return view.redirect_to_selected_app(phase.comp_aparell), {}

        if action == "confirm_partition":
            partition_key = request.POST.get("partition_key") or ""
            state = confirm_qualification_partition(phase, partition_key)
            messages.success(request, f"Particio '{state.partition_key}' confirmada per '{phase.nom}'.")
            return view.redirect_to_selected_app(phase.comp_aparell), {}

        if action == "regenerate_qualification":
            if request.POST.get("confirm_regeneration") != "1":
                messages.error(request, "Cal confirmar explicitament la regeneracio abans de substituir la proposta.")
                return view.redirect_to_selected_app(phase.comp_aparell), {}
            is_stale = qualification_is_stale(phase)
            preview = _apply_qualification(
                phase,
                replace_existing=True,
                allow_replace_protected=request.POST.get("confirm_replace_protected") == "1",
            )
            summary = preview.summary()
            stale_label = "actualitzada" if is_stale else "regenerada"
            messages.success(
                request,
                (
                    f"Proposta {stale_label} per '{phase.nom}': {summary['candidates']} participants/reserves "
                    f"en {summary['units']} unitats."
                ),
            )
            return view.redirect_to_selected_app(phase.comp_aparell), {}

        messages.error(request, "Accio no reconeguda.")
        return view.redirect_to_selected_app(selected_app), {}
    except IntegrityError:
        messages.error(request, "No s'ha pogut completar l'accio per una restriccio d'unicitat.")
        return view.redirect_to_selected_app(selected_app), {}
    except QualificationError as exc:
        messages.error(request, str(exc))
        return view.redirect_to_selected_app(selected_app), {}
    except ValueError as exc:
        messages.error(request, str(exc))
        return view.redirect_to_selected_app(selected_app), {}


__all__ = ["handle_phase_post"]
