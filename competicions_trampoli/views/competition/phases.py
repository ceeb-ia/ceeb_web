from django.contrib import messages
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from ...forms import CompeticioAparellFaseForm, ProgramUnitManualForm, ProgramUnitPartitionForm
from ...models import Competicio
from ...models.competicio import CompeticioAparell, CompeticioAparellFase
from ...services.fases.planner import (
    create_manual_unit_for_phase,
    create_partition_unit_for_phase,
    create_phase_for_comp_aparell,
    generate_base_group_units_for_phase,
    phase_planner_context,
)


class CompeticioAparellFasesPlanner(View):
    template_name = "competicio/fases_planner.html"

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        self.comp_aparell = get_object_or_404(
            CompeticioAparell.objects.select_related("aparell", "competicio"),
            pk=kwargs["app_id"],
            competicio=self.competicio,
        )
        return super().dispatch(request, *args, **kwargs)

    def _phase_for_post(self, request):
        phase_id = request.POST.get("fase_id")
        if not phase_id:
            return None
        return get_object_or_404(
            CompeticioAparellFase,
            pk=phase_id,
            comp_aparell=self.comp_aparell,
            competicio=self.competicio,
        )

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self.get_context())

    def post(self, request, *args, **kwargs):
        action = str(request.POST.get("action") or "").strip()
        try:
            if action == "create_phase":
                form = CompeticioAparellFaseForm(request.POST, comp_aparell=self.comp_aparell)
                if form.is_valid():
                    phase = create_phase_for_comp_aparell(self.comp_aparell, form)
                    messages.success(request, f"Fase '{phase.nom}' creada.")
                    return redirect(self.get_success_url())
                return render(request, self.template_name, self.get_context(phase_form=form))

            phase = self._phase_for_post(request)
            if phase is None:
                messages.error(request, "Selecciona una fase.")
                return redirect(self.get_success_url())

            if action == "create_manual_unit":
                form = ProgramUnitManualForm(request.POST)
                if form.is_valid():
                    unit = create_manual_unit_for_phase(phase, form)
                    messages.success(request, f"Unitat '{unit.nom}' creada amb {unit.capacity} slots.")
                    return redirect(self.get_success_url())
                return render(request, self.template_name, self.get_context(manual_unit_form=form))

            if action == "create_partition_unit":
                form = ProgramUnitPartitionForm(request.POST)
                if form.is_valid():
                    units = create_partition_unit_for_phase(phase, form)
                    messages.success(request, f"S'ha creat {len(units)} unitat de particio.")
                    return redirect(self.get_success_url())
                return render(request, self.template_name, self.get_context(partition_unit_form=form))

            if action == "generate_from_base_groups":
                units = generate_base_group_units_for_phase(phase)
                messages.success(request, f"S'han generat {len(units)} unitats des dels grups base.")
                return redirect(self.get_success_url())

            messages.error(request, "Accio no reconeguda.")
            return redirect(self.get_success_url())
        except IntegrityError:
            messages.error(request, "No s'ha pogut completar l'accio per una restriccio d'unicitat.")
            return redirect(self.get_success_url())
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse(
            "trampoli_aparell_fases",
            kwargs={"pk": self.competicio.id, "app_id": self.comp_aparell.id},
        )

    def get_context(self, *, phase_form=None, manual_unit_form=None, partition_unit_form=None):
        planner = phase_planner_context(self.comp_aparell)
        return {
            "competicio": self.competicio,
            "comp_aparell": self.comp_aparell,
            "phases": planner["phases"],
            "phase_count": planner["phase_count"],
            "unit_count": planner["unit_count"],
            "phase_form": phase_form or CompeticioAparellFaseForm(comp_aparell=self.comp_aparell),
            "manual_unit_form": manual_unit_form or ProgramUnitManualForm(),
            "partition_unit_form": partition_unit_form or ProgramUnitPartitionForm(),
        }


__all__ = ["CompeticioAparellFasesPlanner"]
