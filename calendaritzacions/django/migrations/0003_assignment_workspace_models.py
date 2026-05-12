from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("calendaritzacions_django", "0002_calendarizationrun_task_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssignmentWorkspace",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(blank=True, max_length=255)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("active", "Active"),
                            ("applied", "Applied"),
                            ("archived", "Archived"),
                        ],
                        default="draft",
                        max_length=32,
                    ),
                ),
                ("source_artifact", models.CharField(blank=True, max_length=128)),
                ("summary", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assignment_workspaces",
                        to="calendaritzacions_django.calendarizationrun",
                    ),
                ),
            ],
            options={
                "ordering": ("-updated_at", "-id"),
                "indexes": [
                    models.Index(fields=["run", "status", "-updated_at"], name="cal_ws_run_status_idx"),
                    models.Index(fields=["run", "-created_at"], name="cal_ws_run_created_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="WorkspaceAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("team_id", models.CharField(max_length=128)),
                ("team_name", models.CharField(blank=True, max_length=255)),
                ("entity", models.CharField(blank=True, max_length=255)),
                ("group_id", models.CharField(blank=True, max_length=128)),
                ("assigned_number", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("seed_request_original", models.CharField(blank=True, max_length=64)),
                ("previous_group_id", models.CharField(blank=True, max_length=128)),
                ("previous_number", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workspace_assignments",
                        to="calendaritzacions_django.calendarizationrun",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assignments",
                        to="calendaritzacions_django.assignmentworkspace",
                    ),
                ),
            ],
            options={
                "ordering": ("team_id", "id"),
                "indexes": [
                    models.Index(fields=["run", "team_id"], name="cal_wsa_run_team_idx"),
                    models.Index(fields=["workspace", "team_id"], name="cal_wsa_ws_team_idx"),
                    models.Index(fields=["workspace", "group_id", "assigned_number"], name="cal_wsa_ws_slot_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("workspace", "team_id"), name="cal_ws_assignment_team_uniq"),
                ],
            },
        ),
        migrations.CreateModel(
            name="WorkspaceResourceIncident",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "incident_type",
                    models.CharField(
                        choices=[
                            ("resource_excess", "Resource excess"),
                            ("seed_deviation", "Seed deviation"),
                            ("assignment_conflict", "Assignment conflict"),
                            ("other", "Other"),
                        ],
                        default="resource_excess",
                        max_length=64,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Open"),
                            ("reviewing", "Reviewing"),
                            ("resolved", "Resolved"),
                            ("ignored", "Ignored"),
                        ],
                        default="open",
                        max_length=32,
                    ),
                ),
                ("severity", models.PositiveSmallIntegerField(default=0)),
                ("resource_id", models.CharField(blank=True, max_length=255)),
                ("excess", models.IntegerField(default=0)),
                ("locals_count", models.PositiveIntegerField(default=0)),
                ("capacity", models.PositiveIntegerField(default=0)),
                ("team_ids", models.JSONField(blank=True, default=list)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workspace_resource_incidents",
                        to="calendaritzacions_django.calendarizationrun",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="resource_incidents",
                        to="calendaritzacions_django.assignmentworkspace",
                    ),
                ),
            ],
            options={
                "ordering": ("status", "-severity", "-excess", "resource_id", "id"),
                "indexes": [
                    models.Index(fields=["run", "status", "incident_type"], name="cal_wsi_run_status_type_idx"),
                    models.Index(fields=["run", "resource_id", "-excess"], name="cal_wsi_run_resource_idx"),
                    models.Index(fields=["workspace", "status", "resource_id"], name="cal_wsi_ws_triage_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="WorkspaceResourceMatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("round_index", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("group_id", models.CharField(blank=True, max_length=128)),
                ("home_team_id", models.CharField(blank=True, max_length=128)),
                ("away_team_id", models.CharField(blank=True, max_length=128)),
                ("home_resource_id", models.CharField(blank=True, max_length=255)),
                ("away_resource_id", models.CharField(blank=True, max_length=255)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workspace_resource_matches",
                        to="calendaritzacions_django.calendarizationrun",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="resource_matches",
                        to="calendaritzacions_django.assignmentworkspace",
                    ),
                ),
            ],
            options={
                "ordering": ("round_index", "group_id", "id"),
                "indexes": [
                    models.Index(fields=["run", "home_team_id"], name="cal_wsm_run_home_team_idx"),
                    models.Index(fields=["run", "away_team_id"], name="cal_wsm_run_away_team_idx"),
                    models.Index(fields=["workspace", "round_index", "group_id"], name="cal_wsm_ws_round_idx"),
                    models.Index(fields=["run", "home_resource_id", "round_index"], name="cal_wsm_run_resource_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="WorkspaceChangeLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(max_length=128)),
                ("before", models.JSONField(blank=True, default=dict)),
                ("after", models.JSONField(blank=True, default=dict)),
                ("note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "assignment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="change_logs",
                        to="calendaritzacions_django.workspaceassignment",
                    ),
                ),
                (
                    "incident",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="change_logs",
                        to="calendaritzacions_django.workspaceresourceincident",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workspace_change_logs",
                        to="calendaritzacions_django.calendarizationrun",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="change_logs",
                        to="calendaritzacions_django.assignmentworkspace",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at", "-id"),
                "indexes": [
                    models.Index(fields=["workspace", "-created_at"], name="cal_wcl_ws_created_idx"),
                    models.Index(fields=["run", "-created_at"], name="cal_wcl_run_created_idx"),
                    models.Index(fields=["run", "action"], name="cal_wcl_run_action_idx"),
                ],
            },
        ),
    ]
