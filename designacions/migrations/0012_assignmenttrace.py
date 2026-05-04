from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("designacions", "0011_match_classification_positions"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssignmentTrace",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("engine_name", models.CharField(max_length=80)),
                ("stage", models.CharField(max_length=80)),
                ("phase_name", models.CharField(blank=True, default="", max_length=80)),
                ("rescue_kind", models.CharField(blank=True, default="", max_length=80)),
                ("rescue_iteration", models.IntegerField(blank=True, null=True)),
                ("route_id", models.CharField(blank=True, default="", max_length=255)),
                ("candidate_id", models.CharField(blank=True, default="", max_length=255)),
                ("tutor_id", models.CharField(blank=True, default="", max_length=80)),
                ("route_match_ids", models.JSONField(default=list)),
                ("route_match_codes", models.JSONField(default=list)),
                ("route_size", models.IntegerField(default=1)),
                ("inserted_into_existing_route", models.BooleanField(default=False)),
                ("selected_score", models.FloatField(blank=True, null=True)),
                ("selected_cost", models.FloatField(blank=True, null=True)),
                ("level_fit", models.CharField(blank=True, default="", max_length=80)),
                ("warning_codes", models.JSONField(default=list)),
                ("mobility_summary", models.JSONField(default=dict)),
                ("debug_payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "assignment",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="trace",
                        to="designacions.assignment",
                    ),
                ),
                (
                    "match",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assignment_traces",
                        to="designacions.match",
                    ),
                ),
                (
                    "referee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assignment_traces",
                        to="designacions.referee",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assignment_traces",
                        to="designacions.designationrun",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["run", "stage"], name="designacion_run_id_38dc33_idx"),
                    models.Index(fields=["run", "referee"], name="designacion_run_id_4b8b2b_idx"),
                    models.Index(fields=["run", "match"], name="designacion_run_id_5445b1_idx"),
                    models.Index(fields=["route_id"], name="designacion_route_i_1c5b64_idx"),
                ],
            },
        ),
    ]
