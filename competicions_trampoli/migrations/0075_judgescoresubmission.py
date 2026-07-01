from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0074_judgeportalassignment_subject_scope"),
    ]

    operations = [
        migrations.CreateModel(
            name="JudgeScoreSubmission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("subject_kind", models.CharField(default="inscripcio", max_length=30)),
                ("subject_id", models.PositiveIntegerField()),
                ("exercici", models.PositiveSmallIntegerField(default=1)),
                ("field_code", models.CharField(max_length=80)),
                ("runtime_field_code", models.CharField(blank=True, default="", max_length=120)),
                ("judge_index", models.PositiveSmallIntegerField(default=1)),
                ("item_start", models.PositiveSmallIntegerField(default=1)),
                ("item_count", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("inputs_patch", models.JSONField(blank=True, default=dict)),
                ("normalized_inputs_patch", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendent"),
                            ("approved", "Aprovada"),
                            ("rejected", "Rebutjada"),
                            ("superseded", "Substituida"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "competicio",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="judge_score_submissions",
                        to="competicions_trampoli.competicio",
                    ),
                ),
                (
                    "comp_aparell",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="judge_score_submissions",
                        to="competicions_trampoli.competicioaparell",
                    ),
                ),
                (
                    "fase",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="judge_score_submissions",
                        to="competicions_trampoli.competicioaparellfase",
                    ),
                ),
                (
                    "reviewed_by_assignment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviewed_score_submissions",
                        to="competicions_trampoli.judgeportalassignment",
                    ),
                ),
                (
                    "reviewed_by_token",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reviewed_score_submissions",
                        to="competicions_trampoli.judgedevicetoken",
                    ),
                ),
                (
                    "submitted_by_assignment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="score_submissions",
                        to="competicions_trampoli.judgeportalassignment",
                    ),
                ),
                (
                    "submitted_by_token",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="score_submissions",
                        to="competicions_trampoli.judgedevicetoken",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="judgescoresubmission",
            index=models.Index(
                fields=["competicio", "comp_aparell", "fase", "status"],
                name="judgesub_scope_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="judgescoresubmission",
            index=models.Index(fields=["submitted_by_token", "status"], name="judgesub_token_status_idx"),
        ),
        migrations.AddIndex(
            model_name="judgescoresubmission",
            index=models.Index(fields=["field_code", "runtime_field_code", "status"], name="judgesub_field_status_idx"),
        ),
        migrations.AddIndex(
            model_name="judgescoresubmission",
            index=models.Index(fields=["subject_kind", "subject_id", "exercici"], name="judgesub_subject_ex_idx"),
        ),
    ]
