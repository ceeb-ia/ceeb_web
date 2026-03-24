from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0047_equipcontext_inscripcioequipassignacio"),
    ]

    operations = [
        migrations.AddField(
            model_name="competicioaparell",
            name="expected_team_size",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="competicioaparell",
            name="participant_mode",
            field=models.CharField(
                choices=[("individual", "Individual"), ("team_context", "Equips d'un context")],
                default="individual",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="competicioaparell",
            name="team_context",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="aparells_cfg",
                to="competicions_trampoli.equipcontext",
            ),
        ),
        migrations.AddField(
            model_name="competicioaparell",
            name="team_scoring_mode",
            field=models.CharField(
                blank=True,
                choices=[
                    ("members_plus_shared", "Membres + compartides"),
                    ("members_only", "Nomes membres"),
                    ("shared_only", "Nomes compartides"),
                ],
                default="",
                max_length=24,
            ),
        ),
        migrations.CreateModel(
            name="TeamScoreEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("exercici", models.PositiveSmallIntegerField(default=1)),
                ("inputs", models.JSONField(blank=True, default=dict)),
                ("outputs", models.JSONField(blank=True, default=dict)),
                ("total", models.DecimalField(decimal_places=3, default=0, max_digits=10)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("comp_aparell", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="team_scores", to="competicions_trampoli.competicioaparell")),
                ("competicio", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="team_scores", to="competicions_trampoli.competicio")),
                ("equip", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="team_scores", to="competicions_trampoli.equip")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["competicio", "comp_aparell", "exercici"], name="competicion_competi_1db8d6_idx"),
                    models.Index(fields=["competicio", "equip"], name="competicion_competi_7e7bf1_idx"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="teamscoreentry",
            constraint=models.UniqueConstraint(fields=("competicio", "equip", "exercici", "comp_aparell"), name="uniq_teamscoreentry_per_exercici_aparell"),
        ),
        migrations.CreateModel(
            name="TeamScoreEntryVideo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("video_file", models.FileField(upload_to="trampoli/team_score_videos/%Y/%m/%d/")),
                ("status", models.CharField(choices=[("pending", "Pendent"), ("ready", "Disponible"), ("failed", "Error")], default="pending", max_length=20)),
                ("duration_seconds", models.PositiveIntegerField(blank=True, null=True)),
                ("file_size_bytes", models.PositiveBigIntegerField(default=0)),
                ("mime_type", models.CharField(blank=True, default="", max_length=100)),
                ("original_filename", models.CharField(blank=True, default="", max_length=255)),
                ("error_message", models.CharField(blank=True, default="", max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("judge_token", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="team_score_videos", to="competicions_trampoli.judgedevicetoken")),
                ("team_score_entry", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="video_capture", to="competicions_trampoli.teamscoreentry")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["status", "created_at"], name="competicion_status_25d19e_idx"),
                    models.Index(fields=["judge_token", "created_at"], name="competicion_judge_t_521b8c_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="TeamScoreEntryVideoEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("upload", "Upload"), ("replace", "Replace"), ("delete", "Delete"), ("upload_rejected", "Upload Rejected")], max_length=30)),
                ("ok", models.BooleanField(default=True)),
                ("http_status", models.PositiveSmallIntegerField(default=200)),
                ("detail", models.CharField(blank=True, default="", max_length=255)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("comp_aparell", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="team_score_video_events", to="competicions_trampoli.competicioaparell")),
                ("competicio", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="team_score_video_events", to="competicions_trampoli.competicio")),
                ("equip", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="team_score_video_events", to="competicions_trampoli.equip")),
                ("judge_token", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="team_score_video_events", to="competicions_trampoli.judgedevicetoken")),
                ("team_score_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="video_events", to="competicions_trampoli.teamscoreentry")),
                ("video", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="events", to="competicions_trampoli.teamscoreentryvideo")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["competicio", "created_at"], name="competicion_competi_2d4a94_idx"),
                    models.Index(fields=["action", "created_at"], name="competicion_action__1af2ee_idx"),
                    models.Index(fields=["judge_token", "created_at"], name="competicion_judge_t_2a4c56_idx"),
                    models.Index(fields=["team_score_entry", "created_at"], name="competicion_team_sc_ba7619_idx"),
                ],
            },
        ),
    ]
