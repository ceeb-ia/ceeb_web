from django.shortcuts import get_object_or_404, redirect
from django.db.models import Count
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, ListView

from ceeb_web.access import user_has_any_global_group

from ...access import GLOBAL_COMPETICIONS_GROUPS, user_has_competicio_capability
from ...forms import CompeticioForm
from ...models import Competicio, CompeticioMembership


class CompeticioDashboardMixin:
    template_name = "competicio/home.html"
    context_object_name = "competicions"
    paginate_by = None

    def get_queryset(self):
        user = self.request.user
        qs = Competicio.objects.annotate(participant_count=Count("inscripcions", distinct=True)).order_by("-created_at", "-id")
        if user.is_superuser or user.groups.filter(name="platform_admin").exists():
            return qs
        return qs.filter(memberships__user=user, memberships__is_active=True).distinct()

    def _competition_status(self, competicio):
        today = timezone.localdate()
        if competicio.data == today:
            return {"key": "active", "label": "Activa"}
        if competicio.data and competicio.data < today:
            return {"key": "finished", "label": "Finalitzada"}
        return {"key": "preparation", "label": "Preparacio"}

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        actions = {}
        status_counts = {"active": 0, "preparation": 0, "finished": 0}
        total_participants = 0

        for comp in ctx.get("competicions", []):
            status = self._competition_status(comp)
            comp.home_status_key = status["key"]
            comp.home_status_label = status["label"]
            status_counts[status["key"]] = status_counts.get(status["key"], 0) + 1
            total_participants += getattr(comp, "participant_count", 0) or 0
            actions[comp.id] = {
                "can_view_inscripcions": user_has_competicio_capability(user, comp, "inscripcions.view"),
                "can_view_fases": user_has_competicio_capability(user, comp, "scoring.edit"),
                "can_view_rotacions": user_has_competicio_capability(user, comp, "rotacions.view"),
                "can_view_classificacions": user_has_competicio_capability(user, comp, "classificacions.view"),
                "can_view_notes": user_has_competicio_capability(user, comp, "scoring.view"),
                "can_delete_competicio": user_has_competicio_capability(user, comp, "competition.delete"),
            }

        ctx["comp_actions"] = actions
        ctx["competition_status_counts"] = status_counts
        ctx["competition_total_participants"] = total_participants
        ctx["can_manage_global_competicions"] = user_has_any_global_group(user, GLOBAL_COMPETICIONS_GROUPS)
        return ctx


class CompeticioHomeView(CompeticioDashboardMixin, ListView):
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


class CompeticioListView(CompeticioDashboardMixin, ListView):
    model = Competicio
    template_name = "competicio/competicio_created_list.html"


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
