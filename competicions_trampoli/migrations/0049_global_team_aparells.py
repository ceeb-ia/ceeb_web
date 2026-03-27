from django.db import migrations, models
import django.db.models.deletion


def _context_member_rows(Inscripcio, InscripcioEquipAssignacio, competicio_id, context, equip_id):
    code = str(getattr(context, "code", "") or "").strip().lower()
    if code == "native":
        return list(
            Inscripcio.objects
            .filter(competicio_id=competicio_id, equip_id=equip_id)
            .order_by("grup_competicio_id", "ordre_competicio", "ordre_sortida", "id")
        )
    ins_ids = list(
        InscripcioEquipAssignacio.objects
        .filter(competicio_id=competicio_id, context_id=context.id, equip_id=equip_id)
        .values_list("inscripcio_id", flat=True)
    )
    if not ins_ids:
        return []
    return list(
        Inscripcio.objects
        .filter(competicio_id=competicio_id, id__in=ins_ids)
        .order_by("grup_competicio_id", "ordre_competicio", "ordre_sortida", "id")
    )


def _ensure_team_subject(
    TeamCompetitiveSubject,
    Inscripcio,
    InscripcioEquipAssignacio,
    EquipContext,
    Equip,
    *,
    competicio_id,
    comp_aparell_id,
    context_id,
    equip_id,
):
    context = EquipContext.objects.get(pk=context_id)
    equip = Equip.objects.get(pk=equip_id)
    members = _context_member_rows(
        Inscripcio,
        InscripcioEquipAssignacio,
        competicio_id,
        context,
        equip_id,
    )
    member_ids = [int(member.id) for member in members]
    member_names = [str(getattr(member, "nom_i_cognoms", "") or "").strip() for member in members]
    context_name = str(getattr(context, "nom", "") or getattr(context, "code", "")).strip()
    team_name = str(getattr(equip, "nom", "") or f"Equip {equip.id}").strip()
    label = f"{context_name} · {team_name}".strip(" ·")
    if member_names:
        label = f"{label} ({', '.join(member_names)})"
    subject, _created = TeamCompetitiveSubject.objects.get_or_create(
        competicio_id=competicio_id,
        comp_aparell_id=comp_aparell_id,
        context_id=context_id,
        equip_id=equip_id,
        defaults={
            "member_ids": member_ids,
            "member_names": member_names,
            "label": label,
        },
    )
    updates = []
    if list(subject.member_ids or []) != member_ids:
        subject.member_ids = member_ids
        updates.append("member_ids")
    if list(subject.member_names or []) != member_names:
        subject.member_names = member_names
        updates.append("member_names")
    if str(subject.label or "") != label:
        subject.label = label
        updates.append("label")
    if updates:
        subject.save(update_fields=updates + ["updated_at"])
    return subject


def forwards(apps, schema_editor):
    Aparell = apps.get_model("competicions_trampoli", "Aparell")
    CompeticioAparell = apps.get_model("competicions_trampoli", "CompeticioAparell")
    CompeticioAparellEquipContextSource = apps.get_model("competicions_trampoli", "CompeticioAparellEquipContextSource")
    Equip = apps.get_model("competicions_trampoli", "Equip")
    EquipContext = apps.get_model("competicions_trampoli", "EquipContext")
    Inscripcio = apps.get_model("competicions_trampoli", "Inscripcio")
    InscripcioEquipAssignacio = apps.get_model("competicions_trampoli", "InscripcioEquipAssignacio")
    TeamCompetitiveSubject = apps.get_model("competicions_trampoli", "TeamCompetitiveSubject")
    TeamScoreEntry = apps.get_model("competicions_trampoli", "TeamScoreEntry")
    TeamScoreEntryVideoEvent = apps.get_model("competicions_trampoli", "TeamScoreEntryVideoEvent")

    team_app_rows = list(
        CompeticioAparell.objects
        .filter(participant_mode="team_context")
        .exclude(team_context_id__isnull=True)
        .order_by("aparell_id", "competicio_id", "id")
    )
    team_aparell_ids = sorted({int(row.aparell_id) for row in team_app_rows})
    mixed_aparell_ids = []
    for aparell_id in team_aparell_ids:
        modes = set(
            CompeticioAparell.objects
            .filter(aparell_id=aparell_id)
            .values_list("participant_mode", flat=True)
        )
        if "individual" in modes and "team_context" in modes:
            mixed_aparell_ids.append(aparell_id)
    if mixed_aparell_ids:
        raise RuntimeError(
            "Migracio bloquejada: hi ha aparells globals usats alhora com a individuals i d'equip. "
            f"Aparell IDs conflictius: {', '.join(str(x) for x in mixed_aparell_ids)}"
        )

    if team_aparell_ids:
        Aparell.objects.filter(id__in=team_aparell_ids).update(competition_unit="team")

    for row in team_app_rows:
        CompeticioAparellEquipContextSource.objects.get_or_create(
            competicio_id=row.competicio_id,
            comp_aparell_id=row.id,
            context_id=row.team_context_id,
        )

    contexts_by_comp_aparell = {
        int(row.id): int(row.team_context_id)
        for row in team_app_rows
        if row.team_context_id
    }

    for score in TeamScoreEntry.objects.all().order_by("id"):
        context_id = contexts_by_comp_aparell.get(int(score.comp_aparell_id))
        if not context_id:
            raise RuntimeError(
                f"No s'ha pogut resoldre el context d'equip per al TeamScoreEntry {score.id}."
            )
        subject = _ensure_team_subject(
            TeamCompetitiveSubject,
            Inscripcio,
            InscripcioEquipAssignacio,
            EquipContext,
            Equip,
            competicio_id=int(score.competicio_id),
            comp_aparell_id=int(score.comp_aparell_id),
            context_id=context_id,
            equip_id=int(score.equip_id),
        )
        TeamScoreEntry.objects.filter(pk=score.pk).update(team_subject_id=subject.id)

    for event in TeamScoreEntryVideoEvent.objects.all().order_by("id"):
        subject_id = None
        if getattr(event, "team_score_entry_id", None):
            score = TeamScoreEntry.objects.filter(pk=event.team_score_entry_id).only("team_subject_id").first()
            subject_id = getattr(score, "team_subject_id", None)
        if not subject_id:
            context_id = contexts_by_comp_aparell.get(int(event.comp_aparell_id or 0))
            equip_id = int(getattr(event, "equip_id", 0) or 0)
            if context_id and equip_id:
                subject = _ensure_team_subject(
                    TeamCompetitiveSubject,
                    Inscripcio,
                    InscripcioEquipAssignacio,
                    EquipContext,
                    Equip,
                    competicio_id=int(event.competicio_id),
                    comp_aparell_id=int(event.comp_aparell_id),
                    context_id=context_id,
                    equip_id=equip_id,
                )
                subject_id = subject.id
        if not subject_id:
            raise RuntimeError(
                f"No s'ha pogut resoldre la unitat competitiva per al TeamScoreEntryVideoEvent {event.id}."
            )
        TeamScoreEntryVideoEvent.objects.filter(pk=event.pk).update(team_subject_id=subject_id)


def backwards(apps, schema_editor):
    raise RuntimeError("Aquesta migracio no te reversio automatica.")


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0048_team_context_scoring"),
    ]

    operations = [
        migrations.AddField(
            model_name="aparell",
            name="competition_unit",
            field=models.CharField(
                choices=[("individual", "Individual"), ("team", "Equip")],
                default="individual",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="CompeticioAparellEquipContextSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("comp_aparell", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="team_context_sources", to="competicions_trampoli.competicioaparell")),
                ("competicio", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="aparell_equip_context_sources", to="competicions_trampoli.competicio")),
                ("context", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="comp_aparell_sources", to="competicions_trampoli.equipcontext")),
            ],
            options={
                "ordering": ["comp_aparell_id", "context_id"],
            },
        ),
        migrations.AddConstraint(
            model_name="competicioaparellequipcontextsource",
            constraint=models.UniqueConstraint(fields=("comp_aparell", "context"), name="uniq_comp_aparell_context_source"),
        ),
        migrations.AddIndex(
            model_name="competicioaparellequipcontextsource",
            index=models.Index(fields=["competicio", "context"], name="competicion_competi_41f8ab_idx"),
        ),
        migrations.AddIndex(
            model_name="competicioaparellequipcontextsource",
            index=models.Index(fields=["competicio", "comp_aparell"], name="competicion_competi_0f6f6c_idx"),
        ),
        migrations.CreateModel(
            name="TeamCompetitiveSubject",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("member_ids", models.JSONField(blank=True, default=list)),
                ("member_names", models.JSONField(blank=True, default=list)),
                ("label", models.CharField(blank=True, default="", max_length=255)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("comp_aparell", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="team_subjects", to="competicions_trampoli.competicioaparell")),
                ("competicio", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="team_subjects", to="competicions_trampoli.competicio")),
                ("context", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="team_subjects", to="competicions_trampoli.equipcontext")),
                ("equip", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="competitive_subjects", to="competicions_trampoli.equip")),
            ],
        ),
        migrations.AddConstraint(
            model_name="teamcompetitivesubject",
            constraint=models.UniqueConstraint(fields=("competicio", "comp_aparell", "context", "equip"), name="uniq_team_competitive_subject"),
        ),
        migrations.AddIndex(
            model_name="teamcompetitivesubject",
            index=models.Index(fields=["competicio", "comp_aparell"], name="competicion_competi_4e5f33_idx"),
        ),
        migrations.AddIndex(
            model_name="teamcompetitivesubject",
            index=models.Index(fields=["competicio", "context"], name="competicion_competi_c56fca_idx"),
        ),
        migrations.AddField(
            model_name="teamscoreentry",
            name="team_subject",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="scores", to="competicions_trampoli.teamcompetitivesubject"),
        ),
        migrations.AddField(
            model_name="teamscoreentryvideoevent",
            name="team_subject",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="video_events", to="competicions_trampoli.teamcompetitivesubject"),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="teamscoreentry",
            name="team_subject",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="scores", to="competicions_trampoli.teamcompetitivesubject"),
        ),
        migrations.AlterField(
            model_name="teamscoreentryvideoevent",
            name="team_subject",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="video_events", to="competicions_trampoli.teamcompetitivesubject"),
        ),
        migrations.RemoveConstraint(
            model_name="teamscoreentry",
            name="uniq_teamscoreentry_per_exercici_aparell",
        ),
        migrations.RemoveIndex(
            model_name="teamscoreentry",
            name="competicion_competi_7e7bf1_idx",
        ),
        migrations.RemoveField(
            model_name="teamscoreentry",
            name="equip",
        ),
        migrations.AddConstraint(
            model_name="teamscoreentry",
            constraint=models.UniqueConstraint(fields=("competicio", "team_subject", "exercici", "comp_aparell"), name="uniq_teamscoreentry_per_subject_exercici_aparell"),
        ),
        migrations.AddIndex(
            model_name="teamscoreentry",
            index=models.Index(fields=["competicio", "team_subject"], name="competicion_competi_6f7f66_idx"),
        ),
        migrations.RemoveField(
            model_name="competicioaparell",
            name="expected_team_size",
        ),
        migrations.RemoveField(
            model_name="competicioaparell",
            name="participant_mode",
        ),
        migrations.RemoveField(
            model_name="competicioaparell",
            name="team_context",
        ),
        migrations.RemoveField(
            model_name="competicioaparell",
            name="team_scoring_mode",
        ),
    ]
