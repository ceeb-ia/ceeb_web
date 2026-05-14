"""Celery-facing execution helpers for persistent resource solver components."""

from __future__ import annotations

import json
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from calendaritzacions.django.models import CalendarizationComponentRun, CalendarizationRun
from calendaritzacions.django.services.component_runs import (
    atomic_write_text,
    heartbeat_component,
    mark_component_status,
)


def enqueue_component(component_run: CalendarizationComponentRun) -> CalendarizationComponentRun:
    """Queue or execute a component attempt according to the configured backend."""

    _ensure_default_paths(component_run)
    backend = getattr(settings, "CALENDARITZACIONS_ASYNC_BACKEND", "sync")
    if backend == "sync":
        _solve_resource_component(
            component_run.run_id,
            component_run.component_id,
            component_run.attempt,
        )
        component_run.refresh_from_db()
        return component_run
    if backend == "celery":
        from calendaritzacions.django.tasks import solve_resource_component_task

        mark_component_status(component_run, CalendarizationComponentRun.STATUS_QUEUED)
        async_result = solve_resource_component_task.apply_async(
            args=(component_run.run_id, component_run.component_id, component_run.attempt),
            queue="heavy_queue",
        )
        _append_component_log(
            component_run,
            "queued",
            {"celery_task_id": str(getattr(async_result, "id", ""))},
        )
        component_run.refresh_from_db()
        return component_run
    raise NotImplementedError(f"Unsupported calendaritzacions async backend: {backend}")


def _solve_resource_component(run_id: int, component_id: str, attempt: int) -> str:
    """Solve one persisted component attempt idempotently."""

    component_run = CalendarizationComponentRun.objects.select_related("run").get(
        run_id=run_id,
        component_id=component_id,
        attempt=attempt,
    )

    _ensure_default_paths(component_run)
    if _success_artifacts_exist(component_run):
        _append_component_log(component_run, "already_success")
        return "already_success"

    if int(component_run.attempt) != int(component_run.active_attempt):
        status = _inactive_attempt_status(component_run)
        mark_component_status(component_run, status, error_message="Intent no actiu; no s'executa.")
        _append_component_log(component_run, status, {"active_attempt": component_run.active_attempt})
        return status

    try:
        mark_component_status(component_run, CalendarizationComponentRun.STATUS_RUNNING, error_message="")
        _append_component_log(component_run, "component_start")
        heartbeat_component(component_run)

        context_path = _resolve_component_path(component_run, component_run.context_path)
        if not context_path.exists():
            raise FileNotFoundError(f"Component context does not exist: {context_path}")

        _append_component_log(component_run, "context_loaded", {"context_path": str(context_path)})
        heartbeat_component(component_run)

        _append_component_log(component_run, "solve_started")
        heartbeat_component(component_run)

        from calendaritzacions.engine.variants.resource_solver.component_solver import solve_component_context

        result = solve_component_context(
            context_path,
            _attempt_dir(component_run),
            component_id=component_run.component_id,
        )

        component_run.refresh_from_db()
        if int(component_run.attempt) != int(component_run.active_attempt):
            status = _inactive_attempt_status(component_run)
            mark_component_status(component_run, status, error_message="Intent substituit mentre s'executava.")
            _append_component_log(component_run, status, {"active_attempt": component_run.active_attempt})
            return status

        _apply_solver_paths(component_run, result)
        if not _is_valid_json_file(component_run.raw_result_path):
            raise FileNotFoundError(f"Component raw result does not exist or is invalid: {component_run.raw_result_path}")
        if not _is_valid_json_file(component_run.solution_path):
            raise FileNotFoundError(f"Component solution does not exist or is invalid: {component_run.solution_path}")
        _append_component_log(component_run, "model_built", {"path": component_run.model_summary_path})
        heartbeat_component(component_run)
        _append_component_log(component_run, "solve_finished", {"path": component_run.raw_result_path})
        heartbeat_component(component_run)
        _append_component_log(component_run, "artifacts_written", {"path": component_run.solution_path})
        heartbeat_component(component_run)

        component_run.error_message = ""
        component_run.error_path = ""
        component_run.save(
            update_fields=[
                "model_summary_path",
                "raw_result_path",
                "solution_path",
                "logs_path",
                "error_message",
                "error_path",
            ]
        )
        if not _mark_active_component_status(
            component_run,
            CalendarizationComponentRun.STATUS_SUCCESS,
            error_message="",
        ):
            _append_component_log(component_run, "success_ignored_inactive")
            return "superseded"
        _finalize_run_if_components_complete(component_run.run_id)
        return "success"
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        error_path = _attempt_dir(component_run) / "error.txt"
        atomic_write_text(error_path, f"{message}\n\n{traceback.format_exc()}")
        component_run.error_path = str(error_path)
        component_run.logs_path = str(_logs_path(component_run))
        component_run.save(update_fields=["error_path", "logs_path"])
        _append_component_log(
            component_run,
            "error",
            {"error": message, "error_path": str(error_path)},
        )
        _mark_active_component_status(
            component_run,
            CalendarizationComponentRun.STATUS_ERROR,
            error_message=message,
        )
        return "error"


def _ensure_default_paths(component_run: CalendarizationComponentRun) -> None:
    attempt_dir = _attempt_dir(component_run)
    updates: list[str] = []
    defaults = {
        "logs_path": attempt_dir / "logs.jsonl",
        "model_summary_path": attempt_dir / "model_summary.json",
        "raw_result_path": attempt_dir / "raw_result.json",
        "solution_path": attempt_dir / "solution_partial.json",
    }
    for field, path in defaults.items():
        if not getattr(component_run, field):
            setattr(component_run, field, str(path))
            updates.append(field)
    if updates:
        component_run.save(update_fields=updates)


def _attempt_dir(component_run: CalendarizationComponentRun) -> Path:
    if component_run.context_path:
        return _resolve_component_path(component_run, component_run.context_path).parent
    if component_run.raw_result_path:
        return Path(component_run.raw_result_path).parent
    return Path("components") / component_run.component_id / f"attempt_{component_run.attempt:03d}"


def _logs_path(component_run: CalendarizationComponentRun) -> Path:
    return Path(component_run.logs_path) if component_run.logs_path else _attempt_dir(component_run) / "logs.jsonl"


def _success_artifacts_exist(component_run: CalendarizationComponentRun) -> bool:
    if component_run.status not in {
        CalendarizationComponentRun.STATUS_SUCCESS,
        CalendarizationComponentRun.STATUS_MERGED,
    }:
        return False
    return _is_valid_json_file(component_run.raw_result_path) and _is_valid_json_file(component_run.solution_path)


def _is_valid_json_file(path_value: str) -> bool:
    if not path_value:
        return False
    path = Path(path_value)
    if not path.exists():
        return False
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return True


def _inactive_attempt_status(component_run: CalendarizationComponentRun) -> str:
    if int(component_run.attempt) < int(component_run.active_attempt):
        return CalendarizationComponentRun.STATUS_SUPERSEDED
    return CalendarizationComponentRun.STATUS_SKIPPED


def _apply_solver_paths(component_run: CalendarizationComponentRun, result: dict[str, Any]) -> None:
    paths = result.get("paths") if isinstance(result, dict) else None
    if not isinstance(paths, dict):
        paths = {}
    attempt_dir = _attempt_dir(component_run)
    component_run.model_summary_path = str(paths.get("model_summary") or attempt_dir / "model_summary.json")
    component_run.raw_result_path = str(paths.get("raw_result") or attempt_dir / "raw_result.json")
    component_run.solution_path = str(paths.get("solution_partial") or attempt_dir / "solution_partial.json")
    component_run.logs_path = str(_logs_path(component_run))


def _append_component_log(
    component_run: CalendarizationComponentRun,
    event: str,
    payload: dict[str, Any] | None = None,
) -> None:
    path = _logs_path(component_run)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "ts": timezone.now().isoformat(),
        "run_id": component_run.run_id,
        "component_id": component_run.component_id,
        "attempt": component_run.attempt,
        "event": event,
    }
    if payload:
        line.update(payload)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True))
        handle.write("\n")
        handle.flush()


def _mark_active_component_status(
    component_run: CalendarizationComponentRun,
    status: str,
    *,
    error_message: str = "",
) -> bool:
    now = timezone.now()
    updates: dict[str, Any] = {"status": status}
    if status in CalendarizationComponentRun.TERMINAL_STATUSES:
        updates["finished_at"] = now
    if error_message is not None:
        updates["error_message"] = error_message
    updated = CalendarizationComponentRun.objects.filter(
        pk=component_run.pk,
        attempt=F("active_attempt"),
    ).update(**updates)
    if not updated:
        return False
    for field, value in updates.items():
        setattr(component_run, field, value)
    return True


def _resolve_component_path(component_run: CalendarizationComponentRun, path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    root = _audit_root_for_component(component_run)
    return root / path if root is not None else path


def _audit_root_for_component(component_run: CalendarizationComponentRun) -> Path | None:
    audit_paths = getattr(component_run.run, "audit_paths", {}) or {}
    if isinstance(audit_paths, dict):
        manifest = audit_paths.get("component_manifest")
        if manifest:
            manifest_path = Path(str(manifest))
            if manifest_path.name == "manifest.json" and manifest_path.parent.name == "components":
                return manifest_path.parent.parent
    for value in (
        component_run.context_path,
        component_run.validation_path,
        component_run.raw_result_path,
        component_run.solution_path,
        component_run.logs_path,
        component_run.error_path,
    ):
        if not value:
            continue
        candidate = Path(str(value))
        if not candidate.is_absolute():
            continue
        parts = candidate.parts
        if "components" in parts:
            return Path(*parts[: parts.index("components")])
    return None


def _finalize_run_if_components_complete(run_id: int) -> bool:
    try:
        run = CalendarizationRun.objects.get(pk=run_id)
    except CalendarizationRun.DoesNotExist:
        return False
    active_components = list(
        CalendarizationComponentRun.objects.filter(run=run, attempt=F("active_attempt")).order_by("component_id")
    )
    if not active_components:
        return False
    if any(component.status != CalendarizationComponentRun.STATUS_SUCCESS for component in active_components):
        return False

    try:
        payload = _merge_active_components(run, active_components)
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        logs = list(run.logs or [])
        logs.append(f"components: merge error ({message})")
        run.logs = logs[-500:]
        run.error_message = message
        run.save(update_fields=["logs", "error_message"])
        return False

    result = _resource_solver_result_from_payload(payload["solution"])
    context = _combined_context_from_components(active_components)
    output_path = _componentized_output_path(run, active_components)

    from calendaritzacions.reporting.resource_solver_excel_adapter import write_resource_solver_workbook

    write_resource_solver_workbook(str(output_path), result=result, context=context)

    audit_paths = dict(run.audit_paths or {}) if isinstance(run.audit_paths, dict) else {}
    merged_root = _merged_root_for_components(active_components)
    audit_paths.update(
        {
            "component_merge_validation": str(merged_root / "component_merge_validation.json"),
            "component_merged_raw_result": str(merged_root / "merged_raw_result.json"),
            "component_merged_solution": str(merged_root / "merged_solution.json"),
        }
    )
    logs = list(run.logs or [])
    logs.extend(str(item) for item in result.logs)
    logs.append(f"components: merge success components={len(active_components)} status={result.status}")
    run.mark_success(
        output_path=str(output_path),
        logs=logs[-500:],
        audit_paths=audit_paths,
        kpis_path=getattr(run, "kpis_path", ""),
    )
    CalendarizationComponentRun.objects.filter(
        run=run,
        attempt=F("active_attempt"),
        status=CalendarizationComponentRun.STATUS_SUCCESS,
    ).update(status=CalendarizationComponentRun.STATUS_MERGED, finished_at=timezone.now())
    return True


def _merge_active_components(run: CalendarizationRun, components: list[CalendarizationComponentRun]) -> dict[str, Any]:
    from calendaritzacions.engine.variants.resource_solver.component_merge import merge_component_results

    context = _combined_context_from_components(components)
    attempt_dirs = [_attempt_dir(component) for component in components]
    merged_root = _merged_root_for_components(components)
    return merge_component_results(
        context,
        attempt_dirs,
        component_ids=[component.component_id for component in components],
        output_dir=merged_root,
    )


def _combined_context_from_components(components: list[CalendarizationComponentRun]):
    from calendaritzacions.engine.variants.resource_solver.component_solver import load_component_context_payload

    contexts = [
        load_component_context_payload(_resolve_component_path(component, component.context_path))
        for component in components
    ]
    if not contexts:
        raise ValueError("No component contexts available for merge")
    first = contexts[0]
    base_resources: dict[str, Any] = {}
    capacities: dict[str, Any] = {}
    for context in contexts:
        base_resources.update(context.base_resources)
        capacities.update(context.capacities)
    return replace(
        first,
        teams=tuple(team for context in contexts for team in context.teams),
        base_resources=base_resources,
        capacities=capacities,
        pressure=tuple(row for context in contexts for row in context.pressure),
        groups=tuple(group for context in contexts for group in context.groups),
        candidates=tuple(candidate for context in contexts for candidate in context.candidates),
    )


def _resource_solver_result_from_payload(payload: dict[str, Any]):
    from calendaritzacions.engine.variants.resource_solver.types import (
        Assignment,
        GroupSummary,
        RealMatch,
        ResourceSolverResult,
        ResourceUsage,
    )

    return ResourceSolverResult(
        status=str(payload.get("status", "UNKNOWN")),
        objective_value=_optional_float(payload.get("objective_value")),
        best_bound=_optional_float(payload.get("best_bound")),
        wall_time=float(payload.get("wall_time") or 0.0),
        assignments=tuple(Assignment(str(item["team_id"]), str(item["group_id"]), int(item["number"])) for item in payload.get("assignments", [])),
        real_matches=tuple(
            RealMatch(
                round_index=int(item["round_index"]),
                group_id=str(item["group_id"]),
                home_team_id=str(item["home_team_id"]),
                away_team_id=str(item["away_team_id"]),
                home_number=int(item["home_number"]),
                away_number=int(item["away_number"]),
                resource_id=str(item["resource_id"]),
            )
            for item in payload.get("real_matches", [])
        ),
        resource_usage=tuple(
            ResourceUsage(
                resource_id=str(item["resource_id"]),
                locals_count=int(item["locals_count"]),
                capacity=int(item["capacity"]),
                excess=int(item["excess"]),
                team_ids=tuple(str(team_id) for team_id in item.get("team_ids", ())),
            )
            for item in payload.get("resource_usage", [])
        ),
        group_summary=tuple(
            GroupSummary(
                group_id=str(item["group_id"]),
                assigned_numbers={int(key): str(value) for key, value in (item.get("assigned_numbers") or {}).items()},
                empty_numbers=tuple(int(value) for value in item.get("empty_numbers", ())),
                rests_by_team={
                    str(team_id): tuple(int(value) for value in values)
                    for team_id, values in (item.get("rests_by_team") or {}).items()
                },
                entity_excess={str(key): int(value) for key, value in (item.get("entity_excess") or {}).items()},
            )
            for item in payload.get("group_summary", [])
        ),
        entity_excess=_entity_excess_from_payload(payload.get("entity_excess") or {}),
        audit_payloads=payload.get("audit_payloads") if isinstance(payload.get("audit_payloads"), dict) else {},
        logs=tuple(str(item) for item in payload.get("logs", ())),
    )


def _entity_excess_from_payload(value: dict[str, Any]) -> dict[tuple[str, str], int]:
    result: dict[tuple[str, str], int] = {}
    for key, count in value.items():
        if "|" in str(key):
            entity, group_id = str(key).split("|", 1)
        else:
            entity, group_id = str(key), ""
        result[(entity, group_id)] = int(count)
    return result


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _merged_root_for_components(components: list[CalendarizationComponentRun]) -> Path:
    root = _audit_root_for_component(components[0]) or _attempt_dir(components[0]).parents[2]
    return root / "merged"


def _componentized_output_path(run: CalendarizationRun, components: list[CalendarizationComponentRun]) -> Path:
    root = _audit_root_for_component(components[0]) or _attempt_dir(components[0]).parents[2]
    input_file = getattr(run, "input_file", None)
    input_name = Path(str(getattr(input_file, "path", "") or getattr(input_file, "name", "") or "input")).stem
    return root / f"assignacions_{input_name}.xlsx"
