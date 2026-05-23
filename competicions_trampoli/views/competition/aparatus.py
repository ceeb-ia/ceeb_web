from django.contrib import messages
from django.db import IntegrityError
from django.db.models import Count, Exists, OuterRef, Subquery
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import CreateView, ListView, UpdateView, View

from ...forms import AparellForm, CompeticioAparellForm
from ...models import Competicio
from ...models.competicio import Aparell, CompeticioAparell
from ...models.scoring import ScoringSchema
from ...services.inscripcions.aparell_participation import (
    apply_participation_config,
    available_participation_fields,
    config_has_required_filters,
    field_value_options,
    normalize_participation_config,
    parse_participation_config_from_post,
    participation_mode_choices,
    participation_operator_choices,
    participation_preview,
)
from ...services.inscripcions.history import (
    capture_inscripcions_history_snapshot,
    record_inscripcions_history_entry,
)
from ...services.scoring.team_scoring import is_team_context_app


class TrampoliAparellList(ListView):
    template_name = "legacy/trampoli_aparells_list.html"
    context_object_name = "aparells_cfg"

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return (
            CompeticioAparell.objects
            .filter(competicio=self.competicio)
            .select_related("aparell", "aparell__created_by")
            .order_by("ordre", "id")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["competicio"] = self.competicio
        ctx["show_owner"] = (
            self.request.user.is_superuser
            or self.request.user.groups.filter(name="platform_admin").exists()
        )
        return ctx


class CompeticioAparellCreate(CreateView):
    template_name = "legacy/trampoli_aparell_form.html"
    form_class = CompeticioAparellForm

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["competicio"] = self.competicio
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.competicio = self.competicio
        try:
            obj.save()
        except IntegrityError:
            form.add_error("codi_local", "Ja existeix una instancia d'aparell amb aquest codi local.")
            return self.form_invalid(form)

        self.object = obj
        return redirect(self.get_success_url())

    def get_success_url(self):
        next_url = self.request.GET.get("next")
        if next_url:
            return next_url
        return reverse("trampoli_aparells_list", kwargs={"pk": self.kwargs["pk"]})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["competicio"] = self.competicio
        return ctx

class CompeticioAparellUpdate(UpdateView):
    template_name = "legacy/trampoli_aparell_form.html"
    form_class = CompeticioAparellForm
    model = CompeticioAparell
    pk_url_kwarg = "app_id"


    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        # IMPORTANT: només permet editar aparells d'aquesta competició
        qs = CompeticioAparell.objects.filter(competicio=self.competicio)
        if self.request.user.is_superuser or self.request.user.groups.filter(name="platform_admin").exists():
            return qs
        return qs.filter(aparell__created_by=self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["competicio"] = self.competicio
        kwargs["user"] = self.request.user
        return kwargs

    def get_success_url(self):
        next_url = self.request.GET.get("next")
        if next_url:
            return next_url
        return reverse("trampoli_aparells_list", kwargs={"pk": self.kwargs["pk"]})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["competicio"] = self.competicio
        return ctx


class CompeticioAparellParticipationView(View):
    template_name = "legacy/trampoli_aparell_participation.html"

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        qs = CompeticioAparell.objects.filter(competicio=self.competicio).select_related("aparell")
        if not (request.user.is_superuser or request.user.groups.filter(name="platform_admin").exists()):
            qs = qs.filter(aparell__created_by=request.user)
        self.comp_aparell = get_object_or_404(qs, pk=kwargs["app_id"])
        return super().dispatch(request, *args, **kwargs)

    def _active_config(self):
        fields = available_participation_fields(self.competicio)
        return normalize_participation_config(
            self.comp_aparell.participation_config,
            allowed_field_codes=[field["code"] for field in fields],
        )

    def _filter_rows(self, config):
        rows = [dict(item) for item in (config.get("filters") or [])]
        rows.append({"field": "", "operator": "is_any", "values": []})
        while len(rows) < 4:
            rows.append({"field": "", "operator": "is_any", "values": []})
        return rows[:8]

    def _context(self, *, config=None, preview=None):
        fields = available_participation_fields(self.competicio)
        config = config or self._active_config()
        current_preview = participation_preview(self.competicio, self.comp_aparell, self._active_config())
        return {
            "competicio": self.competicio,
            "comp_aparell": self.comp_aparell,
            "is_team_app": is_team_context_app(self.comp_aparell),
            "participation_fields": fields,
            "participation_field_values": field_value_options(self.competicio, fields),
            "participation_operator_choices": participation_operator_choices(),
            "participation_mode_choices": participation_mode_choices(),
            "participation_config": config,
            "participation_filter_rows": self._filter_rows(config),
            "participation_preview": preview,
            "current_participation_preview": current_preview,
        }

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._context())

    def post(self, request, *args, **kwargs):
        fields = available_participation_fields(self.competicio)
        config = parse_participation_config_from_post(
            request.POST,
            allowed_field_codes=[field["code"] for field in fields],
        )
        intent = str(request.POST.get("intent") or "preview").strip()
        if is_team_context_app(self.comp_aparell):
            messages.error(request, "La participacio massiva per filtres nomes aplica a aparells individuals.")
            return render(request, self.template_name, self._context(config=config))
        if not config_has_required_filters(config):
            messages.error(request, "Afegeix com a minim un filtre o selecciona que totes les inscripcions competeixen.")
            return render(request, self.template_name, self._context(config=config))

        preview = participation_preview(self.competicio, self.comp_aparell, config)
        if intent != "apply":
            return render(request, self.template_name, self._context(config=config, preview=preview))

        if request.POST.get("confirm_participation_apply") != "1":
            messages.error(request, "Confirma la substitucio massiva abans d'aplicar la participacio.")
            return render(request, self.template_name, self._context(config=config, preview=preview))

        before_snapshot = capture_inscripcions_history_snapshot(request, self.competicio)
        applied = apply_participation_config(self.competicio, self.comp_aparell, config)
        record_inscripcions_history_entry(
            request,
            self.competicio,
            action_type="apply_aparell_participation",
            action_label=f"Aplicar participacio de {self.comp_aparell.display_nom}",
            before_snapshot=before_snapshot,
            after_snapshot=capture_inscripcions_history_snapshot(request, self.competicio),
        )
        messages.success(
            request,
            f"Participacio aplicada: {applied['included_count']} competeixen i {applied['excluded_count']} queden excloses.",
        )
        return redirect(
            reverse(
                "trampoli_aparell_participation",
                kwargs={"pk": self.competicio.id, "app_id": self.comp_aparell.id},
            )
        )


class AparellList(ListView):
    template_name = "competicio/aparells_list.html"
    context_object_name = "aparells"

    def get_queryset(self):
        schema_qs = ScoringSchema.objects.filter(aparell_id=OuterRef("pk"))
        qs = (
            Aparell.objects
            .select_related("created_by")
            .annotate(competicio_usage_count=Count("competicio_cfg", distinct=True))
            .annotate(has_scoring_schema=Exists(schema_qs))
            .annotate(scoring_schema_updated_at=Subquery(schema_qs.values("updated_at")[:1]))
            .order_by("nom", "id")
        )
        if self.request.user.is_superuser or self.request.user.groups.filter(name="platform_admin").exists():
            return qs
        return qs.filter(created_by=self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        aparells = list(ctx.get("aparells") or [])
        ctx["aparells"] = aparells
        ctx["show_owner"] = (
            self.request.user.is_superuser
            or self.request.user.groups.filter(name="platform_admin").exists()
        )
        ctx["aparell_catalog_stats"] = {
            "total": len(aparells),
            "active": sum(1 for aparell in aparells if aparell.actiu),
            "used": sum(1 for aparell in aparells if getattr(aparell, "competicio_usage_count", 0)),
            "with_schema": sum(1 for aparell in aparells if getattr(aparell, "has_scoring_schema", False)),
        }
        return ctx


class AparellCreate(CreateView):
    template_name = "competicio/aparell_form.html"
    form_class = AparellForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.created_by = self.request.user
        obj.save()
        self.object = obj
        return redirect(self.get_success_url())

    def get_success_url(self):
        next_url = self.request.GET.get("next")
        if next_url:
            return next_url
        return reverse("aparells_list")


class AparellUpdate(UpdateView):
    template_name = "competicio/aparell_form.html"
    form_class = AparellForm
    model = Aparell

    def get_queryset(self):
        qs = Aparell.objects.all()
        if self.request.user.is_superuser or self.request.user.groups.filter(name="platform_admin").exists():
            return qs
        return qs.filter(created_by=self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_success_url(self):
        next_url = self.request.GET.get("next")
        if next_url:
            return next_url
        return reverse("aparells_list")


class AparellDeleteView(View):
    def post(self, request, pk):
        qs = Aparell.objects.all()
        if not (request.user.is_superuser or request.user.groups.filter(name="platform_admin").exists()):
            qs = qs.filter(created_by=request.user)
        aparell = get_object_or_404(qs, pk=pk)

        in_use_count = CompeticioAparell.objects.filter(aparell=aparell).count()
        if in_use_count > 0:
            messages.error(
                request,
                f"No pots eliminar '{aparell.nom}': esta en us a {in_use_count} competicio(ns).",
            )
            return redirect(reverse("aparells_list"))

        try:
            aparell.delete()
        except ProtectedError:
            messages.error(
                request,
                f"No pots eliminar '{aparell.nom}': hi ha dependències actives.",
            )
            return redirect(reverse("aparells_list"))

        messages.success(request, f"Aparell '{aparell.nom}' eliminat.")
        return redirect(reverse("aparells_list"))


class CompeticioAparellDeleteView(View):
    def post(self, request, pk, app_id):
        qs = CompeticioAparell.objects.filter(pk=app_id, competicio_id=pk)
        if not (request.user.is_superuser or request.user.groups.filter(name="platform_admin").exists()):
            qs = qs.filter(aparell__created_by=request.user)
        comp_aparell = get_object_or_404(qs)
        comp_aparell.delete()
        return redirect(reverse("trampoli_config", kwargs={"pk": pk}))


__all__ = [
    "AparellCreate",
    "AparellDeleteView",
    "AparellList",
    "AparellUpdate",
    "CompeticioAparellCreate",
    "CompeticioAparellDeleteView",
    "CompeticioAparellParticipationView",
    "CompeticioAparellUpdate",
    "TrampoliAparellList",
]
