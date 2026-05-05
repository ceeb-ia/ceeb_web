"""Backward-compatible facade for the legacy assignment engine.

The implementation has moved to ``calendaritzacions.engine.legacy`` modules.
This module preserves the historical import surface used by ``main.py`` and
existing scripts/tests.
"""

from collections import Counter, defaultdict
import hashlib
from math import log2
import sys
import unicodedata

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from calendaritzacions.domain.phases import PRIMERA_FASE as primera_fase
from calendaritzacions.engine.legacy.costs import (
    build_disposicions,
    cost_calc,
    day_entropy,
    level_entropy,
    position_entropy,
    recalcular_costos_base_sense_factors,
)
from calendaritzacions.engine.legacy.fairness import (
    actualitzar_costos_entitat,
    rebuild_entitat_factor,
)
from calendaritzacions.engine.legacy.group_sizing import crear_grups_equilibrats
from calendaritzacions.engine.legacy.local_search import (
    homogeneitzar_costs,
    homogeneitzar_nivell,
)
from calendaritzacions.engine.legacy.matrix import build_cost_matrix
from calendaritzacions.engine.legacy.repairs import (
    build_groups_from_assignment,
    check_feasibility_entity,
    entity_conflicts,
    repair_by_hungarian_per_position,
)
from calendaritzacions.engine.legacy.service import assignar_grups_hungares
from calendaritzacions.engine.legacy.slots import add_dummies, build_slots
from calendaritzacions.engine.legacy.utils import (
    normalize_seed_value,
    obtenir_entitat,
    parse_int,
)

SCIPY_OK = True

__all__ = [
    "SCIPY_OK",
    "Counter",
    "actualitzar_costos_entitat",
    "add_dummies",
    "assignar_grups_hungares",
    "build_cost_matrix",
    "build_disposicions",
    "build_groups_from_assignment",
    "build_slots",
    "check_feasibility_entity",
    "cost_calc",
    "crear_grups_equilibrats",
    "day_entropy",
    "defaultdict",
    "entity_conflicts",
    "hashlib",
    "homogeneitzar_costs",
    "homogeneitzar_nivell",
    "level_entropy",
    "linear_sum_assignment",
    "log2",
    "normalize_seed_value",
    "np",
    "obtenir_entitat",
    "pd",
    "parse_int",
    "position_entropy",
    "primera_fase",
    "rebuild_entitat_factor",
    "recalcular_costos_base_sense_factors",
    "repair_by_hungarian_per_position",
    "sys",
    "unicodedata",
]
