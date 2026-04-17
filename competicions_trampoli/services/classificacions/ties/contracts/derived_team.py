from copy import deepcopy

from ...filters import normalize_team_mode
from ...pipeline_runtime import PIPELINE_VERSION
from .base import TieContractBase, compact_pipeline_for_save
from .team_pool import TEAM_POOL_TIE_CONTRACT


def _is_derived_team_context(context):
    return normalize_team_mode(getattr(context, "team_mode", "")) == "derived_from_individual"


class DerivedTeamTieContract(TieContractBase):
    """Pipeline-first contract for team ties derived from individual results.

    The contract keeps participant-level configuration available for derived
    teams, but falls back to the stricter team_pool rules whenever the resolved
    context points there. The surrounding save path still decides whether the
    exercise_selection_scope mirror is persisted, so this contract only keeps it
    alive when the context is really a derived team.
    """

    name = "derived_team"
    removed_pipeline_keys = ()

    def sanitize_pipeline_for_save(self, pipeline, context):
        if getattr(context, "is_team_pool", False) or getattr(context, "is_team_pool_scope", False):
            return TEAM_POOL_TIE_CONTRACT.sanitize_pipeline_for_save(pipeline, context)

        out = compact_pipeline_for_save(pipeline)
        if not _is_derived_team_context(context):
            out.pop("participants", None)
            out.pop("agregacio_participants", None)
        return out

    def sanitize_item_for_save(self, item, context):
        out = deepcopy(item if isinstance(item, dict) else {})
        out["pipeline"] = self.sanitize_pipeline_for_save(out.get("pipeline"), context)
        out["pipeline_version"] = PIPELINE_VERSION

        pipeline = out.get("pipeline")
        if isinstance(pipeline, dict) and not _is_derived_team_context(context):
            pipeline.pop("exercise_selection_scope", None)
        return out


DERIVED_TEAM_TIE_CONTRACT = DerivedTeamTieContract()
