from __future__ import annotations

from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from ....forms import (
    CompeticioAparellFaseForm,
    PhaseGroupPlanForm,
    PhaseSourceCutForm,
    ProgramUnitManualForm,
    ProgramUnitPartitionForm,
)
from ....models import Competicio
from ....models.competicio import CompeticioAparell, CompeticioAparellFase
from ....services.avatar.aparells.messages import AVATAR_MESSAGES as PHASES_AVATAR_MESSAGES
from ....services.fases.dashboard import _source_row_text, phase_dashboard_context
from .actions import handle_phase_post


USER_PHASE_STATUS_CHOICES = (
    (CompeticioAparellFase.Estat.PLANNED, "Esborrany"),
    (CompeticioAparellFase.Estat.PUBLISHED, "Publicada"),
    (CompeticioAparellFase.Estat.CLOSED, "Tancada"),
)


def _preview_candidate_value(candidate, key: str, default=None):
    if isinstance(candidate, dict):
        return candidate.get(key, default)
    return getattr(candidate, key, default)


def _preview_candidate_row(candidate) -> dict:
    row = _preview_candidate_value(candidate, "source_row", {})
    return row if isinstance(row, dict) else {}


def _preview_candidate_score(candidate) -> str:
    score = _preview_candidate_value(candidate, "source_score")
    if score in (None, ""):
        return ""
    return str(score).rstrip("0").rstrip(".") if "." in str(score) else str(score)


def _preview_candidate_display(candidate) -> dict:
    row = _preview_candidate_row(candidate)
    label = _source_row_text(row, "participant", "nom", "name", "label", "equip_nom")
    subject_kind = str(_preview_candidate_value(candidate, "subject_kind", "") or "").strip()
    subject_id = _preview_candidate_value(candidate, "subject_id")
    if not label and subject_kind and subject_id:
        label = f"{subject_kind}:{subject_id}"
    meta = _source_row_text(row, "entitat_nom", "entitat", "club", "categoria", "subcategoria")
    details = []
    position = _preview_candidate_value(candidate, "source_position")
    if position:
        details.append(f"#{position}")
    score = _preview_candidate_score(candidate)
    if score:
        details.append(f"{score} pts")
    partition_key = str(_preview_candidate_value(candidate, "source_particio_key", "") or "").strip()
    if partition_key and partition_key != "global":
        details.append(partition_key)
    if meta:
        details.append(meta)
    status = str(_preview_candidate_value(candidate, "status", "") or "").strip()
    return {
        "label": label or "Candidat sense nom",
        "meta": " / ".join(details),
        "status": status,
    }


def _annotate_qualification_preview_on_units(selected_phase, qualification_preview) -> None:
    if selected_phase is None or not qualification_preview:
        return
    units = list(getattr(selected_phase, "ui_units", []) or [])
    preview_units = qualification_preview.get("units") if isinstance(qualification_preview, dict) else None
    if not units or not preview_units:
        return

    preview_by_unit_id = {
        int(unit_preview["unit_id"]): unit_preview
        for unit_preview in preview_units
        if isinstance(unit_preview, dict) and unit_preview.get("unit_id")
    }
    preview_by_index = [
        unit_preview
        for unit_preview in preview_units
        if isinstance(unit_preview, dict)
    ]
    reserves = qualification_preview.get("reserves") if isinstance(qualification_preview, dict) else {}
    reserves = reserves if isinstance(reserves, dict) else {}

    for index, unit in enumerate(units):
        unit_preview = preview_by_unit_id.get(int(unit.id)) or (
            preview_by_index[index] if index < len(preview_by_index) else None
        )
        if not unit_preview:
            continue
        unit.ui_qualification_preview = unit_preview
        candidates = list(unit_preview.get("candidates") or [])
        for slot, candidate in zip(unit.slots.all(), candidates):
            slot.ui_qualification_preview_candidate = _preview_candidate_display(candidate)
        partition_key = str(unit_preview.get("partition_key") or unit.partition_key or "global").strip() or "global"
        unit.ui_qualification_preview_reserves = [
            _preview_candidate_display(candidate)
            for candidate in reserves.get(partition_key, [])
        ]


class CompeticioFasesPlanner(View):
    template_name = "competicio/fases/planner.html"

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        self.comp_aparell = self._selected_comp_aparell(kwargs.get("app_id"), request.GET.get("app"))
        self.selected_phase_id = request.GET.get("phase")
        return super().dispatch(request, *args, **kwargs)

    def _selected_comp_aparell(self, route_app_id, query_app_id):
        app_id = route_app_id or query_app_id
        if not app_id:
            return None
        return get_object_or_404(
            CompeticioAparell.objects.select_related("aparell", "competicio"),
            pk=app_id,
            competicio=self.competicio,
        )

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self.get_context())

    def post(self, request, *args, **kwargs):
        self.selected_phase_id = request.POST.get("fase_id") or self.selected_phase_id
        response, invalid_forms = handle_phase_post(self, request)
        if response is not None:
            return response
        return render(request, self.template_name, self.get_context(**invalid_forms))

    def redirect_to_selected_app(self, comp_aparell=None, phase=None):
        app = comp_aparell or self.comp_aparell
        url = reverse("trampoli_fases", kwargs={"pk": self.competicio.id})
        if app is not None:
            url = f"{url}?app={app.id}"
            phase_id = getattr(phase, "id", None) or self.request.POST.get("fase_id") or self.selected_phase_id
            if phase_id:
                url = f"{url}&phase={phase_id}"
        return redirect(url)

    def _source_cut_initial(self, phase):
        if phase is None:
            return {}
        config = phase.config if isinstance(phase.config, dict) else {}
        source = config.get("source") if isinstance(config.get("source"), dict) else {}
        cut = config.get("cut") if isinstance(config.get("cut"), dict) else {}
        return {
            "classificacio": source.get("classificacio_id"),
            "cut_mode": cut.get("mode") or "top_n",
            "qualifiers_count": cut.get("qualifiers_count"),
            "reserve_count": cut.get("reserve_count") or 0,
            "partition_mode": cut.get("partition_mode") or "global",
            "tie_policy": cut.get("tie_policy") or "classification_order",
            "unit_capacity": cut.get("unit_capacity") or 8,
            "unit_name_template": cut.get("unit_name_template") or "{fase} - {particio}",
        }

    def _group_plan_initial(self, phase):
        if phase is None:
            return {}
        config = phase.config if isinstance(phase.config, dict) else {}
        settings = config.get("group_plan_settings") if isinstance(config.get("group_plan_settings"), dict) else {}
        cut = config.get("cut") if isinstance(config.get("cut"), dict) else {}
        return {
            "split_mode": settings.get("split_mode") or "by_count",
            "units_per_partition": settings.get("units_per_partition") or 1,
            "unit_capacity": settings.get("unit_capacity") or cut.get("unit_capacity") or 8,
            "formation_strategy": settings.get("formation_strategy") or "classification_order",
            "unit_name_template": settings.get("unit_name_template") or cut.get("unit_name_template") or "{fase} - {particio}",
        }

    def get_context(
        self,
        *,
        phase_form=None,
        source_cut_form=None,
        manual_unit_form=None,
        partition_unit_form=None,
        group_plan_form=None,
        group_plan_preview=None,
        qualification_preview=None,
    ):
        dashboard = phase_dashboard_context(
            self.competicio,
            selected_app_id=getattr(self.comp_aparell, "id", None),
            selected_phase_id=self.selected_phase_id,
        )
        selected_app = dashboard["comp_aparell"]
        selected_phase = dashboard.get("selected_phase")
        _annotate_qualification_preview_on_units(selected_phase, qualification_preview)
        phase_initial = {}
        if selected_phase is not None:
            phase_initial["parent"] = selected_phase
        return {
            **dashboard,
            "phase_form": phase_form or CompeticioAparellFaseForm(comp_aparell=selected_app, initial=phase_initial),
            "source_cut_form": source_cut_form or PhaseSourceCutForm(
                competicio=self.competicio,
                initial=self._source_cut_initial(selected_phase),
            ),
            "manual_unit_form": manual_unit_form or ProgramUnitManualForm(),
            "partition_unit_form": partition_unit_form or ProgramUnitPartitionForm(),
            "group_plan_form": group_plan_form or PhaseGroupPlanForm(initial=self._group_plan_initial(selected_phase)),
            "group_plan_preview": group_plan_preview,
            "qualification_preview": qualification_preview,
            "phase_status_choices": USER_PHASE_STATUS_CHOICES,
            "avatar_messages": PHASES_AVATAR_MESSAGES,
            "avatar_initial_topic": "competition_apparatus_phases",
        }


class CompeticioAparellFasesPlanner(CompeticioFasesPlanner):
    pass


__all__ = ["CompeticioAparellFasesPlanner", "CompeticioFasesPlanner"]
