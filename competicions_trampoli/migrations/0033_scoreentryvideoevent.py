# Manual migration (environment without local Django runtime)

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0032_scoreentryvideo"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScoreEntryVideoEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("upload", "Upload"),
                            ("replace", "Replace"),
                            ("delete", "Delete"),
                            ("upload_rejected", "Upload Rejected"),
                        ],
                        max_length=30,
                    ),
                ),
                ("ok", models.BooleanField(default=True)),
                ("http_status", models.PositiveSmallIntegerField(default=200)),
                ("detail", models.CharField(blank=True, default="", max_length=255)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "comp_aparell",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="score_video_events",
                        to="competicions_trampoli.competicioaparell",
                    ),
                ),
                (
                    "competicio",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="score_video_events",
                        to="competicions_trampoli.competicio",
                    ),
                ),
                (
                    "inscripcio",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="score_video_events",
                        to="competicions_trampoli.inscripcio",
                    ),
                ),
                (
                    "judge_token",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="score_video_events",
                        to="competicions_trampoli.judgedevicetoken",
                    ),
                ),
                (
                    "score_entry",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="video_events",
                        to="competicions_trampoli.scoreentry",
                    ),
                ),
                (
                    "video",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="events",
                        to="competicions_trampoli.scoreentryvideo",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="scoreentryvideoevent",
            index=models.Index(fields=["competicio", "created_at"], name="comp_videoev_comp_e7ce10_idx"),
        ),
        migrations.AddIndex(
            model_name="scoreentryvideoevent",
            index=models.Index(fields=["action", "created_at"], name="comp_videoev_action_1e0f95_idx"),
        ),
        migrations.AddIndex(
            model_name="scoreentryvideoevent",
            index=models.Index(fields=["judge_token", "created_at"], name="comp_videoev_judge_8c85e0_idx"),
        ),
        migrations.AddIndex(
            model_name="scoreentryvideoevent",
            index=models.Index(fields=["score_entry", "created_at"], name="comp_videoev_score_0f43f8_idx"),
        ),
    ]
