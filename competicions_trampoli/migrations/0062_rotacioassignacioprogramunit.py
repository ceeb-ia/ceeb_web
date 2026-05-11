from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0061_program_units"),
    ]

    operations = [
        migrations.CreateModel(
            name="RotacioAssignacioProgramUnit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ordre", models.PositiveIntegerField(db_index=True, default=1)),
                (
                    "assignacio",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="program_unit_links",
                        to="competicions_trampoli.rotacioassignacio",
                    ),
                ),
                (
                    "program_unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rotacio_links",
                        to="competicions_trampoli.programunit",
                    ),
                ),
            ],
            options={
                "ordering": ["ordre", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="rotacioassignacioprogramunit",
            constraint=models.UniqueConstraint(
                fields=("assignacio", "program_unit"),
                name="uniq_rot_assignacio_program_unit_link",
            ),
        ),
        migrations.AddIndex(
            model_name="rotacioassignacioprogramunit",
            index=models.Index(
                fields=["program_unit", "ordre"],
                name="rot_assign_unit_ordre_idx",
            ),
        ),
    ]
