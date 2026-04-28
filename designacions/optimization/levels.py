from __future__ import annotations

from typing import Any

from designacions.services.assignment_feasibility import normalize_text_key


LEVEL_FIT_IDEAL = "ideal"
LEVEL_FIT_ACCEPTABLE = "acceptable"
LEVEL_FIT_EXCEPTIONAL = "exceptional"
LEVEL_FIT_FORBIDDEN = "forbidden"
LEVEL_FIT_UNSCORABLE = "unscorable"
FIT_IDEAL = LEVEL_FIT_IDEAL
FIT_ACCEPTABLE = LEVEL_FIT_ACCEPTABLE
FIT_EXCEPTIONAL = LEVEL_FIT_EXCEPTIONAL
FIT_FORBIDDEN = LEVEL_FIT_FORBIDDEN
FIT_UNSCORABLE = LEVEL_FIT_UNSCORABLE
FIT_LABELS = (
    FIT_IDEAL,
    FIT_ACCEPTABLE,
    FIT_EXCEPTIONAL,
    FIT_FORBIDDEN,
    FIT_UNSCORABLE,
)

TUTOR_LEVEL_ORDER = ("NIVELLA1", "NIVELLB1", "NIVELLC1", "NIVELLD1", "D")
MATCH_LEVEL_ORDER = (
    "SÈNIOR",
    "JÚNIOR",
    "JUVENIL",
    "CADET",
    "INFANTIL",
    "PREINFANTIL",
    "ALEVÍ",
    "BENJAMÍ",
    "PREBENJAMÍ",
    "MENUT",
    "INFANTIL MIXT",
    "ALEVÍ MIXT",
    "BENJAMÍ MIXT",
    "PREBENJAMÍ MIXT",
    "MENUT MIXT",
    "PREALEVÍ",
    "PREALEVÍ MIXT",
    "MENUDETS",
    "MENUDETS MIXT",
    "MENUTS",
    "MENUTS MIXT",
)


def _position(value: Any, order: tuple[str, ...]) -> int | None:
    text = normalize_text_key(value)
    if not text:
        return None
    normalized_order = [normalize_text_key(item) for item in order]
    if text in normalized_order:
        return normalized_order.index(text)
    for index, token in sorted(enumerate(normalized_order), key=lambda item: len(item[1]), reverse=True):
        if token and token in text:
            return index
    return None


def tutor_level_position(value: Any) -> int | None:
    return _position(value, TUTOR_LEVEL_ORDER)


def match_level_position(value: Any) -> int | None:
    return _position(value, MATCH_LEVEL_ORDER)


def hardest_match_level(values: list[Any] | tuple[Any, ...]) -> Any:
    ranked = []
    fallback = None
    for value in values:
        if value is None:
            continue
        try:
            if value != value:
                continue
        except Exception:
            pass
        if fallback is None:
            fallback = value
        position = match_level_position(value)
        if position is not None:
            ranked.append((position, value))
    if ranked:
        return sorted(ranked, key=lambda item: item[0])[0][1]
    return fallback


def normalized_tutor_position(value: Any) -> float | None:
    position = tutor_level_position(value)
    if position is None:
        return None
    return position / max(len(TUTOR_LEVEL_ORDER) - 1, 1)


def normalized_match_position(value: Any) -> float | None:
    position = match_level_position(value)
    if position is None:
        return None
    return position / max(len(MATCH_LEVEL_ORDER) - 1, 1)


def level_gap(tutor_level: Any, match_level: Any) -> int | None:
    tutor_pos = tutor_level_position(tutor_level)
    match_pos = match_level_position(match_level)
    if tutor_pos is None or match_pos is None:
        return None
    return tutor_pos - match_pos


def is_high_match_level(match_level: Any) -> bool:
    position = match_level_position(match_level)
    return position is not None and position <= 2


def level_fit(tutor_level: Any, match_level: Any, config: dict[str, Any] | None = None) -> str:
    config = config or {}
    gap = level_gap(tutor_level, match_level)
    match_pos = match_level_position(match_level)
    if gap is None or match_pos is None:
        if bool(config.get("strict_unknown_high_level")) and is_high_match_level(match_level):
            return LEVEL_FIT_FORBIDDEN
        return LEVEL_FIT_UNSCORABLE

    # SÈNIOR is deliberately stricter than the continuous legacy distance.
    if match_pos == 0:
        if gap <= 0:
            return LEVEL_FIT_IDEAL
        if gap == 1:
            return LEVEL_FIT_EXCEPTIONAL
        return LEVEL_FIT_FORBIDDEN

    if gap <= 0:
        return LEVEL_FIT_IDEAL
    if gap == 1:
        if is_high_match_level(match_level) or float(config.get("classification_importance", 0.0) or 0.0) >= float(
            config.get("exceptional_classification_threshold", 0.75)
        ):
            return LEVEL_FIT_EXCEPTIONAL
        return LEVEL_FIT_ACCEPTABLE
    return LEVEL_FIT_FORBIDDEN


def level_distance_cost(tutor_level: Any, match_level: Any, weight: float = 1000.0) -> float:
    tutor_pos = normalized_tutor_position(tutor_level)
    match_pos = normalized_match_position(match_level)
    if tutor_pos is None or match_pos is None:
        return 0.0
    return abs(tutor_pos - match_pos) * float(weight)


def is_level_fit_viable(fit: str, *, allow_exceptional: bool = True, allow_unscorable: bool = True) -> bool:
    if fit == LEVEL_FIT_FORBIDDEN:
        return False
    if fit == LEVEL_FIT_EXCEPTIONAL and not allow_exceptional:
        return False
    if fit == LEVEL_FIT_UNSCORABLE and not allow_unscorable:
        return False
    return True
