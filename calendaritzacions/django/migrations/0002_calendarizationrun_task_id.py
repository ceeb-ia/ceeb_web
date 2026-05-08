from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("calendaritzacions_django", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="calendarizationrun",
            name="task_id",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
