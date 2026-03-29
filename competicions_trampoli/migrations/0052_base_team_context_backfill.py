from django.db import migrations


BASE_CONTEXT_CODE = "native"
BASE_CONTEXT_NAME = "Base"
BASE_CONTEXT_DESCRIPTION = "Context base d'equips de la competicio"


def forwards(apps, schema_editor):
    Competicio = apps.get_model("competicions_trampoli", "Competicio")
    EquipContext = apps.get_model("competicions_trampoli", "EquipContext")
    Inscripcio = apps.get_model("competicions_trampoli", "Inscripcio")
    InscripcioEquipAssignacio = apps.get_model("competicions_trampoli", "InscripcioEquipAssignacio")

    for competicio in Competicio.objects.all().iterator():
        context, _created = EquipContext.objects.get_or_create(
            competicio_id=competicio.id,
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

        existing_ids = set(
            InscripcioEquipAssignacio.objects
            .filter(competicio_id=competicio.id, context_id=context.id)
            .values_list("inscripcio_id", flat=True)
        )
        creates = []
        rows = (
            Inscripcio.objects
            .filter(competicio_id=competicio.id)
            .exclude(equip_id__isnull=True)
            .exclude(id__in=existing_ids)
            .values("id", "equip_id")
        )
        for row in rows.iterator():
            creates.append(
                InscripcioEquipAssignacio(
                    competicio_id=competicio.id,
                    context_id=context.id,
                    inscripcio_id=row["id"],
                    equip_id=row["equip_id"],
                    origen="manual",
                    criteri={},
                )
            )
        if creates:
            InscripcioEquipAssignacio.objects.bulk_create(creates, batch_size=500)


def backwards(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("competicions_trampoli", "0051_team_series"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
