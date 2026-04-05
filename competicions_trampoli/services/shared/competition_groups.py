from collections import OrderedDict, defaultdict

from django.db import transaction
from django.db.models import Count, Max

from ...models import GrupCompeticio, Inscripcio


UNASSIGNED_GROUP_KEY = 0
SHOW_OUT_OF_PROGRAM_IN_COMPETITION_VIEWS_KEY = "show_out_of_program_in_competition_views"


def normalize_positive_int(value):
    try:
        num = int(value)
    except Exception:
        return None
    return num if num > 0 else None


def group_label(group) -> str:
    if not group:
        return "Sense grup"
    nom = str(getattr(group, "nom", "") or "").strip()
    if nom:
        return nom
    display_num = normalize_positive_int(getattr(group, "display_num", None))
    if display_num:
        return f"Grup {display_num}"
    return "Sense grup"


def get_competicio_groups(competicio, include_inactive=True):
    qs = GrupCompeticio.objects.filter(competicio=competicio)
    if not include_inactive:
        qs = qs.filter(actiu=True)
    return qs.order_by("display_num", "id")


def get_group_maps(competicio, include_inactive=True):
    groups = list(get_competicio_groups(competicio, include_inactive=include_inactive))
    by_id = {g.id: g for g in groups}
    by_display_num = {}
    label_by_id = {}
    name_map = {}
    for group in groups:
        by_display_num[group.display_num] = group
        label = group_label(group)
        label_by_id[group.id] = label
        if group.nom.strip():
            name_map[str(group.display_num)] = group.nom.strip()
    return {
        "groups": groups,
        "by_id": by_id,
        "by_display_num": by_display_num,
        "label_by_id": label_by_id,
        "name_map": name_map,
    }


def get_group_participant_counts(competicio):
    rows = (
        Inscripcio.objects
        .filter(competicio=competicio, grup_competicio_id__isnull=False)
        .values("grup_competicio_id")
        .annotate(total=Count("id"))
    )
    return {
        int(row["grup_competicio_id"]): int(row["total"] or 0)
        for row in rows
        if row.get("grup_competicio_id")
    }


def get_unassigned_participant_count(competicio) -> int:
    return int(
        Inscripcio.objects
        .filter(competicio=competicio, grup_competicio_id__isnull=True)
        .count()
    )


def get_programmed_group_ids(competicio):
    from ...models.rotacions import RotacioAssignacioGrup

    return set(
        RotacioAssignacioGrup.objects
        .filter(assignacio__competicio=competicio)
        .values_list("grup_id", flat=True)
    )


def get_out_of_program_group_ids(competicio):
    participant_group_ids = set(get_group_participant_counts(competicio).keys())
    if not participant_group_ids:
        return set()
    return participant_group_ids - get_programmed_group_ids(competicio)


def get_group_member_previews(competicio, limit=5):
    rows = (
        Inscripcio.objects
        .filter(competicio=competicio, grup_competicio_id__isnull=False)
        .select_related("grup_competicio")
        .order_by("grup_competicio__display_num", "ordre_competicio", "ordre_sortida", "id")
        .only("id", "nom_i_cognoms", "grup_competicio_id", "ordre_competicio", "ordre_sortida")
    )
    previews = defaultdict(list)
    max_items = max(1, int(limit or 1))
    for inscripcio in rows:
        group_id = int(getattr(inscripcio, "grup_competicio_id", 0) or 0)
        if not group_id or len(previews[group_id]) >= max_items:
            continue
        label = str(getattr(inscripcio, "nom_i_cognoms", "") or "").strip()
        if label:
            previews[group_id].append(label)
    return previews


def build_group_summary_rows(competicio, include_inactive=False, member_preview_limit=5):
    group_maps = get_group_maps(competicio, include_inactive=include_inactive)
    groups = list(group_maps["groups"])
    participant_counts = get_group_participant_counts(competicio)
    programmed_group_ids = get_programmed_group_ids(competicio)
    out_of_program_group_ids = get_out_of_program_group_ids(competicio)
    member_previews = get_group_member_previews(competicio, limit=member_preview_limit)

    rows = []
    for group in groups:
        members_count = int(participant_counts.get(group.id, 0) or 0)
        rows.append(
            {
                "id": int(group.id),
                "display_num": int(group.display_num),
                "legacy_num": int(group.legacy_num or group.display_num or 0),
                "name": str(group.nom or "").strip(),
                "label": group_label(group),
                "actiu": bool(group.actiu),
                "members_count": members_count,
                "member_names_preview": list(member_previews.get(group.id, []) or []),
                "is_programmed": int(group.id) in programmed_group_ids,
                "is_out_of_program": int(group.id) in out_of_program_group_ids,
                "is_empty": members_count == 0,
            }
        )

    rows.sort(key=lambda row: (row["display_num"], row["id"]))
    return rows


def build_group_workspace_summary(competicio, include_inactive=False):
    rows = build_group_summary_rows(competicio, include_inactive=include_inactive)
    return {
        "groups_total": len(rows),
        "groups_with_members": sum(1 for row in rows if row["members_count"] > 0),
        "empty_groups": sum(1 for row in rows if row["members_count"] <= 0),
        "assigned_count": sum(int(row["members_count"] or 0) for row in rows),
        "unassigned_count": get_unassigned_participant_count(competicio),
        "out_of_program_groups": sum(1 for row in rows if row["is_out_of_program"]),
        "programmed_groups": sum(1 for row in rows if row["is_programmed"]),
    }


def show_out_of_program_in_competition_views(competicio) -> bool:
    view_cfg = competicio.inscripcions_view or {}
    return bool(view_cfg.get(SHOW_OUT_OF_PROGRAM_IN_COMPETITION_VIEWS_KEY, False))


def set_show_out_of_program_in_competition_views(competicio, value):
    cfg = dict(competicio.inscripcions_view or {})
    cfg[SHOW_OUT_OF_PROGRAM_IN_COMPETITION_VIEWS_KEY] = bool(value)
    competicio.inscripcions_view = cfg
    competicio.save(update_fields=["inscripcions_view"])
    return bool(cfg[SHOW_OUT_OF_PROGRAM_IN_COMPETITION_VIEWS_KEY])


def sync_competicio_group_names_view(competicio):
    view_cfg = dict(competicio.inscripcions_view or {})
    raw_group_names = view_cfg.get("group_names") or {}
    legacy_names = raw_group_names if isinstance(raw_group_names, dict) else {}

    updates = []
    for group in get_competicio_groups(competicio):
        if group.nom.strip():
            continue
        fallback_name = str(legacy_names.get(str(group.display_num)) or "").strip()
        if not fallback_name:
            continue
        group.nom = fallback_name
        updates.append(group)
    if updates:
        GrupCompeticio.objects.bulk_update(updates, ["nom"], batch_size=200)

    names_map = get_group_maps(competicio).get("name_map") or {}
    if names_map:
        view_cfg["group_names"] = names_map
    else:
        view_cfg.pop("group_names", None)
    if view_cfg != (competicio.inscripcions_view or {}):
        competicio.inscripcions_view = view_cfg
        competicio.save(update_fields=["inscripcions_view"])
    return names_map


def next_group_display_num(competicio) -> int:
    return (GrupCompeticio.objects.filter(competicio=competicio).aggregate(Max("display_num"))["display_num__max"] or 0) + 1


def get_group_for_display_num(competicio, display_num):
    clean = normalize_positive_int(display_num)
    if not clean:
        return None
    return GrupCompeticio.objects.filter(competicio=competicio, display_num=clean).first()


def ensure_group_for_display_num(competicio, display_num, name=""):
    clean = normalize_positive_int(display_num)
    if not clean:
        return None
    resolved_name = str(name or "").strip()
    if not resolved_name:
        view_cfg = competicio.inscripcions_view or {}
        raw_group_names = view_cfg.get("group_names") or {}
        if isinstance(raw_group_names, dict):
            resolved_name = str(raw_group_names.get(str(clean)) or "").strip()
    group, created = GrupCompeticio.objects.get_or_create(
        competicio=competicio,
        display_num=clean,
        defaults={
            "legacy_num": clean,
            "nom": resolved_name,
            "actiu": True,
        },
    )
    if not created:
        updates = []
        if not group.actiu:
            group.actiu = True
            updates.append("actiu")
        incoming_name = resolved_name
        if incoming_name and not group.nom.strip():
            group.nom = incoming_name
            updates.append("nom")
        if updates:
            group.save(update_fields=updates)
    return group


def get_inscripcio_group_key(inscripcio) -> int:
    group_id = getattr(inscripcio, "grup_competicio_id", None)
    if group_id:
        return int(group_id)
    legacy = normalize_positive_int(getattr(inscripcio, "grup", None))
    return legacy or UNASSIGNED_GROUP_KEY


def get_inscripcio_group_display_num(inscripcio):
    group = getattr(inscripcio, "grup_competicio", None)
    if group is not None and getattr(group, "display_num", None):
        return int(group.display_num)
    legacy = normalize_positive_int(getattr(inscripcio, "grup", None))
    return legacy or None


def _resolve_group_id_for_inscripcio(inscripcio, groups_by_display_num=None):
    group_id = getattr(inscripcio, "grup_competicio_id", None)
    if group_id:
        return int(group_id)
    display_num = get_inscripcio_group_display_num(inscripcio)
    if not display_num:
        return None
    groups_by_display_num = groups_by_display_num or {}
    group = groups_by_display_num.get(display_num)
    return int(group.id) if group is not None and getattr(group, "id", None) else None


def get_inscripcio_group_label(inscripcio, label_by_id=None) -> str:
    group = getattr(inscripcio, "grup_competicio", None)
    if group is not None:
        if label_by_id and getattr(group, "id", None) in label_by_id:
            return label_by_id[group.id]
        return group_label(group)
    legacy_num = normalize_positive_int(getattr(inscripcio, "grup", None))
    if legacy_num:
        return f"Grup {legacy_num}"
    return "Sense grup"


def get_inscripcio_competition_order(inscripcio):
    order = getattr(inscripcio, "ordre_competicio", None)
    if order is not None:
        return order
    return getattr(inscripcio, "ordre_sortida", None)


def append_competition_order_for_group(group, inscripcio_id):
    max_order = (
        Inscripcio.objects
        .filter(grup_competicio=group)
        .aggregate(Max("ordre_competicio"))["ordre_competicio__max"]
        or 0
    )
    Inscripcio.objects.filter(id=inscripcio_id).update(
        grup_competicio=group,
        grup=group.display_num,
        ordre_competicio=max_order + 1,
    )


def compact_competition_order_for_group(group):
    if not group:
        return 0
    ids = list(
        Inscripcio.objects
        .filter(grup_competicio=group)
        .order_by("ordre_competicio", "ordre_sortida", "id")
        .values_list("id", flat=True)
    )
    updates = [
        Inscripcio(id=ins_id, ordre_competicio=idx)
        for idx, ins_id in enumerate(ids, start=1)
    ]
    if updates:
        Inscripcio.objects.bulk_update(updates, ["ordre_competicio"], batch_size=500)
    return len(updates)


def move_inscripcio_to_group(inscripcio, target_group):
    with transaction.atomic():
        old_group = getattr(inscripcio, "grup_competicio", None)
        if old_group and getattr(old_group, "id", None) == getattr(target_group, "id", None):
            return False
        append_competition_order_for_group(target_group, inscripcio.id)
        compact_competition_order_for_group(old_group)
    return True


def save_group_competition_order(group, ordered_ids):
    provided_ids = []
    seen = set()
    for raw in ordered_ids or []:
        clean = normalize_positive_int(raw)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        provided_ids.append(clean)

    live_ids = list(
        Inscripcio.objects
        .filter(grup_competicio=group)
        .order_by("ordre_competicio", "ordre_sortida", "id")
        .values_list("id", flat=True)
    )
    if set(provided_ids) != set(live_ids):
        raise ValueError("Cal desar l'ordre amb tots els participants del grup visibles.")

    updates = [
        Inscripcio(id=ins_id, ordre_competicio=idx)
        for idx, ins_id in enumerate(provided_ids, start=1)
    ]
    if updates:
        Inscripcio.objects.bulk_update(updates, ["ordre_competicio"], batch_size=500)
    return len(updates)


def get_group_members_payload(group):
    rows = (
        Inscripcio.objects
        .filter(grup_competicio=group)
        .order_by("ordre_competicio", "ordre_sortida", "id")
        .only("id", "nom_i_cognoms", "entitat", "ordre_competicio", "ordre_sortida")
    )
    payload = []
    for idx, inscripcio in enumerate(rows, start=1):
        payload.append(
            {
                "id": int(inscripcio.id),
                "nom": str(getattr(inscripcio, "nom_i_cognoms", "") or "").strip(),
                "entitat": str(getattr(inscripcio, "entitat", "") or "").strip(),
                "ordre_competicio": int(getattr(inscripcio, "ordre_competicio", None) or idx),
                "ordre_sortida": int(getattr(inscripcio, "ordre_sortida", None) or 0),
            }
        )
    return payload


def deactivate_empty_group(group):
    members_count = int(
        Inscripcio.objects
        .filter(grup_competicio=group)
        .count()
    )
    if members_count > 0:
        raise ValueError("No es pot eliminar un grup amb participants.")
    if group.actiu:
        group.actiu = False
        group.save(update_fields=["actiu"])
    return group


def assign_inscripcions_to_group(group, inscripcio_ids):
    clean_ids = []
    seen = set()
    for raw_id in inscripcio_ids or []:
        inscripcio_id = normalize_positive_int(raw_id)
        if not inscripcio_id or inscripcio_id in seen:
            continue
        seen.add(inscripcio_id)
        clean_ids.append(inscripcio_id)

    if not clean_ids:
        return {"updated": 0, "source_group_ids": [], "target_group_id": int(group.id)}

    old_group_ids = set(
        Inscripcio.objects
        .filter(id__in=clean_ids)
        .exclude(grup_competicio_id=group.id)
        .values_list("grup_competicio_id", flat=True)
    )
    old_group_ids.discard(None)

    with transaction.atomic():
        for inscripcio_id in clean_ids:
            append_competition_order_for_group(group, inscripcio_id)
        if old_group_ids:
            old_groups = list(GrupCompeticio.objects.filter(id__in=old_group_ids))
            for old_group in old_groups:
                compact_competition_order_for_group(old_group)

    return {
        "updated": len(clean_ids),
        "source_group_ids": sorted(int(group_id) for group_id in old_group_ids),
        "target_group_id": int(group.id),
    }


def unassign_inscripcions_from_groups(inscripcio_ids):
    clean_ids = []
    seen = set()
    for raw_id in inscripcio_ids or []:
        inscripcio_id = normalize_positive_int(raw_id)
        if not inscripcio_id or inscripcio_id in seen:
            continue
        seen.add(inscripcio_id)
        clean_ids.append(inscripcio_id)

    if not clean_ids:
        return {"updated": 0, "source_group_ids": []}

    old_group_ids = set(
        Inscripcio.objects
        .filter(id__in=clean_ids, grup_competicio_id__isnull=False)
        .values_list("grup_competicio_id", flat=True)
    )
    old_group_ids.discard(None)

    with transaction.atomic():
        Inscripcio.objects.filter(id__in=clean_ids).update(
            grup_competicio=None,
            grup=None,
            ordre_competicio=None,
        )
        if old_group_ids:
            old_groups = list(GrupCompeticio.objects.filter(id__in=old_group_ids))
            for old_group in old_groups:
                compact_competition_order_for_group(old_group)

    return {
        "updated": len(clean_ids),
        "source_group_ids": sorted(int(group_id) for group_id in old_group_ids),
    }


def assign_groups_by_display_num(competicio, display_num_to_inscripcio_ids, clear_missing=False):
    """
    Assigna grups estables a un mapping {display_num: [inscripcio_ids]} i actualitza
    el mirall legacy `Inscripcio.grup`.
    """
    normalized = {}
    for raw_display_num, raw_ids in (display_num_to_inscripcio_ids or {}).items():
        display_num = normalize_positive_int(raw_display_num)
        if not display_num or not isinstance(raw_ids, (list, tuple)):
            continue
        ids = []
        seen = set()
        for raw_id in raw_ids:
            ins_id = normalize_positive_int(raw_id)
            if not ins_id or ins_id in seen:
                continue
            seen.add(ins_id)
            ids.append(ins_id)
        if ids:
            normalized[display_num] = ids

    groups_cache = {}
    ids_seen = set()
    with transaction.atomic():
        if clear_missing:
            target_ids = [ins_id for ids in normalized.values() for ins_id in ids]
            Inscripcio.objects.filter(competicio=competicio).exclude(id__in=target_ids).update(
                grup_competicio=None,
                grup=None,
                ordre_competicio=None,
            )

        for display_num, ids in normalized.items():
            group = groups_cache.get(display_num)
            if group is None:
                group = ensure_group_for_display_num(competicio, display_num)
                groups_cache[display_num] = group
            for idx, ins_id in enumerate(ids, start=1):
                ids_seen.add(ins_id)
                Inscripcio.objects.filter(competicio=competicio, id=ins_id).update(
                    grup_competicio=group,
                    grup=group.display_num,
                    ordre_competicio=idx,
                )
    return ids_seen


def build_inscripcio_groups_map(inscripcions):
    grouped = defaultdict(list)
    for ins in inscripcions:
        grouped[get_inscripcio_group_key(ins)].append(ins)
    return grouped


def normalize_inscripcio_ids(values):
    out = []
    seen = set()
    for raw in values or []:
        clean = normalize_positive_int(raw)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def get_group_member_preview(group, limit=5, offset=0):
    if not group:
        return []
    try:
        limit = int(limit)
    except Exception:
        limit = 5
    if limit <= 0:
        limit = 5
    try:
        offset = int(offset)
    except Exception:
        offset = 0
    if offset < 0:
        offset = 0

    rows = (
        Inscripcio.objects
        .filter(grup_competicio=group)
        .order_by("ordre_competicio", "ordre_sortida", "id")
        .only("id", "nom_i_cognoms", "entitat", "ordre_competicio", "ordre_sortida")
    )
    out = []
    for ins in rows[offset:offset + limit]:
        label = str(getattr(ins, "nom_i_cognoms", "") or "").strip() or f"Inscripcio {ins.id}"
        secondary_label = str(getattr(ins, "entitat", "") or "").strip()
        out.append(
            {
                "id": ins.id,
                "label": label,
                "nom": label,
                "name": label,
                "secondary_label": secondary_label,
                "entitat": secondary_label,
                "order_competicio": int(ins.ordre_competicio) if getattr(ins, "ordre_competicio", None) is not None else None,
                "order_sortida": int(ins.ordre_sortida) if getattr(ins, "ordre_sortida", None) is not None else None,
            }
        )
    return out


def get_programmed_groups_emptied_by_ids(competicio, inscripcio_ids, exclude_group_id=None):
    clean_ids = normalize_inscripcio_ids(inscripcio_ids)
    if not clean_ids:
        return []

    programmed_group_ids = get_programmed_group_ids(competicio)
    if not programmed_group_ids:
        return []

    group_maps = get_group_maps(competicio)
    groups_by_display_num = group_maps["by_display_num"]
    groups_by_id = group_maps["by_id"]

    selected = list(
        Inscripcio.objects
        .filter(competicio=competicio, id__in=clean_ids)
        .select_related("grup_competicio")
        .only("id", "grup", "grup_competicio")
    )
    moving_counts = defaultdict(int)
    for inscripcio in selected:
        group_id = _resolve_group_id_for_inscripcio(inscripcio, groups_by_display_num)
        if not group_id or group_id == exclude_group_id:
            continue
        moving_counts[group_id] += 1

    if not moving_counts:
        return []

    total_counts = get_group_participant_counts(competicio)
    blocked = []
    for group_id, moved_count in moving_counts.items():
        if group_id not in programmed_group_ids:
            continue
        if moved_count >= total_counts.get(group_id, 0):
            group = groups_by_id.get(group_id)
            if group is not None:
                blocked.append(group)
    blocked.sort(key=lambda group: (group.display_num, group.id))
    return blocked


def get_group_summary_counts(competicio, include_inactive=False):
    groups = list(get_competicio_groups(competicio, include_inactive=include_inactive))
    group_ids = {group.id for group in groups}
    participant_counts = get_group_participant_counts(competicio)
    active_member_counts = {
        group_id: count
        for group_id, count in participant_counts.items()
        if group_id in group_ids
    }
    programmed_ids = get_programmed_group_ids(competicio) & group_ids
    out_of_program_ids = {group_id for group_id in active_member_counts.keys() if group_id not in programmed_ids}
    assigned_count = sum(active_member_counts.values())
    unassigned_count = Inscripcio.objects.filter(competicio=competicio, grup_competicio__isnull=True).count()

    return {
        "groups_total": len(groups),
        "groups_with_members": len(active_member_counts),
        "empty_groups": max(0, len(groups) - len(active_member_counts)),
        "assigned_count": assigned_count,
        "unassigned_count": unassigned_count,
        "programmed_groups": len(programmed_ids),
        "out_of_program_groups": len(out_of_program_ids),
        "participant_group_count": len(active_member_counts),
    }


def get_group_status(group, members_count=None, programmed_group_ids=None):
    if not group:
        return "missing"
    if members_count is None:
        members_count = Inscripcio.objects.filter(grup_competicio=group).count()
    if int(members_count or 0) <= 0:
        return "empty"
    if programmed_group_ids is None:
        programmed_group_ids = get_programmed_group_ids(group.competicio)
    return "programmed" if group.id in programmed_group_ids else "out_of_program"


def get_group_card_payload(
    group,
    *,
    members_count=None,
    member_limit=5,
    programmed_group_ids=None,
    is_out_of_program=None,
):
    if group is None:
        return None
    if members_count is None:
        members_count = int(
            Inscripcio.objects.filter(grup_competicio=group).count()
        )
    if programmed_group_ids is None:
        programmed_group_ids = get_programmed_group_ids(group.competicio)
    if is_out_of_program is None:
        is_out_of_program = bool(members_count > 0 and group.id not in programmed_group_ids)
    member_preview = get_group_member_preview(group, limit=member_limit)
    member_names = [row["label"] for row in member_preview if row.get("label")]
    status = get_group_status(group, members_count=members_count, programmed_group_ids=programmed_group_ids)
    return {
        "id": group.id,
        "display_num": int(group.display_num),
        "label": group_label(group),
        "name": str(getattr(group, "nom", "") or "").strip(),
        "legacy_num": int(group.legacy_num) if getattr(group, "legacy_num", None) is not None else None,
        "actiu": bool(group.actiu),
        "members_count": int(members_count or 0),
        "members_preview": member_preview,
        "member_names_preview": member_names[:member_limit],
        "member_names_remaining": max(0, int(members_count or 0) - len(member_names)),
        "is_programmed": group.id in programmed_group_ids,
        "is_out_of_program": bool(is_out_of_program),
        "status": status,
        "can_delete": bool(int(members_count or 0) == 0),
    }


def get_group_detail_payload(group, *, member_limit=50, programmed_group_ids=None, page=1, page_size=None):
    if group is None:
        return None
    if programmed_group_ids is None:
        programmed_group_ids = get_programmed_group_ids(group.competicio)
    members_count = int(
        Inscripcio.objects.filter(grup_competicio=group).count()
    )
    resolved_page = normalize_positive_int(page) or 1
    resolved_page_size = normalize_positive_int(page_size) or normalize_positive_int(member_limit) or 10
    members_total_pages = max(1, (members_count + resolved_page_size - 1) // resolved_page_size)
    resolved_page = min(resolved_page, members_total_pages)
    offset = (resolved_page - 1) * resolved_page_size
    members = get_group_member_preview(group, limit=resolved_page_size, offset=offset)
    return {
        "id": group.id,
        "display_num": int(group.display_num),
        "label": group_label(group),
        "name": str(getattr(group, "nom", "") or "").strip(),
        "legacy_num": int(group.legacy_num) if getattr(group, "legacy_num", None) is not None else None,
        "actiu": bool(group.actiu),
        "members_count": members_count,
        "members": members,
        "members_preview": members[:5],
        "members_total": members_count,
        "members_page": resolved_page,
        "members_page_size": resolved_page_size,
        "members_total_pages": members_total_pages,
        "members_has_prev": resolved_page > 1,
        "members_has_next": resolved_page < members_total_pages,
        "is_programmed": group.id in programmed_group_ids,
        "is_out_of_program": bool(members_count > 0 and group.id not in programmed_group_ids),
        "status": get_group_status(group, members_count=members_count, programmed_group_ids=programmed_group_ids),
        "can_delete": bool(members_count == 0),
    }


def move_inscripcions_to_group(group, inscripcio_ids):
    clean_ids = normalize_inscripcio_ids(inscripcio_ids)
    if group is None or not clean_ids:
        return {
            "updated": 0,
            "moved_ids": [],
            "skipped_ids": clean_ids,
            "compacted_group_ids": [],
        }

    rows = list(
        Inscripcio.objects
        .filter(competicio=group.competicio, id__in=clean_ids)
        .select_related("grup_competicio")
        .order_by("ordre_competicio", "ordre_sortida", "id")
        .only("id", "grup_competicio_id", "grup", "ordre_competicio", "ordre_sortida")
    )
    movable = [ins for ins in rows if getattr(ins, "grup_competicio_id", None) != group.id]
    if not movable:
        return {
            "updated": 0,
            "moved_ids": [],
            "skipped_ids": clean_ids,
            "compacted_group_ids": [],
        }

    group_maps = get_group_maps(group.competicio, include_inactive=True)
    groups_by_id = group_maps["by_id"]
    old_group_ids = sorted({
        int(ins.grup_competicio_id)
        for ins in movable
        if getattr(ins, "grup_competicio_id", None) and int(ins.grup_competicio_id) != group.id
    })
    max_order = (
        Inscripcio.objects
        .filter(grup_competicio=group)
        .aggregate(Max("ordre_competicio"))["ordre_competicio__max"]
        or 0
    )
    updates = []
    for idx, ins in enumerate(movable, start=1):
        updates.append(
            Inscripcio(
                id=ins.id,
                grup_competicio=group,
                grup=group.display_num,
                ordre_competicio=max_order + idx,
            )
        )

    with transaction.atomic():
        if updates:
            Inscripcio.objects.bulk_update(
                updates,
                ["grup_competicio", "grup", "ordre_competicio"],
                batch_size=500,
            )
        for group_id in old_group_ids:
            compact_competition_order_for_group(groups_by_id.get(group_id))

    moved_id_set = {ins.id for ins in movable}
    return {
        "updated": len(updates),
        "moved_ids": [ins.id for ins in movable],
        "skipped_ids": [ins_id for ins_id in clean_ids if ins_id not in moved_id_set],
        "compacted_group_ids": old_group_ids,
    }


def clear_inscripcions_group(competicio, inscripcio_ids):
    clean_ids = normalize_inscripcio_ids(inscripcio_ids)
    if not clean_ids:
        return {
            "updated": 0,
            "cleared_ids": [],
            "compacted_group_ids": [],
        }

    rows = list(
        Inscripcio.objects
        .filter(competicio=competicio, id__in=clean_ids)
        .select_related("grup_competicio")
        .order_by("grup_competicio_id", "ordre_competicio", "ordre_sortida", "id")
        .only("id", "grup_competicio_id", "grup", "ordre_competicio", "ordre_sortida")
    )
    old_group_ids = sorted({
        int(ins.grup_competicio_id)
        for ins in rows
        if getattr(ins, "grup_competicio_id", None)
    })
    updates = [Inscripcio(id=ins.id, grup_competicio=None, grup=None, ordre_competicio=None) for ins in rows]
    groups_by_id = get_group_maps(competicio, include_inactive=True)["by_id"]

    with transaction.atomic():
        if updates:
            Inscripcio.objects.bulk_update(
                updates,
                ["grup_competicio", "grup", "ordre_competicio"],
                batch_size=500,
            )
        for group_id in old_group_ids:
            compact_competition_order_for_group(groups_by_id.get(group_id))

    return {
        "updated": len(updates),
        "cleared_ids": [ins.id for ins in rows],
        "compacted_group_ids": old_group_ids,
    }


def safe_deactivate_empty_group(group):
    if group is None:
        return False, "group_missing"
    if not group.actiu:
        return False, "group_inactive"
    members_count = Inscripcio.objects.filter(grup_competicio=group).count()
    if members_count > 0:
        return False, "group_not_empty"
    group.actiu = False
    group.save(update_fields=["actiu"])
    return True, "deactivated"
