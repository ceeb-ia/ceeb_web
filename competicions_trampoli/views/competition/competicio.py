from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, TemplateView

from ...access import user_has_competicio_capability
from ...forms import CompeticioForm
from ...models import Competicio, CompeticioMembership


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
    return redirect("scoring_notes_home", pk=pk)




__all__ = [
    "CompeticioCreateView",
    "CompeticioDeleteView",
    "CompeticioHomeView",
    "CompeticioListView",
    "notes_home_router",
]
