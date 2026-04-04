import random

from django.db import transaction

from ...models import Inscripcio
from .queries import (
    LEGACY_SORT_KEY_MAP,
    _build_sort_field_runtime_context,
    _custom_sort_token_key,
    _normalize_custom_sort_order,
    _normalize_custom_sort_token,
    _resolve_sort_field_runtime,
    get_inscripcio_value,
)
from .shared import INSCRIPCIONS_SORT_STACK_SESSION_KEY


def _norm_val(value):
    return "__NULL__" if value in (None, "") else str(value)


def sort_records_by_field_stable(records, sort_code, descending=False, custom_rank_map=None):
    custom_map = custom_rank_map if isinstance(custom_rank_map, dict) else {}
    custom_enabled = bool(custom_map)
    custom_filled = []
    fallback_filled = []
    empty = []
    context = _build_sort_field_runtime_context(records, sort_code)
    for obj in records:
        runtime = _resolve_sort_field_runtime(obj, sort_code, context=context)
        token = runtime.get("token") or ""
        if not token:
            empty.append(obj)
            continue
        if custom_enabled:
            key = _custom_sort_token_key(token)
            if key in custom_map:
                custom_filled.append((obj, custom_map[key]))
                continue
        fallback_filled.append((obj, runtime.get("sort_scalar")))
    custom_filled.sort(key=lambda item: item[1], reverse=descending)
    fallback_filled.sort(key=lambda item: item[1], reverse=descending)
    return [obj for (obj, _rank) in custom_filled] + [obj for (obj, _value) in fallback_filled] + empty


def arrow_positions(n: int) -> list[int]:
    if n <= 0:
        return []
    seq = []
    if n % 2 == 0:
        left = n // 2 - 1
        right = n // 2
        while left >= 0 or right < n:
            if left >= 0:
                seq.append(left)
                left -= 1
            if right < n:
                seq.append(right)
                right += 1
    else:
        center = n // 2
        seq.append(center)
        step = 1
        while center - step >= 0 or center + step < n:
            if center - step >= 0:
                seq.append(center - step)
            if center + step < n:
                seq.append(center + step)
            step += 1
    return seq


def shuffle_ordre_sortida(qs):
    ids = list(qs.values_list("id", flat=True))
    random.shuffle(ids)
    with transaction.atomic():
        for idx, ins_id in enumerate(ids, start=1):
            Inscripcio.objects.filter(id=ins_id).update(ordre_sortida=idx)


def recalcular_ordre_sortida(qs, group_codes):
    records = list(qs.order_by("ordre_sortida", "id"))

    def sort_key(obj):
        group_values = tuple(_norm_val(get_inscripcio_value(obj, code)) for code in group_codes)
        previous = obj.ordre_sortida if obj.ordre_sortida is not None else 10**12
        return (group_values, previous, obj.id)

    records.sort(key=sort_key)
    with transaction.atomic():
        for idx, obj in enumerate(records, start=1):
            if obj.ordre_sortida != idx:
                Inscripcio.objects.filter(id=obj.id).update(ordre_sortida=idx)


def set_competicio_custom_sort_order_values(competicio, sort_code, raw_values=None, clear=False, allowed_sort_codes=None):
    code_raw = str(sort_code or "").strip()
    code = LEGACY_SORT_KEY_MAP.get(code_raw, code_raw)
    if not code:
        raise ValueError("sort_key invalid")
    if allowed_sort_codes is not None and code not in set(allowed_sort_codes):
        raise ValueError("sort_key invalid")

    values = [] if clear else _normalize_custom_sort_order(raw_values)
    view_cfg = dict(competicio.inscripcions_view or {})
    custom_map = view_cfg.get("custom_sort_orders")
    if not isinstance(custom_map, dict):
        custom_map = {}
    custom_map = dict(custom_map)

    if values:
        custom_map[code] = values
    else:
        custom_map.pop(code, None)

    if custom_map:
        view_cfg["custom_sort_orders"] = custom_map
    else:
        view_cfg.pop("custom_sort_orders", None)

    competicio.inscripcions_view = view_cfg
    competicio.save(update_fields=["inscripcions_view"])
    return values


def _split_custom_sort_tokens(custom_tokens, available_token_keys):
    active = []
    stale = []
    available = set(available_token_keys or set())
    seen = set()
    for raw in custom_tokens or []:
        token = _normalize_custom_sort_token(raw)
        if not token:
            continue
        key = _custom_sort_token_key(token)
        if not key or key in seen:
            continue
        seen.add(key)
        if key in available:
            active.append(token)
        else:
            stale.append(token)
    return active, stale


def clear_inscripcions_sort_state_for_competicio(request, competicio_id):
    prefix = f"{competicio_id}||"
    store = request.session.get(INSCRIPCIONS_SORT_STACK_SESSION_KEY)
    if not isinstance(store, dict):
        return
    changed = False
    for key in list(store.keys()):
        if isinstance(key, str) and key.startswith(prefix):
            store.pop(key, None)
            changed = True
    if changed:
        request.session[INSCRIPCIONS_SORT_STACK_SESSION_KEY] = store
        request.session.modified = True


__all__ = [
    "_split_custom_sort_tokens",
    "arrow_positions",
    "clear_inscripcions_sort_state_for_competicio",
    "recalcular_ordre_sortida",
    "set_competicio_custom_sort_order_values",
    "shuffle_ordre_sortida",
    "sort_records_by_field_stable",
]
