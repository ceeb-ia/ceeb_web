"""Template-based Django views for calendaritzacions runs."""

from __future__ import annotations

import re
from pathlib import Path

from django.http import FileResponse, Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import DetailView, FormView, ListView, View

from calendaritzacions.django.forms import CalendarizationRunForm
from calendaritzacions.django.models import CalendarizationRun
from calendaritzacions.django.services.audit_presenter import build_audit_presentation
from calendaritzacions.django.services.audit_reader import read_json_file
from calendaritzacions.django.services.runs import enqueue_run
from calendaritzacions.django.services.storage import ensure_run_audit_path, open_output_file

try:
    from ceeb_web.access import AppAccessRequiredMixin
except Exception:  # pragma: no cover - standalone package fallback
    class AppAccessRequiredMixin:  # type: ignore[no-redef]
        required_app_access = ""


class CalendaritzacionsAccessMixin(AppAccessRequiredMixin):
    required_app_access = "calendaritzacions"


class RunListView(CalendaritzacionsAccessMixin, ListView):
    model = CalendarizationRun
    template_name = "calendaritzacions/run_list.html"
    context_object_name = "runs"
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset()
        status = self.request.GET.get("status")
        engine = self.request.GET.get("engine")
        if status:
            queryset = queryset.filter(status=status)
        if engine:
            queryset = queryset.filter(engine_name=engine)
        return queryset


class RunCreateView(CalendaritzacionsAccessMixin, FormView):
    template_name = "calendaritzacions/run_create.html"
    form_class = CalendarizationRunForm

    def get_initial(self):
        initial = super().get_initial()
        phase = self.request.GET.get("phase")
        engine = self.request.GET.get("engine")
        valid_phases = {choice[0] for choice in CalendarizationRun.PHASE_CHOICES}
        valid_engines = {choice[0] for choice in CalendarizationRun.ENGINE_CHOICES}
        if phase in valid_phases:
            initial["phase"] = phase
        if engine in valid_engines:
            initial["engine_name"] = engine
        return initial

    def form_valid(self, form):
        run = form.save()
        enqueue_run(run)
        return redirect("calendaritzacions:run_detail", pk=run.pk)


class RunDetailView(CalendaritzacionsAccessMixin, DetailView):
    model = CalendarizationRun
    template_name = "calendaritzacions/run_detail.html"
    context_object_name = "run"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["plot_galleries"] = _build_plot_galleries(self.object)
        return context


class RunDeleteView(CalendaritzacionsAccessMixin, View):
    def post(self, request, *args, **kwargs):
        run = get_object_or_404(CalendarizationRun, pk=kwargs["pk"])
        if not run.is_finished:
            return HttpResponseBadRequest("No es pot eliminar un run pendent o en execucio.")
        if run.input_file:
            run.input_file.delete(save=False)
        run.delete()
        return redirect("calendaritzacions:run_list")


class RunPlotView(CalendaritzacionsAccessMixin, View):
    def get(self, request, *args, **kwargs):
        run = get_object_or_404(CalendarizationRun, pk=kwargs["pk"])
        path = _ensure_run_plot_path(
            run,
            artifact=kwargs["artifact"],
            plot_id=kwargs["plot_id"],
        )
        return FileResponse(path.open("rb"), content_type="image/png")


class AuditDetailView(CalendaritzacionsAccessMixin, DetailView):
    model = CalendarizationRun
    template_name = "calendaritzacions/audit_detail.html"
    context_object_name = "run"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        artifact = self.kwargs["artifact"]
        try:
            path = ensure_run_audit_path(self.object, artifact)
            payload = read_json_file(str(path))
            related_payloads = _read_related_audit_payloads(self.object, exclude=artifact)
            context["audit"] = {
                "artifact": artifact,
                "path": str(path),
                "payload": payload,
                "presentation": build_audit_presentation(artifact, payload, related_payloads=related_payloads),
            }
        except (FileNotFoundError, ValueError, OSError) as exc:
            raise Http404(str(exc)) from exc
        return context


class RunDownloadView(CalendaritzacionsAccessMixin, View):
    def get(self, request, *args, **kwargs):
        run = get_object_or_404(CalendarizationRun, pk=kwargs["pk"])
        return open_output_file(run)


class RunStatusJsonView(CalendaritzacionsAccessMixin, View):
    def get(self, request, *args, **kwargs):
        run = get_object_or_404(CalendarizationRun, pk=kwargs["pk"])
        redis_logs = []
        progress = None
        try:
            from logs import read_logs_sync

            redis_logs = read_logs_sync(str(run.pk), limit=200)
            progress_values = [
                item.get("progress")
                for item in redis_logs
                if isinstance(item, dict) and isinstance(item.get("progress"), int)
            ]
            if progress_values:
                progress = max(progress_values)
        except Exception:
            redis_logs = []

        log_lines = list(run.logs or [])
        if redis_logs:
            log_lines = [
                str(item.get("message", ""))
                for item in redis_logs
                if isinstance(item, dict) and item.get("message")
            ] or log_lines
        if progress is None:
            progress = _progress_from_log_lines(log_lines)

        return JsonResponse(
            {
                "id": run.pk,
                "status": run.status,
                "progress": progress,
                "is_finished": run.is_finished,
                "logs": log_lines,
                "error_message": run.error_message,
                "download_url": (
                    request.build_absolute_uri(reverse("calendaritzacions:run_download", kwargs={"pk": run.pk}))
                    if run.status == CalendarizationRun.STATUS_SUCCESS and run.output_path
                    else ""
                ),
                "audits": run.available_audits,
            }
        )


def _read_related_audit_payloads(run: CalendarizationRun, *, exclude: str) -> dict[str, object]:
    related: dict[str, object] = {}
    raw_audit_paths = getattr(run, "audit_paths", {})
    audit_paths = raw_audit_paths if isinstance(raw_audit_paths, dict) else {}
    for artifact in ("team_catalog", "resource_solution", "resource_solver_result"):
        if artifact == exclude:
            continue
        path = audit_paths.get(artifact)
        if not path:
            continue
        try:
            related[artifact] = read_json_file(path)
        except (FileNotFoundError, ValueError, OSError):
            continue
    return related


def _build_plot_galleries(run: CalendarizationRun) -> list[dict[str, object]]:
    galleries: list[dict[str, object]] = []
    for artifact, title in [
        ("input_demand", "Plots pre-run"),
        ("resource_solver_final_plots", "Plots post-run"),
    ]:
        plots = _plot_ids_for_artifact(run, artifact)
        if not plots:
            continue
        galleries.append(
            {
                "title": title,
                "artifact": artifact,
                "plots": [
                    {
                        "id": plot_id,
                        "label": _plot_label(plot_id),
                        "url": reverse(
                            "calendaritzacions:run_plot",
                            kwargs={"pk": run.pk, "artifact": artifact, "plot_id": plot_id},
                        ),
                    }
                    for plot_id in plots
                ],
            }
        )
    return galleries


def _progress_from_log_lines(log_lines: list[object]) -> int | None:
    values: list[int] = []
    for line in log_lines:
        match = re.match(r"^\[(\d{1,3})%\]", str(line).strip())
        if not match:
            continue
        values.append(max(0, min(100, int(match.group(1)))))
    if not values:
        return None
    return max(values)


def _plot_ids_for_artifact(run: CalendarizationRun, artifact: str) -> list[str]:
    try:
        payload = read_json_file(str(ensure_run_audit_path(run, artifact)))
    except (FileNotFoundError, ValueError, OSError, Http404):
        return []
    plots = payload.get("plots") if isinstance(payload, dict) else None
    if not isinstance(plots, dict):
        return []
    return sorted(
        plot_id
        for plot_id, path in plots.items()
        if plot_id != "manifest" and path and str(path).lower().endswith(".png")
    )


def _ensure_run_plot_path(run: CalendarizationRun, *, artifact: str, plot_id: str) -> Path:
    artifact_path = ensure_run_audit_path(run, artifact)
    payload = read_json_file(str(artifact_path))
    plots = payload.get("plots") if isinstance(payload, dict) else None
    if not isinstance(plots, dict) or plot_id not in plots:
        raise Http404("Plot does not exist.")

    resolved = Path(str(plots[plot_id])).expanduser().resolve()
    root = artifact_path.parent.resolve()
    if root not in (resolved, *resolved.parents):
        raise Http404("Plot path is outside the audit directory.")
    if resolved.suffix.lower() != ".png" or not resolved.exists() or not resolved.is_file():
        raise Http404("Plot file does not exist.")
    return resolved


def _plot_label(plot_id: str) -> str:
    labels = {
        "heatmap": "Mapa demanda",
        "friday": "Divendres",
        "by_venue": "Per pista",
        "top_slots": "Slots crítics",
        "group_sizes": "Mida grups",
        "resource_excess": "Pressió recursos",
        "entity_conflicts": "Conflictes entitat",
        "status_summary": "Resum final",
    }
    return labels.get(plot_id, plot_id.replace("_", " ").title())
