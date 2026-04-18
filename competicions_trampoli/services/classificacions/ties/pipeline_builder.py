import json

from ..filters import (
    EXERCISE_SELECTION_SCOPE_PER_MEMBER,
    normalize_exercise_selection_scope,
    normalize_team_mode,
)
from .pipeline_helpers import (
    ALLOWED_EXERCISE_SELECTION_MODES,
    normalize_aggregation,
    normalize_exercicis_cfg,
    normalize_participants_cfg,
    unique_nonempty_strings,
    unique_positive_ints,
)


UNSUPPORTED_PER_EXERCISE_FIELD_PIPELINE_KEYS = (
    "camps_mode_per_aparell",
    "camps_per_exercici_per_aparell",
    "agregacio_camps_per_exercici_per_aparell",
)

TIE_INPUT_SOURCE_RAW_EXERCISES = "raw_exercises"
TIE_INPUT_SOURCE_MAIN_SELECTED_CONTRIBUTORS = "main_selected_contributors"
ALLOWED_TIE_INPUT_SOURCE_MODES = {
    TIE_INPUT_SOURCE_RAW_EXERCISES,
    TIE_INPUT_SOURCE_MAIN_SELECTED_CONTRIBUTORS,
}


def strip_unsupported_per_exercise_field_pipeline_keys(raw_pipeline):
    if not isinstance(raw_pipeline, dict):
        return {}
    pipeline = json.loads(json.dumps(raw_pipeline))
    for key in UNSUPPORTED_PER_EXERCISE_FIELD_PIPELINE_KEYS:
        pipeline.pop(key, None)
    return pipeline


def normalize_tie_input_source(raw_input_source, *, fallback=None):
    entry = raw_input_source if isinstance(raw_input_source, dict) else {}
    fallback_entry = fallback if isinstance(fallback, dict) else {}
    mode = str(
        entry.get("mode")
        or fallback_entry.get("mode")
        or raw_input_source
        or fallback
        or TIE_INPUT_SOURCE_RAW_EXERCISES
    ).strip().lower()
    if mode not in ALLOWED_TIE_INPUT_SOURCE_MODES:
        mode = TIE_INPUT_SOURCE_RAW_EXERCISES
    return {"mode": mode}


def _extract_tie_input_source(tie, *, fallback_pipeline=None):
    item = tie if isinstance(tie, dict) else {}
    pipeline = item.get("pipeline") if isinstance(item.get("pipeline"), dict) else {}
    raw_input_source = pipeline.get("input_source")
    if raw_input_source is None:
        raw_input_source = item.get("input_source")
    fallback_input_source = None
    if isinstance(fallback_pipeline, dict):
        fallback_input_source = fallback_pipeline.get("input_source")
    return normalize_tie_input_source(raw_input_source, fallback=fallback_input_source)


def _normalize_legacy_tie_pipeline(raw_tie, *, tipus="individual", team_mode="", fallback_pipeline=None):
    tie = raw_tie if isinstance(raw_tie, dict) else {}
    base = strip_unsupported_per_exercise_field_pipeline_keys(fallback_pipeline or {})
    app_ids = []
    scope = tie.get("scope") if isinstance(tie.get("scope"), dict) else {}
    app_scope = scope.get("aparells") if isinstance(scope.get("aparells"), dict) else {}
    if str(app_scope.get("mode") or "").strip().lower() == "seleccionar":
        app_ids = unique_positive_ints(app_scope.get("ids"))
    elif tie.get("aparell_id") not in (None, "", 0, "0"):
        try:
            parsed = int(tie.get("aparell_id"))
        except Exception:
            parsed = None
        app_ids = [parsed] if parsed and parsed > 0 else []
    if not app_ids:
        app_ids = unique_positive_ints(((base.get("aparells") or {}).get("ids")) or [])

    camps = unique_nonempty_strings(tie.get("camps") or tie.get("camp"))
    camps_map = {}
    agg_map = {}
    for app_id in app_ids:
        key = str(app_id)
        camps_map[key] = list(camps or ((base.get("camps_per_aparell") or {}).get(key) or ["total"]))
        agg_map[key] = normalize_aggregation(
            tie.get("agregacio_camps"),
            fallback=((base.get("agregacio_camps_per_aparell") or {}).get(key) or base.get("agregacio_camps", "sum")),
        )

    ex_scope = scope.get("exercicis") if isinstance(scope.get("exercicis"), dict) else {}
    ex_mode = str(ex_scope.get("mode") or "").strip().lower()
    use_base_ex = ex_mode in {"", "hereta"}
    ex_cfg = base.get("exercicis") or {"mode": "tots", "best_n": 1, "index": 1, "ids": [], "max_per_participant": 0}
    if not use_base_ex:
        ex_cfg = normalize_exercicis_cfg(ex_scope, fallback=ex_cfg)

    tie_scope = normalize_exercise_selection_scope(tie.get("exercise_selection_scope"), allow_inherit=True)
    if not tie_scope:
        tie_scope = (base.get("exercise_selection_scope") or EXERCISE_SELECTION_SCOPE_PER_MEMBER)
    elif tie_scope == "hereta":
        tie_scope = (base.get("exercise_selection_scope") or EXERCISE_SELECTION_SCOPE_PER_MEMBER)

    mode_seleccio = str(tie.get("mode_seleccio_exercicis") or "hereta").strip().lower()
    if mode_seleccio == "hereta":
        mode_seleccio = str(base.get("mode_seleccio_exercicis") or "per_aparell_global").strip().lower()

    ex_per_app = {}
    raw_ex_map = tie.get("exercicis_per_aparell") if isinstance(tie.get("exercicis_per_aparell"), dict) else {}
    raw_agg_ex_map = (
        tie.get("agregacio_exercicis_per_aparell")
        if isinstance(tie.get("agregacio_exercicis_per_aparell"), dict)
        else {}
    )
    agg_exercicis = normalize_aggregation(tie.get("agregacio_exercicis"), fallback=base.get("agregacio_exercicis", "sum"))
    agg_ex_per_app = {}
    for app_id in app_ids:
        key = str(app_id)
        if key in raw_ex_map or app_id in raw_ex_map:
            ex_per_app[key] = normalize_exercicis_cfg(
                raw_ex_map.get(key) or raw_ex_map.get(app_id),
                fallback=ex_cfg,
            )
        if key in raw_agg_ex_map or app_id in raw_agg_ex_map:
            agg_ex_per_app[key] = normalize_aggregation(
                raw_agg_ex_map.get(key) or raw_agg_ex_map.get(app_id),
                fallback=agg_exercicis,
            )

    pipeline = {
        **base,
        "aparells": {"mode": "seleccionar", "ids": app_ids},
        "input_source": _extract_tie_input_source(tie, fallback_pipeline=base),
        "camps_per_aparell": camps_map,
        "agregacio_camps_per_aparell": agg_map,
        "agregacio_camps": normalize_aggregation(tie.get("agregacio_camps"), fallback=base.get("agregacio_camps", "sum")),
        "exercicis": ex_cfg,
        "exercise_selection_scope": tie_scope,
        "mode_seleccio_exercicis": mode_seleccio if mode_seleccio in ALLOWED_EXERCISE_SELECTION_MODES else "per_aparell_global",
        "exercicis_per_aparell": ex_per_app,
        "agregacio_exercicis_per_aparell": agg_ex_per_app,
        "agregacio_exercicis": agg_exercicis,
        "agregacio_aparells": normalize_aggregation(tie.get("agregacio_aparells"), fallback=base.get("agregacio_aparells", "sum")),
        "mode_resultat_aparells": "score",
        "ordre": "asc" if str(tie.get("ordre") or "desc").strip().lower() == "asc" else "desc",
    }
    if str(tipus or "").strip().lower() == "equips" and normalize_team_mode(team_mode) == "derived_from_individual":
        participants_scope = scope.get("participants") if isinstance(scope.get("participants"), dict) else {}
        pipeline["participants"] = normalize_participants_cfg(participants_scope or {"mode": "tots"})
        pipeline["agregacio_participants"] = normalize_aggregation(tie.get("agregacio_participants"), "sum")
    return pipeline


def build_tie_pipeline_criterion(raw_tie, *, idx=0, tipus="individual", team_mode="", fallback_pipeline=None):
    from ..pipeline_runtime import PIPELINE_VERSION, normalize_scoring_pipeline

    tie = raw_tie if isinstance(raw_tie, dict) else {}
    ordre = "asc" if str(tie.get("ordre") or "desc").strip().lower() == "asc" else "desc"
    input_source = _extract_tie_input_source(tie, fallback_pipeline=fallback_pipeline)
    if isinstance(tie.get("pipeline"), dict):
        raw_pipeline = strip_unsupported_per_exercise_field_pipeline_keys(tie.get("pipeline"))
    else:
        raw_pipeline = _normalize_legacy_tie_pipeline(
            tie,
            tipus=tipus,
            team_mode=team_mode,
            fallback_pipeline=fallback_pipeline,
        )
    pipeline = normalize_scoring_pipeline(raw_pipeline, tipus=tipus, team_mode=team_mode, strict=False)
    pipeline["ordre"] = ordre
    pipeline["input_source"] = input_source
    item_id = str(tie.get("id") or f"tie_{idx + 1}").strip() or f"tie_{idx + 1}"
    nom = str(tie.get("nom") or "").strip()
    return {
        "id": item_id,
        "nom": nom,
        "ordre": ordre,
        "pipeline_version": PIPELINE_VERSION,
        "pipeline": pipeline,
    }


__all__ = [
    "ALLOWED_TIE_INPUT_SOURCE_MODES",
    "TIE_INPUT_SOURCE_MAIN_SELECTED_CONTRIBUTORS",
    "TIE_INPUT_SOURCE_RAW_EXERCISES",
    "build_tie_pipeline_criterion",
    "normalize_tie_input_source",
    "strip_unsupported_per_exercise_field_pipeline_keys",
]
