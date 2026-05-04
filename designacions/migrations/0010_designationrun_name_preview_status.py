from django.db import migrations, models


def backfill_run_names(apps, schema_editor):
    DesignationRun = apps.get_model("designacions", "DesignationRun")
    for run in DesignationRun.objects.order_by("id"):
        if not getattr(run, "name", ""):
            run.name = f"Run #{run.id}"
            run.save(update_fields=["name"])


class Migration(migrations.Migration):

    dependencies = [
        ("designacions", "0009_address_normalized_text_match_address_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="designationrun",
            name="name",
            field=models.CharField(blank=True, db_index=True, default="", max_length=160),
        ),
        migrations.AlterField(
            model_name="designationrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "Queued"),
                    ("processing", "Processing"),
                    ("preview", "Preview"),
                    ("done", "Done"),
                    ("failed", "Failed"),
                ],
                default="queued",
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_run_names, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="designationrun",
            name="name",
            field=models.CharField(db_index=True, max_length=160),
        ),
    ]
