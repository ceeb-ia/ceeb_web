"""Execution boundary between Django and the calendaritzacions application layer."""

from __future__ import annotations

from django.conf import settings

from calendaritzacions.application import process_calendarization
from calendaritzacions.application.progress import progress_for_task
from calendaritzacions.django.models import CalendarizationRun
from calendaritzacions.django.services.audit_reader import discover_audit_paths


def _split_process_output(output) -> tuple[str, list[str], dict[str, str], str]:
    if isinstance(output, tuple):
        output_path = str(output[0]) if output else ""
        logs = list(output[1]) if len(output) > 1 and output[1] is not None else []
        audit_paths = dict(output[2]) if len(output) > 2 and isinstance(output[2], dict) else {}
        kpis_path = str(output[3]) if len(output) > 3 and output[3] else ""
        return output_path, logs, audit_paths, kpis_path
    return str(output), [], {}, ""


def execute_run(run: CalendarizationRun) -> CalendarizationRun:
    run.mark_running()
    logs: list[str] = []
    try:
        task_id = str(run.pk) if run.pk is not None else None
        output = process_calendarization(
            input_path=run.input_file.path,
            return_logs=True,
            return_artifacts=True,
            task_id=task_id,
            segona_fase_bool=(run.phase == CalendarizationRun.PHASE_SECOND),
            engine_name=run.engine_name,
            resource_solver_level_constraint_mode=run.resource_solver_level_constraint_mode,
            resource_solver_linkage_mode=run.resource_solver_linkage_mode,
            resource_solver_decomposition_mode=getattr(run, "resource_solver_decomposition_mode", "audit_only"),
            progress_reporter=DjangoRunProgressReporter(task_id),
        )
        output_path, logs, audit_paths, kpis_path = _split_process_output(output)
        if not audit_paths:
            audit_paths = discover_audit_paths(output_path)
        partial_audit_paths = _audit_paths_for_task(task_id)
        audit_paths = {**partial_audit_paths, **audit_paths}
        result_status = getattr(output, "status", None) if not isinstance(output, tuple) else None
        if result_status == CalendarizationRun.STATUS_RUNNING:
            run.status = CalendarizationRun.STATUS_RUNNING
            run.output_path = output_path
            run.kpis_path = kpis_path
            run.logs = logs
            run.audit_paths = audit_paths
            run.error_message = ""
            run.save(update_fields=["status", "output_path", "kpis_path", "logs", "audit_paths", "error_message"])
            return run
        run.mark_success(output_path=output_path, logs=logs, audit_paths=audit_paths, kpis_path=kpis_path)
    except Exception as exc:
        run.mark_error(str(exc), logs=logs)
    return run


class DjangoRunProgressReporter:
    def __init__(self, task_id: str | None) -> None:
        self._task_id = task_id
        self._redis_progress = progress_for_task(task_id)

    def report(self, message: str, percent: int | None = None) -> None:
        self._redis_progress.report(message, percent)
        if not self._task_id:
            return
        _append_progress_log(self._task_id, message, percent)

    def report_artifact(self, name: str, path: str) -> None:
        if not self._task_id or not name or not path:
            return
        _record_audit_path(self._task_id, name, path)


def _audit_paths_for_task(task_id: str | None) -> dict[str, str]:
    if not task_id:
        return {}
    try:
        run = CalendarizationRun.objects.get(pk=int(task_id))
    except Exception:
        return {}
    return dict(run.audit_paths or {}) if isinstance(run.audit_paths, dict) else {}


def _record_audit_path(task_id: str, name: str, path: str) -> None:
    try:
        run = CalendarizationRun.objects.get(pk=int(task_id))
    except Exception:
        return
    audit_paths = dict(run.audit_paths or {}) if isinstance(run.audit_paths, dict) else {}
    if audit_paths.get(name) == path:
        return
    audit_paths[name] = path
    run.audit_paths = audit_paths
    run.save(update_fields=["audit_paths"])


def _append_progress_log(task_id: str, message: str, percent: int | None) -> None:
    try:
        run = CalendarizationRun.objects.get(pk=int(task_id))
    except (CalendarizationRun.DoesNotExist, TypeError, ValueError):
        return
    line = f"[{percent}%] {message}" if percent is not None else str(message)
    logs = list(run.logs or [])
    if logs and logs[-1] == line:
        return
    logs.append(line)
    run.logs = logs[-200:]
    run.save(update_fields=["logs"])


def enqueue_run(run: CalendarizationRun) -> CalendarizationRun:
    backend = getattr(settings, "CALENDARITZACIONS_ASYNC_BACKEND", "sync")
    if backend == "sync":
        return execute_run(run)
    if backend == "celery":
        from calendaritzacions.django.tasks import execute_calendarization_run_task

        async_result = execute_calendarization_run_task.delay(run.pk)
        run.task_id = str(async_result.id)
        run.save(update_fields=["task_id"])
        return run
    raise NotImplementedError(f"Unsupported calendaritzacions async backend: {backend}")
