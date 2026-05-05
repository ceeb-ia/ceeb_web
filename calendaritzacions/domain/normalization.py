import math
from typing import Any


NAN = math.nan


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(math.isnan(value))
    except (TypeError, ValueError):
        return False


def parse_int(x: Any, default: Any = NAN) -> Any:
    try:
        if _is_missing(x):
            return default
        value = float(x)
        if value.is_integer():
            return int(value)
        return default
    except Exception:
        return default


def normalize_seed_value(x: Any) -> Any:
    text = str(x).strip().lower()
    if text in ["casa", "fora"]:
        return text
    return parse_int(x, default=NAN)

