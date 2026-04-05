from types import SimpleNamespace

from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView

from ...models import Competicio


class ConfiguracioCompeticio(TemplateView):
    template_name = "competicio/configuracio_trampoli.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        competicio = get_object_or_404(Competicio, pk=self.kwargs["pk"])

        # El teu template fa servir "object.competicio.nom" i "object.competicio.aparells_cfg..."
        # així que li passem un objecte "fake" amb l'atribut competicio.
        ctx["object"] = SimpleNamespace(competicio=competicio)

        return ctx


__all__ = ["ConfiguracioCompeticio"]

