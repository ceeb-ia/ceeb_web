"""Celery tasks for calendaritzacions Django runs."""

from __future__ import annotations

from celery import signals
from celery import shared_task


MEMORY_LOST_MESSAGE = (
    "La tasca ha estat interrompuda pel worker abans de finalitzar. "
    "El procés ha rebut un SIGKILL/WorkerLostError; la causa més probable és falta de memòria "
    "durant la resolució del resource_solver."
)


@shared_task(bind=True, queue="heavy_queue")
def execute_calendarization_run_task(self, run_id: int) -> int:
    from calendaritzacions.django.models import CalendarizationRun
    from calendaritzacions.django.services.runs import execute_run

    run = CalendarizationRun.objects.get(pk=run_id)
    if not run.task_id:
        run.task_id = str(self.request.id)
        run.save(update_fields=["task_id"])
    execute_run(run)
    return run_id


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
