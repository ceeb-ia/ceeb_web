from collections import OrderedDict

from django.db.models import Count
from django.utils.text import slugify

from ..models import Competicio, Equip, EquipContext, Inscripcio, InscripcioEquipAssignacio


NATIVE_EQUIP_CONTEXT_CODE = "native"
BASE_EQUIP_CONTEXT_NAME = "Base"
BASE_EQUIP_CONTEXT_DESCRIPTION = "Context base d'equips de la competicio"


def normalize_equip_context_code(raw) -> str:
    code = str(raw or "").strip()
    return code or NATIVE_EQUIP_CONTEXT_CODE


def is_native_equip_context(raw) -> bool:
    return normalize_equip_context_code(raw) == NATIVE_EQUIP_CONTEXT_CODE


def ensure_base_equip_context(competicio):
    # Runtime contract: functional flows always self-heal the base/native
    # context on entry. Audit/report commands must inspect raw persisted state
    # directly and must not call this helper.
    if competicio is None:
        return None
    ctx, _created = EquipContext.objects.get_or_create(
        competicio=competicio,
        code=NATIVE_EQUIP_CONTEXT_CODE,
        defaults={
            "nom": BASE_EQUIP_CONTEXT_NAME,
            "description": BASE_EQUIP_CONTEXT_DESCRIPTION,
        },
    )
    dirty = False
    if str(ctx.nom or "").strip() != BASE_EQUIP_CONTEXT_NAME:
        ctx.nom = BASE_EQUIP_CONTEXT_NAME
        dirty = True
    if str(ctx.description or "").strip() != BASE_EQUIP_CONTEXT_DESCRIPTION:
        ctx.description = BASE_EQUIP_CONTEXT_DESCRIPTION
        dirty = True
    if dirty:
        ctx.save(update_fields=["nom", "description", "updated_at"])
    return ctx


def get_equip_context_queryset(competicio):
    base_ctx = ensure_base_equip_context(competicio)
    rows = list(EquipContext.objects.filter(competicio=competicio).order_by("nom", "id"))
    if base_ctx is None:
        return rows
    rows.sort(
        key=lambda ctx: (
            0 if int(getattr(ctx, "id", 0) or 0) == int(base_ctx.id) else 1,
            str(getattr(ctx, "nom", "") or "").lower(),
            int(getattr(ctx, "id", 0) or 0),
        )
    )
    return rows


def get_equip_context_payload(competicio):
    out = []
    for ctx in get_equip_context_queryset(competicio):
        code = str(ctx.code or "").strip()
        out.append(
            {
                "code": code,
                "nom": BASE_EQUIP_CONTEXT_NAME if code == NATIVE_EQUIP_CONTEXT_CODE else str(ctx.nom or "").strip(),
                "description": (
                    BASE_EQUIP_CONTEXT_DESCRIPTION
                    if code == NATIVE_EQUIP_CONTEXT_CODE
                    else str(ctx.description or "").strip()
                ),
                "is_native": code == NATIVE_EQUIP_CONTEXT_CODE,
            }
        )
    return out


def get_equip_context(competicio, context_code):
    code = normalize_equip_context_code(context_code)
    if code == NATIVE_EQUIP_CONTEXT_CODE:
        return ensure_base_equip_context(competicio)
    return EquipContext.objects.filter(competicio=competicio, code=code).first()


def get_custom_equip_context(competicio, context_code):
    code = normalize_equip_context_code(context_code)
    if code == NATIVE_EQUIP_CONTEXT_CODE:
        return None
    return get_equip_context(competicio, code)


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


def _context_assignment_rows(competicio, context_code, ins_ids=None):
    ctx = get_equip_context(competicio, context_code)
    if ctx is None:
        return []
    qs = (
        InscripcioEquipAssignacio.objects
        .filter(competicio=competicio, context=ctx)
        .select_related("equip")
        .order_by("inscripcio_id")
    )
    if ins_ids is not None:
        ids = [int(x) for x in ins_ids if str(x).isdigit()]
        if not ids:
            return []
        qs = qs.filter(inscripcio_id__in=ids)
    return list(qs)


def get_contextual_assignment_map(competicio, inscripcions_or_ids, context_code):
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
        return OrderedDict()

    rows = _context_assignment_rows(competicio, context_code, ins_ids=ins_ids)
    return OrderedDict((row.inscripcio_id, row) for row in rows)


def resolve_inscripcio_equip(inscripcio, context_code=None, fallback="native", assignment_map=None):
    if inscripcio is None:
        return None

    code = normalize_equip_context_code(context_code)
    ins_id = getattr(inscripcio, "id", None)
    assign_map = assignment_map if isinstance(assignment_map, dict) else {}
    row = assign_map.get(ins_id)
    if row is not None:
        equip = getattr(row, "equip", None)
        if equip is not None:
            return equip

    competicio = getattr(inscripcio, "competicio", None)
    competicio_id = getattr(inscripcio, "competicio_id", None)
    if competicio is None and competicio_id:
        competicio = getattr(inscripcio, "_competicio_cache", None)
    if competicio is None and competicio_id:
        competicio = Competicio.objects.filter(id=competicio_id).first()
        if competicio is not None:
            try:
                inscripcio._competicio_cache = competicio
            except Exception:
                pass

    if competicio is not None and ins_id:
        rows = _context_assignment_rows(competicio, code, ins_ids=[ins_id])
        if rows:
            return getattr(rows[0], "equip", None)

    fallback_code = normalize_equip_context_code(fallback) if fallback not in (None, "") else ""
    if not fallback_code:
        return None
    if fallback_code == code:
        return None
    if competicio is not None and ins_id:
        rows = _context_assignment_rows(competicio, fallback_code, ins_ids=[ins_id])
        if rows:
            return getattr(rows[0], "equip", None)
    return None


def get_equips_for_context(competicio, context_code):
    ctx = get_equip_context(competicio, context_code)
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

    equips = list(Equip.objects.filter(competicio=competicio, context=ctx).order_by("nom", "id"))
    for equip in equips:
        equip.membres_count = counts.get(equip.id, 0)
    return equips


def get_team_members_payload_for_context(competicio, context_code):
    ctx = get_equip_context(competicio, context_code)
    grouped = OrderedDict()
    base_assignment_map = get_contextual_assignment_map(competicio, Inscripcio.objects.filter(competicio=competicio).values_list("id", flat=True), NATIVE_EQUIP_CONTEXT_CODE)

    def _append_member(team_id, inscripcio):
        if not team_id or inscripcio is None:
            return
        members = grouped.setdefault(int(team_id), [])
        base_team = resolve_inscripcio_equip(
            inscripcio,
            context_code=NATIVE_EQUIP_CONTEXT_CODE,
            fallback=None,
            assignment_map=base_assignment_map,
        )
        members.append(
            {
                "id": int(getattr(inscripcio, "id", 0) or 0),
                "nom": str(getattr(inscripcio, "nom_i_cognoms", "") or "").strip(),
                "document": str(getattr(inscripcio, "document", "") or "").strip(),
                "entitat": str(getattr(inscripcio, "entitat", "") or "").strip(),
                "categoria": str(getattr(inscripcio, "categoria", "") or "").strip(),
                "subcategoria": str(getattr(inscripcio, "subcategoria", "") or "").strip(),
                "native_team_name": str(getattr(base_team, "nom", "") or "").strip(),
            }
        )

    if ctx is None:
        return grouped

    rows = (
        InscripcioEquipAssignacio.objects
        .filter(competicio=competicio, context=ctx)
        .select_related("equip", "inscripcio")
        .only(
            "equip_id",
            "inscripcio_id",
            "inscripcio__id",
            "inscripcio__nom_i_cognoms",
            "inscripcio__document",
            "inscripcio__entitat",
            "inscripcio__categoria",
            "inscripcio__subcategoria",
            "inscripcio__ordre_sortida",
        )
        .order_by("inscripcio__ordre_sortida", "inscripcio_id")
    )
    for row in rows:
        _append_member(getattr(row, "equip_id", None), getattr(row, "inscripcio", None))
    return grouped


def get_equip_context_summary(competicio, context_code):
    ctx = get_equip_context(competicio, context_code)
    code = normalize_equip_context_code(getattr(ctx, "code", context_code))
    total_inscripcions = Inscripcio.objects.filter(competicio=competicio).count()
    equips = list(get_equips_for_context(competicio, code))
    teams_total = len(equips)
    teams_with_members = sum(1 for equip in equips if int(getattr(equip, "membres_count", 0) or 0) > 0)

    assigned_count = int(
        InscripcioEquipAssignacio.objects
        .filter(competicio=competicio, context=ctx)
        .count()
        if ctx is not None else 0
    )

    return {
        "context_code": code,
        "teams_total": teams_total,
        "teams_with_members": teams_with_members,
        "assigned_count": assigned_count,
        "unassigned_count": max(0, int(total_inscripcions or 0) - assigned_count),
        "total_inscripcions": int(total_inscripcions or 0),
    }
