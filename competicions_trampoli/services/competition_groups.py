from collections import defaultdict

from django.db import transaction
from django.db.models import Max

from ..models import GrupCompeticio, Inscripcio


UNASSIGNED_GROUP_KEY = 0


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
