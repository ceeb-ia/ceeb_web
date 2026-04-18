from dataclasses import dataclass

from ..filters import (
    EXERCISE_SELECTION_SCOPE_PER_MEMBER,
    EXERCISE_SELECTION_SCOPE_TEAM_POOL,
    normalize_exercise_selection_scope,
    normalize_team_mode,
)
from .pipeline_builder import TIE_INPUT_SOURCE_RAW_EXERCISES, normalize_tie_input_source


TIE_CONTRACT_PER_MEMBER = "per_member"
TIE_CONTRACT_TEAM_POOL = "team_pool"
TIE_CONTRACT_DERIVED_TEAM = "derived_team"
TIE_CONTRACT_NATIVE_TEAM = "native_team"


@dataclass(frozen=True)
class TieContext:
    tipus: str = "individual"
    team_mode: str = ""
    exercise_selection_scope: str = EXERCISE_SELECTION_SCOPE_PER_MEMBER
    input_source_mode: str = TIE_INPUT_SOURCE_RAW_EXERCISES
    contract_name: str = TIE_CONTRACT_PER_MEMBER
    is_team: bool = False
    is_derived_team: bool = False
    is_native_team: bool = False

    @property
    def is_team_pool(self):
        return self.contract_name == TIE_CONTRACT_TEAM_POOL

    @property
    def is_per_member(self):
        return self.contract_name == TIE_CONTRACT_PER_MEMBER

    @property
    def is_team_pool_scope(self):
        return self.exercise_selection_scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL


def _extract_exercise_selection_scope(tie, main_pipeline=None):
    item = tie if isinstance(tie, dict) else {}
    pipeline = item.get("pipeline") if isinstance(item.get("pipeline"), dict) else {}
    raw_scope = pipeline.get("exercise_selection_scope")
    if raw_scope is None:
        raw_scope = item.get("exercise_selection_scope")
    if raw_scope is None and isinstance(main_pipeline, dict):
        raw_scope = main_pipeline.get("exercise_selection_scope")
    scope = normalize_exercise_selection_scope(raw_scope, allow_inherit=True)
    if scope == "hereta":
        scope = EXERCISE_SELECTION_SCOPE_PER_MEMBER
    return scope or EXERCISE_SELECTION_SCOPE_PER_MEMBER


def _extract_input_source_mode(tie, main_pipeline=None):
    item = tie if isinstance(tie, dict) else {}
    pipeline = item.get("pipeline") if isinstance(item.get("pipeline"), dict) else {}
    raw_input_source = pipeline.get("input_source")
    if raw_input_source is None:
        raw_input_source = item.get("input_source")
    fallback_input_source = None
    if isinstance(main_pipeline, dict):
        fallback_input_source = main_pipeline.get("input_source")
    return normalize_tie_input_source(raw_input_source, fallback=fallback_input_source).get("mode") or TIE_INPUT_SOURCE_RAW_EXERCISES


def resolve_tie_context(tie, *, tipus="individual", team_mode="", main_pipeline=None):
    tipus_norm = str(tipus or "").strip().lower()
    team_mode_norm = normalize_team_mode(team_mode)
    exercise_selection_scope = _extract_exercise_selection_scope(tie, main_pipeline=main_pipeline)
    input_source_mode = _extract_input_source_mode(tie, main_pipeline=main_pipeline)
    if team_mode_norm == "native_team":
        contract_name = TIE_CONTRACT_NATIVE_TEAM
    elif team_mode_norm == "derived_from_individual":
        contract_name = TIE_CONTRACT_DERIVED_TEAM
    else:
        contract_name = (
            TIE_CONTRACT_TEAM_POOL
            if exercise_selection_scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL
            else TIE_CONTRACT_PER_MEMBER
        )
    return TieContext(
        tipus=tipus_norm or "individual",
        team_mode=team_mode_norm,
        exercise_selection_scope=exercise_selection_scope,
        input_source_mode=input_source_mode,
        contract_name=contract_name,
        is_team=tipus_norm == "equips",
        is_derived_team=tipus_norm == "equips" and team_mode_norm == "derived_from_individual",
        is_native_team=tipus_norm == "equips" and team_mode_norm == "native_team",
    )
