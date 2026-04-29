from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from designacions.services.assignment_feasibility import normalize_text_key

from .levels import MATCH_LEVEL_ORDER, TUTOR_LEVEL_ORDER, match_level_position, tutor_level_position


@dataclass(frozen=True)
class PhaseSpec:
    name: str
    tutor_levels: list[str] = field(default_factory=list)
    allowed_max_level_position: int | None = None
    allowed_level_labels: list[str] = field(default_factory=list)
    allow_exceptional: bool = False
    rescue_after_phase: bool = False
    max_route_size: int = 2
    top_n_routes_per_tutor: int = 20


def default_phase_specs(config: dict[str, Any] | None = None) -> list[PhaseSpec]:
    config = config or {}
    high_labels = _cfg_list(config, "phase_high_levels", list(MATCH_LEVEL_ORDER[:3]))
    medium_max = config.get("phase_medium_max_level", "PREINFANTIL")
    medium_position = match_level_position(medium_max)
    if medium_position is None:
        medium_position = match_level_position("PREINFANTIL")

    max_route_size = int(config.get("route_max_new_matches_per_phase", 2))
    top_n = int(config.get("route_top_n_per_tutor", 20))

    return [
        PhaseSpec(
            name="high",
            tutor_levels=["NIVELLA1"],
            allowed_level_labels=high_labels,
            allow_exceptional=bool(config.get("phase_high_allow_exceptional", False)),
            rescue_after_phase=True,
            max_route_size=max_route_size,
            top_n_routes_per_tutor=top_n,
        ),
        PhaseSpec(
            name="medium",
            tutor_levels=["NIVELLA1", "NIVELLB1"],
            allowed_max_level_position=medium_position,
            allow_exceptional=bool(config.get("phase_medium_allow_exceptional", False)),
            rescue_after_phase=bool(config.get("phase_medium_rescue_after_phase", False)),
            max_route_size=max_route_size,
            top_n_routes_per_tutor=top_n,
        ),
        PhaseSpec(
            name="general",
            tutor_levels=list(TUTOR_LEVEL_ORDER),
            allowed_max_level_position=None,
            allow_exceptional=bool(config.get("phase_general_allow_exceptional", True)),
            rescue_after_phase=False,
            max_route_size=max_route_size,
            top_n_routes_per_tutor=top_n,
        ),
    ]


def phase_allows_tutor(tutor: Any, phase: PhaseSpec) -> bool:
    if not phase.tutor_levels:
        return True
    tutor_level = _value(tutor, "level", "nivell", "Nivell", default="")
    tutor_pos = tutor_level_position(tutor_level)
    if tutor_pos is not None:
        allowed_positions = {tutor_level_position(level) for level in phase.tutor_levels}
        return tutor_pos in allowed_positions
    normalized_level = normalize_text_key(tutor_level)
    return normalized_level in {normalize_text_key(level) for level in phase.tutor_levels}


def phase_allows_fragment(fragment: Any, phase: PhaseSpec) -> bool:
    if not phase.allowed_level_labels and phase.allowed_max_level_position is None:
        return True
    level = _value(fragment, "level_demand", "level", "categoria", "Categoria")
    position = match_level_position(level)
    if phase.allowed_level_labels:
        normalized_level = normalize_text_key(level)
        allowed = {normalize_text_key(label) for label in phase.allowed_level_labels}
        if normalized_level in allowed:
            return True
        for label in allowed:
            if label and label in normalized_level:
                return True
        return False
    return position is not None and position <= int(phase.allowed_max_level_position)


def _cfg_list(config: dict[str, Any], key: str, default: list[str]) -> list[str]:
    value = config.get(key, default)
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    try:
        return list(value)
    except TypeError:
        return list(default)


def _value(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


__all__ = ["PhaseSpec", "default_phase_specs", "phase_allows_tutor", "phase_allows_fragment"]
