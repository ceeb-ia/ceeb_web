from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("calendaritzacions_django", "0010_calendarizationrun_competition_grouping"),
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
                ],
                default="resource_solver",
                max_length=64,
            ),
        ),
    ]
