from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("designacions", "0005_designationrun_params"),
    ]

    operations = [
        migrations.AddField(
            model_name="assignment",
            name="manual_override_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="assignment",
            name="manual_override_warning",
            field=models.BooleanField(default=False),
        ),
    ]
