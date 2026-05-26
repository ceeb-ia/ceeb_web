from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0067_rotaciofranja_nota_interna"),
    ]

    operations = [
        migrations.CreateModel(
            name="JudgePortalAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(blank=True, default="", max_length=160)),
                ("ordre", models.PositiveSmallIntegerField(default=1)),
                ("permissions", models.JSONField(blank=True, default=list)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "comp_aparell",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="judge_portal_assignments",
                        to="competicions_trampoli.competicioaparell",
                    ),
                ),
                (
                    "competicio",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="judge_portal_assignments",
                        to="competicions_trampoli.competicio",
                    ),
                ),
                (
                    "fase",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="judge_portal_assignments",
                        to="competicions_trampoli.competicioaparellfase",
                    ),
                ),
                (
                    "judge_token",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="portal_assignments",
                        to="competicions_trampoli.judgedevicetoken",
                    ),
                ),
            ],
            options={
                "ordering": ["judge_token_id", "ordre", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="judgeportalassignment",
            index=models.Index(fields=["competicio", "comp_aparell"], name="judgeassign_comp_app_idx"),
        ),
        migrations.AddIndex(
            model_name="judgeportalassignment",
            index=models.Index(fields=["judge_token", "is_active"], name="judgeassign_token_active_idx"),
        ),
        migrations.AddIndex(
            model_name="judgeportalassignment",
            index=models.Index(fields=["fase", "is_active"], name="judgeassign_fase_active_idx"),
        ),
        migrations.AddConstraint(
            model_name="judgeportalassignment",
            constraint=models.UniqueConstraint(fields=("judge_token", "ordre"), name="uniq_judge_assignment_token_ordre"),
        ),
    ]
