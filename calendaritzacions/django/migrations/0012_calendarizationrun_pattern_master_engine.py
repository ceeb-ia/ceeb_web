from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("calendaritzacions_django", "0011_calendarizationrun_conflict_repair_engine"),
    ]

    operations = [
        migrations.AlterField(
            model_name="calendarizationrun",
            name="engine_name",
            field=models.CharField(
                choices=[
                    ("legacy", "Legacy"),
                    ("resource_solver", "Resource solver"),
                    ("resource_solver_linkage", "Resource solver + linkage"),
                    ("resource_solver_conflict_repair", "Resource solver + conflict repair"),
                    ("resource_solver_pattern_master", "Resource solver + pattern master"),
                ],
                default="resource_solver",
                max_length=64,
            ),
        ),
    ]
