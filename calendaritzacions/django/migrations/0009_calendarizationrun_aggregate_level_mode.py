from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("calendaritzacions_django", "0008_calendarizationrun_decomposition_mode"),
    ]

    operations = [
        migrations.AlterField(
            model_name="calendarizationrun",
            name="resource_solver_level_constraint_mode",
            field=models.CharField(
                choices=[
                    ("off", "Desactivat"),
                    ("soft", "Suau per parelles"),
                    ("aggregate", "Suau agregat"),
                    ("hard", "Dur estructural"),
                ],
                default="off",
                max_length=16,
            ),
        ),
    ]
