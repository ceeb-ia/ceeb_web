from django.db import migrations, models


def _backfill_judge_ui_config(apps, schema_editor):
    CompeticioAparell = apps.get_model("competicions_trampoli", "CompeticioAparell")
    CompeticioAparell.objects.filter(judge_ui_config__isnull=True).update(judge_ui_config={})


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0056_rotaciofranja_color_fons_rotaciofranja_ordre_visual"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.AddField(
                    model_name="competicioaparell",
                    name="judge_ui_config",
                    field=models.JSONField(blank=True, null=True),
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="competicioaparell",
                    name="judge_ui_config",
                    field=models.JSONField(blank=True, default=dict),
                ),
            ],
        ),
        migrations.RunPython(_backfill_judge_ui_config, migrations.RunPython.noop),
    ]
