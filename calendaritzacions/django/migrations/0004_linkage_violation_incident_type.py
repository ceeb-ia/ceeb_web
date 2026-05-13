from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("calendaritzacions_django", "0003_assignment_workspace_models"),
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
                    ("resource_solver_vinculacio", "Resource solver + vinculacio"),
                ],
                default="resource_solver",
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="workspaceresourceincident",
            name="incident_type",
            field=models.CharField(
                choices=[
                    ("resource_excess", "Resource excess"),
                    ("seed_deviation", "Seed deviation"),
                    ("assignment_conflict", "Assignment conflict"),
                    ("linkage_violation", "Linkage violation"),
                    ("other", "Other"),
                ],
                default="resource_excess",
                max_length=64,
            ),
        ),
    ]
