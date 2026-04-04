"""Compatibility boundary for classification filter and team-mode helpers."""

from ..services_classificacions_2 import CLASSIFICACIO_FILTER_KEYS as _CLASSIFICACIO_FILTER_KEYS
from ..services_classificacions_2 import EXERCISE_SELECTION_SCOPE_INHERIT as _EXERCISE_SELECTION_SCOPE_INHERIT
from ..services_classificacions_2 import EXERCISE_SELECTION_SCOPE_PER_MEMBER as _EXERCISE_SELECTION_SCOPE_PER_MEMBER
from ..services_classificacions_2 import EXERCISE_SELECTION_SCOPE_TEAM_POOL as _EXERCISE_SELECTION_SCOPE_TEAM_POOL
from ..services_classificacions_2 import _infer_team_mode_from_comp_aparells as _infer_team_mode_from_comp_aparells
from ..services_classificacions_2 import _normalize_classificacio_equips_cfg as _normalize_classificacio_equips_cfg
from ..services_classificacions_2 import _normalize_classificacio_filters as _normalize_classificacio_filters
from ..services_classificacions_2 import _normalize_equip_assignment_source as _normalize_equip_assignment_source
from ..services_classificacions_2 import _normalize_exercise_selection_scope as _normalize_exercise_selection_scope
from ..services_classificacions_2 import _normalize_team_mode as _normalize_team_mode


CLASSIFICACIO_FILTER_KEYS = _CLASSIFICACIO_FILTER_KEYS
EXERCISE_SELECTION_SCOPE_INHERIT = _EXERCISE_SELECTION_SCOPE_INHERIT
EXERCISE_SELECTION_SCOPE_PER_MEMBER = _EXERCISE_SELECTION_SCOPE_PER_MEMBER
EXERCISE_SELECTION_SCOPE_TEAM_POOL = _EXERCISE_SELECTION_SCOPE_TEAM_POOL


def infer_team_mode_from_comp_aparells(*args, **kwargs):
    return _infer_team_mode_from_comp_aparells(*args, **kwargs)


def normalize_classificacio_equips_cfg(*args, **kwargs):
    return _normalize_classificacio_equips_cfg(*args, **kwargs)


def normalize_classificacio_filters(*args, **kwargs):
    return _normalize_classificacio_filters(*args, **kwargs)


def normalize_equip_assignment_source(*args, **kwargs):
    return _normalize_equip_assignment_source(*args, **kwargs)


def normalize_exercise_selection_scope(*args, **kwargs):
    return _normalize_exercise_selection_scope(*args, **kwargs)


def normalize_team_mode(*args, **kwargs):
    return _normalize_team_mode(*args, **kwargs)

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
