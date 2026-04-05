from urllib.parse import parse_qs, urlparse

from django.contrib import messages
from django.db.models import Max
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, FormView, UpdateView

from ...forms import ImportInscripcionsExcelForm, InscripcioForm
from ...models import Competicio, Inscripcio
from ...services.competition_groups import (
    compact_competition_order_for_group,
    ensure_group_for_display_num,
    get_group_for_display_num,
    move_inscripcio_to_group,
    sync_competicio_group_names_view,
)
from ...services.equip_contexts import (
    BASE_EQUIP_CONTEXT_DESCRIPTION,
    BASE_EQUIP_CONTEXT_NAME,
    NATIVE_EQUIP_CONTEXT_CODE,
    get_equip_context,
    get_equip_context_payload,
    normalize_equip_context_code,
)
from ...services.import_excel import importar_inscripcions_excel


class InscripcioFormViewMixin:
    form_class = InscripcioForm
    template_name = "competicio/inscripcio_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        self.team_contexts_payload = get_equip_context_payload(self.competicio)
        self.team_context_code = self._resolve_team_context_code()
        self.team_context = get_equip_context(self.competicio, self.team_context_code)
        self.team_context_selected = next(
            (item for item in self.team_contexts_payload if item["code"] == self.team_context_code),
            self.team_contexts_payload[0]
            if self.team_contexts_payload
            else {
                "code": NATIVE_EQUIP_CONTEXT_CODE,
                "nom": BASE_EQUIP_CONTEXT_NAME,
                "description": BASE_EQUIP_CONTEXT_DESCRIPTION,
                "is_native": True,
            },
        )
        return super().dispatch(request, *args, **kwargs)

    def _extract_team_context_from_url(self, raw_url):
        if not raw_url:
            return ""
        try:
            parsed = urlparse(str(raw_url))
            values = parse_qs(parsed.query or "").get("team_context") or []
        except Exception:
            return ""
        return str(values[0] or "").strip() if values else ""

    def _resolve_team_context_code(self):
        raw_candidates = [
            self.request.GET.get("team_context"),
            self.request.POST.get("team_context"),
            self._extract_team_context_from_url(self.request.GET.get("next")),
            self._extract_team_context_from_url(self.request.POST.get("next")),
            self._extract_team_context_from_url(self.request.META.get("HTTP_REFERER")),
        ]
        valid_codes = {item["code"] for item in self.team_contexts_payload}
        for raw in raw_candidates:
            code = normalize_equip_context_code(raw)
            if code in valid_codes:
                return code
        return NATIVE_EQUIP_CONTEXT_CODE

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["competicio"] = self.competicio
        kwargs["team_context_code"] = self.team_context_code
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        next_url = self.request.GET.get("next") or self.request.POST.get("next", "")
        ctx["competicio"] = self.competicio
        ctx["next"] = next_url
        ctx["team_context_selected_code"] = self.team_context_code
        ctx["team_context_selected"] = self.team_context_selected
        ctx["team_contexts"] = list(self.team_contexts_payload)
        ctx["cancel_url"] = next_url or self.request.META.get("HTTP_REFERER") or reverse("inscripcions_list", kwargs={"pk": self.kwargs["pk"]})
        form = ctx.get("form")
        ctx["form_basic_fields"] = []
        ctx["form_extra_fields"] = []
        ctx["show_altres_fields"] = {}
        ctx["full_width_basic_field_names"] = []
        ctx["altres_wrapper_field_names"] = []
        ctx["team_base_hint"] = ""
        if form is not None:
            ctx["form_basic_fields"] = [form[name] for name in getattr(form, "basic_field_names", []) if name in form.fields]
            ctx["form_extra_fields"] = [form[name] for name in getattr(form, "extra_field_names", []) if name in form.fields]
            ctx["show_altres_fields"] = dict(getattr(form, "show_altres_fields", {}) or {})
            ctx["full_width_basic_field_names"] = list(getattr(form, "full_width_basic_field_names", []) or [])
            ctx["altres_wrapper_field_names"] = list(getattr(form, "other_wrapper_field_names", []) or [])
            current_base_equip = getattr(form, "current_base_equip", None)
            ctx["team_base_hint"] = str(getattr(current_base_equip, "nom", "") or "").strip()
        return ctx

    def get_success_url(self):
        nxt = self.request.GET.get("next") or self.request.POST.get("next")
        if nxt:
            return nxt
        return reverse("inscripcions_list", kwargs={"pk": self.kwargs["pk"]})


class InscripcioUpdateView(InscripcioFormViewMixin, UpdateView):
    model = Inscripcio
    pk_url_kwarg = "ins_id"

    def get_queryset(self):
        return Inscripcio.objects.filter(competicio_id=self.competicio.id)

    def form_valid(self, form):
        old_group = None
        if self.object and self.object.pk:
            old_group = Inscripcio.objects.select_related("grup_competicio").filter(pk=self.object.pk).first()
        response = super().form_valid(form)
        current = self.object
        new_group = get_group_for_display_num(current.competicio, current.grup)
        if current.grup and new_group is None:
            new_group = ensure_group_for_display_num(current.competicio, current.grup)
        if new_group is not None:
            if old_group and old_group.grup_competicio_id == new_group.id:
                Inscripcio.objects.filter(pk=current.pk).update(grup_competicio=new_group, grup=new_group.display_num)
            else:
                move_inscripcio_to_group(current, new_group)
        else:
            previous_group = old_group.grup_competicio if old_group else None
            Inscripcio.objects.filter(pk=current.pk).update(grup=None, grup_competicio=None, ordre_competicio=None)
            compact_competition_order_for_group(previous_group)
        sync_competicio_group_names_view(current.competicio)
        return response


class InscripcioCreateView(InscripcioFormViewMixin, CreateView):
    model = Inscripcio

    def _resolve_team_context_code(self):
        return NATIVE_EQUIP_CONTEXT_CODE

    def form_valid(self, form):
        form.instance.competicio = self.competicio
        if not form.instance.ordre_sortida:
            max_ord = Inscripcio.objects.filter(competicio=self.competicio).aggregate(m=Max("ordre_sortida"))["m"] or 0
            form.instance.ordre_sortida = max_ord + 1
        response = super().form_valid(form)
        group = get_group_for_display_num(self.competicio, self.object.grup)
        if self.object.grup and group is None:
            group = ensure_group_for_display_num(self.competicio, self.object.grup)
        if group is not None:
            move_inscripcio_to_group(self.object, group)
        sync_competicio_group_names_view(self.competicio)
        return response


class InscripcioDeleteView(DeleteView):
    model = Inscripcio
    pk_url_kwarg = "ins_id"
    template_name = "competicio/inscripcio_confirm_delete.html"

    def get_queryset(self):
        return Inscripcio.objects.filter(competicio_id=self.kwargs["pk"])

    def get_success_url(self):
        nxt = self.request.GET.get("next")
        if nxt:
            return nxt
        return reverse("inscripcions_list", kwargs={"pk": self.kwargs["pk"]})

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        old_group = getattr(self.object, "grup_competicio", None)
        response = super().delete(request, *args, **kwargs)
        compact_competition_order_for_group(old_group)
        sync_competicio_group_names_view(get_object_or_404(Competicio, pk=self.kwargs["pk"]))
        return response

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
    "InscripcioCreateView",
    "InscripcioDeleteView",
    "InscripcioFormViewMixin",
    "InscripcioUpdateView",
    "InscripcionsImportExcelView",
]
