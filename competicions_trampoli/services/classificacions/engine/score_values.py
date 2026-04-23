from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from ....models.scoring import ScoreEntry


logger = logging.getLogger(__name__)


def _to_float(v):
    try:
        if v is None or v == "":
            return 0.0
        if isinstance(v, Decimal):
            return float(v)
        return float(v)
    except Exception:
        return 0.0


def _try_strict_float(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def _numeric_scalar_or_1x1(v):
    """
    Accepta escalar numeric o estructura 1x1 (p.ex. [[7.5]] o [7.5]).
    Retorna float o None si no es puntuable com a escalar.
    """
    base = _try_strict_float(v)
    if base is not None:
        return base

    if not isinstance(v, list) or len(v) != 1:
        return None

    inner = v[0]
    if isinstance(inner, list):
        if len(inner) != 1:
            return None
        return _try_strict_float(inner[0])

    return _try_strict_float(inner)


def _field_value_from_entry(entry: ScoreEntry, code: str):
    c = (code or "").strip()
    if not c:
        return None

    if c.lower() == "total":
        return entry.total

    out = entry.outputs or {}
    if isinstance(out, dict) and c in out:
        return out.get(c)

    ins = entry.inputs or {}
    if isinstance(ins, dict) and c in ins:
        return ins.get(c)

    if isinstance(out, dict):
        if c == "TOTAL" and "TOTAL" in out:
            return out.get("TOTAL")
        if c == "total" and "total" in out:
            return out.get("total")

    return None


def _get_score_field(entry: ScoreEntry, code: str) -> float:
    raw = _field_value_from_entry(entry, code)
    if raw is None:
        return 0.0

    num = _numeric_scalar_or_1x1(raw)
    if num is not None:
        return num

    logger.warning(
        "Classificacio: camp no puntuable (escalar o 1x1). "
        "entry_id=%s inscripcio_id=%s comp_aparell_id=%s camp=%s tipus=%s",
        getattr(entry, "id", None),
        getattr(entry, "inscripcio_id", None),
        getattr(entry, "comp_aparell_id", None),
        (code or "").strip(),
        type(raw).__name__,
    )
    return 0.0


def _median(vals):
    xs = sorted([_to_float(x) for x in (vals or [])])
    n = len(xs)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return float(xs[mid])
    return float((xs[mid - 1] + xs[mid]) / 2.0)


def _apply_simple_agg(vals, mode: str):
    vals = [_to_float(x) for x in (vals or [])]
    if not vals:
        return 0.0
    m = (mode or "sum").lower().strip()
    if m == "sum":
        return float(sum(vals))
    if m == "avg":
        return float(sum(vals) / len(vals))
    if m == "max":
        return float(max(vals))
    if m == "min":
        return float(min(vals))
    if m == "median":
        return float(_median(vals))
    return float(sum(vals))


__all__ = [
    "_apply_simple_agg",
    "_field_value_from_entry",
    "_get_score_field",
    "_median",
    "_numeric_scalar_or_1x1",
    "_to_float",
    "_try_strict_float",
]
