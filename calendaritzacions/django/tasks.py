"""Celery tasks for calendaritzacions Django runs."""

from __future__ import annotations

import logging

from celery import signals
from celery import shared_task


logger = logging.getLogger(__name__)

MEMORY_LOST_MESSAGE = (
    "La tasca ha estat interrompuda pel worker abans de finalitzar. "
    "El procés ha rebut un SIGKILL/WorkerLostError; la causa més probable és falta de memòria "
    "durant la resolució del resource_solver."
)


@shared_task(bind=True, queue="heavy_queue", acks_late=False)
def execute_calendarization_run_task(self, run_id: int) -> int:
    return _execute_calendarization_run(self, run_id)


@shared_task(bind=True, queue="heavy_queue", acks_late=False)
def solve_resource_component_task(self, run_id: int, component_id: str, attempt: int) -> str:
    from calendaritzacions.django.services.component_tasks import _solve_resource_component

    celery_task_id = str(getattr(getattr(self, "request", None), "id", ""))
    logger.info(
        "calendaritzacions: task component rebuda run_id=%s component_id=%s attempt=%s celery_task_id=%s",
        run_id,
        component_id,
        attempt,
        celery_task_id,
    )
    return _solve_resource_component(run_id, component_id, attempt)


def _execute_calendarization_run(task, run_id: int) -> int:
    from calendaritzacions.django.models import CalendarizationRun
    from calendaritzacions.django.services.runs import execute_run

    celery_task_id = str(getattr(getattr(task, "request", None), "id", ""))
    logger.info("calendaritzacions: task rebuda run_id=%s celery_task_id=%s", run_id, celery_task_id)

    run = CalendarizationRun.objects.get(pk=run_id)
    if not run.task_id:
        run.task_id = celery_task_id
        run.save(update_fields=["task_id"])
    if run.is_finished:
        logger.info(
            "calendaritzacions: ignorant redelivery de run ja finalitzat run_id=%s status=%s celery_task_id=%s",
            run_id,
            run.status,
            celery_task_id,
        )
        _append_run_log(run, "Redelivery ignorada: el run ja estava finalitzat.")
        return run_id
    if getattr(run, "output_path", ""):
        logger.info(
            "calendaritzacions: ignorant redelivery de run amb resultat existent run_id=%s output=%s celery_task_id=%s",
            run_id,
            run.output_path,
            celery_task_id,
        )
        run.mark_success(
            output_path=run.output_path,
            logs=list(run.logs or []),
            audit_paths=dict(run.audit_paths or {}),
            kpis_path=getattr(run, "kpis_path", ""),
        )
        _append_run_log(run, "Redelivery ignorada: el run ja tenia resultat generat.")
        return run_id

    _push_run_log(run_id, "Worker heavy ha rebut la tasca.", progress=1, status="running")
    run.mark_running()
    _append_run_log(run, "Worker heavy ha rebut la tasca.")
    logger.info(
        "calendaritzacions: iniciant run_id=%s engine=%s phase=%s input=%s",
        run_id,
        run.engine_name,
        run.phase,
        _input_name(run),
    )
    start_message = f"Iniciant execucio: motor={run.engine_name}, fase={run.phase}, input={_input_name(run)}"
    _append_run_log(run, start_message)
    _push_run_log(
        run_id,
        start_message,
        progress=2,
        status="running",
    )
    execute_run(run)
    run.refresh_from_db()
    logger.info(
        "calendaritzacions: run finalitzat run_id=%s status=%s error=%s output=%s",
        run_id,
        run.status,
        run.error_message,
        run.output_path,
    )
    return run_id


def _push_run_log(run_id: int, message: str, progress: int | None = None, status: str | None = None) -> None:
    try:
        from asgiref.sync import async_to_sync
        from logs import push_log

        async_to_sync(push_log)(str(run_id), message, progress=progress, status=status)
    except Exception as exc:  # pragma: no cover - progress logging must not break the run
        logger.warning("calendaritzacions: no s'ha pogut publicar progres run_id=%s: %s", run_id, exc)


def _input_name(run) -> str:
    input_file = getattr(run, "input_file", None)
    return str(getattr(input_file, "name", "") or getattr(input_file, "path", "") or "desconegut")


def _append_run_log(run, message: str) -> None:
    try:
        logs = list(run.logs or [])
        if not logs or logs[-1] != message:
            logs.append(message)
            run.logs = logs
            run.save(update_fields=["logs"])
    except Exception as exc:  # pragma: no cover - diagnostic logging must not break the run
        logger.warning("calendaritzacions: no s'ha pogut guardar log inicial run_id=%s: %s", run.pk, exc)


@signals.task_failure.connect
def mark_calendarization_worker_lost(sender=None, exception=None, args=None, kwargs=None, **_extra) -> None:
    task_name = getattr(sender, "name", "")
    if task_name != execute_calendarization_run_task.name:
        return
    if not _looks_like_worker_lost(exception):
        return

    run_id = _extract_run_id(args, kwargs)
    if run_id is None:
        return

    from calendaritzacions.django.models import CalendarizationRun

    try:
        run = CalendarizationRun.objects.get(pk=run_id)
    except CalendarizationRun.DoesNotExist:
        return
    if run.is_finished:
        return
    logs = list(run.logs or [])
    logs.append(MEMORY_LOST_MESSAGE)
    run.mark_error(MEMORY_LOST_MESSAGE, logs=logs)


def _looks_like_worker_lost(exception) -> bool:
    try:
        from billiard.exceptions import WorkerLostError
    except Exception:  # pragma: no cover - dependency fallback
        WorkerLostError = ()  # type: ignore[assignment]

    if WorkerLostError and isinstance(exception, WorkerLostError):
        return True
    text = str(exception or "")
    return "WorkerLostError" in text or "SIGKILL" in text or "signal 9" in text


def _extract_run_id(args, kwargs) -> int | None:
    if args:
        try:
            return int(args[0])
        except (TypeError, ValueError):
            return None
    if kwargs and "run_id" in kwargs:
        try:
            return int(kwargs["run_id"])
        except (TypeError, ValueError):
            return None
    return None
