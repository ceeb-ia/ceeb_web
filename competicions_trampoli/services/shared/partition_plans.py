import math


CREATION_STRATEGIES = {
    "per_bucket",
    "count",
    "size_fixed",
    "size_balanced",
    "range_balanced",
    "count_with_range",
}

FALLBACK_MODES = {"all_filtered", "strict", "adjust_k", "ignore_range"}


def parse_fallback_mode(raw):
    mode = str(raw or "all_filtered").strip().lower()
    return mode if mode in FALLBACK_MODES else "all_filtered"


def normalize_creation_strategy(raw, default="per_bucket"):
    strategy = str(raw or default).strip().lower()
    return strategy if strategy in CREATION_STRATEGIES else default


def balanced_sizes(total, count):
    if total <= 0 or count <= 0:
        return []
    count = min(count, total)
    base = total // count
    remainder = total % count
    return [base + (1 if index < remainder else 0) for index in range(count)]


def fixed_sizes(total, size):
    if total <= 0 or size <= 0:
        return []
    out = []
    remaining = total
    while remaining > 0:
        take = size if remaining >= size else remaining
        out.append(take)
        remaining -= take
    return out


def resolve_count_for_range(total, min_size, max_size, preferred_count=None, fallback_mode="strict"):
    if total <= 0 or min_size <= 0 or max_size <= 0 or min_size > max_size:
        return None, {"used_fallback": True, "fallback_reason": "range_infeasible"}
    count_min = math.ceil(total / max_size)
    count_max = math.floor(total / min_size)
    meta = {"used_fallback": False, "fallback_reason": ""}
    feasible = count_min <= count_max and count_max >= 1
    if feasible:
        if preferred_count is None:
            count_target = int(round(total / ((min_size + max_size) / 2.0)))
            return max(count_min, min(count_target, count_max)), meta
        count = int(preferred_count)
        if count < count_min or count > count_max:
            if fallback_mode == "strict":
                return None, {"used_fallback": True, "fallback_reason": "k_out_of_range"}
            if fallback_mode in ("adjust_k", "all_filtered"):
                meta["used_fallback"] = True
                meta["fallback_reason"] = "k_adjusted_to_feasible_range"
                count = max(count_min, min(count, count_max))
            elif fallback_mode == "ignore_range":
                meta["used_fallback"] = True
                meta["fallback_reason"] = "range_ignored_for_k"
                count = max(1, min(count, max(1, total)))
        return count, meta
    if fallback_mode == "strict":
        return None, {"used_fallback": True, "fallback_reason": "range_infeasible"}
    count = max(1, min(int(preferred_count) if preferred_count is not None else math.ceil(total / max_size), max(1, total)))
    return count, {"used_fallback": True, "fallback_reason": "range_infeasible_auto_k"}


def int_payload_value(payload, *keys, default=0):
    data = payload if isinstance(payload, dict) else {}
    for key in keys:
        raw = data.get(key)
        if raw in (None, ""):
            continue
        try:
            return int(raw)
        except Exception:
            return default
    return default


def sizes_for_strategy(total, strategy, payload=None, fallback_mode="strict"):
    data = payload if isinstance(payload, dict) else {}
    strategy = normalize_creation_strategy(strategy)
    if strategy == "count":
        count = int_payload_value(data, "team_count", "group_count")
        if count < 1:
            raise ValueError("count invalid")
        return balanced_sizes(total, count), {"used_fallback": False, "fallback_reason": ""}
    if strategy in ("size_fixed", "size_balanced"):
        size = int_payload_value(data, "team_size", "group_size")
        if size < 2:
            raise ValueError("size invalid")
        if strategy == "size_fixed":
            return fixed_sizes(total, size), {"used_fallback": False, "fallback_reason": ""}
        return balanced_sizes(total, math.ceil(total / size)), {"used_fallback": False, "fallback_reason": ""}
    if strategy in ("range_balanced", "count_with_range"):
        min_size = int_payload_value(data, "min_size")
        max_size = int_payload_value(data, "max_size")
        if min_size <= 0 or max_size <= 0 or min_size > max_size:
            raise ValueError("min_size/max_size invalid")
        preferred_count = None
        if strategy == "count_with_range":
            preferred_count = int_payload_value(data, "team_count", "group_count")
            if preferred_count < 1:
                raise ValueError("count invalid")
        count, meta = resolve_count_for_range(
            total,
            min_size,
            max_size,
            preferred_count=preferred_count,
            fallback_mode=parse_fallback_mode(fallback_mode),
        )
        if count is None:
            raise ValueError("range invalid")
        return balanced_sizes(total, count), meta
    return [], {"used_fallback": False, "fallback_reason": ""}
