"""Reusable inscripcions group/history helpers.

This module centralizes the group-name sync and rotation-safe move helpers that
legacy views still use. It intentionally reuses the competition_groups service
where possible so behavior stays aligned with the existing runtime.
"""

from collections import defaultdict

from django.db import transaction

from ...models import GrupCompeticio, Inscripcio
from ..competition_groups import (
    ensure_group_for_display_num,
    get_group_maps,
    get_programmed_group_ids,
    get_programmed_groups_emptied_by_ids,
    normalize_positive_int,
    sync_competicio_group_names_view,
)


def _normalize_group_names_map(raw_group_names):
    out = {}
    if not isinstance(raw_group_names, dict):
        return out
    for raw_group, raw_label in raw_group_names.items():
        try:
            group_num = int(str(raw_group).strip())
        except Exception:
            continue
        if group_num <= 0:
            continue
        label = str(raw_label or "").strip()
        if not label:
            continue
        out[group_num] = label
    return out


def _persist_group_suggested_names(competicio, preview_groups):
    suggested_by_display_num = {}
    for row in preview_groups or []:
        group_num = normalize_positive_int(row.get("group_num"))
        suggested_name = str(row.get("suggested_name") or "").strip()
        if not group_num or not suggested_name:
            continue
        suggested_by_display_num[group_num] = suggested_name

    if not suggested_by_display_num:
        sync_competicio_group_names_view(competicio)
        return 0

    groups = list(
        GrupCompeticio.objects.filter(
            competicio=competicio,
            display_num__in=list(suggested_by_display_num.keys()),
        )
    )
    updates = []
    for group in groups:
        suggested_name = suggested_by_display_num.get(group.display_num, "")
        if not suggested_name or group.nom == suggested_name:
            continue
        group.nom = suggested_name
        updates.append(group)

    if updates:
        GrupCompeticio.objects.bulk_update(updates, ["nom"], batch_size=200)

    sync_competicio_group_names_view(competicio)
    return len(updates)


def renumber_groups_for_competicio(competicio):
    sync_competicio_group_names_view(competicio)


def _resolve_group_id_for_inscripcio(inscripcio, groups_by_display_num):
    group_id = getattr(inscripcio, "grup_competicio_id", None)
    if group_id:
        return int(group_id)
    legacy_group_num = normalize_positive_int(getattr(inscripcio, "grup", None))
    if not legacy_group_num:
        return None
    group = groups_by_display_num.get(legacy_group_num)
    if not group:
        return None
    return int(group.id)


def _programmed_groups_emptied_by_move(competicio, target_ids):
    return get_programmed_groups_emptied_by_ids(competicio, target_ids)


def sync_stable_groups_from_legacy(competicio):
    view_cfg = competicio.inscripcions_view or {}
    group_names = _normalize_group_names_map(view_cfg.get("group_names") or {})
    live_display_nums = list(
        Inscripcio.objects.filter(competicio=competicio, grup__isnull=False)
        .order_by("grup")
        .values_list("grup", flat=True)
        .distinct()
    )
    live_display_nums = [int(num) for num in live_display_nums if isinstance(num, int) and num > 0]

    group_maps = get_group_maps(competicio)
    groups_by_display = group_maps["by_display_num"]
    touched_group_ids = set()
    updates = []
    with transaction.atomic():
        for display_num in live_display_nums:
            group = groups_by_display.get(display_num)
            name = str(group_names.get(display_num) or "").strip()
            if group is None:
                group = ensure_group_for_display_num(competicio, display_num, name=name)
                groups_by_display[display_num] = group
            else:
                fields = []
                if not group.actiu:
                    group.actiu = True
                    fields.append("actiu")
                if name != group.nom:
                    group.nom = name
                    fields.append("nom")
                if fields:
                    group.save(update_fields=fields)
            touched_group_ids.add(group.id)

        stale_groups = [
            group
            for group in get_group_maps(competicio)["groups"]
            if group.id not in touched_group_ids
        ]
        if stale_groups:
            GrupCompeticio.objects.filter(id__in=[group.id for group in stale_groups]).update(actiu=False)

        counters = defaultdict(int)
        qs = (
            Inscripcio.objects.filter(competicio=competicio)
            .order_by("grup", "ordre_sortida", "id")
            .only("id", "grup", "grup_competicio", "ordre_competicio")
        )
        for inscripcio in qs:
            display_num = getattr(inscripcio, "grup", None)
            group = groups_by_display.get(display_num)
            next_group_id = getattr(group, "id", None)
            next_comp_order = None
            if next_group_id:
                counters[next_group_id] = int(counters.get(next_group_id, 0) or 0) + 1
                next_comp_order = counters[next_group_id]
            if inscripcio.grup_competicio_id != next_group_id or inscripcio.ordre_competicio != next_comp_order:
                inscripcio.grup_competicio_id = next_group_id
                inscripcio.ordre_competicio = next_comp_order
                updates.append(inscripcio)
        if updates:
            Inscripcio.objects.bulk_update(updates, ["grup_competicio", "ordre_competicio"], batch_size=500)

    sync_competicio_group_names_view(competicio)


__all__ = [
    "_persist_group_suggested_names",
    "_programmed_groups_emptied_by_move",
    "renumber_groups_for_competicio",
    "sync_stable_groups_from_legacy",
]
