from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("calendaritzacions_django", "0007_calendarizationcomponentrun"),
    ]

    operations = [
        migrations.AddField(
            model_name="calendarizationrun",
            name="resource_solver_decomposition_mode",
            field=models.CharField(
                choices=[
                    ("audit_only", "Auditoria"),
                    ("off", "Desactivat"),
                    ("persist_components", "Persistir components"),
                    ("solve_components", "Resoldre components"),
                ],
                default="audit_only",
                max_length=32,
            ),
        ),
    ]
