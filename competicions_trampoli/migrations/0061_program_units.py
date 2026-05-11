from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0060_competicioaparellfase"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProgramUnit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=180)),
                (
                    "tipus",
                    models.CharField(
                        choices=[
                            ("group", "Grup"),
                            ("serie", "Serie"),
                            ("block", "Bloc"),
                            ("team", "Equip"),
                            ("custom", "Custom"),
                        ],
                        default="custom",
                        max_length=30,
                    ),
                ),
                ("ordre", models.PositiveIntegerField(default=1)),
                ("partition_key", models.CharField(blank=True, default="", max_length=255)),
                ("partition_values", models.JSONField(blank=True, default=dict)),
                ("capacity", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("planned", "Planificada"),
                            ("generated", "Generada"),
                            ("confirmed", "Confirmada"),
                            ("published", "Publicada"),
                        ],
                        default="planned",
                        max_length=30,
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "fase",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="program_units",
                        to="competicions_trampoli.competicioaparellfase",
                    ),
                ),
            ],
            options={
                "ordering": ["fase_id", "ordre", "id"],
            },
        ),
        migrations.CreateModel(
            name="ProgramUnitSlot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slot_index", models.PositiveIntegerField()),
                ("ordre", models.PositiveIntegerField(default=1)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("empty", "Buida"),
                            ("filled", "Omplerta"),
                            ("reserve", "Reserva"),
                            ("pending_decision", "Pendent de decisio"),
                            ("withdrawn", "Baixa"),
                            ("manual", "Manual"),
                        ],
                        default="empty",
                        max_length=30,
                    ),
                ),
                ("subject_kind", models.CharField(blank=True, default="", max_length=50)),
                ("subject_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("source_particio_key", models.CharField(blank=True, default="", max_length=255)),
                ("source_position", models.PositiveIntegerField(blank=True, null=True)),
                ("source_score", models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ("source_row", models.JSONField(blank=True, default=dict)),
                ("locked", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "source_classificacio",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="program_unit_slots",
                        to="competicions_trampoli.classificacioconfig",
                    ),
                ),
                (
                    "unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="slots",
                        to="competicions_trampoli.programunit",
                    ),
                ),
            ],
            options={
                "ordering": ["unit_id", "ordre", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="programunit",
            constraint=models.UniqueConstraint(fields=("fase", "ordre"), name="uniq_program_unit_fase_ordre"),
        ),
        migrations.AddIndex(
            model_name="programunit",
            index=models.Index(fields=["fase", "status"], name="programunit_fase_status_idx"),
        ),
        migrations.AddIndex(
            model_name="programunit",
            index=models.Index(fields=["fase", "tipus"], name="programunit_fase_tipus_idx"),
        ),
        migrations.AddConstraint(
            model_name="programunitslot",
            constraint=models.UniqueConstraint(fields=("unit", "slot_index"), name="uniq_program_slot_unit_index"),
        ),
        migrations.AddConstraint(
            model_name="programunitslot",
            constraint=models.UniqueConstraint(fields=("unit", "ordre"), name="uniq_program_slot_unit_ordre"),
        ),
        migrations.AddIndex(
            model_name="programunitslot",
            index=models.Index(fields=["unit", "status"], name="programslot_unit_status_idx"),
        ),
        migrations.AddIndex(
            model_name="programunitslot",
            index=models.Index(fields=["subject_kind", "subject_id"], name="programslot_subject_idx"),
        ),
    ]
