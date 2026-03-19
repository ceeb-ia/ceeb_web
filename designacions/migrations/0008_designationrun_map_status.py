from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("designacions", "0007_assignment_manual_override_db_defaults"),
    ]

    operations = [
        migrations.AddField(
            model_name="designationrun",
            name="map_status",
            field=models.CharField(
                choices=[
                    ("ready", "Ready"),
                    ("queued", "Queued"),
                    ("processing", "Processing"),
                    ("failed", "Failed"),
                ],
                default="ready",
                max_length=20,
            ),
        ),
    ]
