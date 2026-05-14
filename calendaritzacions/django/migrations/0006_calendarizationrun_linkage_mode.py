from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("calendaritzacions_django", "0005_calendarizationrun_level_constraint_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="calendarizationrun",
            name="resource_solver_linkage_mode",
            field=models.CharField(
                choices=[
                    ("input", "Input Excel"),
                    ("simulated", "Simulat"),
                    ("off", "Desactivat"),
                ],
                default="input",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="calendarizationrun",
            name="engine_name",
            field=models.CharField(
                choices=[
                    ("legacy", "Legacy"),
                    ("resource_solver", "Resource solver"),
                    ("resource_solver_linkage", "Resource solver + linkage"),
                ],
                default="resource_solver",
                max_length=64,
            ),
        ),
    ]
