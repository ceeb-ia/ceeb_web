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


@shared_task(bind=True, queue="heavy_queue")
def execute_calendarization_run_task(self, run_id: int) -> int:
    from calendaritzacions.django.models import CalendarizationRun
    from calendaritzacions.django.services.runs import execute_run

    logger.info("calendaritzacions: task rebuda run_id=%s celery_task_id=%s", run_id, self.request.id)
    _push_run_log(run_id, "Worker heavy ha rebut la tasca.", progress=1, status="running")

    run = CalendarizationRun.objects.get(pk=run_id)
    if not run.task_id:
        run.task_id = str(self.request.id)
        run.save(update_fields=["task_id"])
    if not run.is_finished:
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
    logger.info("calendaritzacions: run finalitzat run_id=%s", run_id)
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
