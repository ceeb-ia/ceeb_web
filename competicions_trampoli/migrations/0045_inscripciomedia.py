from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0044_rename_judgeconv_comp_status_last_idx_competicion_competi_d6842f_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="InscripcioMedia",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fitxer", models.FileField(upload_to="inscripcions/media/%Y/%m/%d/")),
                ("tipus", models.CharField(choices=[("audio", "Audio"), ("video", "Video"), ("image", "Imatge"), ("other", "Altre")], db_index=True, default="other", max_length=20)),
                ("mime_type", models.CharField(blank=True, default="", max_length=120)),
                ("original_filename", models.CharField(blank=True, default="", max_length=255)),
                ("file_size_bytes", models.PositiveBigIntegerField(default=0)),
                ("is_primary", models.BooleanField(default=False)),
                ("source", models.CharField(choices=[("manual", "Manual"), ("assisted", "Assisted")], default="manual", max_length=20)),
                ("match_score", models.DecimalField(blank=True, decimal_places=4, max_digits=5, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("competicio", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="inscripcions_media", to="competicions_trampoli.competicio")),
                ("inscripcio", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="media_files", to="competicions_trampoli.inscripcio")),
            ],
            options={
                "ordering": ["inscripcio_id", "-is_primary", "-created_at", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="inscripciomedia",
            index=models.Index(fields=["competicio", "inscripcio"], name="competicion_competi_891850_idx"),
        ),
        migrations.AddIndex(
            model_name="inscripciomedia",
            index=models.Index(fields=["competicio", "tipus"], name="competicion_competi_739e45_idx"),
        ),
        migrations.AddConstraint(
            model_name="inscripciomedia",
            constraint=models.UniqueConstraint(condition=models.Q(("is_primary", True)), fields=("inscripcio", "tipus"), name="uniq_primary_media_per_inscripcio_tipus"),
        ),
    ]
