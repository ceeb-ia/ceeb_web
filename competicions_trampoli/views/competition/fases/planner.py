from __future__ import annotations

from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from ....forms import CompeticioAparellFaseForm, PhaseSourceCutForm, ProgramUnitManualForm, ProgramUnitPartitionForm
from ....models import Competicio
from ....models.competicio import CompeticioAparell
from ....services.fases.dashboard import phase_dashboard_context
from .actions import handle_phase_post


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

    def get_context(
        self,
        *,
        phase_form=None,
        source_cut_form=None,
        manual_unit_form=None,
        partition_unit_form=None,
        qualification_preview=None,
    ):
        dashboard = phase_dashboard_context(
            self.competicio,
            selected_app_id=getattr(self.comp_aparell, "id", None),
            selected_phase_id=self.selected_phase_id,
        )
        selected_app = dashboard["comp_aparell"]
        selected_phase = dashboard.get("selected_phase")
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
            "qualification_preview": qualification_preview,
        }


class CompeticioAparellFasesPlanner(CompeticioFasesPlanner):
    pass


__all__ = ["CompeticioAparellFasesPlanner", "CompeticioFasesPlanner"]
