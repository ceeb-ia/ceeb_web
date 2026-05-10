"""Persistence models for the optional Django calendaritzacions app."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


def input_upload_to(_instance: "CalendarizationRun", filename: str) -> str:
    subdir = getattr(settings, "CALENDARITZACIONS_UPLOAD_SUBDIR", "calendaritzacions/inputs")
    return f"{subdir.rstrip('/')}/{filename}"


class CalendarizationRun(models.Model):
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_ERROR = "error"

    ENGINE_LEGACY = "legacy"
    ENGINE_RESOURCE_SOLVER = "resource_solver"

    PHASE_FIRST = "primera_fase"
    PHASE_SECOND = "segona_fase"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_ERROR, "Error"),
    )
    ENGINE_CHOICES = (
        (ENGINE_LEGACY, "Legacy"),
        (ENGINE_RESOURCE_SOLVER, "Resource solver"),
    )
    PHASE_CHOICES = (
        (PHASE_FIRST, "Primera fase"),
        (PHASE_SECOND, "Segona fase"),
    )

    input_file = models.FileField(upload_to=input_upload_to)
    input_name = models.CharField(max_length=255, blank=True)
    engine_name = models.CharField(max_length=64, choices=ENGINE_CHOICES, default=ENGINE_RESOURCE_SOLVER)
    phase = models.CharField(max_length=32, choices=PHASE_CHOICES, default=PHASE_FIRST)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    task_id = models.CharField(max_length=255, blank=True)
    output_path = models.TextField(blank=True)
    kpis_path = models.TextField(blank=True)
    audit_paths = models.JSONField(default=dict, blank=True)
    logs = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        label = self.input_name or getattr(self.input_file, "name", "") or "calendarization"
        return f"{label} ({self.engine_name}, {self.phase})"

    @property
    def is_finished(self) -> bool:
        return self.status in {self.STATUS_SUCCESS, self.STATUS_ERROR}

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    @property
    def available_audits(self) -> list[str]:
        if not isinstance(self.audit_paths, dict):
            return []
        return sorted(key for key, value in self.audit_paths.items() if value)

    def save(self, *args, **kwargs):
        if not self.input_name and self.input_file:
            self.input_name = self.input_file.name.rsplit("/", 1)[-1]
        super().save(*args, **kwargs)

    def _save_status_fields(self, fields: list[str]) -> None:
        if self.pk is None:
            self.save()
        else:
            self.save(update_fields=fields)

    def mark_running(self) -> None:
        self.status = self.STATUS_RUNNING
        self.started_at = timezone.now()
        self.finished_at = None
        self.error_message = ""
        self._save_status_fields(["status", "started_at", "finished_at", "error_message"])

    def mark_success(
        self,
        *,
        output_path: str,
        logs: list[str] | None = None,
        audit_paths: dict[str, str] | None = None,
        kpis_path: str = "",
    ) -> None:
        self.status = self.STATUS_SUCCESS
        self.output_path = output_path
        self.kpis_path = kpis_path
        self.logs = logs or []
        self.audit_paths = audit_paths or {}
        self.error_message = ""
        self.finished_at = timezone.now()
        self._save_status_fields(
            [
                "status",
                "output_path",
                "kpis_path",
                "logs",
                "audit_paths",
                "error_message",
                "finished_at",
            ]
        )

    def mark_error(self, message: str, logs: list[str] | None = None) -> None:
        self.status = self.STATUS_ERROR
        if logs is not None:
            self.logs = logs
        self.error_message = message
        self.finished_at = timezone.now()
        self._save_status_fields(["status", "logs", "error_message", "finished_at"])
