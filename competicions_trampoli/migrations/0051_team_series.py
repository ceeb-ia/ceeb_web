from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0050_rename_competicion_competi_41f8ab_idx_competicion_competi_63994e_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="SerieEquip",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_num", models.PositiveIntegerField()),
                ("nom", models.CharField(blank=True, default="", max_length=180)),
                ("actiu", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("comp_aparell", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="series_equip", to="competicions_trampoli.competicioaparell")),
                ("competicio", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="series_equip", to="competicions_trampoli.competicio")),
            ],
            options={
                "ordering": ["comp_aparell_id", "display_num", "id"],
            },
        ),
        migrations.CreateModel(
            name="SerieEquipItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ordre", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("serie", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="competicions_trampoli.serieequip")),
                ("team_subject", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="serie_items", to="competicions_trampoli.teamcompetitivesubject")),
            ],
            options={
                "ordering": ["ordre", "id"],
            },
        ),
        migrations.CreateModel(
            name="RotacioAssignacioSerieEquip",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ordre", models.PositiveIntegerField(db_index=True, default=1)),
                ("assignacio", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="serie_links", to="competicions_trampoli.rotacioassignacio")),
                ("serie", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rotacio_links", to="competicions_trampoli.serieequip")),
            ],
            options={
                "ordering": ["ordre", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="serieequip",
            constraint=models.UniqueConstraint(fields=("competicio", "comp_aparell", "display_num"), name="uniq_serie_equip_display_num_per_app"),
        ),
        migrations.AddIndex(
            model_name="serieequip",
            index=models.Index(fields=["competicio", "comp_aparell", "actiu"], name="competicion_competi_8b69dd_idx"),
        ),
        migrations.AddConstraint(
            model_name="serieequipitem",
            constraint=models.UniqueConstraint(fields=("serie", "team_subject"), name="uniq_serie_equip_item_subject"),
        ),
        migrations.AddIndex(
            model_name="serieequipitem",
            index=models.Index(fields=["serie", "ordre"], name="competicion_serie_i_6cf549_idx"),
        ),
        migrations.AddIndex(
            model_name="serieequipitem",
            index=models.Index(fields=["team_subject"], name="competicion_team_s_8a272e_idx"),
        ),
        migrations.AddConstraint(
            model_name="rotacioassignacioserieequip",
            constraint=models.UniqueConstraint(fields=("assignacio", "serie"), name="uniq_rot_assignacio_serie_equip_link"),
        ),
        migrations.AddIndex(
            model_name="rotacioassignacioserieequip",
            index=models.Index(fields=["serie", "ordre"], name="competicion_serie_i_24c55a_idx"),
        ),
    ]
