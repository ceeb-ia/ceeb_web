from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0062_rotacioassignacioprogramunit"),
    ]

    operations = [
        migrations.AddField(
            model_name="scoreentry",
            name="fase",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="scores",
                to="competicions_trampoli.competicioaparellfase",
            ),
        ),
        migrations.AddField(
            model_name="teamscoreentry",
            name="fase",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="team_scores",
                to="competicions_trampoli.competicioaparellfase",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="scoreentry",
            name="uniq_scoreentry_per_exercici_aparell",
        ),
        migrations.RemoveConstraint(
            model_name="teamscoreentry",
            name="uniq_teamscoreentry_per_subject_exercici_aparell",
        ),
        migrations.AddConstraint(
            model_name="scoreentry",
            constraint=models.UniqueConstraint(
                condition=models.Q(("fase__isnull", True)),
                fields=("competicio", "inscripcio", "exercici", "comp_aparell"),
                name="uniq_scoreentry_legacy_exercici_app",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoreentry",
            constraint=models.UniqueConstraint(
                condition=models.Q(("fase__isnull", False)),
                fields=("competicio", "inscripcio", "exercici", "comp_aparell", "fase"),
                name="uniq_scoreentry_fase_exercici_app",
            ),
        ),
        migrations.AddConstraint(
            model_name="teamscoreentry",
            constraint=models.UniqueConstraint(
                condition=models.Q(("fase__isnull", True)),
                fields=("competicio", "team_subject", "exercici", "comp_aparell"),
                name="uniq_teamscoreentry_legacy_ex_app",
            ),
        ),
        migrations.AddConstraint(
            model_name="teamscoreentry",
            constraint=models.UniqueConstraint(
                condition=models.Q(("fase__isnull", False)),
                fields=("competicio", "team_subject", "exercici", "comp_aparell", "fase"),
                name="uniq_teamscoreentry_fase_ex_app",
            ),
        ),
        migrations.AddIndex(
            model_name="scoreentry",
            index=models.Index(
                fields=["competicio", "comp_aparell", "fase", "exercici"],
                name="scoreentry_phase_lookup_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="teamscoreentry",
            index=models.Index(
                fields=["competicio", "comp_aparell", "fase", "exercici"],
                name="teamscore_phase_lookup_idx",
            ),
        ),
    ]
