# Generated manually for the local competition-apparatus identity migration.

from django.db import migrations, models


def backfill_local_identity(apps, schema_editor):
    CompeticioAparell = apps.get_model("competicions_trampoli", "CompeticioAparell")
    for comp_aparell in CompeticioAparell.objects.select_related("aparell").order_by("competicio_id", "ordre", "id"):
        aparell = comp_aparell.aparell
        comp_aparell.nom_local = (comp_aparell.nom_local or getattr(aparell, "nom", "") or "").strip()
        comp_aparell.codi_local = (comp_aparell.codi_local or getattr(aparell, "codi", "") or "").strip().upper()
        comp_aparell.save(update_fields=["nom_local", "codi_local"])


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0058_scorewarningacknowledgement"),
    ]

    operations = [
        migrations.AddField(
            model_name="competicioaparell",
            name="codi_local",
            field=models.CharField(blank=True, db_index=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="competicioaparell",
            name="nom_local",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.RunPython(backfill_local_identity, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="competicioaparell",
            name="uniq_competicio_aparell",
        ),
        migrations.AddConstraint(
            model_name="competicioaparell",
            constraint=models.UniqueConstraint(
                condition=~models.Q(("codi_local", "")),
                fields=("competicio", "codi_local"),
                name="uniq_competicio_comp_app_codi_local",
            ),
        ),
    ]
