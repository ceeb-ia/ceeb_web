"""Contract-specific validation helpers for desempat items."""

from ..filters import (
    EXERCISE_SELECTION_SCOPE_INHERIT,
    EXERCISE_SELECTION_SCOPE_PER_MEMBER,
    EXERCISE_SELECTION_SCOPE_TEAM_POOL,
    normalize_exercise_selection_scope,
    normalize_team_mode,
)
from .legacy_projection import project_ties_legacy_projection


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


def strip_native_team_tie_payload(tie):
    """Drop native-team-forbidden participant payload from a tie."""

    tie = tie if isinstance(tie, dict) else {}
    pipeline = _as_dict(tie.get("pipeline"))
    scope = _as_dict(tie.get("scope"))
    scope.pop("participants", None)
    if scope:
        tie["scope"] = scope
    else:
        tie.pop("scope", None)

    tie.pop("agregacio_participants", None)
    pipeline.pop("participants", None)
    pipeline.pop("agregacio_participants", None)
    if pipeline:
        tie["pipeline"] = pipeline
    return tie


def materialize_desempat_for_validation(
    desempat,
    *,
    tipus="individual",
    team_mode="",
    selected_app_ids=None,
    allow_participants=True,
    fallback_pipeline=None,
    main_scope=None,
    strip_pipeline_exercise_scope=True,
):
    """Build the temporary validation projection used by desempat checks.

    This keeps the validation-side cleanup in one place while preserving the
    legacy materialization shape expected by the existing callers.
    """

    materialized = project_ties_legacy_projection(
        desempat,
        tipus=tipus,
        team_mode=team_mode,
        selected_app_ids=selected_app_ids,
        allow_participants=allow_participants,
        fallback_pipeline=fallback_pipeline,
    )
    for tie in materialized:
        if not isinstance(tie, dict):
            continue
        strip_team_pool_tie_payload(tie, main_scope=main_scope)
        if normalize_team_mode(team_mode) == "native_team":
            strip_native_team_tie_payload(tie)
        if strip_pipeline_exercise_scope:
            tie.pop("exercise_selection_scope", None)
            pipeline = tie.get("pipeline")
            if isinstance(pipeline, dict):
                pipeline.pop("exercise_selection_scope", None)
    return materialized


def validate_raw_desempat_legacy_payload(desempat):
    """Validate legacy-only tie inputs before canonical save compaction.

    The persistence serializer intentionally compacts legacy UI fields into a
    pipeline-first shape. These checks preserve legacy validation errors that
    would otherwise disappear during that compaction.
    """

    errors = []
    allowed_selection_modes = {"hereta", "per_aparell_global", "per_aparell_override", "global_pool"}
    forbidden_pipeline_keys = {
        "victories",
        "camps_mode_per_aparell",
        "camps_per_exercici_per_aparell",
        "agregacio_camps_per_exercici_per_aparell",
    }
    for idx, tie in enumerate(desempat if isinstance(desempat, list) else []):
        if not isinstance(tie, dict):
            continue
        pipeline = _as_dict(tie.get("pipeline"))
        for key in forbidden_pipeline_keys:
            if key in pipeline:
                errors.append(f"desempat[{idx}].pipeline.{key} no esta permes.")
        scope = _as_dict(tie.get("scope"))
        app_scope = _as_dict(scope.get("aparells"))
        app_mode = str(app_scope.get("mode") or "hereta").strip().lower()
        if app_mode == "tots":
            errors.append(
                f"desempat[{idx}].scope.aparells.mode='tots' no esta permès; usa 'hereta' o seleccio explicita."
            )

        ex_scope = _as_dict(scope.get("exercicis"))
        mode_sel_raw = (
            tie.get("mode_seleccio_exercicis")
            or ex_scope.get("mode_seleccio_exercicis")
            or "hereta"
        )
        mode_sel = str(mode_sel_raw).strip().lower()
        if mode_sel not in allowed_selection_modes:
            errors.append(f"desempat[{idx}].mode_seleccio_exercicis invalid: {mode_sel}")
    return errors


__all__ = [
    "materialize_desempat_for_validation",
    "strip_native_team_tie_payload",
    "strip_team_pool_tie_payload",
    "validate_raw_desempat_legacy_payload",
    "validate_team_pool_tie_contract",
]
