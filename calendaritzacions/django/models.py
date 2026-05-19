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
    ENGINE_RESOURCE_SOLVER_LINKAGE = "resource_solver_linkage"
    ENGINE_RESOURCE_SOLVER_VINCULACIO = "resource_solver_vinculacio"

    LINKAGE_MODE_OFF = "off"
    LINKAGE_MODE_INPUT = "input"
    LINKAGE_MODE_SIMULATED = "simulated"

    COMPETITION_GROUPING_AUTO = "auto"
    COMPETITION_GROUPING_LEAGUE = "league"
    COMPETITION_GROUPING_FIELDS = "fields"

    LEVEL_CONSTRAINT_OFF = "off"
    LEVEL_CONSTRAINT_SOFT = "soft"
    LEVEL_CONSTRAINT_AGGREGATE = "aggregate"
    LEVEL_CONSTRAINT_HARD = "hard"

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
        (ENGINE_RESOURCE_SOLVER_LINKAGE, "Resource solver + linkage"),
    )
    PHASE_CHOICES = (
        (PHASE_FIRST, "Primera fase"),
        (PHASE_SECOND, "Segona fase"),
    )
    LEVEL_CONSTRAINT_CHOICES = (
        (LEVEL_CONSTRAINT_OFF, "Desactivat"),
        (LEVEL_CONSTRAINT_SOFT, "Suau per parelles"),
        (LEVEL_CONSTRAINT_AGGREGATE, "Suau agregat"),
        (LEVEL_CONSTRAINT_HARD, "Dur estructural"),
    )
    RESOURCE_SOLVER_DECOMPOSITION_OFF = "off"
    RESOURCE_SOLVER_DECOMPOSITION_AUDIT_ONLY = "audit_only"
    RESOURCE_SOLVER_DECOMPOSITION_PERSIST_COMPONENTS = "persist_components"
    RESOURCE_SOLVER_DECOMPOSITION_SOLVE_COMPONENTS = "solve_components"
    RESOURCE_SOLVER_DECOMPOSITION_CHOICES = (
        (RESOURCE_SOLVER_DECOMPOSITION_AUDIT_ONLY, "Auditoria"),
        (RESOURCE_SOLVER_DECOMPOSITION_OFF, "Desactivat"),
        (RESOURCE_SOLVER_DECOMPOSITION_PERSIST_COMPONENTS, "Persistir components"),
        (RESOURCE_SOLVER_DECOMPOSITION_SOLVE_COMPONENTS, "Resoldre components"),
    )
    LINKAGE_MODE_CHOICES = (
        (LINKAGE_MODE_INPUT, "Input Excel"),
        (LINKAGE_MODE_SIMULATED, "Simulat"),
        (LINKAGE_MODE_OFF, "Desactivat"),
    )
    COMPETITION_GROUPING_CHOICES = (
        (COMPETITION_GROUPING_AUTO, "Auto"),
        (COMPETITION_GROUPING_LEAGUE, "Nom Lliga"),
        (COMPETITION_GROUPING_FIELDS, "Modalitat / categoria / subcategoria"),
    )

    input_file = models.FileField(upload_to=input_upload_to)
    input_name = models.CharField(max_length=255, blank=True)
    engine_name = models.CharField(max_length=64, choices=ENGINE_CHOICES, default=ENGINE_RESOURCE_SOLVER)
    phase = models.CharField(max_length=32, choices=PHASE_CHOICES, default=PHASE_FIRST)
    resource_solver_level_constraint_mode = models.CharField(
        max_length=16,
        choices=LEVEL_CONSTRAINT_CHOICES,
        default=LEVEL_CONSTRAINT_OFF,
    )
    resource_solver_linkage_mode = models.CharField(
        max_length=16,
        choices=LINKAGE_MODE_CHOICES,
        default=LINKAGE_MODE_INPUT,
    )
    resource_solver_decomposition_mode = models.CharField(
        max_length=32,
        choices=RESOURCE_SOLVER_DECOMPOSITION_CHOICES,
        default=RESOURCE_SOLVER_DECOMPOSITION_AUDIT_ONLY,
    )
    resource_solver_competition_grouping = models.CharField(
        max_length=16,
        choices=COMPETITION_GROUPING_CHOICES,
        default=COMPETITION_GROUPING_AUTO,
    )
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


class CalendarizationComponentRun(models.Model):
    STATUS_PENDING = "pending"
    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_ERROR = "error"
    STATUS_STALE = "stale"
    STATUS_SKIPPED = "skipped"
    STATUS_MERGED = "merged"
    STATUS_SUPERSEDED = "superseded"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_ERROR, "Error"),
        (STATUS_STALE, "Stale"),
        (STATUS_SKIPPED, "Skipped"),
        (STATUS_MERGED, "Merged"),
        (STATUS_SUPERSEDED, "Superseded"),
    )

    TERMINAL_STATUSES = frozenset(
        {
            STATUS_SUCCESS,
            STATUS_ERROR,
            STATUS_STALE,
            STATUS_SKIPPED,
            STATUS_MERGED,
            STATUS_SUPERSEDED,
        }
    )

    run = models.ForeignKey(CalendarizationRun, on_delete=models.CASCADE, related_name="component_runs")
    component_id = models.CharField(max_length=32)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempt = models.PositiveIntegerField(default=1)
    active_attempt = models.PositiveIntegerField(default=1)

    team_count = models.PositiveIntegerField(default=0)
    candidate_count = models.PositiveIntegerField(default=0)
    competition_count = models.PositiveIntegerField(default=0)
    resource_count = models.PositiveIntegerField(default=0)
    linkage_count = models.PositiveIntegerField(default=0)

    queued_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    context_path = models.TextField(blank=True, default="")
    validation_path = models.TextField(blank=True, default="")
    model_summary_path = models.TextField(blank=True, default="")
    raw_result_path = models.TextField(blank=True, default="")
    solution_path = models.TextField(blank=True, default="")
    logs_path = models.TextField(blank=True, default="")
    error_path = models.TextField(blank=True, default="")
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("run_id", "component_id", "attempt")
        constraints = (
            models.UniqueConstraint(
                fields=("run", "component_id", "attempt"),
                name="cal_component_run_attempt_uniq",
            ),
        )
        indexes = (
            models.Index(fields=("run", "status"), name="cal_comp_run_status_idx"),
            models.Index(fields=("run", "component_id", "active_attempt"), name="cal_comp_run_active_idx"),
        )

    def __str__(self) -> str:
        return f"Run {self.run_id} component {self.component_id} attempt {self.attempt} ({self.status})"

    @property
    def is_active_attempt(self) -> bool:
        return self.attempt == self.active_attempt


class AssignmentWorkspace(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_APPLIED = "applied"
    STATUS_ARCHIVED = "archived"

    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_APPLIED, "Applied"),
        (STATUS_ARCHIVED, "Archived"),
    )

    run = models.ForeignKey(CalendarizationRun, on_delete=models.CASCADE, related_name="assignment_workspaces")
    name = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    source_artifact = models.CharField(max_length=128, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-id")
        indexes = (
            models.Index(fields=("run", "status", "-updated_at"), name="cal_ws_run_status_idx"),
            models.Index(fields=("run", "-created_at"), name="cal_ws_run_created_idx"),
        )

    def __str__(self) -> str:
        return self.name or f"Workspace {self.pk or '-'} for run {self.run_id}"


class WorkspaceAssignment(models.Model):
    workspace = models.ForeignKey(AssignmentWorkspace, on_delete=models.CASCADE, related_name="assignments")
    run = models.ForeignKey(CalendarizationRun, on_delete=models.CASCADE, related_name="workspace_assignments")
    team_id = models.CharField(max_length=128)
    team_name = models.CharField(max_length=255, blank=True)
    entity = models.CharField(max_length=255, blank=True)
    group_id = models.CharField(max_length=128, blank=True)
    assigned_number = models.PositiveSmallIntegerField(null=True, blank=True)
    seed_request_original = models.CharField(max_length=64, blank=True)
    previous_group_id = models.CharField(max_length=128, blank=True)
    previous_number = models.PositiveSmallIntegerField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("team_id", "id")
        constraints = (
            models.UniqueConstraint(fields=("workspace", "team_id"), name="cal_ws_assignment_team_uniq"),
        )
        indexes = (
            models.Index(fields=("run", "team_id"), name="cal_wsa_run_team_idx"),
            models.Index(fields=("workspace", "team_id"), name="cal_wsa_ws_team_idx"),
            models.Index(fields=("workspace", "group_id", "assigned_number"), name="cal_wsa_ws_slot_idx"),
        )

    def __str__(self) -> str:
        label = self.team_name or self.team_id
        slot = f"{self.group_id}:{self.assigned_number}" if self.group_id or self.assigned_number else "-"
        return f"{label} -> {slot}"


class WorkspaceResourceIncident(models.Model):
    TYPE_RESOURCE_EXCESS = "resource_excess"
    TYPE_SEED_DEVIATION = "seed_deviation"
    TYPE_ASSIGNMENT_CONFLICT = "assignment_conflict"
    TYPE_LINKAGE_VIOLATION = "linkage_violation"
    TYPE_LEVEL_MISMATCH = "level_mismatch"
    TYPE_OTHER = "other"

    STATUS_OPEN = "open"
    STATUS_REVIEWING = "reviewing"
    STATUS_RESOLVED = "resolved"
    STATUS_IGNORED = "ignored"

    TYPE_CHOICES = (
        (TYPE_RESOURCE_EXCESS, "Resource excess"),
        (TYPE_SEED_DEVIATION, "Seed deviation"),
        (TYPE_ASSIGNMENT_CONFLICT, "Assignment conflict"),
        (TYPE_LINKAGE_VIOLATION, "Linkage violation"),
        (TYPE_LEVEL_MISMATCH, "Level mismatch"),
        (TYPE_OTHER, "Other"),
    )
    STATUS_CHOICES = (
        (STATUS_OPEN, "Open"),
        (STATUS_REVIEWING, "Reviewing"),
        (STATUS_RESOLVED, "Resolved"),
        (STATUS_IGNORED, "Ignored"),
    )

    workspace = models.ForeignKey(AssignmentWorkspace, on_delete=models.CASCADE, related_name="resource_incidents")
    run = models.ForeignKey(CalendarizationRun, on_delete=models.CASCADE, related_name="workspace_resource_incidents")
    incident_type = models.CharField(max_length=64, choices=TYPE_CHOICES, default=TYPE_RESOURCE_EXCESS)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_OPEN)
    severity = models.PositiveSmallIntegerField(default=0)
    resource_id = models.CharField(max_length=255, blank=True)
    excess = models.IntegerField(default=0)
    locals_count = models.PositiveIntegerField(default=0)
    capacity = models.PositiveIntegerField(default=0)
    team_ids = models.JSONField(default=list, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("status", "-severity", "-excess", "resource_id", "id")
        indexes = (
            models.Index(fields=("run", "status", "incident_type"), name="cal_wsi_run_status_type_idx"),
            models.Index(fields=("run", "resource_id", "-excess"), name="cal_wsi_run_resource_idx"),
            models.Index(fields=("workspace", "status", "resource_id"), name="cal_wsi_ws_triage_idx"),
        )

    def __str__(self) -> str:
        target = self.resource_id or self.incident_type
        return f"{target} ({self.status})"


class WorkspaceResourceMatch(models.Model):
    workspace = models.ForeignKey(AssignmentWorkspace, on_delete=models.CASCADE, related_name="resource_matches")
    run = models.ForeignKey(CalendarizationRun, on_delete=models.CASCADE, related_name="workspace_resource_matches")
    round_index = models.PositiveSmallIntegerField(null=True, blank=True)
    group_id = models.CharField(max_length=128, blank=True)
    home_team_id = models.CharField(max_length=128, blank=True)
    away_team_id = models.CharField(max_length=128, blank=True)
    home_resource_id = models.CharField(max_length=255, blank=True)
    away_resource_id = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("round_index", "group_id", "id")
        indexes = (
            models.Index(fields=("run", "home_team_id"), name="cal_wsm_run_home_team_idx"),
            models.Index(fields=("run", "away_team_id"), name="cal_wsm_run_away_team_idx"),
            models.Index(fields=("workspace", "round_index", "group_id"), name="cal_wsm_ws_round_idx"),
            models.Index(fields=("run", "home_resource_id", "round_index"), name="cal_wsm_run_resource_idx"),
        )

    def __str__(self) -> str:
        return f"Round {self.round_index or '-'}: {self.home_team_id or '-'} vs {self.away_team_id or '-'}"


class WorkspaceChangeLog(models.Model):
    workspace = models.ForeignKey(AssignmentWorkspace, on_delete=models.CASCADE, related_name="change_logs")
    run = models.ForeignKey(CalendarizationRun, on_delete=models.CASCADE, related_name="workspace_change_logs")
    assignment = models.ForeignKey(
        WorkspaceAssignment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="change_logs",
    )
    incident = models.ForeignKey(
        WorkspaceResourceIncident,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="change_logs",
    )
    action = models.CharField(max_length=128)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = (
            models.Index(fields=("workspace", "-created_at"), name="cal_wcl_ws_created_idx"),
            models.Index(fields=("run", "-created_at"), name="cal_wcl_run_created_idx"),
            models.Index(fields=("run", "action"), name="cal_wcl_run_action_idx"),
        )

    def __str__(self) -> str:
        return f"{self.action} on workspace {self.workspace_id}"
