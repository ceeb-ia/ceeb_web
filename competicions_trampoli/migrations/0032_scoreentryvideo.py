# Manual migration (environment without local Django runtime)

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0031_publiclivetoken"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScoreEntryVideo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("video_file", models.FileField(upload_to="trampoli/score_videos/%Y/%m/%d/")),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Pendent"), ("ready", "Disponible"), ("failed", "Error")],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("duration_seconds", models.PositiveIntegerField(blank=True, null=True)),
                ("file_size_bytes", models.PositiveBigIntegerField(default=0)),
                ("mime_type", models.CharField(blank=True, default="", max_length=100)),
                ("original_filename", models.CharField(blank=True, default="", max_length=255)),
                ("error_message", models.CharField(blank=True, default="", max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "judge_token",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="score_videos",
                        to="competicions_trampoli.judgedevicetoken",
                    ),
                ),
                (
                    "score_entry",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="video_capture",
                        to="competicions_trampoli.scoreentry",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="scoreentryvideo",
            index=models.Index(fields=["status", "created_at"], name="competicion_status_26cc34_idx"),
        ),
        migrations.AddIndex(
            model_name="scoreentryvideo",
            index=models.Index(fields=["judge_token", "created_at"], name="competicion_judge_t_89f5da_idx"),
        ),
    ]

