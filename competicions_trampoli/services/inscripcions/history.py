from datetime import datetime

from django.db import transaction

from ...models import Equip, EquipContext, GrupCompeticio, Inscripcio, InscripcioEquipAssignacio
from ...models.competicio import InscripcioAparellExclusio
from ..shared.birth_year_ranges import clear_inscripcions_derived_group_config_cache
from ..shared.competition_groups import sync_competicio_group_names_view
from ..teams.equip_contexts import NATIVE_EQUIP_CONTEXT_CODE, get_equip_context
from .shared import (
    INSCRIPCIONS_HISTORY_DEPTH,
    INSCRIPCIONS_HISTORY_SESSION_KEY,
    INSCRIPCIONS_SORT_STACK_SESSION_KEY,
    json_clone,
)


def _read_sort_stack_store(request):
    raw = request.session.get(INSCRIPCIONS_SORT_STACK_SESSION_KEY)
    if not isinstance(raw, dict):
        return {}
    return raw


def _write_sort_stack_store(request, store):
    request.session[INSCRIPCIONS_SORT_STACK_SESSION_KEY] = store
    request.session.modified = True


def _history_comp_key(competicio_id):
    return str(int(competicio_id))


def _read_inscripcions_history_store(request):
    raw = request.session.get(INSCRIPCIONS_HISTORY_SESSION_KEY)
    if not isinstance(raw, dict):
        return {}
    return raw


def _write_inscripcions_history_store(request, store):
    request.session[INSCRIPCIONS_HISTORY_SESSION_KEY] = store
    request.session.modified = True


def _capture_sort_stack_state_for_competicio(request, competicio_id):
    prefix = f"{competicio_id}||"
    stack_store = _read_sort_stack_store(request)
    out = {}
    for key, value in stack_store.items():
        if isinstance(key, str) and key.startswith(prefix) and isinstance(value, dict):
            out[key] = json_clone(value)
    return out


def _restore_sort_stack_state_for_competicio(request, competicio_id, state_snapshot):
    prefix = f"{competicio_id}||"
    stack_store = _read_sort_stack_store(request)
    for key in list(stack_store.keys()):
        if isinstance(key, str) and key.startswith(prefix):
            stack_store.pop(key, None)

    if isinstance(state_snapshot, dict):
        for key, value in state_snapshot.items():
            if isinstance(key, str) and key.startswith(prefix) and isinstance(value, dict):
                stack_store[key] = json_clone(value)

    _write_sort_stack_store(request, stack_store)


def capture_inscripcions_history_snapshot(request, competicio):
    inscripcions_rows = list(
        Inscripcio.objects
        .filter(competicio=competicio)
        .order_by("id")
        .values(
            "id",
            "ordre_sortida",
            "grup",
            "grup_competicio_id",
            "ordre_competicio",
            "equip_id",
        )
    )
    grups_rows = list(
        GrupCompeticio.objects
        .filter(competicio=competicio)
        .order_by("display_num", "id")
        .values("id", "legacy_num", "display_num", "nom", "actiu")
    )
    exclusions_rows = list(
        InscripcioAparellExclusio.objects
        .filter(inscripcio__competicio=competicio)
        .order_by("inscripcio_id", "comp_aparell_id")
        .values("inscripcio_id", "comp_aparell_id", "motiu")
    )
    equips_rows = list(
        Equip.objects
        .filter(competicio=competicio)
        .order_by("id")
        .values("id", "context_id", "nom", "origen", "criteri")
    )
    equip_context_rows = list(
        EquipContext.objects
        .filter(competicio=competicio)
        .order_by("id")
        .values("id", "code", "nom", "description")
    )
    equip_assignacio_rows = list(
        InscripcioEquipAssignacio.objects
        .filter(competicio=competicio)
        .order_by("context_id", "inscripcio_id")
        .values("context_id", "inscripcio_id", "equip_id", "origen", "criteri")
    )
    return {
        "inscripcions_fields": json_clone(inscripcions_rows),
        "grups_competicio": json_clone(grups_rows),
        "competicio_fields": {
            "tab_merges": json_clone(competicio.tab_merges or {}),
            "inscripcions_view": json_clone(competicio.inscripcions_view or {}),
        },
        "aparells_exclusions": json_clone(exclusions_rows),
        "equips_state": json_clone(equips_rows),
        "equip_contexts_state": json_clone(equip_context_rows),
        "equip_assignacions_state": json_clone(equip_assignacio_rows),
        "sort_stack_state": _capture_sort_stack_state_for_competicio(request, competicio.id),
    }


def _apply_equips_state_snapshot(competicio, equips_state):
    rows = equips_state if isinstance(equips_state, list) else []
    base_ctx = get_equip_context(competicio, NATIVE_EQUIP_CONTEXT_CODE)
    normalized = []
    seen_ids = set()
    valid_context_ids = set(
        EquipContext.objects.filter(competicio=competicio).values_list("id", flat=True)
    )
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            equip_id = int(row.get("id"))
        except Exception:
            continue
        if equip_id <= 0 or equip_id in seen_ids:
            continue
        try:
            context_id = int(row.get("context_id"))
        except Exception:
            context_id = getattr(base_ctx, "id", None)
        if context_id not in valid_context_ids:
            context_id = getattr(base_ctx, "id", None)
        if context_id not in valid_context_ids:
            continue
        seen_ids.add(equip_id)
        normalized.append(
            Equip(
                id=equip_id,
                competicio=competicio,
                context_id=context_id,
                nom=str(row.get("nom") or "").strip(),
                origen=str(row.get("origen") or Equip.Origen.MANUAL).strip() or Equip.Origen.MANUAL,
                criteri=json_clone(row.get("criteri") or {}),
            )
        )

    Equip.objects.filter(competicio=competicio).delete()
    if normalized:
        Equip.objects.bulk_create(normalized)


def _apply_equip_contexts_state_snapshot(competicio, equip_contexts_state):
    rows = equip_contexts_state if isinstance(equip_contexts_state, list) else []
    normalized = []
    seen_ids = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            ctx_id = int(row.get("id"))
        except Exception:
            continue
        if ctx_id <= 0 or ctx_id in seen_ids:
            continue
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        seen_ids.add(ctx_id)
        normalized.append(
            EquipContext(
                id=ctx_id,
                competicio=competicio,
                code=code,
                nom=str(row.get("nom") or "").strip(),
                description=str(row.get("description") or "").strip(),
            )
        )

    EquipContext.objects.filter(competicio=competicio).delete()
    if normalized:
        EquipContext.objects.bulk_create(normalized)


def _apply_equip_assignacions_state_snapshot(competicio, equip_assignacions_state):
    rows = equip_assignacions_state if isinstance(equip_assignacions_state, list) else []
    normalized = []
    seen_keys = set()
    valid_context_ids = set(
        EquipContext.objects.filter(competicio=competicio).values_list("id", flat=True)
    )
    valid_ins_ids = set(
        Inscripcio.objects.filter(competicio=competicio).values_list("id", flat=True)
    )
    valid_equip_context_map = dict(
        Equip.objects
        .filter(competicio=competicio)
        .values_list("id", "context_id")
    )
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            context_id = int(row.get("context_id"))
            inscripcio_id = int(row.get("inscripcio_id"))
            equip_id = int(row.get("equip_id"))
        except Exception:
            continue
        key = (context_id, inscripcio_id)
        if (
            key in seen_keys
            or context_id not in valid_context_ids
            or inscripcio_id not in valid_ins_ids
            or equip_id not in valid_equip_context_map
            or int(valid_equip_context_map.get(equip_id) or 0) != context_id
        ):
            continue
        seen_keys.add(key)
        normalized.append(
            InscripcioEquipAssignacio(
                competicio=competicio,
                context_id=context_id,
                inscripcio_id=inscripcio_id,
                equip_id=equip_id,
                origen=str(row.get("origen") or InscripcioEquipAssignacio.Origen.MANUAL).strip() or InscripcioEquipAssignacio.Origen.MANUAL,
                criteri=json_clone(row.get("criteri") or {}),
            )
        )

    InscripcioEquipAssignacio.objects.filter(competicio=competicio).delete()
    if normalized:
        InscripcioEquipAssignacio.objects.bulk_create(normalized, batch_size=500)


def _apply_legacy_base_assignacions_from_snapshot(competicio, inscripcions_fields):
    rows = inscripcions_fields if isinstance(inscripcions_fields, list) else []
    base_ctx = get_equip_context(competicio, NATIVE_EQUIP_CONTEXT_CODE)
    if base_ctx is None:
        return
    valid_ins_ids = set(
        Inscripcio.objects.filter(competicio=competicio).values_list("id", flat=True)
    )
    valid_equip_ids = set(
        Equip.objects.filter(competicio=competicio).values_list("id", flat=True)
    )
    existing_ins_ids = set(
        InscripcioEquipAssignacio.objects
        .filter(competicio=competicio, context=base_ctx)
        .values_list("inscripcio_id", flat=True)
    )
    creates = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            ins_id = int(row.get("id"))
            equip_id = int(row.get("equip_id"))
        except Exception:
            continue
        if (
            ins_id not in valid_ins_ids
            or equip_id not in valid_equip_ids
            or ins_id in existing_ins_ids
        ):
            continue
        existing_ins_ids.add(ins_id)
        creates.append(
            InscripcioEquipAssignacio(
                competicio=competicio,
                context=base_ctx,
                inscripcio_id=ins_id,
                equip_id=equip_id,
                origen=InscripcioEquipAssignacio.Origen.MANUAL,
                criteri={},
            )
        )
    if creates:
        InscripcioEquipAssignacio.objects.bulk_create(creates, batch_size=500)


def _apply_inscripcions_fields_snapshot(competicio, inscripcions_fields):
    rows = inscripcions_fields if isinstance(inscripcions_fields, list) else []
    by_id = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            ins_id = int(row.get("id"))
        except Exception:
            continue
        by_id[ins_id] = {
            "ordre_sortida": row.get("ordre_sortida"),
            "grup": row.get("grup"),
            "grup_competicio_id": row.get("grup_competicio_id"),
            "ordre_competicio": row.get("ordre_competicio"),
        }

    if not by_id:
        return

    updates = []
    qs = Inscripcio.objects.filter(competicio=competicio, id__in=list(by_id.keys()))
    for obj in qs.only("id", "ordre_sortida", "grup", "grup_competicio", "ordre_competicio"):
        row = by_id.get(obj.id)
        if row is None:
            continue
        next_ord = row.get("ordre_sortida")
        next_grp = row.get("grup")
        next_grup_competicio_id = row.get("grup_competicio_id")
        next_ordre_competicio = row.get("ordre_competicio")
        if (
            obj.ordre_sortida != next_ord
            or obj.grup != next_grp
            or obj.grup_competicio_id != next_grup_competicio_id
            or obj.ordre_competicio != next_ordre_competicio
        ):
            obj.ordre_sortida = next_ord
            obj.grup = next_grp
            obj.grup_competicio_id = next_grup_competicio_id
            obj.ordre_competicio = next_ordre_competicio
            updates.append(obj)

    if updates:
        Inscripcio.objects.bulk_update(
            updates,
            ["ordre_sortida", "grup", "grup_competicio", "ordre_competicio"],
            batch_size=500,
        )


def _apply_grups_competicio_snapshot(competicio, grups_rows):
    rows = grups_rows if isinstance(grups_rows, list) else []
    normalized = []
    seen_ids = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            group_id = int(row.get("id"))
            display_num = int(row.get("display_num"))
        except Exception:
            continue
        if group_id <= 0 or display_num <= 0 or group_id in seen_ids:
            continue
        seen_ids.add(group_id)
        normalized.append(
            GrupCompeticio(
                id=group_id,
                competicio=competicio,
                legacy_num=row.get("legacy_num"),
                display_num=display_num,
                nom=str(row.get("nom") or "").strip(),
                actiu=bool(row.get("actiu", True)),
            )
        )

    current_ids = set(
        GrupCompeticio.objects.filter(competicio=competicio).values_list("id", flat=True)
    )
    target_ids = {obj.id for obj in normalized}
    stale_ids = list(current_ids - target_ids)
    if stale_ids:
        Inscripcio.objects.filter(competicio=competicio, grup_competicio_id__in=stale_ids).update(
            grup_competicio=None,
            ordre_competicio=None,
        )
        GrupCompeticio.objects.filter(competicio=competicio, id__in=stale_ids).delete()

    existing_ids = current_ids & target_ids
    if existing_ids:
        updates = [obj for obj in normalized if obj.id in existing_ids]
        if updates:
            GrupCompeticio.objects.bulk_update(
                updates,
                ["legacy_num", "display_num", "nom", "actiu"],
                batch_size=200,
            )
    creates = [obj for obj in normalized if obj.id not in existing_ids]
    if creates:
        GrupCompeticio.objects.bulk_create(creates, batch_size=200)


def _apply_aparells_exclusions_snapshot(competicio, exclusions):
    rows = exclusions if isinstance(exclusions, list) else []
    seen_pairs = set()
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            ins_id = int(row.get("inscripcio_id"))
            app_id = int(row.get("comp_aparell_id"))
        except Exception:
            continue
        key = (ins_id, app_id)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        normalized.append(
            InscripcioAparellExclusio(
                inscripcio_id=ins_id,
                comp_aparell_id=app_id,
                motiu=str(row.get("motiu") or ""),
            )
        )

    InscripcioAparellExclusio.objects.filter(inscripcio__competicio=competicio).delete()
    if normalized:
        InscripcioAparellExclusio.objects.bulk_create(normalized, batch_size=500)


def _apply_competicio_fields_snapshot(competicio, competicio_fields):
    fields = competicio_fields if isinstance(competicio_fields, dict) else {}
    tab_merges = fields.get("tab_merges")
    inscripcions_view = fields.get("inscripcions_view")

    updates = []
    if tab_merges is not None:
        competicio.tab_merges = json_clone(tab_merges) if isinstance(tab_merges, dict) else {}
        updates.append("tab_merges")
    if inscripcions_view is not None:
        competicio.inscripcions_view = json_clone(inscripcions_view) if isinstance(inscripcions_view, dict) else {}
        updates.append("inscripcions_view")
    if updates:
        competicio.save(update_fields=updates)
        if "inscripcions_view" in updates:
            clear_inscripcions_derived_group_config_cache()


def apply_inscripcions_history_snapshot(request, competicio, snapshot):
    snap = snapshot if isinstance(snapshot, dict) else {}
    with transaction.atomic():
        _apply_equip_contexts_state_snapshot(competicio, snap.get("equip_contexts_state"))
        _apply_equips_state_snapshot(competicio, snap.get("equips_state"))
        _apply_grups_competicio_snapshot(competicio, snap.get("grups_competicio"))
        _apply_inscripcions_fields_snapshot(competicio, snap.get("inscripcions_fields"))
        _apply_equip_assignacions_state_snapshot(competicio, snap.get("equip_assignacions_state"))
        _apply_legacy_base_assignacions_from_snapshot(competicio, snap.get("inscripcions_fields"))
        _apply_aparells_exclusions_snapshot(competicio, snap.get("aparells_exclusions"))
        _apply_competicio_fields_snapshot(competicio, snap.get("competicio_fields"))

    sync_competicio_group_names_view(competicio)
    _restore_sort_stack_state_for_competicio(request, competicio.id, snap.get("sort_stack_state"))


def record_inscripcions_history_entry(request, competicio, action_type, action_label, before_snapshot, after_snapshot):
    before = before_snapshot if isinstance(before_snapshot, dict) else {}
    after = after_snapshot if isinstance(after_snapshot, dict) else {}
    if before == after:
        return False

    entry = {
        "action_type": str(action_type or "").strip() or "unknown",
        "action_label": str(action_label or "").strip() or "Canvi",
        "created_at": datetime.utcnow().isoformat(),
        "before": before,
        "after": after,
    }

    store = _read_inscripcions_history_store(request)
    comp_key = _history_comp_key(competicio.id)
    bucket = store.get(comp_key)
    if not isinstance(bucket, dict):
        bucket = {"undo": [], "redo": []}

    undo = bucket.get("undo")
    if not isinstance(undo, list):
        undo = []
    undo.append(entry)
    if len(undo) > INSCRIPCIONS_HISTORY_DEPTH:
        undo = undo[-INSCRIPCIONS_HISTORY_DEPTH:]

    bucket["undo"] = undo
    bucket["redo"] = []
    store[comp_key] = bucket
    _write_inscripcions_history_store(request, store)
    return True


def get_inscripcions_history_state(request, competicio_id):
    store = _read_inscripcions_history_store(request)
    comp_key = _history_comp_key(competicio_id)
    bucket = store.get(comp_key)
    if not isinstance(bucket, dict):
        bucket = {}

    undo = bucket.get("undo")
    redo = bucket.get("redo")
    if not isinstance(undo, list):
        undo = []
    if not isinstance(redo, list):
        redo = []

    undo_top = undo[-1] if undo else {}
    redo_top = redo[-1] if redo else {}
    undo_label = str(undo_top.get("action_label") or "").strip()
    redo_label = str(redo_top.get("action_label") or "").strip()

    return {
        "can_undo": bool(undo),
        "can_redo": bool(redo),
        "undo_label": undo_label,
        "redo_label": redo_label,
        "undo_count": len(undo),
        "redo_count": len(redo),
    }


def with_inscripcions_history_payload(payload, request, competicio_id):
    data = payload if isinstance(payload, dict) else {}
    data["history"] = get_inscripcions_history_state(request, competicio_id)
    return data


__all__ = [
    "apply_inscripcions_history_snapshot",
    "capture_inscripcions_history_snapshot",
    "get_inscripcions_history_state",
    "record_inscripcions_history_entry",
    "with_inscripcions_history_payload",
]
