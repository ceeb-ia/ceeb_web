from types import SimpleNamespace

from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView

from ...models import Competicio
from ...models.rotacions import RotacioAssignacio, RotacioFranja
from ...services.fases.dashboard import phase_dashboard_context


class ConfiguracioCompeticio(TemplateView):
    template_name = "competicio/configuracio_trampoli.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        competicio = get_object_or_404(Competicio, pk=self.kwargs["pk"])

        # Keep the legacy object shape while the configuration page is migrated.
        ctx["object"] = SimpleNamespace(competicio=competicio)
        ctx["competicio"] = competicio

        aparells_cfg = list(
            competicio.aparells_cfg.select_related("aparell", "aparell__created_by")
            .order_by("ordre", "id")
        )
        classificacions = list(competicio.classificacions_cfg.order_by("ordre", "id"))
        classificacions_active_count = sum(1 for item in classificacions if item.activa)
        classificacions_published_count = sum(
            1 for item in classificacions
            if item.activa and getattr(item, "publicada", True)
        )
        phase_ctx = phase_dashboard_context(competicio)

        ctx.update(
            {
                "aparells_cfg": aparells_cfg,
                "classificacions_cfg": classificacions,
                "inscripcions_count": competicio.inscripcions.count(),
                "aparells_count": len(aparells_cfg),
                "classificacions_count": len(classificacions),
                "classificacions_active_count": classificacions_active_count,
                "classificacions_published_count": classificacions_published_count,
                "classificacions_internal_count": max(0, classificacions_active_count - classificacions_published_count),
                "rotacio_franja_count": RotacioFranja.objects.filter(competicio=competicio).count(),
                "rotacio_assignacio_count": RotacioAssignacio.objects.filter(competicio=competicio).count(),
                "app_summaries": phase_ctx["app_summaries"],
                "total_phase_count": phase_ctx["total_phase_count"],
                "total_unit_count": phase_ctx["total_unit_count"],
                "total_pending_unit_count": phase_ctx["total_pending_unit_count"],
            }
        )

        return ctx


__all__ = ["ConfiguracioCompeticio"]

