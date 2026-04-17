from copy import deepcopy

from ...filters import normalize_team_mode
from ...pipeline_runtime import PIPELINE_VERSION
from .base import TieContractBase, compact_pipeline_for_save


def _is_native_team_context(context):
    return normalize_team_mode(getattr(context, "team_mode", "")) == "native_team"


class NativeTeamTieContract(TieContractBase):
    """Pipeline-first contract for native team ties.

    Native teams do not carry participant-derived configuration in the saved
    tie payload. That means participants and their aggregation are always
    stripped from the canonical pipeline, and the editable exercise selection
    mirror is only kept when the caller is explicitly working with a derived
    team context.
    """

    name = "native_team"
    removed_pipeline_keys = ()

    def sanitize_pipeline_for_save(self, pipeline, context):
        out = compact_pipeline_for_save(pipeline)
        if _is_native_team_context(context):
            out.pop("participants", None)
            out.pop("agregacio_participants", None)
        return out

    def sanitize_item_for_save(self, item, context):
        out = deepcopy(item if isinstance(item, dict) else {})
        out["pipeline"] = self.sanitize_pipeline_for_save(out.get("pipeline"), context)
        out["pipeline_version"] = PIPELINE_VERSION

        pipeline = out.get("pipeline")
        if isinstance(pipeline, dict):
            pipeline.pop("exercise_selection_scope", None)
        return out


NATIVE_TEAM_TIE_CONTRACT = NativeTeamTieContract()
