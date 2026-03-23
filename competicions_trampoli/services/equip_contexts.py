from collections import OrderedDict

from django.db.models import Count
from django.utils.text import slugify

from ..models import Equip, EquipContext, Inscripcio, InscripcioEquipAssignacio


NATIVE_EQUIP_CONTEXT_CODE = "native"


def normalize_equip_context_code(raw) -> str:
    code = str(raw or "").strip()
    return code or NATIVE_EQUIP_CONTEXT_CODE


def is_native_equip_context(raw) -> bool:
    return normalize_equip_context_code(raw) == NATIVE_EQUIP_CONTEXT_CODE


def get_equip_context_queryset(competicio):
    return EquipContext.objects.filter(competicio=competicio).order_by("nom", "id")


def get_equip_context_payload(competicio):
    out = [
        {
            "code": NATIVE_EQUIP_CONTEXT_CODE,
            "nom": "Natiu",
            "description": "Equip natiu de la inscripcio",
            "is_native": True,
        }
    ]
    for ctx in get_equip_context_queryset(competicio):
        out.append(
            {
                "code": str(ctx.code or "").strip(),
                "nom": str(ctx.nom or "").strip(),
                "description": str(ctx.description or "").strip(),
                "is_native": False,
            }
        )
    return out


def get_custom_equip_context(competicio, context_code):
    code = normalize_equip_context_code(context_code)
    if code == NATIVE_EQUIP_CONTEXT_CODE:
        return None
    return EquipContext.objects.filter(competicio=competicio, code=code).first()


def build_unique_equip_context_code(competicio, name: str, exclude_context_id=None) -> str:
    base = slugify(name or "") or "context-equip"
    code = base
    idx = 2
    qs = EquipContext.objects.filter(competicio=competicio)
    if exclude_context_id:
        qs = qs.exclude(id=exclude_context_id)
    existing = set(qs.values_list("code", flat=True))
    while code in existing or code == NATIVE_EQUIP_CONTEXT_CODE:
        code = f"{base}-{idx}"
        idx += 1
    return code


def get_contextual_assignment_map(competicio, inscripcions_or_ids, context_code):
    code = normalize_equip_context_code(context_code)
    if code == NATIVE_EQUIP_CONTEXT_CODE:
        return {}

    ctx = get_custom_equip_context(competicio, code)
    if ctx is None:
        return {}

    ins_ids = []
    for item in inscripcions_or_ids or []:
        ins_id = getattr(item, "id", item)
        try:
            ins_id = int(ins_id)
        except Exception:
            continue
        if ins_id > 0:
            ins_ids.append(ins_id)
    if not ins_ids:
        return {}

    rows = (
        InscripcioEquipAssignacio.objects
        .filter(competicio=competicio, context=ctx, inscripcio_id__in=ins_ids)
        .select_related("equip")
        .order_by("inscripcio_id")
    )
    return OrderedDict((row.inscripcio_id, row) for row in rows)


def resolve_inscripcio_equip(inscripcio, context_code=None, fallback="native", assignment_map=None):
    code = normalize_equip_context_code(context_code)
    if code == NATIVE_EQUIP_CONTEXT_CODE:
        return getattr(inscripcio, "equip", None)

    assign_map = assignment_map if isinstance(assignment_map, dict) else {}
    row = assign_map.get(getattr(inscripcio, "id", None))
    if row is not None:
        return getattr(row, "equip", None)

    if str(fallback or "").strip().lower() == NATIVE_EQUIP_CONTEXT_CODE:
        return getattr(inscripcio, "equip", None)
    return None


def get_equips_for_context(competicio, context_code):
    code = normalize_equip_context_code(context_code)
    if code == NATIVE_EQUIP_CONTEXT_CODE:
        return list(
            Equip.objects
            .filter(competicio=competicio)
            .annotate(membres_count=Count("membres"))
            .order_by("nom", "id")
        )

    ctx = get_custom_equip_context(competicio, code)
    if ctx is None:
        return []

    counts = {
        row["equip_id"]: int(row["total"] or 0)
        for row in (
            InscripcioEquipAssignacio.objects
            .filter(competicio=competicio, context=ctx)
            .values("equip_id")
            .annotate(total=Count("id"))
        )
    }
    equips = list(Equip.objects.filter(competicio=competicio).order_by("nom", "id"))
    for equip in equips:
        equip.membres_count = counts.get(equip.id, 0)
    return equips


def get_equip_context_summary(competicio, context_code):
    code = normalize_equip_context_code(context_code)
    total_inscripcions = Inscripcio.objects.filter(competicio=competicio).count()
    equips = list(get_equips_for_context(competicio, code))
    teams_total = len(equips)
    teams_with_members = sum(1 for equip in equips if int(getattr(equip, "membres_count", 0) or 0) > 0)

    if code == NATIVE_EQUIP_CONTEXT_CODE:
        assigned_count = Inscripcio.objects.filter(competicio=competicio).exclude(equip__isnull=True).count()
    else:
        ctx = get_custom_equip_context(competicio, code)
        if ctx is None:
            assigned_count = 0
        else:
            assigned_count = InscripcioEquipAssignacio.objects.filter(competicio=competicio, context=ctx).count()

    assigned_count = int(assigned_count or 0)
    return {
        "context_code": code,
        "teams_total": teams_total,
        "teams_with_members": teams_with_members,
        "assigned_count": assigned_count,
        "unassigned_count": max(0, int(total_inscripcions or 0) - assigned_count),
        "total_inscripcions": int(total_inscripcions or 0),
    }
