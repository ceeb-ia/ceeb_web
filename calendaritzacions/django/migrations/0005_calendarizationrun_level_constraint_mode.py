from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("calendaritzacions_django", "0004_linkage_violation_incident_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="calendarizationrun",
            name="resource_solver_level_constraint_mode",
            field=models.CharField(
                choices=[("off", "Desactivat"), ("soft", "Suau")],
                default="off",
                max_length=16,
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
                    ("level_mismatch", "Level mismatch"),
                    ("other", "Other"),
                ],
                default="resource_excess",
                max_length=64,
            ),
        ),
    ]
