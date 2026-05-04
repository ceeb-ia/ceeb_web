from django.db import migrations, models
import django.db.models.deletion


DEFAULT_PHASE_CODE = "DEFAULT"
DEFAULT_PHASE_NAME = "Fase unica"


def backfill_default_phases(apps, schema_editor):
    CompeticioAparell = apps.get_model("competicions_trampoli", "CompeticioAparell")
    CompeticioAparellFase = apps.get_model("competicions_trampoli", "CompeticioAparellFase")
    for comp_aparell in CompeticioAparell.objects.order_by("competicio_id", "ordre", "id"):
        CompeticioAparellFase.objects.get_or_create(
            competicio_id=comp_aparell.competicio_id,
            comp_aparell_id=comp_aparell.id,
            codi=DEFAULT_PHASE_CODE,
            defaults={
                "nom": DEFAULT_PHASE_NAME,
                "ordre": 1,
                "estat": "published",
                "config": {
                    "source_mode": "legacy_default",
                    "implicit": True,
                },
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0059_competicioaparell_local_identity"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompeticioAparellFase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=120)),
                ("codi", models.CharField(db_index=True, max_length=40)),
                ("ordre", models.PositiveSmallIntegerField(default=1)),
                (
                    "estat",
                    models.CharField(
                        choices=[
                            ("planned", "Planificada"),
                            ("generated", "Generada"),
                            ("partially_confirmed", "Parcialment confirmada"),
                            ("confirmed", "Confirmada"),
                            ("published", "Publicada"),
                            ("closed", "Tancada"),
                            ("stale", "Obsoleta"),
                        ],
                        default="planned",
                        max_length=30,
                    ),
                ),
                ("config", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "comp_aparell",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fases",
                        to="competicions_trampoli.competicioaparell",
                    ),
                ),
                (
                    "competicio",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="aparell_fases",
                        to="competicions_trampoli.competicio",
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="children",
                        to="competicions_trampoli.competicioaparellfase",
                    ),
                ),
            ],
            options={
                "ordering": ["comp_aparell_id", "ordre", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="competicioaparellfase",
            constraint=models.UniqueConstraint(
                fields=("competicio", "comp_aparell", "codi"),
                name="uniq_comp_app_fase_codi",
            ),
        ),
        migrations.AddIndex(
            model_name="competicioaparellfase",
            index=models.Index(fields=["competicio", "comp_aparell", "ordre"], name="compfase_comp_app_ordre_idx"),
        ),
        migrations.AddIndex(
            model_name="competicioaparellfase",
            index=models.Index(fields=["competicio", "estat"], name="compfase_comp_estat_idx"),
        ),
        migrations.RunPython(backfill_default_phases, migrations.RunPython.noop),
    ]
