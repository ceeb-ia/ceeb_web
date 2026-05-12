"""Admin registration for calendarization persistence models."""

from __future__ import annotations

from django.contrib import admin

from calendaritzacions.django.models import (
    AssignmentWorkspace,
    CalendarizationRun,
    WorkspaceAssignment,
    WorkspaceChangeLog,
    WorkspaceResourceIncident,
    WorkspaceResourceMatch,
)


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


@admin.register(AssignmentWorkspace)
class AssignmentWorkspaceAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "name", "status", "source_artifact", "created_at", "updated_at")
    list_filter = ("status", "source_artifact", "created_at")
    search_fields = ("name", "run__input_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(WorkspaceAssignment)
class WorkspaceAssignmentAdmin(admin.ModelAdmin):
    list_display = ("id", "workspace", "run", "team_id", "team_name", "group_id", "assigned_number", "updated_at")
    list_filter = ("group_id", "assigned_number")
    search_fields = ("team_id", "team_name", "entity", "group_id", "run__input_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(WorkspaceResourceIncident)
class WorkspaceResourceIncidentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "workspace",
        "run",
        "incident_type",
        "status",
        "severity",
        "resource_id",
        "excess",
        "updated_at",
    )
    list_filter = ("status", "incident_type", "severity")
    search_fields = ("resource_id", "run__input_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(WorkspaceResourceMatch)
class WorkspaceResourceMatchAdmin(admin.ModelAdmin):
    list_display = ("id", "workspace", "run", "round_index", "group_id", "home_team_id", "away_team_id")
    list_filter = ("round_index", "group_id")
    search_fields = ("home_team_id", "away_team_id", "home_resource_id", "away_resource_id", "run__input_name")
    readonly_fields = ("created_at",)


@admin.register(WorkspaceChangeLog)
class WorkspaceChangeLogAdmin(admin.ModelAdmin):
    list_display = ("id", "workspace", "run", "action", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("action", "note", "run__input_name")
    readonly_fields = ("created_at",)
