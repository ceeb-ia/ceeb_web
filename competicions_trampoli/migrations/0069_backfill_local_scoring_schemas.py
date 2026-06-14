import copy

from django.db import migrations


def backfill_local_scoring_schemas(apps, schema_editor):
    ScoringSchema = apps.get_model("competicions_trampoli", "ScoringSchema")
    CompeticioAparell = apps.get_model("competicions_trampoli", "CompeticioAparell")

    # Old global schemas can be linked to both the base Aparell and the first
    # CompeticioAparell that introduced them. Split those rows into a clean
    # local schema plus a clean global schema before copying globals elsewhere.
    ambiguous = list(
        ScoringSchema.objects
        .filter(aparell_id__isnull=False, comp_aparell_id__isnull=False)
        .order_by("id")
    )
    for schema in ambiguous:
        aparell_id = schema.aparell_id
        schema_payload = copy.deepcopy(schema.schema if isinstance(schema.schema, dict) else {})

        schema.aparell_id = None
        schema.save(update_fields=["aparell"])

        if not ScoringSchema.objects.filter(aparell_id=aparell_id, comp_aparell_id__isnull=True).exists():
            ScoringSchema.objects.create(
                aparell_id=aparell_id,
                comp_aparell_id=None,
                schema=schema_payload,
            )

    global_schema_by_aparell_id = {
        schema.aparell_id: copy.deepcopy(schema.schema if isinstance(schema.schema, dict) else {})
        for schema in ScoringSchema.objects
        .filter(aparell_id__isnull=False, comp_aparell_id__isnull=True)
        .only("aparell_id", "schema")
    }
    if not global_schema_by_aparell_id:
        return

    local_schema_comp_aparell_ids = set(
        ScoringSchema.objects
        .filter(comp_aparell_id__isnull=False)
        .values_list("comp_aparell_id", flat=True)
    )
    to_create = []
    for comp_aparell in (
        CompeticioAparell.objects
        .filter(aparell_id__in=global_schema_by_aparell_id.keys())
        .only("id", "aparell_id")
        .order_by("id")
    ):
        if comp_aparell.id in local_schema_comp_aparell_ids:
            continue
        to_create.append(
            ScoringSchema(
                comp_aparell_id=comp_aparell.id,
                aparell_id=None,
                schema=copy.deepcopy(global_schema_by_aparell_id.get(comp_aparell.aparell_id) or {}),
            )
        )

    if to_create:
        ScoringSchema.objects.bulk_create(to_create)


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0068_judgeportalassignment"),
    ]

    operations = [
        migrations.RunPython(backfill_local_scoring_schemas, migrations.RunPython.noop),
    ]
