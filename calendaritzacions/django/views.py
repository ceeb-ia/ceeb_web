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
        plot_galleries = _build_plot_galleries(self.object)
        context["plot_galleries"] = plot_galleries
        context["plot_count"] = _plot_count(plot_galleries)
        return context


class ResourceWorkspaceOverviewView(CalendaritzacionsAccessMixin, DetailView):
    model = CalendarizationRun
    template_name = "calendaritzacions/resource_workspace.html"
    context_object_name = "run"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        workspace = _get_or_create_workspace_for_run(self.object)
        summary = _get_workspace_summary(workspace)
        context.update(
            {
                "workspace": workspace,
                "workspace_summary": summary,
                "kpis": summary.get("kpis", []),
                "top_incidents": _decorate_workspace_incidents(self.object, summary.get("top_incidents", [])),
                "incident_summaries": _decorate_workspace_incidents(self.object, summary.get("incident_summaries", [])),
                "league_summaries": summary.get("league_summaries", []),
                "assignment_summaries": summary.get("assignment_summaries", []),
                "venue_round_sheets": _get_workspace_venue_round_sheets(workspace),
                "calendar_view": _get_workspace_calendar_view(workspace),
                "linkage_view": _get_workspace_linkage_view(workspace),
                "plot_galleries": _build_plot_galleries(self.object),
                "workspace_audits": self.object.available_audits,
            }
        )
        return context


class ResourceWorkspaceIncidentDetailView(CalendaritzacionsAccessMixin, DetailView):
    model = CalendarizationRun
    template_name = "calendaritzacions/resource_workspace_incident.html"
    context_object_name = "run"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        workspace = _get_or_create_workspace_for_run(self.object)
        incident = _get_workspace_incident_detail(workspace, self.kwargs["incident_id"])
        if incident is None:
            raise Http404("Incident does not exist.")
        context.update(
            {
                "workspace": workspace,
                "incident": incident,
                "incident_id": self.kwargs["incident_id"],
            }
        )
        return context


class ResourceWorkspaceTeamDetailView(CalendaritzacionsAccessMixin, DetailView):
    model = CalendarizationRun
    template_name = "calendaritzacions/resource_workspace_team.html"
    context_object_name = "run"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        workspace = _get_or_create_workspace_for_run(self.object)
        team = _get_workspace_team_detail(workspace, self.kwargs["team_id"])
        if team is None:
            raise Http404("Team assignment does not exist.")
        context.update(
            {
                "workspace": workspace,
                "team": team,
            }
        )
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
        content_type = "text/html; charset=utf-8" if path.suffix.lower() == ".html" else "image/png"
        return FileResponse(path.open("rb"), content_type=content_type)


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

        response = JsonResponse(
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
                "plot_galleries": _build_plot_galleries(run),
            }
        )
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        return response


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


def _get_workspace_services():
    try:
        from calendaritzacions.django.services.workspaces import (
            get_or_create_workspace_for_run,
            get_workspace_calendar_view,
            get_workspace_linkage_view,
            get_workspace_venue_round_sheets,
            get_workspace_incident_detail,
            get_workspace_summary,
            get_workspace_team_detail,
        )
    except ModuleNotFoundError as exc:
        if exc.name != "calendaritzacions.django.services.workspaces":
            raise
        raise Http404("Resource workspace service is not available.") from exc
    return (
        get_or_create_workspace_for_run,
        get_workspace_summary,
        get_workspace_incident_detail,
        get_workspace_team_detail,
        get_workspace_venue_round_sheets,
        get_workspace_calendar_view,
        get_workspace_linkage_view,
    )


def _get_or_create_workspace_for_run(run: CalendarizationRun):
    get_or_create_workspace_for_run, _, _, _, _, _, _ = _get_workspace_services()
    try:
        return get_or_create_workspace_for_run(run)
    except ValueError as exc:
        raise Http404(str(exc)) from exc


def _get_workspace_summary(workspace) -> dict[str, object]:
    _, get_workspace_summary, _, _, _, _, _ = _get_workspace_services()
    summary = get_workspace_summary(workspace)
    return summary if isinstance(summary, dict) else {}


def _get_workspace_incident_detail(workspace, incident_id: str):
    _, _, get_workspace_incident_detail, _, _, _, _ = _get_workspace_services()
    return get_workspace_incident_detail(workspace, incident_id)


def _get_workspace_team_detail(workspace, team_id: str):
    _, _, _, get_workspace_team_detail, _, _, _ = _get_workspace_services()
    return get_workspace_team_detail(workspace, team_id)


def _get_workspace_venue_round_sheets(workspace) -> dict[str, object]:
    _, _, _, _, get_workspace_venue_round_sheets, _, _ = _get_workspace_services()
    payload = get_workspace_venue_round_sheets(workspace)
    return payload if isinstance(payload, dict) else {"sheets": [], "venues": [], "rounds": []}


def _get_workspace_calendar_view(workspace) -> dict[str, object]:
    _, _, _, _, _, get_workspace_calendar_view, _ = _get_workspace_services()
    payload = get_workspace_calendar_view(workspace)
    return payload if isinstance(payload, dict) else {"groups": [], "filters": {}}


def _get_workspace_linkage_view(workspace) -> dict[str, object]:
    _, _, _, _, _, _, get_workspace_linkage_view = _get_workspace_services()
    payload = get_workspace_linkage_view(workspace)
    return payload if isinstance(payload, dict) else {"groups": [], "filters": {}}


def _decorate_workspace_incidents(run: CalendarizationRun, incidents: object) -> list[object]:
    if not isinstance(incidents, list):
        return []

    decorated: list[object] = []
    for incident in incidents:
        incident_id = _workspace_incident_id(incident)
        if not incident_id:
            decorated.append(incident)
            continue
        if isinstance(incident, dict):
            item = dict(incident)
            item["detail_url"] = reverse(
                "calendaritzacions:resource_workspace_incident",
                kwargs={"pk": run.pk, "incident_id": incident_id},
            )
            decorated.append(item)
        else:
            decorated.append(incident)
    return decorated


def _workspace_incident_id(incident: object) -> str:
    if isinstance(incident, dict):
        value = incident.get("id") or incident.get("incident_id") or incident.get("key")
    else:
        value = getattr(incident, "id", "") or getattr(incident, "incident_id", "") or getattr(incident, "key", "")
    return str(value) if value else ""


def _build_plot_galleries(run: CalendarizationRun) -> list[dict[str, object]]:
    galleries: list[dict[str, object]] = []
    for artifact, title in [
        ("input_demand", "Plots pre-run"),
        ("resource_solver_decomposition_plots", "Descomposicio"),
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
                        "kind": _plot_kind(plot_id, run, artifact),
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


def _plot_count(plot_galleries: list[dict[str, object]]) -> int:
    return sum(len(gallery.get("plots", [])) for gallery in plot_galleries)


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
    except (AttributeError, FileNotFoundError, ValueError, OSError, Http404):
        return []
    plots = payload.get("plots") if isinstance(payload, dict) else None
    if not isinstance(plots, dict):
        return []
    return sorted(
        plot_id
        for plot_id, path in plots.items()
        if plot_id not in {"manifest", "friday"} and path and Path(str(path)).suffix.lower() in {".png", ".html"}
    )


def _plot_kind(plot_id: str, run: CalendarizationRun, artifact: str) -> str:
    try:
        payload = read_json_file(str(ensure_run_audit_path(run, artifact)))
    except (AttributeError, FileNotFoundError, ValueError, OSError, Http404):
        return "image"
    plots = payload.get("plots") if isinstance(payload, dict) else None
    if not isinstance(plots, dict):
        return "image"
    suffix = Path(str(plots.get(plot_id, ""))).suffix.lower()
    return "html" if suffix == ".html" else "image"


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
    if resolved.suffix.lower() not in {".png", ".html"} or not resolved.exists() or not resolved.is_file():
        raise Http404("Plot file does not exist.")
    return resolved


def _plot_label(plot_id: str) -> str:
    if plot_id.startswith("component_network_"):
        return f"Xarxa {plot_id.removeprefix('component_network_')}"
    if plot_id.startswith("component_bridge_network_"):
        return f"Ponts {plot_id.removeprefix('component_bridge_network_')}"
    labels = {
        "heatmap": "Mapa demanda",
        "by_venue": "Per pista",
        "seed_requests_by_modality": "Peticions per modalitat",
        "home_away_distribution": "Casa/Fora per modalitat",
        "assigned_numbers_by_modality": "Assignacions per modalitat",
        "top_slots": "Slots crítics",
        "group_sizes": "Mida grups",
        "resource_excess": "Pressió recursos",
        "entity_conflicts": "Conflictes entitat",
        "status_summary": "Resum final",
        "component_team_count_histogram": "Mida components",
        "top_components_by_teams": "Components principals",
        "components_resources_vs_competitions": "Recursos vs competicions",
        "candidate_pareto_by_component": "Pareto candidats",
        "top_component_competition_resource_heatmap": "Mapa competicio-recurs",
        "top_component_network": "Xarxa component",
        "component_graph_3d": "Graf 3D interactiu",
    }
    return labels.get(plot_id, plot_id.replace("_", " ").title())
