# Generated manually for the optional calendaritzacions Django app.

from __future__ import annotations

import calendaritzacions.django.models
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="CalendarizationRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("input_file", models.FileField(upload_to=calendaritzacions.django.models.input_upload_to)),
                ("input_name", models.CharField(blank=True, max_length=255)),
                (
                    "engine_name",
                    models.CharField(
                        choices=[("legacy", "Legacy"), ("resource_solver", "Resource solver")],
                        default="resource_solver",
                        max_length=64,
                    ),
                ),
                (
                    "phase",
                    models.CharField(
                        choices=[("primera_fase", "Primera fase"), ("segona_fase", "Segona fase")],
                        default="primera_fase",
                        max_length=32,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Pending"), ("running", "Running"), ("success", "Success"), ("error", "Error")],
                        default="pending",
                        max_length=32,
                    ),
                ),
                ("output_path", models.TextField(blank=True)),
                ("kpis_path", models.TextField(blank=True)),
                ("audit_paths", models.JSONField(blank=True, default=dict)),
                ("logs", models.JSONField(blank=True, default=list)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ("-created_at", "-id")},
        ),
    ]
