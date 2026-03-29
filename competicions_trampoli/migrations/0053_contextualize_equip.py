from django.db import migrations, models
import django.db.models.deletion


BASE_CONTEXT_CODE = "native"
BASE_CONTEXT_NAME = "Base"
BASE_CONTEXT_DESCRIPTION = "Context base d'equips de la competicio"


def _normalize_assignment_source(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    raw_mode = str(cfg.get("mode") or "native").strip().lower()
    mode = raw_mode if raw_mode in {"native", "context"} else "native"
    context_code = str(cfg.get("context_code") or "").strip() or BASE_CONTEXT_CODE
    if mode == "native":
        context_code = BASE_CONTEXT_CODE
    return {
        "mode": "context",
        "context_code": context_code,
        "fallback": BASE_CONTEXT_CODE,
    }


def _ensure_base_context(EquipContext, competicio_id):
    context, _created = EquipContext.objects.get_or_create(
        competicio_id=competicio_id,
        code=BASE_CONTEXT_CODE,
        defaults={
            "nom": BASE_CONTEXT_NAME,
            "description": BASE_CONTEXT_DESCRIPTION,
        },
    )
    dirty = False
    if (context.nom or "").strip() != BASE_CONTEXT_NAME:
        context.nom = BASE_CONTEXT_NAME
        dirty = True
    if (context.description or "").strip() != BASE_CONTEXT_DESCRIPTION:
        context.description = BASE_CONTEXT_DESCRIPTION
        dirty = True
    if dirty:
        context.save(update_fields=["nom", "description", "updated_at"])
    return context


def _collect_classificacio_context_usage(ClassificacioConfig, EquipContext):
    usage = {}
    contexts_by_comp = {}
    cfg_ids = list(ClassificacioConfig.objects.values_list("id", flat=True))
    for cfg in ClassificacioConfig.objects.filter(id__in=cfg_ids).only("id", "competicio_id", "schema"):
        schema = cfg.schema if isinstance(cfg.schema, dict) else {}
        equips_cfg = schema.get("equips") or {}
        manual_rows = equips_cfg.get("particions_manuals") or []
        if not isinstance(manual_rows, list):
            continue
        comp_contexts = contexts_by_comp.get(cfg.competicio_id)
        if comp_contexts is None:
            comp_contexts = {
                str(ctx.code or "").strip(): int(ctx.id)
                for ctx in EquipContext.objects.filter(competicio_id=cfg.competicio_id).only("id", "code")
            }
            contexts_by_comp[cfg.competicio_id] = comp_contexts
        assignment_source = _normalize_assignment_source(equips_cfg.get("assignment_source"))
        context_id = comp_contexts.get(assignment_source.get("context_code")) or comp_contexts.get(BASE_CONTEXT_CODE)
        if not context_id:
            continue
        for row in manual_rows:
            if not isinstance(row, dict):
                continue
            for raw_id in (row.get("equip_ids") or []):
                try:
                    equip_id = int(raw_id)
                except Exception:
                    continue
                usage.setdefault(equip_id, set()).add(int(context_id))
    return usage


def forwards(apps, schema_editor):
    Competicio = apps.get_model("competicions_trampoli", "Competicio")
    Equip = apps.get_model("competicions_trampoli", "Equip")
    EquipContext = apps.get_model("competicions_trampoli", "EquipContext")
    InscripcioEquipAssignacio = apps.get_model("competicions_trampoli", "InscripcioEquipAssignacio")
    TeamCompetitiveSubject = apps.get_model("competicions_trampoli", "TeamCompetitiveSubject")
    TeamScoreEntryVideoEvent = apps.get_model("competicions_trampoli", "TeamScoreEntryVideoEvent")
    ClassificacioConfig = apps.get_model("competicions_trampoli", "ClassificacioConfig")

    base_context_by_comp = {}
    context_ids_by_comp = {}
    context_code_map_by_comp = {}
    for competicio_id in Competicio.objects.values_list("id", flat=True):
        base_ctx = _ensure_base_context(EquipContext, competicio_id)
        base_context_by_comp[int(competicio_id)] = int(base_ctx.id)
        ctx_ids = set(
            EquipContext.objects
            .filter(competicio_id=competicio_id)
            .values_list("id", flat=True)
        )
        context_ids_by_comp[int(competicio_id)] = {int(ctx_id) for ctx_id in ctx_ids}
        context_code_map_by_comp[int(competicio_id)] = {
            str(ctx.code or "").strip(): int(ctx.id)
            for ctx in EquipContext.objects.filter(competicio_id=competicio_id).only("id", "code")
        }

    classificacio_usage = _collect_classificacio_context_usage(ClassificacioConfig, EquipContext)
    equip_context_map = {}

    equips = list(Equip.objects.all().order_by("id"))
    for equip in equips:
        competicio_id = int(equip.competicio_id)
        valid_context_ids = context_ids_by_comp.get(competicio_id, set())
        inferred_context_ids = set(
            int(ctx_id)
            for ctx_id in InscripcioEquipAssignacio.objects
            .filter(equip_id=equip.id)
            .values_list("context_id", flat=True)
            if int(ctx_id) in valid_context_ids
        )
        inferred_context_ids.update(
            int(ctx_id)
            for ctx_id in TeamCompetitiveSubject.objects
            .filter(equip_id=equip.id)
            .values_list("context_id", flat=True)
            if int(ctx_id) in valid_context_ids
        )
        inferred_context_ids.update(
            int(ctx_id)
            for ctx_id in TeamScoreEntryVideoEvent.objects
            .filter(equip_id=equip.id)
            .values_list("team_subject__context_id", flat=True)
            if int(ctx_id) in valid_context_ids
        )
        inferred_context_ids.update(
            int(ctx_id)
            for ctx_id in classificacio_usage.get(int(equip.id), set())
            if int(ctx_id) in valid_context_ids
        )
        if not inferred_context_ids:
            inferred_context_ids = {base_context_by_comp[competicio_id]}

        primary_context_id = (
            base_context_by_comp[competicio_id]
            if base_context_by_comp[competicio_id] in inferred_context_ids
            else min(inferred_context_ids)
        )
        Equip.objects.filter(pk=equip.id).update(context_id=primary_context_id)
        equip_context_map[(int(equip.id), int(primary_context_id))] = int(equip.id)

        for extra_context_id in sorted(inferred_context_ids):
            if extra_context_id == primary_context_id:
                continue
            clone = Equip.objects.create(
                competicio_id=competicio_id,
                context_id=int(extra_context_id),
                nom=equip.nom,
                origen=equip.origen,
                criteri=equip.criteri or {},
            )
            equip_context_map[(int(equip.id), int(extra_context_id))] = int(clone.id)
            InscripcioEquipAssignacio.objects.filter(
                equip_id=equip.id,
                context_id=int(extra_context_id),
            ).update(equip_id=clone.id)
            TeamCompetitiveSubject.objects.filter(
                equip_id=equip.id,
                context_id=int(extra_context_id),
            ).update(equip_id=clone.id)
            TeamScoreEntryVideoEvent.objects.filter(
                equip_id=equip.id,
                team_subject__context_id=int(extra_context_id),
            ).update(equip_id=clone.id)

    for cfg in ClassificacioConfig.objects.all().only("id", "competicio_id", "schema"):
        schema = cfg.schema if isinstance(cfg.schema, dict) else {}
        equips_cfg = schema.get("equips") or {}
        manual_rows = equips_cfg.get("particions_manuals") or []
        if not isinstance(manual_rows, list):
            continue
        assignment_source = _normalize_assignment_source(equips_cfg.get("assignment_source"))
        context_id = (
            context_code_map_by_comp.get(int(cfg.competicio_id), {}).get(assignment_source.get("context_code"))
            or base_context_by_comp.get(int(cfg.competicio_id))
        )
        if not context_id:
            continue
        changed = False
        remapped_rows = []
        for row in manual_rows:
            if not isinstance(row, dict):
                remapped_rows.append(row)
                continue
            next_row = dict(row)
            next_ids = []
            for raw_id in (row.get("equip_ids") or []):
                try:
                    equip_id = int(raw_id)
                except Exception:
                    continue
                mapped_id = equip_context_map.get((equip_id, int(context_id)))
                if mapped_id is None:
                    mapped_id = equip_context_map.get(
                        (equip_id, base_context_by_comp.get(int(cfg.competicio_id), 0))
                    )
                if mapped_id is None:
                    mapped_id = equip_id
                if mapped_id != equip_id:
                    changed = True
                if mapped_id not in next_ids:
                    next_ids.append(mapped_id)
            next_row["equip_ids"] = next_ids
            remapped_rows.append(next_row)
        if changed:
            equips_cfg["assignment_source"] = assignment_source
            equips_cfg["particions_manuals"] = remapped_rows
            schema["equips"] = equips_cfg
            ClassificacioConfig.objects.filter(pk=cfg.pk).update(schema=schema)


def backwards(apps, schema_editor):
    return


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("competicions_trampoli", "0052_base_team_context_backfill"),
    ]

    operations = [
        migrations.AddField(
            model_name="equip",
            name="context",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="equips",
                to="competicions_trampoli.equipcontext",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="equip",
            name="uniq_equip_nom_per_competicio",
        ),
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="equip",
            name="context",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="equips",
                to="competicions_trampoli.equipcontext",
            ),
        ),
        migrations.RemoveIndex(
            model_name="equip",
            name="competicion_competi_09e48b_idx",
        ),
        migrations.AddIndex(
            model_name="equip",
            index=models.Index(fields=["competicio", "context"], name="equip_competicio_context_idx"),
        ),
        migrations.AddIndex(
            model_name="equip",
            index=models.Index(fields=["context", "nom"], name="equip_context_nom_idx"),
        ),
        migrations.AddIndex(
            model_name="equip",
            index=models.Index(fields=["competicio", "nom"], name="equip_competicio_nom_idx"),
        ),
        migrations.AddConstraint(
            model_name="equip",
            constraint=models.UniqueConstraint(fields=("context", "nom"), name="uniq_equip_nom_per_context"),
        ),
    ]
