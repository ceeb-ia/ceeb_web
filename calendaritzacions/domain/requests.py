import math
from typing import Any, Mapping


def request_type(raw_value: Any) -> str:
    text = str(raw_value).strip().lower()
    if text == "casa":
        return "casa"
    if text == "fora":
        return "fora"
    try:
        value = int(float(raw_value))
        if 1 <= value <= 8:
            return "explicit"
    except Exception:
        pass
    return "none"


def request_display_code(raw_value: Any) -> str:
    req_type = request_type(raw_value)
    if req_type == "casa":
        return "CASA"
    if req_type == "fora":
        return "FORA"
    if req_type == "explicit":
        try:
            return str(int(float(raw_value)))
        except Exception:
            return ""
    return ""


def expected_seed(raw_value: Any, equip_id: Any, mapping: Mapping[Any, Any]) -> int | float:
    req_type = request_type(raw_value)
    if req_type == "explicit":
        try:
            return int(float(raw_value))
        except Exception:
            return math.nan
    if req_type in {"casa", "fora"}:
        mapped = mapping.get(equip_id)
        if mapped is None:
            return math.nan
        return int(mapped)
    return math.nan

