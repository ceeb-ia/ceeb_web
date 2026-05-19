from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("calendaritzacions_django", "0009_calendarizationrun_aggregate_level_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="calendarizationrun",
            name="resource_solver_competition_grouping",
            field=models.CharField(
                choices=[
                    ("auto", "Auto"),
                    ("league", "Nom Lliga"),
                    ("fields", "Modalitat / categoria / subcategoria"),
                ],
                default="auto",
                max_length=16,
            ),
        ),
    ]
