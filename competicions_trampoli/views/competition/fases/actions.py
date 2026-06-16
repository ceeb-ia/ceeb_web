from __future__ import annotations

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404

from ....forms import (
    CompeticioAparellFaseForm,
    PhaseGroupPlanForm,
    PhaseScoringSettingsForm,
    PhaseSourceCutForm,
    ProgramUnitEditForm,
    ProgramUnitManualForm,
    ProgramUnitPartitionForm,
)
from ....models.competicio import CompeticioAparell, CompeticioAparellFase, ProgramUnit, ProgramUnitSlot
from ....services.fases.group_plan import structural_cut_signature
from ....services.fases.logos import logo_choice_paths
from ....services.fases.planner import (
    configure_phase_group_plan,
    configure_phase_scoring_settings,
    create_manual_unit_for_phase,
    create_partition_unit_for_phase,
    create_phase_for_comp_aparell,
    configure_phase_source_cut,
    update_program_unit_for_phase,
)
from ....services.fases.qualification import (
    QualificationError,
    accept_current_qualification_snapshot,
    apply_qualification,
    confirm_qualification_partition,
    preview_as_dict,
    qualification_is_stale,
    record_qualification_preview,
)
from ....services.fases.slot_overrides import (
    SlotOverrideError,
    add_extra_slot_to_unit,
    assign_inscripcio_to_slot,
    assign_reserve_to_slot,
    assign_snapshot_candidate_to_slot,
    assign_team_unit_to_slot,
    clear_program_unit_slots,
    clear_slot_assignment,
    delete_program_slot,
    mark_slot_withdrawn,
    reorder_program_unit_slots,
)
from ....services.fases import apply_group_plan, group_plan_as_dict, preview_group_plan


USER_PHASE_STATUSES = {
    CompeticioAparellFase.Estat.PLANNED,
    CompeticioAparellFase.Estat.PUBLISHED,
    CompeticioAparellFase.Estat.CLOSED,
}


def _group_plan_is_stale(phase):
    config = phase.config if isinstance(phase.config, dict) else {}
    group_plan = config.get("group_plan") if isinstance(config.get("group_plan"), dict) else {}
    cut = config.get("cut") if isinstance(config.get("cut"), dict) else {}
    stored = str(group_plan.get("cut_signature") or "").strip()
    return bool(group_plan.get("stale") or (stored and stored != structural_cut_signature(cut)))


def _publish_blockers(phase) -> list[str]:
    blockers = []
    if _group_plan_is_stale(phase):
        blockers.append("revisa o regenera el pla de grups")
    if not phase.program_units.exists():
        blockers.append("genera unitats de grups")
    elif not ProgramUnitSlot.objects.filter(
        unit__fase=phase,
        status__in=[ProgramUnitSlot.Status.FILLED, ProgramUnitSlot.Status.MANUAL],
        subject_id__isnull=False,
    ).exists():
        blockers.append("omple almenys una unitat amb participants/equips")
    config = phase.config if isinstance(phase.config, dict) else {}
    qualification = config.get("qualification") if isinstance(config.get("qualification"), dict) else {}
    if not qualification.get("run_id"):
        blockers.append("congela el snapshot")
    elif qualification.get("stale") or qualification_is_stale(phase):
        blockers.append("recalcula el snapshot")
    if phase.partition_states.filter(status="stale").exists():
        blockers.append("revisa les particions obsoletes")
    return blockers


def _phase_snapshot_is_stale(phase) -> bool:
    config = phase.config if isinstance(phase.config, dict) else {}
    qualification = config.get("qualification") if isinstance(config.get("qualification"), dict) else {}
    return bool(qualification.get("stale") or (qualification.get("run_id") and qualification_is_stale(phase)))


def _phase_has_applied_snapshot(phase) -> bool:
    config = phase.config if isinstance(phase.config, dict) else {}
    qualification = config.get("qualification") if isinstance(config.get("qualification"), dict) else {}
    return bool(qualification.get("run_id"))


def _phase_is_draft(phase) -> bool:
    return phase.estat not in {
        CompeticioAparellFase.Estat.PUBLISHED,
        CompeticioAparellFase.Estat.CLOSED,
    }


def _unit_has_scoreable_subjects(unit) -> bool:
    return unit.slots.filter(
        status__in=[ProgramUnitSlot.Status.FILLED, ProgramUnitSlot.Status.MANUAL],
        subject_id__isnull=False,
    ).exists()


def _unit_publish_blockers(phase, unit) -> list[str]:
    blockers = []
    if phase.estat == CompeticioAparellFase.Estat.CLOSED:
        blockers.append("la fase esta tancada")
    if _phase_snapshot_is_stale(phase):
        blockers.append("recalcula el snapshot")
    if phase.partition_states.filter(status="stale").exists():
        blockers.append("revisa les particions obsoletes")
    if not _unit_has_scoreable_subjects(unit):
        blockers.append("la unitat no te places amb participant/equip")
    return blockers


def _set_phase_status_after_unit_change(phase) -> None:
    if phase.estat in {
        CompeticioAparellFase.Estat.CLOSED,
        CompeticioAparellFase.Estat.PUBLISHED,
        CompeticioAparellFase.Estat.STALE,
    }:
        return
    if phase.program_units.filter(status=ProgramUnit.Status.PUBLISHED).exists():
        phase.estat = CompeticioAparellFase.Estat.PARTIALLY_CONFIRMED
        phase.save(update_fields=["estat", "updated_at"])


def _publish_units_for_phase(phase) -> int:
    blockers = _publish_blockers(phase)
    if blockers:
        raise QualificationError("No es pot publicar encara: " + "; ".join(blockers) + ".")
    unit_ids = [
        unit.id
        for unit in ProgramUnit.objects.filter(fase=phase).prefetch_related("slots").order_by("ordre", "id")
        if _unit_has_scoreable_subjects(unit)
    ]
    if not unit_ids:
        raise QualificationError("No hi ha cap unitat amb places puntuables per publicar.")
    return ProgramUnit.objects.filter(fase=phase, id__in=unit_ids).update(status=ProgramUnit.Status.PUBLISHED)


def phase_for_post(competicio, request):
    phase_id = request.POST.get("fase_id")
    if not phase_id:
        return None
    return get_object_or_404(
        CompeticioAparellFase,
        pk=phase_id,
        competicio=competicio,
    )


def _phase_branch_delete_order(phase) -> list[int]:
    phases = list(
        CompeticioAparellFase.objects
        .filter(competicio=phase.competicio, comp_aparell=phase.comp_aparell)
        .only("id", "parent_id")
    )
    children_by_parent: dict[int, list[int]] = {}
    for item in phases:
        if item.parent_id:
            children_by_parent.setdefault(int(item.parent_id), []).append(int(item.id))

    ordered: list[int] = []

    def visit(phase_id: int) -> None:
        for child_id in children_by_parent.get(phase_id, []):
            visit(child_id)
        ordered.append(phase_id)

    visit(int(phase.id))
    return ordered


def _programmed_units_in_branch(phase_ids: list[int]):
    return (
        ProgramUnit.objects
        .filter(fase_id__in=phase_ids, rotacio_links__isnull=False)
        .distinct()
        .order_by("fase__ordre", "ordre", "id")
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
        if action == "update_base_scoring_settings":
            comp_aparell_id = request.POST.get("comp_aparell_id")
            comp_aparell = get_object_or_404(
                CompeticioAparell,
                pk=comp_aparell_id,
                competicio=view.competicio,
            )
            try:
                nombre_exercicis = int(request.POST.get("nombre_exercicis") or 1)
            except (TypeError, ValueError):
                nombre_exercicis = 0
            if nombre_exercicis < 1 or nombre_exercicis > 5:
                messages.error(request, "El nombre d'exercicis de la preliminar ha de ser entre 1 i 5.")
                return view.redirect_to_selected_app(comp_aparell), {}
            comp_aparell.nombre_exercicis = nombre_exercicis
            comp_aparell.full_clean()
            comp_aparell.save(update_fields=["nombre_exercicis"])
            messages.success(request, f"Exercicis de la preliminar de '{comp_aparell.display_nom}' actualitzats.")
            return view.redirect_to_selected_app(comp_aparell), {}

        if action == "update_app_phase_logo":
            comp_aparell_id = request.POST.get("comp_aparell_id")
            comp_aparell = get_object_or_404(
                CompeticioAparell,
                pk=comp_aparell_id,
                competicio=view.competicio,
            )
            logo_path = str(request.POST.get("logo_path") or "").strip()
            if logo_path not in logo_choice_paths(view.competicio):
                messages.error(request, "Logo d'aparell no vàlid per aquesta competició.")
                return view.redirect_to_selected_app(comp_aparell), {}
            config = comp_aparell.judge_ui_config if isinstance(comp_aparell.judge_ui_config, dict) else {}
            config["phase_planner_logo"] = logo_path
            comp_aparell.judge_ui_config = config
            comp_aparell.full_clean()
            comp_aparell.save(update_fields=["judge_ui_config"])
            messages.success(request, f"Logo de '{comp_aparell.display_nom}' actualitzat.")
            return view.redirect_to_selected_app(comp_aparell), {}

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
                messages.error(request, "No es pot eliminar una fase que té fases filles.")
                return view.redirect_to_selected_app(phase.comp_aparell), {}
            if phase.program_units.exists():
                messages.error(request, "No es pot eliminar una fase que té blocs previstos.")
                return view.redirect_to_selected_app(phase.comp_aparell), {}
            phase_name = phase.nom
            phase.delete()
            messages.success(request, f"Fase '{phase_name}' eliminada.")
            return view.redirect_to_selected_app(view.comp_aparell, phase="base"), {}

        if action == "delete_phase_branch":
            if request.POST.get("confirm_branch_delete") != "1":
                messages.error(request, "Cal confirmar l'eliminació de la branca.")
                return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}
            branch_phase_ids = _phase_branch_delete_order(phase)
            programmed_units = _programmed_units_in_branch(branch_phase_ids)
            if programmed_units.exists():
                sample = list(programmed_units.values_list("nom", flat=True)[:3])
                suffix = f": {', '.join(sample)}" if sample else ""
                messages.error(
                    request,
                    "No es pot eliminar aquesta branca perquè té unitats programades a rotacions" + suffix + ".",
                )
                return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}
            phase_name = phase.nom
            phase_count = len(branch_phase_ids)
            try:
                with transaction.atomic():
                    for phase_id in branch_phase_ids:
                        CompeticioAparellFase.objects.get(pk=phase_id).delete()
            except ProtectedError:
                messages.error(
                    request,
                    "No es pot eliminar aquesta branca perquè alguna fase ja té dades protegides.",
                )
                return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}
            messages.success(request, f"Branca '{phase_name}' eliminada ({phase_count} fase/s).")
            return view.redirect_to_selected_app(view.comp_aparell, phase="base"), {}

        if action == "update_phase_status":
            status = str(request.POST.get("estat") or "").strip()
            if status not in USER_PHASE_STATUSES:
                messages.error(request, "Estat de fase no vàlid.")
                return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}
            if status == CompeticioAparellFase.Estat.PUBLISHED:
                published_count = _publish_units_for_phase(phase)
            else:
                published_count = 0
            phase.estat = status
            phase.full_clean()
            phase.save(update_fields=["estat", "updated_at"])
            if status == CompeticioAparellFase.Estat.PUBLISHED:
                messages.success(request, f"Fase '{phase.nom}' publicada amb {published_count} unitat/s visibles al portal.")
            else:
                messages.success(request, f"Estat de '{phase.nom}' actualitzat.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "configure_source_cut":
            form = PhaseSourceCutForm(request.POST, competicio=view.competicio, fase=phase)
            if form.is_valid():
                try:
                    configure_phase_source_cut(phase, form)
                except QualificationError as exc:
                    form.add_error("classificacio", str(exc))
                    return None, {"source_cut_form": form}
                messages.success(request, f"Origen i tall de '{phase.nom}' configurats.")
                return view.redirect_to_selected_app(phase.comp_aparell), {}
            return None, {"source_cut_form": form}

        if action == "update_phase_scoring_settings":
            form = PhaseScoringSettingsForm(request.POST)
            if form.is_valid():
                configure_phase_scoring_settings(phase, form)
                messages.success(request, f"Exercicis de '{phase.nom}' actualitzats.")
                return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}
            messages.error(request, "Revisa el nombre d'exercicis de la fase.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

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
                messages.success(request, f"S'ha creat {len(units)} bloc de partició.")
                return view.redirect_to_selected_app(phase.comp_aparell), {}
            return None, {"partition_unit_form": form}

        if action == "update_program_unit":
            form = ProgramUnitEditForm(request.POST)
            if form.is_valid():
                unit = update_program_unit_for_phase(phase, form)
                messages.success(request, f"Unitat '{unit.nom}' actualitzada.")
                return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}
            messages.error(request, "Revisa la configuració de la unitat.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "delete_program_unit":
            unit_id = request.POST.get("unit_id")
            unit = get_object_or_404(ProgramUnit, pk=unit_id, fase=phase)
            if unit.rotacio_links.exists():
                messages.error(request, "No es pot eliminar una unitat que ja està programada a rotacions.")
                return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}
            unit_name = unit.nom
            unit.delete()
            messages.success(request, f"Unitat '{unit_name}' eliminada.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "confirm_program_unit":
            unit_id = request.POST.get("unit_id")
            unit = get_object_or_404(ProgramUnit, pk=unit_id, fase=phase)
            if unit.status != ProgramUnit.Status.PUBLISHED:
                unit.status = ProgramUnit.Status.CONFIRMED
                unit.save(update_fields=["status", "updated_at"])
            messages.success(request, f"Unitat '{unit.nom}' confirmada. Encara no es mostra al portal.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "publish_program_unit":
            unit_id = request.POST.get("unit_id")
            unit = get_object_or_404(ProgramUnit, pk=unit_id, fase=phase)
            blockers = _unit_publish_blockers(phase, unit)
            if blockers:
                messages.error(request, "No es pot publicar la unitat encara: " + "; ".join(blockers) + ".")
                return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}
            unit.status = ProgramUnit.Status.PUBLISHED
            unit.save(update_fields=["status", "updated_at"])
            _set_phase_status_after_unit_change(phase)
            messages.success(request, f"Unitat '{unit.nom}' publicada al portal de jutges.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "unpublish_program_unit":
            unit_id = request.POST.get("unit_id")
            unit = get_object_or_404(ProgramUnit, pk=unit_id, fase=phase)
            if unit.status == ProgramUnit.Status.PUBLISHED:
                unit.status = ProgramUnit.Status.CONFIRMED if _unit_has_scoreable_subjects(unit) else ProgramUnit.Status.GENERATED
                unit.save(update_fields=["status", "updated_at"])
            messages.success(request, f"Unitat '{unit.nom}' retirada del portal de jutges.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "add_extra_program_slot":
            unit_id = int(request.POST.get("unit_id") or 0)
            slot = add_extra_slot_to_unit(phase, unit_id)
            messages.success(request, f"Plaça extra afegida a '{slot.unit.nom}' en ordre {slot.ordre}.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "reorder_program_unit_slots":
            unit_id = int(request.POST.get("unit_id") or 0)
            raw_order = str(request.POST.get("slot_order") or "").strip()
            ordered_slot_ids = [int(item) for item in raw_order.split(",") if item.strip().isdigit()]
            unit = reorder_program_unit_slots(phase, unit_id, ordered_slot_ids)
            messages.success(request, f"Ordre de places actualitzat a '{unit.nom}'.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "clear_program_unit_slots":
            if not _phase_is_draft(phase):
                messages.error(request, "Només es poden buidar places mentre la fase està en esborrany.")
                return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}
            unit_id = int(request.POST.get("unit_id") or 0)
            unit, cleared_count = clear_program_unit_slots(phase, unit_id)
            messages.success(request, f"{cleared_count} places buidades a '{unit.nom}'.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "assign_reserve_to_slot":
            slot_id = int(request.POST.get("slot_id") or 0)
            reserve_key = str(request.POST.get("reserve_key") or "").strip()
            slot = assign_reserve_to_slot(phase, slot_id, reserve_key)
            messages.success(request, f"Reserva assignada a '{slot.unit.nom}' en ordre {slot.ordre}.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "assign_snapshot_candidate_to_slot":
            slot_id = int(request.POST.get("slot_id") or 0)
            candidate_key = str(request.POST.get("candidate_key") or "").strip()
            slot = assign_snapshot_candidate_to_slot(phase, slot_id, candidate_key)
            messages.success(request, f"Candidat recuperat a '{slot.unit.nom}' en ordre {slot.ordre}.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "assign_inscripcio_to_slot":
            slot_id = int(request.POST.get("slot_id") or 0)
            inscripcio_id = int(request.POST.get("inscripcio_id") or 0)
            slot = assign_inscripcio_to_slot(phase, slot_id, inscripcio_id)
            messages.success(request, f"Inscripció assignada manualment a '{slot.unit.nom}' en ordre {slot.ordre}.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "assign_team_unit_to_slot":
            slot_id = int(request.POST.get("slot_id") or 0)
            team_subject_id = int(request.POST.get("team_subject_id") or 0)
            slot = assign_team_unit_to_slot(phase, slot_id, team_subject_id)
            messages.success(request, f"Equip assignat manualment a '{slot.unit.nom}' en ordre {slot.ordre}.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "mark_slot_withdrawn":
            slot_id = int(request.POST.get("slot_id") or 0)
            slot = mark_slot_withdrawn(phase, slot_id)
            messages.success(request, f"Baixa marcada a '{slot.unit.nom}' en ordre {slot.ordre}.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "clear_slot_assignment":
            slot_id = int(request.POST.get("slot_id") or 0)
            slot = clear_slot_assignment(phase, slot_id)
            messages.success(request, f"Plaça buidada a '{slot.unit.nom}' en ordre {slot.ordre}.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "delete_program_slot":
            slot_id = int(request.POST.get("slot_id") or 0)
            unit, ordre = delete_program_slot(phase, slot_id)
            messages.success(request, f"Plaça d'ordre {ordre} eliminada de '{unit.nom}'.")
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "accept_current_qualification_snapshot":
            preview = accept_current_qualification_snapshot(phase)
            summary = preview.summary()
            messages.success(
                request,
                f"Snapshot actual validat: {summary['candidates']} participants/reserves i {summary['slots']} places.",
            )
            return view.redirect_to_selected_app(phase.comp_aparell, phase=phase), {}

        if action == "preview_group_plan":
            form = PhaseGroupPlanForm(request.POST)
            if not form.is_valid():
                return None, {"group_plan_form": form}
            configure_phase_group_plan(phase, form)
            preview = preview_group_plan(phase)
            summary = preview.summary()
            messages.info(
                request,
                (
                    f"Pla de grups de '{phase.nom}': "
                    f"{summary.get('units', 0)} unitats buides i {summary.get('slots', 0)} places."
                ),
            )
            return None, {"group_plan_preview": group_plan_as_dict(preview)}

        if action == "apply_group_plan":
            form = PhaseGroupPlanForm(request.POST)
            if not form.is_valid():
                return None, {"group_plan_form": form}
            configure_phase_group_plan(phase, form)
            preview = apply_group_plan(
                phase,
                replace_existing=request.POST.get("replace_existing") == "1",
                allow_replace_protected=request.POST.get("allow_replace_protected") == "1",
            )
            summary = preview.summary()
            messages.success(
                request,
                (
                    f"Unitats buides generades per '{phase.nom}': "
                    f"{summary.get('units', 0)} unitats i {summary.get('slots', 0)} places."
                ),
            )
            return view.redirect_to_selected_app(phase.comp_aparell), {}

        if action == "preview_qualification":
            preview = record_qualification_preview(phase)
            summary = preview.summary()
            messages.info(
                request,
                (
                    f"Snapshot previst de '{phase.nom}': {summary['candidates']} participants/reserves "
                    f"per omplir {summary['slots']} places existents."
                ),
            )
            return None, {"qualification_preview": preview_as_dict(preview)}

        if action == "apply_qualification":
            has_snapshot = _phase_has_applied_snapshot(phase)
            preview = _apply_qualification(phase, replace_existing=has_snapshot)
            summary = preview.summary()
            action_label = "actualitzat" if has_snapshot else "congelat"
            messages.success(
                request,
                (
                    f"Snapshot {action_label} per '{phase.nom}': {summary['candidates']} participants/reserves "
                    f"assignats als slots existents. Fase planificada i llesta per publicar."
                ),
            )
            return view.redirect_to_selected_app(phase.comp_aparell), {}

        if action == "confirm_partition":
            partition_key = request.POST.get("partition_key") or ""
            state = confirm_qualification_partition(phase, partition_key)
            messages.success(request, f"Partició '{state.partition_key}' confirmada per '{phase.nom}'.")
            return view.redirect_to_selected_app(phase.comp_aparell), {}

        messages.error(request, "Acció no reconeguda.")
        return view.redirect_to_selected_app(selected_app), {}
    except IntegrityError:
        messages.error(request, "No s'ha pogut completar l'acció per una restricció d'unicitat.")
        return view.redirect_to_selected_app(selected_app), {}
    except QualificationError as exc:
        messages.error(request, str(exc))
        return view.redirect_to_selected_app(selected_app), {}
    except SlotOverrideError as exc:
        messages.error(request, str(exc))
        return view.redirect_to_selected_app(selected_app), {}
    except ValueError as exc:
        messages.error(request, str(exc))
        return view.redirect_to_selected_app(selected_app), {}


__all__ = ["handle_phase_post"]
