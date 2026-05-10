from __future__ import annotations

from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from ....forms import CompeticioAparellFaseForm, ProgramUnitManualForm, ProgramUnitPartitionForm
from ....models import Competicio
from ....models.competicio import CompeticioAparell
from ....services.fases.dashboard import phase_dashboard_context
from .actions import handle_phase_post


class CompeticioFasesPlanner(View):
    template_name = "competicio/fases/planner.html"

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        self.comp_aparell = self._selected_comp_aparell(kwargs.get("app_id"), request.GET.get("app"))
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
        response, invalid_forms = handle_phase_post(self, request)
        if response is not None:
            return response
        return render(request, self.template_name, self.get_context(**invalid_forms))

    def redirect_to_selected_app(self, comp_aparell=None):
        app = comp_aparell or self.comp_aparell
        url = reverse("trampoli_fases", kwargs={"pk": self.competicio.id})
        if app is not None:
            url = f"{url}?app={app.id}"
        return redirect(url)

    def get_context(self, *, phase_form=None, manual_unit_form=None, partition_unit_form=None):
        dashboard = phase_dashboard_context(
            self.competicio,
            selected_app_id=getattr(self.comp_aparell, "id", None),
        )
        selected_app = dashboard["comp_aparell"]
        return {
            **dashboard,
            "phase_form": phase_form or CompeticioAparellFaseForm(comp_aparell=selected_app),
            "manual_unit_form": manual_unit_form or ProgramUnitManualForm(),
            "partition_unit_form": partition_unit_form or ProgramUnitPartitionForm(),
        }


class CompeticioAparellFasesPlanner(CompeticioFasesPlanner):
    pass


__all__ = ["CompeticioAparellFasesPlanner", "CompeticioFasesPlanner"]
