"""Validation helpers for the canonical scoring/tie pipeline."""

from .pipeline_runtime import (
    ALLOWED_AGGREGATIONS,
    ALLOWED_CANDIDATE_SOURCE_MODES,
    ALLOWED_EXERCISE_MODES,
    ALLOWED_EXERCISE_SELECTION_MODES,
    ALLOWED_PARTICIPANT_MODES,
    SCORING_PIPELINE_ALLOWED_KEYS,
    SCORING_PIPELINE_FORBIDDEN_KEYS,
    _normalize_agg,
    _normalize_candidate_source_cfg,
    _normalize_candidate_source_mode,
    _normalize_exercicis_cfg,
    _normalize_participants_cfg,
    _pipeline_selected_app_ids,
    _sanitize_scoring_pipeline_legacy_aliases,
    normalize_scoring_pipeline,
)


ALLOWED_EXERCISE_SELECTION_SCOPES = {"per_member", "team_pool"}


def _report_disallowed_keys(raw_pipeline, *, prefix):
    errors = []
    if not isinstance(raw_pipeline, dict):
        return errors
    for key in raw_pipeline.keys():
        if key in SCORING_PIPELINE_ALLOWED_KEYS:
            continue
        if key in SCORING_PIPELINE_FORBIDDEN_KEYS:
            errors.append(f"{prefix}.{key} no esta permes.")
        else:
            errors.append(f"{prefix}.{key} no esta permes.")
    return errors


def _validate_aggs(raw_pipeline, *, prefix):
    errors = []
    for key in ("agregacio_camps", "agregacio_exercicis", "agregacio_aparells", "agregacio_participants"):
        if key not in raw_pipeline:
            continue
        value = str(raw_pipeline.get(key) or "").strip().lower()
        if value and value not in ALLOWED_AGGREGATIONS:
            errors.append(f"{prefix}.{key} invalid: {raw_pipeline.get(key)}")
    if "agregacio_exercicis_per_aparell" in raw_pipeline and isinstance(raw_pipeline.get("agregacio_exercicis_per_aparell"), dict):
        for app_key, raw_value in (raw_pipeline.get("agregacio_exercicis_per_aparell") or {}).items():
            value = str(raw_value or "").strip().lower()
            if value and value not in ALLOWED_AGGREGATIONS:
                errors.append(f"{prefix}.agregacio_exercicis_per_aparell[{app_key}] invalid: {raw_value}")
    return errors


def validate_scoring_pipeline_shape(raw_pipeline, *, prefix="pipeline"):
    if not isinstance(raw_pipeline, dict):
        return [f"{prefix} ha de ser un objecte."]

    compat_pipeline = _sanitize_scoring_pipeline_legacy_aliases(raw_pipeline)
    errors = list(_report_disallowed_keys(compat_pipeline, prefix=prefix))
    normalized = normalize_scoring_pipeline(compat_pipeline, strict=True)

    aparells = compat_pipeline.get("aparells")
    if not isinstance(aparells, dict):
        errors.append(f"{prefix}.aparells ha de ser un objecte.")
    else:
        mode = str(aparells.get("mode") or "").strip().lower()
        if mode not in {"seleccionar"}:
            errors.append(f"{prefix}.aparells.mode invalid: {aparells.get('mode')}")
        if not _pipeline_selected_app_ids(normalized):
            errors.append(f"{prefix}.aparells.ids ha de tenir almenys un aparell.")

    camps_map = compat_pipeline.get("camps_per_aparell")
    if not isinstance(camps_map, dict):
        errors.append(f"{prefix}.camps_per_aparell ha de ser un objecte.")
    else:
        for app_key, raw_codes in camps_map.items():
            if not isinstance(raw_codes, (list, tuple, str)):
                errors.append(f"{prefix}.camps_per_aparell[{app_key}] ha de ser una llista o text.")

    for key in ("agregacio_camps_per_aparell", "candidate_source_per_aparell", "exercicis_per_aparell", "agregacio_exercicis_per_aparell"):
        if key in compat_pipeline and not isinstance(compat_pipeline.get(key), dict):
            errors.append(f"{prefix}.{key} ha de ser un objecte.")

    mode_resultat = str(compat_pipeline.get("mode_resultat_aparells") or "").strip().lower()
    if mode_resultat and mode_resultat != "score":
        errors.append(f"{prefix}.mode_resultat_aparells invalid: {compat_pipeline.get('mode_resultat_aparells')}")

    ordre = str(compat_pipeline.get("ordre") or "").strip().lower()
    if ordre and ordre not in {"asc", "desc"}:
        errors.append(f"{prefix}.ordre invalid: {compat_pipeline.get('ordre')}")

    raw_scope = str(compat_pipeline.get("exercise_selection_scope") or "").strip().lower()
    if raw_scope == "hereta":
        errors.append(f"{prefix}.exercise_selection_scope no admet 'hereta'.")
    elif raw_scope and raw_scope not in ALLOWED_EXERCISE_SELECTION_SCOPES:
        errors.append(f"{prefix}.exercise_selection_scope invalid: {compat_pipeline.get('exercise_selection_scope')}")

    mode_sel = str(compat_pipeline.get("mode_seleccio_exercicis") or "").strip().lower()
    if mode_sel == "hereta":
        errors.append(f"{prefix}.mode_seleccio_exercicis no admet 'hereta'.")
    elif mode_sel and mode_sel not in ALLOWED_EXERCISE_SELECTION_MODES:
        errors.append(f"{prefix}.mode_seleccio_exercicis invalid: {compat_pipeline.get('mode_seleccio_exercicis')}")

    candidate_mode = str(compat_pipeline.get("candidate_source_mode") or "").strip().lower()
    if candidate_mode and candidate_mode not in ALLOWED_CANDIDATE_SOURCE_MODES:
        errors.append(f"{prefix}.candidate_source_mode invalid: {compat_pipeline.get('candidate_source_mode')}")
    if "candidate_source_cfg" in compat_pipeline and compat_pipeline.get("candidate_source_cfg") is not None:
        if not isinstance(compat_pipeline.get("candidate_source_cfg"), dict):
            errors.append(f"{prefix}.candidate_source_cfg ha de ser un objecte.")
        else:
            cfg_mode = str((compat_pipeline.get("candidate_source_cfg") or {}).get("mode") or "").strip().lower()
            if cfg_mode and cfg_mode not in ALLOWED_EXERCISE_MODES:
                errors.append(f"{prefix}.candidate_source_cfg.mode invalid: {(compat_pipeline.get('candidate_source_cfg') or {}).get('mode')}")

    exercicis = compat_pipeline.get("exercicis")
    if exercicis is not None and not isinstance(exercicis, dict):
        errors.append(f"{prefix}.exercicis ha de ser un objecte.")
    elif isinstance(exercicis, dict):
        ex_mode = str(exercicis.get("mode") or "").strip().lower()
        if ex_mode == "hereta":
            errors.append(f"{prefix}.exercicis.mode no admet 'hereta'.")
        elif ex_mode and ex_mode not in ALLOWED_EXERCISE_MODES:
            errors.append(f"{prefix}.exercicis.mode invalid: {exercicis.get('mode')}")
        for num_key in ("best_n", "index", "max_per_participant"):
            if exercicis.get(num_key) in (None, ""):
                continue
            try:
                if int(exercicis.get(num_key)) < (0 if num_key == "max_per_participant" else 1):
                    raise ValueError
            except Exception:
                errors.append(f"{prefix}.exercicis.{num_key} invalid.")

    participants = compat_pipeline.get("participants")
    if participants is not None and not isinstance(participants, dict):
        errors.append(f"{prefix}.participants ha de ser un objecte.")
    elif isinstance(participants, dict):
        mode = str(participants.get("mode") or "").strip().lower()
        if mode and mode not in ALLOWED_PARTICIPANT_MODES:
            errors.append(f"{prefix}.participants.mode invalid: {participants.get('mode')}")
        if mode in {"millor_n", "pitjor_n"}:
            try:
                if int(participants.get("n") or 0) <= 0:
                    raise ValueError
            except Exception:
                errors.append(f"{prefix}.participants.n invalid.")

    errors.extend(_validate_aggs(compat_pipeline, prefix=prefix))
    return errors


def collect_pipeline_selected_app_ids(raw_pipeline):
    pipeline = raw_pipeline if isinstance(raw_pipeline, dict) else {}
    return _pipeline_selected_app_ids(pipeline)


__all__ = [
    "collect_pipeline_selected_app_ids",
    "validate_scoring_pipeline_shape",
]
