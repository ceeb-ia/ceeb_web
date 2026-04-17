from dataclasses import dataclass

from ..filters import (
    EXERCISE_SELECTION_SCOPE_PER_MEMBER,
    EXERCISE_SELECTION_SCOPE_TEAM_POOL,
    normalize_exercise_selection_scope,
    normalize_team_mode,
)


TIE_CONTRACT_PER_MEMBER = "per_member"
TIE_CONTRACT_TEAM_POOL = "team_pool"


@dataclass(frozen=True)
class TieContext:
    tipus: str = "individual"
    team_mode: str = ""
    exercise_selection_scope: str = EXERCISE_SELECTION_SCOPE_PER_MEMBER
    contract_name: str = TIE_CONTRACT_PER_MEMBER
    is_team: bool = False
    is_derived_team: bool = False

    @property
    def is_team_pool(self):
        return self.contract_name == TIE_CONTRACT_TEAM_POOL

    @property
    def is_per_member(self):
        return self.contract_name == TIE_CONTRACT_PER_MEMBER


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


def resolve_tie_context(tie, *, tipus="individual", team_mode="", main_pipeline=None):
    tipus_norm = str(tipus or "").strip().lower()
    team_mode_norm = normalize_team_mode(team_mode)
    exercise_selection_scope = _extract_exercise_selection_scope(tie, main_pipeline=main_pipeline)
    contract_name = (
        TIE_CONTRACT_TEAM_POOL
        if exercise_selection_scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL
        else TIE_CONTRACT_PER_MEMBER
    )
    return TieContext(
        tipus=tipus_norm or "individual",
        team_mode=team_mode_norm,
        exercise_selection_scope=exercise_selection_scope,
        contract_name=contract_name,
        is_team=tipus_norm == "equips",
        is_derived_team=tipus_norm == "equips" and team_mode_norm == "derived_from_individual",
    )
