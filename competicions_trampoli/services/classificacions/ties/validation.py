"""Contract-specific validation helpers for desempat items."""

from ..filters import (
    EXERCISE_SELECTION_SCOPE_INHERIT,
    EXERCISE_SELECTION_SCOPE_PER_MEMBER,
    EXERCISE_SELECTION_SCOPE_TEAM_POOL,
    normalize_exercise_selection_scope,
)


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _has_payload(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return value not in ({}, [])


def _has_key(container, key):
    return isinstance(container, dict) and key in container


def _effective_tie_scope(tie, *, main_scope=None):
    tie = tie if isinstance(tie, dict) else {}
    pipeline = _as_dict(tie.get("pipeline"))
    scope = _as_dict(tie.get("scope"))

    raw_scope = pipeline.get("exercise_selection_scope")
    if raw_scope in (None, ""):
        raw_scope = tie.get("exercise_selection_scope")
    if raw_scope in (None, ""):
        raw_scope = scope.get("exercise_selection_scope")

    tie_scope = normalize_exercise_selection_scope(raw_scope, allow_inherit=True)
    if tie_scope == EXERCISE_SELECTION_SCOPE_INHERIT:
        return main_scope or EXERCISE_SELECTION_SCOPE_PER_MEMBER
    return tie_scope or (main_scope or EXERCISE_SELECTION_SCOPE_PER_MEMBER)


def validate_team_pool_tie_contract(tie, *, idx=0, main_scope=None):
    """Validate the team_pool contract for a single desempat item.

    Returns:
        list[str] if the tie is team_pool and has contract violations.
        None if the tie does not resolve to team_pool.
    """

    tie = tie if isinstance(tie, dict) else {}
    effective_scope = _effective_tie_scope(tie, main_scope=main_scope)
    if effective_scope != EXERCISE_SELECTION_SCOPE_TEAM_POOL:
        return None

    errors = []
    pipeline = _as_dict(tie.get("pipeline"))
    scope = _as_dict(tie.get("scope"))

    # Keep the legacy error paths so the UI and existing tests continue to
    # surface the same contract violations, while accepting pipeline-first
    # shapes by looking at their normalized pipeline payload.
    if _has_key(scope, "exercicis") or _has_key(pipeline, "exercicis"):
        errors.append(
            f"desempat[{idx}].scope.exercicis no es compatible amb exercise_selection_scope=team_pool."
        )

    if _has_key(tie, "mode_seleccio_exercicis") or _has_key(pipeline, "mode_seleccio_exercicis"):
        errors.append(
            f"desempat[{idx}].mode_seleccio_exercicis no es compatible amb exercise_selection_scope=team_pool."
        )

    if _has_key(tie, "exercicis_per_aparell") or _has_key(pipeline, "exercicis_per_aparell"):
        errors.append(
            f"desempat[{idx}].exercicis_per_aparell no es compatible amb exercise_selection_scope=team_pool."
        )

    if _has_key(tie, "agregacio_exercicis_per_aparell") or _has_key(pipeline, "agregacio_exercicis_per_aparell"):
        errors.append(
            f"desempat[{idx}].agregacio_exercicis_per_aparell no es compatible amb exercise_selection_scope=team_pool."
        )

    if _has_key(scope, "participants") or _has_key(pipeline, "participants"):
        errors.append(
            f"desempat[{idx}].scope.participants no es compatible amb exercise_selection_scope=team_pool."
        )

    if _has_key(tie, "agregacio_participants") or _has_key(pipeline, "agregacio_participants"):
        errors.append(
            f"desempat[{idx}].agregacio_participants no es compatible amb exercise_selection_scope=team_pool."
        )

    return errors


def strip_team_pool_tie_payload(tie, *, main_scope=None):
    """Drop team_pool-forbidden fields from a tie shape in-place-compatible form.

    This is used by validation/materialization paths that still build temporary
    legacy mirrors for builder-facing checks. The canonical save payload should
    already be clean before reaching this helper.
    """

    tie = tie if isinstance(tie, dict) else {}
    effective_scope = _effective_tie_scope(tie, main_scope=main_scope)
    if effective_scope != EXERCISE_SELECTION_SCOPE_TEAM_POOL:
        return tie

    pipeline = _as_dict(tie.get("pipeline"))
    scope = _as_dict(tie.get("scope"))
    scope.pop("exercicis", None)
    scope.pop("participants", None)
    if scope:
        tie["scope"] = scope
    else:
        tie.pop("scope", None)

    tie.pop("mode_seleccio_exercicis", None)
    tie.pop("exercicis_per_aparell", None)
    tie.pop("agregacio_exercicis_per_aparell", None)
    tie.pop("agregacio_participants", None)

    pipeline.pop("exercicis", None)
    pipeline.pop("mode_seleccio_exercicis", None)
    pipeline.pop("exercicis_per_aparell", None)
    pipeline.pop("agregacio_exercicis", None)
    pipeline.pop("agregacio_exercicis_per_aparell", None)
    pipeline.pop("participants", None)
    pipeline.pop("agregacio_participants", None)
    if pipeline:
        tie["pipeline"] = pipeline
    return tie


__all__ = [
    "strip_team_pool_tie_payload",
    "validate_team_pool_tie_contract",
]
