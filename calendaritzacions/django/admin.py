"""Admin registration for calendarization runs."""

from __future__ import annotations

from django.contrib import admin

from calendaritzacions.django.models import CalendarizationRun


@admin.register(CalendarizationRun)
class CalendarizationRunAdmin(admin.ModelAdmin):
    list_display = ("id", "input_name", "engine_name", "phase", "status", "task_id", "created_at", "finished_at")
    list_filter = ("status", "engine_name", "phase")
    search_fields = ("input_name", "error_message")
    readonly_fields = (
        "output_path",
        "kpis_path",
        "task_id",
        "audit_paths",
        "logs",
        "created_at",
        "started_at",
        "finished_at",
    )
