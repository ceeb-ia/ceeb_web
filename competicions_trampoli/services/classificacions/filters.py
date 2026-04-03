from ..services_classificacions_2 import (
    CLASSIFICACIO_FILTER_KEYS,
    _infer_team_mode_from_comp_aparells,
    _normalize_classificacio_equips_cfg,
    _normalize_classificacio_filters,
    _normalize_equip_assignment_source,
    _normalize_exercise_selection_scope,
    _normalize_team_mode,
)

infer_team_mode_from_comp_aparells = _infer_team_mode_from_comp_aparells
normalize_classificacio_equips_cfg = _normalize_classificacio_equips_cfg
normalize_classificacio_filters = _normalize_classificacio_filters
normalize_equip_assignment_source = _normalize_equip_assignment_source
normalize_exercise_selection_scope = _normalize_exercise_selection_scope
normalize_team_mode = _normalize_team_mode

__all__ = [
    "CLASSIFICACIO_FILTER_KEYS",
    "infer_team_mode_from_comp_aparells",
    "normalize_classificacio_equips_cfg",
    "normalize_classificacio_filters",
    "normalize_equip_assignment_source",
    "normalize_exercise_selection_scope",
    "normalize_team_mode",
]
