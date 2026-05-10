"""Celery tasks for calendaritzacions Django runs."""

from __future__ import annotations

from celery import shared_task


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
