"""Tie contract helpers for classificacions desempat serialization."""

from .context import (
    TIE_CONTRACT_DERIVED_TEAM,
    TIE_CONTRACT_NATIVE_TEAM,
    TIE_CONTRACT_PER_MEMBER,
    TIE_CONTRACT_TEAM_POOL,
    TieContext,
    resolve_tie_context,
)
from .registry import get_tie_contract, resolve_tie_contract
from .serializer_save import (
    canonicalize_desempat_item_for_persistence,
    canonicalize_desempat_items_for_persistence,
    serialize_tie_for_save,
    serialize_ties_for_save,
)
from .builder_rehydration import project_tie_for_builder_rehydration
from .legacy_projection import project_tie_legacy_projection, project_ties_legacy_projection
from .pipeline_builder import build_tie_pipeline_criterion
from .ui_projection import project_tie_ui_state, project_tie_with_ui_state
from .validation import (
    materialize_desempat_for_validation,
    strip_native_team_tie_payload,
    validate_raw_desempat_legacy_payload,
    validate_team_pool_tie_contract,
)

__all__ = [
    "TIE_CONTRACT_DERIVED_TEAM",
    "TIE_CONTRACT_NATIVE_TEAM",
    "TIE_CONTRACT_PER_MEMBER",
    "TIE_CONTRACT_TEAM_POOL",
    "TieContext",
    "build_tie_pipeline_criterion",
    "canonicalize_desempat_item_for_persistence",
    "canonicalize_desempat_items_for_persistence",
    "get_tie_contract",
    "materialize_desempat_for_validation",
    "project_tie_for_builder_rehydration",
    "project_tie_legacy_projection",
    "project_tie_ui_state",
    "project_tie_with_ui_state",
    "project_ties_legacy_projection",
    "resolve_tie_context",
    "resolve_tie_contract",
    "serialize_tie_for_save",
    "serialize_ties_for_save",
    "strip_native_team_tie_payload",
    "validate_raw_desempat_legacy_payload",
    "validate_team_pool_tie_contract",
]
