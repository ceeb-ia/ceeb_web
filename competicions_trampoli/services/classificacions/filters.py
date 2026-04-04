"""Classification filter and team-mode helpers."""

from ._filters_impl import (
    CLASSIFICACIO_FILTER_KEYS,
    EXERCISE_SELECTION_SCOPE_INHERIT,
    EXERCISE_SELECTION_SCOPE_PER_MEMBER,
    EXERCISE_SELECTION_SCOPE_TEAM_POOL,
    infer_team_mode_from_comp_aparells,
    normalize_classificacio_equips_cfg,
    normalize_classificacio_filters,
    normalize_equip_assignment_source,
    normalize_exercise_selection_scope,
    normalize_team_mode,
)

__all__ = [
    "CLASSIFICACIO_FILTER_KEYS",
    "EXERCISE_SELECTION_SCOPE_INHERIT",
    "EXERCISE_SELECTION_SCOPE_PER_MEMBER",
    "EXERCISE_SELECTION_SCOPE_TEAM_POOL",
    "infer_team_mode_from_comp_aparells",
    "normalize_classificacio_equips_cfg",
    "normalize_classificacio_filters",
    "normalize_equip_assignment_source",
    "normalize_exercise_selection_scope",
    "normalize_team_mode",
]
