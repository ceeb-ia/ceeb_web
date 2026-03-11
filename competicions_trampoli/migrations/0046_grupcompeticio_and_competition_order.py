from django.db import migrations, models
import django.db.models.deletion


def _normalize_positive_int_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        raw_values = [value]

    out = []
    seen = set()
    for raw in raw_values:
        try:
            num = int(raw)
        except Exception:
            continue
        if num <= 0 or num in seen:
            continue
        seen.add(num)
        out.append(num)
    return out


def forwards(apps, schema_editor):
    Competicio = apps.get_model("competicions_trampoli", "Competicio")
    Inscripcio = apps.get_model("competicions_trampoli", "Inscripcio")
    GrupCompeticio = apps.get_model("competicions_trampoli", "GrupCompeticio")
    RotacioAssignacio = apps.get_model("competicions_trampoli", "RotacioAssignacio")
    RotacioAssignacioGrup = apps.get_model("competicions_trampoli", "RotacioAssignacioGrup")

    for competicio in Competicio.objects.all().iterator():
        view_cfg = competicio.inscripcions_view or {}
        raw_group_names = view_cfg.get("group_names") or {}
        group_names = raw_group_names if isinstance(raw_group_names, dict) else {}

        group_numbers = set(
            num for num in Inscripcio.objects.filter(
                competicio_id=competicio.id,
                grup__isnull=False,
            ).values_list("grup", flat=True)
            if isinstance(num, int) and num > 0
        )

        for assignacio in RotacioAssignacio.objects.filter(competicio_id=competicio.id).only("grup", "grups"):
            for num in _normalize_positive_int_list(assignacio.grups):
                group_numbers.add(num)
            if not _normalize_positive_int_list(assignacio.grups):
                for num in _normalize_positive_int_list(assignacio.grup):
                    group_numbers.add(num)

        number_to_group_id = {}
        for group_num in sorted(group_numbers):
            group = GrupCompeticio.objects.create(
                competicio_id=competicio.id,
                legacy_num=group_num,
                display_num=group_num,
                nom=str(group_names.get(str(group_num)) or "").strip(),
                actiu=True,
            )
            number_to_group_id[group_num] = group.id

        counters = {}
        updates = []
        qs = Inscripcio.objects.filter(competicio_id=competicio.id).order_by("grup", "ordre_sortida", "id")
        for inscripcio in qs:
            group_num = getattr(inscripcio, "grup", None)
            group_id = number_to_group_id.get(group_num)
            inscripcio.grup_competicio_id = group_id
            if group_id:
                counters[group_id] = counters.get(group_id, 0) + 1
                inscripcio.ordre_competicio = counters[group_id]
            else:
                inscripcio.ordre_competicio = None
            updates.append(inscripcio)
        if updates:
            Inscripcio.objects.bulk_update(
                updates,
                ["grup_competicio", "ordre_competicio"],
                batch_size=500,
            )

        link_rows = []
        for assignacio in RotacioAssignacio.objects.filter(competicio_id=competicio.id).order_by("id"):
            groups = _normalize_positive_int_list(assignacio.grups)
            if not groups:
                groups = _normalize_positive_int_list(assignacio.grup)
            for order_idx, group_num in enumerate(groups, start=1):
                group_id = number_to_group_id.get(group_num)
                if not group_id:
                    continue
                link_rows.append(
                    RotacioAssignacioGrup(
                        assignacio_id=assignacio.id,
                        grup_id=group_id,
                        ordre=order_idx,
                    )
                )
        if link_rows:
            RotacioAssignacioGrup.objects.bulk_create(link_rows, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0045_inscripciomedia"),
    ]

    operations = [
        migrations.CreateModel(
            name="GrupCompeticio",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legacy_num", models.PositiveIntegerField(blank=True, db_index=True, null=True)),
                ("display_num", models.PositiveIntegerField(db_index=True)),
                ("nom", models.CharField(blank=True, default="", max_length=180)),
                ("actiu", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("competicio", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="grups_competicio", to="competicions_trampoli.competicio")),
            ],
            options={
                "ordering": ["display_num", "id"],
            },
        ),
        migrations.AddField(
            model_name="inscripcio",
            name="grup_competicio",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="inscripcions", to="competicions_trampoli.grupcompeticio"),
        ),
        migrations.AddField(
            model_name="inscripcio",
            name="ordre_competicio",
            field=models.PositiveIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.CreateModel(
            name="RotacioAssignacioGrup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ordre", models.PositiveIntegerField(db_index=True, default=1)),
                ("assignacio", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="grup_links", to="competicions_trampoli.rotacioassignacio")),
                ("grup", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rotacio_links", to="competicions_trampoli.grupcompeticio")),
            ],
            options={
                "ordering": ["ordre", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="grupcompeticio",
            index=models.Index(fields=["competicio", "actiu", "display_num"], name="competicion_competi_ef4a46_idx"),
        ),
        migrations.AddConstraint(
            model_name="grupcompeticio",
            constraint=models.UniqueConstraint(fields=("competicio", "display_num"), name="uniq_grup_competicio_display_num"),
        ),
        migrations.AddIndex(
            model_name="inscripcio",
            index=models.Index(fields=["competicio", "grup_competicio", "ordre_competicio"], name="competicion_competi_1c7a67_idx"),
        ),
        migrations.AddIndex(
            model_name="rotacioassignaciogrup",
            index=models.Index(fields=["grup", "ordre"], name="competicion_grup_id_9570d4_idx"),
        ),
        migrations.AddConstraint(
            model_name="rotacioassignaciogrup",
            constraint=models.UniqueConstraint(fields=("assignacio", "grup"), name="uniq_rot_assignacio_grup_link"),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
