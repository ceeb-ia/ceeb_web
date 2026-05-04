from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("designacions", "0010_designationrun_name_preview_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="match",
            name="posicio_equip_local",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="match",
            name="posicio_equip_visitant",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
