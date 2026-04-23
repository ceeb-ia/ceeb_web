from collections import defaultdict
from decimal import Decimal


def _to_float(v):
    try:
        if v is None or v == "":
            return 0.0
        if isinstance(v, Decimal):
            return float(v)
        return float(v)
    except Exception:
        return 0.0


def _pick_exercicis(vals, mode: str, best_n: int):
    """
    vals: llista de valors (1 per exercici) ja agregats per exercici
    """
    xs = [_to_float(x) for x in (vals or [])]
    if not xs:
        return []

    m = (mode or "tots").lower().strip()
    if m == "tots":
        return xs
    if m == "millor_1":
        return [max(xs)]
    if m == "millor_n":
        n = max(1, int(best_n or 1))
        return sorted(xs, reverse=True)[:n]
    if m == "pitjor_1":
        return [min(xs)]
    if m == "pitjor_n":
        n = max(1, int(best_n or 1))
        return sorted(xs)[:n]

    # fallback
    return xs


def _pick_exercicis_rows(
    rows,
    mode: str,
    best_n: int,
    index=None,
    ids=None,
    max_per_participant=0,
    participant_key="inscripcio_id",
):
    """
    rows: [{"idx": int, "value": float, ...}, ...]
    retorna les files seleccionades (mantenint metadades).
    """
    xs = []
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        try:
            idx = int(r.get("idx"))
        except Exception:
            continue
        item = dict(r)
        item["idx"] = idx
        item["value"] = _to_float(r.get("value"))
        xs.append(item)
    if not xs:
        return []

    m = (mode or "tots").lower().strip()

    try:
        max_pp = int(max_per_participant or 0)
    except Exception:
        max_pp = 0
    max_pp = max(0, max_pp)

    def _participant_id_for_row(row):
        pid = row.get(participant_key)
        if pid in (None, ""):
            return "__single__"
        return str(pid)

    def _take_with_cap(rows_iter, limit=None):
        if max_pp <= 0:
            if limit is None:
                return list(rows_iter)
            return list(rows_iter)[:limit]

        counts = defaultdict(int)
        out = []
        for r in rows_iter:
            pid = _participant_id_for_row(r)
            if counts[pid] >= max_pp:
                continue
            counts[pid] += 1
            out.append(r)
            if limit is not None and len(out) >= limit:
                break
        return out

    if m == "tots":
        return _take_with_cap(xs)

    if m == "millor_1":
        ordered = sorted(xs, key=lambda r: (-_to_float(r.get("value")), r.get("idx", 0)))
        return _take_with_cap(ordered, limit=1)

    if m == "millor_n":
        n = max(1, int(best_n or 1))
        ordered = sorted(xs, key=lambda r: (-_to_float(r.get("value")), r.get("idx", 0)))
        return _take_with_cap(ordered, limit=n)

    if m == "pitjor_1":
        ordered = sorted(xs, key=lambda r: (_to_float(r.get("value")), r.get("idx", 0)))
        return _take_with_cap(ordered, limit=1)

    if m == "pitjor_n":
        n = max(1, int(best_n or 1))
        ordered = sorted(xs, key=lambda r: (_to_float(r.get("value")), r.get("idx", 0)))
        return _take_with_cap(ordered, limit=n)

    if m == "primer":
        first_idx = min(r.get("idx", 0) for r in xs)
        for r in xs:
            if r.get("idx") == first_idx:
                return [r]
        return []

    if m == "ultim":
        last_idx = max(r.get("idx", 0) for r in xs)
        for r in xs:
            if r.get("idx") == last_idx:
                return [r]
        return []

    if m == "index":
        try:
            idx = int(index or 1)
        except Exception:
            idx = 1
        for r in xs:
            if r.get("idx") == idx:
                return [r]
        return []

    if m == "llista":
        wanted = set()
        for x in (ids or []):
            try:
                iv = int(x)
            except Exception:
                continue
            if iv > 0:
                wanted.add(iv)
        return _take_with_cap([r for r in xs if r.get("idx") in wanted])

    return _take_with_cap(xs)


def _pick_exercicis_tuples(
    ex_vals,
    mode: str,
    best_n: int,
    index=None,
    ids=None,
    max_per_participant=0,
    participant_key="inscripcio_id",
):
    """
    ex_vals: [(ex_idx, value), ...]
    retorna: [values...]
    """
    rows = []
    for item in (ex_vals or []):
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            idx = int(item[0])
        except Exception:
            continue
        rows.append({"idx": idx, "value": _to_float(item[1])})

    picked = _pick_exercicis_rows(
        rows,
        mode,
        best_n,
        index=index,
        ids=ids,
        max_per_participant=max_per_participant,
        participant_key=participant_key,
    )
    return [_to_float(r.get("value")) for r in picked]


def _normalize_exercicis_cfg(raw_cfg, fallback=None):
    fb = fallback or {}
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}

    mode = str(cfg.get("mode") or fb.get("mode") or "tots").lower().strip()
    allowed_modes = ("tots", "millor_1", "millor_n", "pitjor_1", "pitjor_n", "primer", "ultim", "index", "llista")
    if mode not in allowed_modes:
        mode = str(fb.get("mode") or "tots").lower().strip()
        if mode not in allowed_modes:
            mode = "tots"

    try:
        best_n = int(cfg.get("best_n", fb.get("best_n", 1)))
    except Exception:
        best_n = 1
    best_n = max(1, best_n)

    try:
        index = int(cfg.get("index", fb.get("index", 1)))
    except Exception:
        index = 1
    index = max(1, index)

    try:
        max_per_participant = int(cfg.get("max_per_participant", fb.get("max_per_participant", 0)))
    except Exception:
        max_per_participant = 0
    max_per_participant = max(0, max_per_participant)

    ids_raw = cfg.get("ids", fb.get("ids", []))
    ids = []
    if isinstance(ids_raw, str):
        parts = [x.strip() for x in ids_raw.split(",") if x.strip()]
        for p in parts:
            try:
                iv = int(p)
            except Exception:
                continue
            if iv > 0:
                ids.append(iv)
    elif isinstance(ids_raw, (list, tuple)):
        for x in ids_raw:
            try:
                iv = int(x)
            except Exception:
                continue
            if iv > 0:
                ids.append(iv)

    return {
        "mode": mode,
        "best_n": best_n,
        "index": index,
        "ids": ids,
        "max_per_participant": max_per_participant,
    }


def _normalize_candidate_source_mode(raw_mode):
    mode = str(raw_mode or "raw_exercise").lower().strip()
    if mode in ("raw_exercise", "participant_aggregate", "team_aggregate"):
        return mode
    return "raw_exercise"


def _normalize_candidate_source_cfg(raw_cfg, fallback=None):
    fb = fallback or {}
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    ex_cfg = _normalize_exercicis_cfg(cfg, fallback=fb)
    agg = str(cfg.get("agregacio_exercicis", fb.get("agregacio_exercicis", "sum")) or "sum").lower().strip()
    if agg not in ("sum", "avg", "median", "max", "min"):
        agg = str(fb.get("agregacio_exercicis") or "sum").lower().strip()
        if agg not in ("sum", "avg", "median", "max", "min"):
            agg = "sum"
    ex_cfg.pop("max_per_participant", None)
    ex_cfg["agregacio_exercicis"] = agg
    return ex_cfg


def _normalize_field_mode(raw_mode):
    mode = str(raw_mode or "comu").strip().lower()
    if mode not in {"comu", "per_exercici"}:
        mode = "comu"
    return mode


def _normalize_optional_agg(raw_agg):
    agg = str(raw_agg or "").strip().lower()
    return agg if agg in {"sum", "avg", "median", "max", "min"} else ""


def _pick_participants(vals, mode: str, n: int):
    xs = [_to_float(x) for x in (vals or [])]
    if not xs:
        return []

    m = (mode or "tots").lower().strip()
    if m in ("hereta", "tots"):
        return xs
    if m == "millor_1":
        return [max(xs)]
    if m == "millor_n":
        k = max(1, int(n or 1))
        return sorted(xs, reverse=True)[:k]
    if m == "pitjor_1":
        return [min(xs)]
    if m == "pitjor_n":
        k = max(1, int(n or 1))
        return sorted(xs)[:k]
    return xs


def _normalize_participants_cfg(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    mode = str(cfg.get("mode") or "tots").strip().lower()
    if mode not in {"tots", "millor_1", "millor_n", "pitjor_1", "pitjor_n"}:
        mode = "tots"
    try:
        n_value = max(1, int(cfg.get("n") or cfg.get("best_n") or 1))
    except Exception:
        n_value = 1
    out = {"mode": mode}
    if mode in {"millor_n", "pitjor_n"}:
        out["n"] = n_value
    return out


__all__ = [
    "_normalize_candidate_source_cfg",
    "_normalize_candidate_source_mode",
    "_normalize_exercicis_cfg",
    "_normalize_field_mode",
    "_normalize_optional_agg",
    "_normalize_participants_cfg",
    "_pick_exercicis",
    "_pick_exercicis_rows",
    "_pick_exercicis_tuples",
    "_pick_participants",
]
