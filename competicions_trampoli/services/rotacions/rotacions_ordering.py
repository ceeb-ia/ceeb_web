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


def effective_rotate_steps(mode: str, base_step: int = 0) -> int:
    clean_mode = sanitize_order_mode(mode)
    step = int(base_step or 0)
    if clean_mode == ORDER_MODE_ROTATE:
        return step + 1
    return step


def rotation_unit_key(item_ids: Iterable) -> object:
    items = [item for item in list(item_ids or []) if item not in (None, "")]
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    return "unit:" + "+".join(str(item) for item in items)


def rotation_unit_label(item_ids: Iterable, label_for_item, separator: str = " + ") -> str:
    labels = []
    for item in list(item_ids or []):
        label = str(label_for_item(item) or "").strip()
        if label:
            labels.append(label)
    return separator.join(labels) if labels else "Grup"


def assignacio_grups(assignacio) -> List[int]:
    raw_links = getattr(assignacio, "grup_links", None)
    if raw_links is not None:
        if hasattr(raw_links, "all"):
            raw_links = raw_links.all()
        out = []
        seen = set()
        for link in raw_links:
            try:
                group_id = int(getattr(link, "grup_id", None))
            except Exception:
                continue
            if group_id <= 0 or group_id in seen:
                continue
            seen.add(group_id)
            out.append(group_id)
        if out:
            return out
    groups = normalize_positive_int_list(getattr(assignacio, "grups", None))
    if groups:
        return groups
    return normalize_positive_int_list(getattr(assignacio, "grup", None))


def assignacio_grups_from_values(grups_value, grup_value) -> List[int]:
    groups = normalize_positive_int_list(grups_value)
    if groups:
        return groups
    return normalize_positive_int_list(grup_value)


def assignacio_series(assignacio) -> List[int]:
    raw_links = getattr(assignacio, "serie_links", None)
    if raw_links is None:
        return []
    if hasattr(raw_links, "all"):
        raw_links = raw_links.all()
    out = []
    seen = set()
    for link in raw_links:
        try:
            serie_id = int(getattr(link, "serie_id", None))
        except Exception:
            continue
        if serie_id <= 0 or serie_id in seen:
            continue
        seen.add(serie_id)
        out.append(serie_id)
    return out


def assignacio_program_units(assignacio) -> List[int]:
    raw_links = getattr(assignacio, "program_unit_links", None)
    if raw_links is None:
        return []
    if hasattr(raw_links, "all"):
        raw_links = raw_links.all()
    out = []
    seen = set()
    for link in raw_links:
        try:
            unit_id = int(getattr(link, "program_unit_id", None))
        except Exception:
            continue
        if unit_id <= 0 or unit_id in seen:
            continue
        seen.add(unit_id)
        out.append(unit_id)
    return out


def build_group_rotation_step_map(assignacions, franja_modes=None) -> Dict[Tuple[int, int], int]:
    """
    Returns a map keyed by (group_id, franja_id) -> 0-based rotation step for
    each distinct appearance of the group in franja order.

    The step only advances for appearances whose franja order mode is rotate.
    """
    out: Dict[Tuple[int, int], int] = {}
    counters: Dict[int, int] = {}
    seen = set()
    modes = franja_modes or {}

    for assignacio in list(assignacions or []):
        try:
            franja_id = int(getattr(assignacio, "franja_id", None) or 0)
        except Exception:
            franja_id = 0
        if franja_id <= 0:
            continue

        for group_id in assignacio_grups(assignacio):
            try:
                clean_group_id = int(group_id)
            except Exception:
                continue
            if clean_group_id <= 0:
                continue

            seen_key = (clean_group_id, franja_id)
            if seen_key in seen:
                continue
            seen.add(seen_key)

            step = counters.get(clean_group_id, 0)
            out[seen_key] = step
            mode = sanitize_order_mode(modes.get(str(franja_id)))
            if mode == ORDER_MODE_ROTATE:
                counters[clean_group_id] = step + 1

    return out


def build_series_rotation_step_map(assignacions, franja_modes=None) -> Dict[Tuple[int, int], int]:
    out: Dict[Tuple[int, int], int] = {}
    counters: Dict[int, int] = {}
    seen = set()
    modes = franja_modes or {}

    for assignacio in list(assignacions or []):
        try:
            franja_id = int(getattr(assignacio, "franja_id", None) or 0)
        except Exception:
            franja_id = 0
        if franja_id <= 0:
            continue

        for serie_id in assignacio_series(assignacio):
            seen_key = (serie_id, franja_id)
            if seen_key in seen:
                continue
            seen.add(seen_key)

            step = counters.get(serie_id, 0)
            out[seen_key] = step
            mode = sanitize_order_mode(modes.get(str(franja_id)))
            if mode == ORDER_MODE_ROTATE:
                counters[serie_id] = step + 1

    return out


def build_rotation_unit_step_map(assignacions, unit_key_for_assignacio, franja_modes=None) -> Dict[Tuple[object, int], int]:
    """
    Returns a map keyed by (unit_key, franja_id) -> 0-based rotation step.

    A unit can be a single group/series or a whole rotation cell containing
    several groups. This lets order modes operate on the same competitive unit
    shown to judges instead of advancing each group independently.
    """
    out: Dict[Tuple[object, int], int] = {}
    counters: Dict[object, int] = {}
    seen = set()
    modes = franja_modes or {}

    for assignacio in list(assignacions or []):
        try:
            franja_id = int(getattr(assignacio, "franja_id", None) or 0)
        except Exception:
            franja_id = 0
        if franja_id <= 0:
            continue

        unit_key = unit_key_for_assignacio(assignacio)
        if unit_key in (None, ""):
            continue

        seen_key = (unit_key, franja_id)
        if seen_key in seen:
            continue
        seen.add(seen_key)

        step = counters.get(unit_key, 0)
        out[seen_key] = step
        mode = sanitize_order_mode(modes.get(str(franja_id)))
        if mode == ORDER_MODE_ROTATE:
            counters[unit_key] = step + 1

    return out


def unique_ordered(values: Iterable[int]) -> List[int]:
    out: List[int] = []
    seen = set()
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out
