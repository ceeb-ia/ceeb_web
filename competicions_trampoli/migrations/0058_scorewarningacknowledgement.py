from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("competicions_trampoli", "0057_competicioaparell_judge_ui_config"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScoreWarningAcknowledgement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("warning_key", models.CharField(max_length=255)),
                ("note", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "competicio",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="score_warning_acknowledgements",
                        to="competicions_trampoli.competicio",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="score_warning_acknowledgements",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="scorewarningacknowledgement",
            constraint=models.UniqueConstraint(
                fields=("competicio", "warning_key"),
                name="uniq_score_warning_ack_comp_key",
            ),
        ),
        migrations.AddIndex(
            model_name="scorewarningacknowledgement",
            index=models.Index(fields=["competicio", "created_at"], name="competicion_competi_ef5f73_idx"),
        ),
    ]
