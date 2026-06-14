import json
from collections import OrderedDict

from ..shared.partition_plans import (
    normalize_creation_strategy,
    parse_fallback_mode,
    sizes_for_strategy,
)


def selected_bucket_keys_from_payload(payload):
    data = payload if isinstance(payload, dict) else {}
    raw = data.get("selected_keys")
    if not isinstance(raw, list):
        raw = data.get("selected_bucket_keys")
    if not isinstance(raw, list):
        raw = data.get("selected_tab_keys")
    if not isinstance(raw, list):
        raw = data.get("bucket_keys")
    values = raw if isinstance(raw, list) else []
    out = []
    for value in values:
        key = str(value or "").strip()
        if key and key not in out:
            out.append(key)
    return out


def buckets_to_apply(grouped, payload):
    selected_keys = selected_bucket_keys_from_payload(payload)
    if selected_keys:
        allowed = set(selected_keys)
        return OrderedDict((key, item) for key, item in grouped.items() if key in allowed)
    if str((payload or {}).get("bucket_selection_mode") or "").strip().lower() == "none":
        return OrderedDict()
    return OrderedDict(grouped)


def unique_team_names(existing_names, count, prefix="Equip"):
    used = {str(name or "").strip() for name in existing_names or [] if str(name or "").strip()}
    out = []
    index = 1
    while len(out) < count:
        candidate = f"{prefix} {index}"
        index += 1
        if candidate in used:
            continue
        used.add(candidate)
        out.append(candidate)
    return out


def grouped_from_strategy(records, grouped, payload, existing_names=None):
    data = payload if isinstance(payload, dict) else {}
    strategy = normalize_creation_strategy(data.get("strategy"))
    fallback_mode = parse_fallback_mode(data.get("fallback_mode"))
    if strategy == "per_bucket":
        applied = buckets_to_apply(grouped, data)
        return applied, {
            "strategy": strategy,
            "buckets_total": len(grouped),
            "buckets_applied": len(applied),
            "used_fallback": False,
            "fallback_reason": "",
            "size_min": 0,
            "size_max": 0,
        }

    applied = buckets_to_apply(grouped, data)
    allowed_ids = {
        int(ins_id)
        for item in applied.values()
        for ins_id in (item.get("ids") or [])
    }
    ordered_records = [record for record in records if int(getattr(record, "id", 0) or 0) in allowed_ids]
    sizes, meta = sizes_for_strategy(len(ordered_records), strategy, data, fallback_mode=fallback_mode)
    names = unique_team_names(existing_names or [], len(sizes))
    out = OrderedDict()
    index = 0
    for pos, size in enumerate(sizes):
        members = ordered_records[index:index + size]
        index += size
        if not members:
            continue
        name = names[pos] if pos < len(names) else f"Equip {pos + 1}"
        key = json.dumps(["__strategy__", strategy, pos + 1, name], ensure_ascii=False)
        out[key] = {
            "vals_norm": [name],
            "vals_pretty": [name],
            "ids": [int(member.id) for member in members],
            "strategy_name": name,
            "strategy_index": pos + 1,
        }
    return out, {
        "strategy": strategy,
        "buckets_total": len(grouped),
        "buckets_applied": len(applied),
        "used_fallback": bool(meta.get("used_fallback")),
        "fallback_reason": str(meta.get("fallback_reason") or ""),
        "size_min": min(sizes) if sizes else 0,
        "size_max": max(sizes) if sizes else 0,
    }
