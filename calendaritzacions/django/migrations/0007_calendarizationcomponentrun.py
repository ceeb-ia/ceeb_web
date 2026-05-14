from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("calendaritzacions_django", "0006_calendarizationrun_linkage_mode"),
    ]

    operations = [
        migrations.CreateModel(
            name="CalendarizationComponentRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("component_id", models.CharField(max_length=32)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("success", "Success"),
                            ("error", "Error"),
                            ("stale", "Stale"),
                            ("skipped", "Skipped"),
                            ("merged", "Merged"),
                            ("superseded", "Superseded"),
                        ],
                        default="pending",
                        max_length=32,
                    ),
                ),
                ("attempt", models.PositiveIntegerField(default=1)),
                ("active_attempt", models.PositiveIntegerField(default=1)),
                ("team_count", models.PositiveIntegerField(default=0)),
                ("candidate_count", models.PositiveIntegerField(default=0)),
                ("competition_count", models.PositiveIntegerField(default=0)),
                ("resource_count", models.PositiveIntegerField(default=0)),
                ("linkage_count", models.PositiveIntegerField(default=0)),
                ("queued_at", models.DateTimeField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("heartbeat_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("context_path", models.TextField(blank=True, default="")),
                ("validation_path", models.TextField(blank=True, default="")),
                ("model_summary_path", models.TextField(blank=True, default="")),
                ("raw_result_path", models.TextField(blank=True, default="")),
                ("solution_path", models.TextField(blank=True, default="")),
                ("logs_path", models.TextField(blank=True, default="")),
                ("error_path", models.TextField(blank=True, default="")),
                ("error_message", models.TextField(blank=True, default="")),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="component_runs",
                        to="calendaritzacions_django.calendarizationrun",
                    ),
                ),
            ],
            options={
                "ordering": ("run_id", "component_id", "attempt"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("run", "component_id", "attempt"),
                        name="cal_component_run_attempt_uniq",
                    )
                ],
                "indexes": [
                    models.Index(fields=("run", "status"), name="cal_comp_run_status_idx"),
                    models.Index(fields=("run", "component_id", "active_attempt"), name="cal_comp_run_active_idx"),
                ],
            },
        ),
    ]
