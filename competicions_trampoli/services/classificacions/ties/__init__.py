"""Tie contract helpers for classificacions desempat serialization."""

from .context import (
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
from .validation import validate_team_pool_tie_contract

__all__ = [
    "TIE_CONTRACT_PER_MEMBER",
    "TIE_CONTRACT_TEAM_POOL",
    "TieContext",
    "canonicalize_desempat_item_for_persistence",
    "canonicalize_desempat_items_for_persistence",
    "get_tie_contract",
    "resolve_tie_context",
    "resolve_tie_contract",
    "serialize_tie_for_save",
    "serialize_ties_for_save",
    "validate_team_pool_tie_contract",
]
