import hashlib
from typing import Dict, Iterable, List, Sequence, Tuple, TypeVar


T = TypeVar("T")

ORDER_MODE_MAINTAIN = "maintain"
ORDER_MODE_RANDOM = "random"
ORDER_MODE_ROTATE = "rotate"

ORDER_MODE_LABELS = {
    ORDER_MODE_MAINTAIN: "Mantenir",
    ORDER_MODE_RANDOM: "Aleatori",
    ORDER_MODE_ROTATE: "Primer passa a ultim",
}

ORDER_MODE_CHOICES = [
    ORDER_MODE_MAINTAIN,
    ORDER_MODE_RANDOM,
    ORDER_MODE_ROTATE,
]


def sanitize_order_mode(value: str) -> str:
    mode = (value or "").strip().lower()
    return mode if mode in ORDER_MODE_CHOICES else ORDER_MODE_MAINTAIN


def normalize_positive_int_list(value) -> List[int]:
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        raw_values = [value]

    out: List[int] = []
    seen = set()
    for raw in raw_values:
        if raw is None:
            continue
        if isinstance(raw, str):
            raw = raw.strip()
            if raw == "":
                continue
        try:
            num = int(raw)
        except Exception:
            continue
        if num <= 0 or num in seen:
            continue
        seen.add(num)
        out.append(num)
    return out


def get_rotacions_order_modes(competicio) -> Dict[str, str]:
    cfg = competicio.inscripcions_view or {}
    raw = cfg.get("rotacions_order_modes") or {}
    if not isinstance(raw, dict):
        return {}
    cleaned = {}
    for key, val in raw.items():
        try:
            k = str(int(key))
        except Exception:
            continue
        cleaned[k] = sanitize_order_mode(val)
    return cleaned


def set_rotacio_order_mode(competicio, franja_id: int, mode: str) -> str:
    clean_mode = sanitize_order_mode(mode)
    cfg = competicio.inscripcions_view or {}
    raw = cfg.get("rotacions_order_modes") or {}
    if not isinstance(raw, dict):
        raw = {}
    raw[str(int(franja_id))] = clean_mode
    cfg["rotacions_order_modes"] = raw
    competicio.inscripcions_view = cfg
    competicio.save(update_fields=["inscripcions_view"])
    return clean_mode


def franja_index_map(franges) -> Dict[int, int]:
    # Index 0-based following configured franja order.
    return {f.id: idx for idx, f in enumerate(franges)}


def order_pairs_for_mode(
    pairs: Sequence[Tuple[int, T]],
    mode: str,
    rotate_steps: int = 0,
    seed_prefix: str = "",
) -> List[Tuple[int, T]]:
    """
    pairs: sequence of (inscripcio_id, payload) already sorted in base order.
    """
    items = list(pairs or [])
    if len(items) <= 1:
        return items

    clean_mode = sanitize_order_mode(mode)
    if clean_mode == ORDER_MODE_MAINTAIN:
        return items

    if clean_mode == ORDER_MODE_ROTATE:
        shift = int(rotate_steps or 0) % len(items)
        if shift == 0:
            return items
        return items[shift:] + items[:shift]

    if clean_mode == ORDER_MODE_RANDOM:
        def _k(item: Tuple[int, T]) -> int:
            ins_id = item[0]
            raw = f"{seed_prefix}|{ins_id}".encode("utf-8")
            return int(hashlib.sha256(raw).hexdigest(), 16)

        return sorted(items, key=_k)

    return items


def assignacio_grups(assignacio) -> List[int]:
    groups = normalize_positive_int_list(getattr(assignacio, "grups", None))
    if groups:
        return groups
    return normalize_positive_int_list(getattr(assignacio, "grup", None))


def assignacio_grups_from_values(grups_value, grup_value) -> List[int]:
    groups = normalize_positive_int_list(grups_value)
    if groups:
        return groups
    return normalize_positive_int_list(grup_value)


def unique_ordered(values: Iterable[int]) -> List[int]:
    out: List[int] = []
    seen = set()
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out
