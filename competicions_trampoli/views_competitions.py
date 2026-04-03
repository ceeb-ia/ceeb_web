from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, FormView, ListView, TemplateView

from .access import user_has_competicio_capability
from .forms import CompeticioForm, ImportInscripcionsExcelForm
from .models import Competicio, CompeticioMembership
from .services.import_excel import importar_inscripcions_excel


class CompeticioHomeView(TemplateView):
    template_name = "competicio/home.html"


class CompeticioCreateView(CreateView):
    model = Competicio
    form_class = CompeticioForm
    template_name = "competicio/competicio_form.html"
    success_url = reverse_lazy("created")

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.user.is_authenticated:
            membership, created = CompeticioMembership.objects.get_or_create(
                user=self.request.user,
                competicio=self.object,
                defaults={
                    "role": CompeticioMembership.Role.OWNER,
                    "is_active": True,
                    "granted_by": self.request.user,
                },
            )
            if not created:
                changed = False
                if membership.role != CompeticioMembership.Role.OWNER:
                    membership.role = CompeticioMembership.Role.OWNER
                    changed = True
                if not membership.is_active:
                    membership.is_active = True
                    changed = True
                if membership.granted_by_id is None:
                    membership.granted_by = self.request.user
                    changed = True
                if changed:
                    membership.save(update_fields=["role", "is_active", "granted_by", "updated_at"])
        return response


class CompeticioDeleteView(DeleteView):
    model = Competicio
    template_name = "competicio/competicio_confirm_delete.html"
    success_url = reverse_lazy("created")


class CompeticioListView(ListView):
    model = Competicio
    template_name = "competicio/competicio_created_list.html"
    context_object_name = "competicions"
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        qs = Competicio.objects.all().order_by("-created_at", "-id")
        if user.is_superuser or user.groups.filter(name="platform_admin").exists():
            return qs
        return qs.filter(memberships__user=user, memberships__is_active=True).distinct()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        actions = {}
        for comp in ctx.get("competicions", []):
            actions[comp.id] = {
                "can_view_inscripcions": user_has_competicio_capability(self.request.user, comp, "inscripcions.view"),
                "can_view_rotacions": user_has_competicio_capability(self.request.user, comp, "rotacions.view"),
                "can_view_notes": user_has_competicio_capability(self.request.user, comp, "scoring.view"),
                "can_view_trampoli_config": user_has_competicio_capability(self.request.user, comp, "scoring.edit"),
                "can_delete_competicio": user_has_competicio_capability(self.request.user, comp, "competition.delete"),
            }
        ctx["comp_actions"] = actions
        return ctx


def notes_home_router(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    if competicio.tipus == Competicio.Tipus.TRAMPOLI:
        return redirect("scoring_notes_home", pk=pk)
    return redirect("created")


class InscripcionsImportExcelView(FormView):
    template_name = "competicio/inscripcions_import.html"
    form_class = ImportInscripcionsExcelForm

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["competicio"] = self.competicio
        return ctx

    def form_valid(self, form):
        fitxer = form.cleaned_data["fitxer"]
        sheet = form.cleaned_data.get("sheet") or ""
        result = importar_inscripcions_excel(fitxer, self.competicio, sheet)
        summary = (
            f"Full: {result['full']} | Creats: {result['creats']} | "
            f"Actualitzats: {result['actualitzats']} | Ignorats: {result['ignorats']} | "
            f"Ambiguos: {result.get('ambiguos', 0)} | Errors: {result.get('errors', 0)}"
        )
        if int(result.get("errors", 0) or 0) > 0:
            messages.warning(self.request, f"Importació parcial amb incidències. {summary}")
        else:
            messages.success(self.request, f"Importació OK. {summary}")
        warnings = result.get("warnings") or []
        if warnings:
            parts = []
            for warning in warnings:
                code = str(warning.get("code") or "").strip()
                remapped = str(warning.get("remapped_code") or warning.get("suggested_code") or "").strip()
                if code and remapped:
                    parts.append(f"{code} -> {remapped}")
                elif code:
                    parts.append(code)
            if parts:
                messages.warning(
                    self.request,
                    "S'han detectat columnes d'Excel amb noms reservats i s'han remapejat automaticament "
                    f"({', '.join(parts)}).",
                )
        noms_competicio_excel = result.get("noms_competicio_excel") or []
        if len(noms_competicio_excel) > 1:
            messages.warning(
                self.request,
                "L'Excel conté múltiples noms de competició detectats: "
                + ", ".join(str(name) for name in noms_competicio_excel),
            )
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("inscripcions_list", kwargs={"pk": self.competicio.pk})


__all__ = [
    "CompeticioCreateView",
    "CompeticioDeleteView",
    "CompeticioHomeView",
    "CompeticioListView",
    "InscripcionsImportExcelView",
    "notes_home_router",
]
