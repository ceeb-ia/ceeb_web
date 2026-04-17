from ..filters import (
    EXERCISE_SELECTION_SCOPE_PER_MEMBER,
    normalize_team_mode,
)


ALLOWED_AGGREGATIONS = {"sum", "avg", "median", "max", "min"}
ALLOWED_CANDIDATE_SOURCE_MODES = {"raw_exercise", "participant_aggregate", "team_aggregate"}
ALLOWED_EXERCISE_MODES = {"tots", "millor_1", "millor_n", "pitjor_1", "pitjor_n", "primer", "ultim", "index", "llista"}
ALLOWED_EXERCISE_SELECTION_MODES = {"per_aparell_global", "per_aparell_override", "global_pool"}
ALLOWED_PARTICIPANT_MODES = {"tots", "millor_1", "millor_n", "pitjor_1", "pitjor_n"}


def to_positive_int(value):
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def unique_positive_ints(raw_values):
    out = []
    seen = set()
    values = raw_values
    if not isinstance(values, (list, tuple)):
        return out
    for raw in values:
        parsed = to_positive_int(raw)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        out.append(parsed)
    return out


def unique_nonempty_strings(raw_values):
    out = []
    seen = set()
    values = raw_values
    if isinstance(values, str):
        values = values.split(",")
    if not isinstance(values, (list, tuple)):
        return out
    for raw in values:
        txt = str(raw or "").strip()
        if not txt or txt in seen:
            continue
        seen.add(txt)
        out.append(txt)
    return out


def normalize_aggregation(raw_value, fallback="sum"):
    value = str(raw_value or fallback or "sum").strip().lower()
    if value not in ALLOWED_AGGREGATIONS:
        value = str(fallback or "sum").strip().lower()
    if value not in ALLOWED_AGGREGATIONS:
        value = "sum"
    return value


def normalize_candidate_source_mode(raw_mode):
    mode = str(raw_mode or "raw_exercise").strip().lower()
    return mode if mode in ALLOWED_CANDIDATE_SOURCE_MODES else "raw_exercise"


def normalize_candidate_source_cfg(raw_cfg, fallback=None):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    fb = fallback if isinstance(fallback, dict) else {}
    mode = str(cfg.get("mode") or fb.get("mode") or "tots").strip().lower()
    if mode not in ALLOWED_EXERCISE_MODES:
        mode = str(fb.get("mode") or "tots").strip().lower()
    if mode not in ALLOWED_EXERCISE_MODES:
        mode = "tots"
    try:
        best_n = max(1, int(cfg.get("best_n", fb.get("best_n", 1)) or 1))
    except Exception:
        best_n = 1
    try:
        index = max(1, int(cfg.get("index", fb.get("index", 1)) or 1))
    except Exception:
        index = 1
    ids = unique_positive_ints(cfg.get("ids", fb.get("ids", [])))
    return {
        "mode": mode,
        "best_n": best_n,
        "index": index,
        "ids": ids,
        "agregacio_exercicis": normalize_aggregation(
            cfg.get("agregacio_exercicis"),
            fallback=fb.get("agregacio_exercicis", "sum"),
        ),
    }


def normalize_candidate_source_entry(raw_entry, *, fallback_mode="raw_exercise", fallback_cfg=None):
    entry = raw_entry if isinstance(raw_entry, dict) else {}
    mode = normalize_candidate_source_mode(entry.get("mode") or fallback_mode)
    out = {"mode": mode}
    if mode in {"participant_aggregate", "team_aggregate"}:
        out["cfg"] = normalize_candidate_source_cfg(entry.get("cfg"), fallback=fallback_cfg)
    return out


def normalize_candidate_source_per_aparell(raw_map, *, fallback_mode="raw_exercise", fallback_cfg=None):
    out = {}
    for raw_key, raw_value in (raw_map.items() if isinstance(raw_map, dict) else []):
        app_id = to_positive_int(raw_key)
        if app_id is None:
            continue
        out[str(app_id)] = normalize_candidate_source_entry(
            raw_value,
            fallback_mode=fallback_mode,
            fallback_cfg=fallback_cfg,
        )
    return out


def normalize_exercicis_cfg(raw_cfg, fallback=None):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    fb = fallback if isinstance(fallback, dict) else {}
    mode = str(cfg.get("mode") or fb.get("mode") or "tots").strip().lower()
    if mode not in ALLOWED_EXERCISE_MODES:
        mode = str(fb.get("mode") or "tots").strip().lower()
    if mode not in ALLOWED_EXERCISE_MODES:
        mode = "tots"
    try:
        best_n = max(1, int(cfg.get("best_n", fb.get("best_n", 1)) or 1))
    except Exception:
        best_n = 1
    try:
        index = max(1, int(cfg.get("index", fb.get("index", 1)) or 1))
    except Exception:
        index = 1
    try:
        max_per_participant = max(0, int(cfg.get("max_per_participant", fb.get("max_per_participant", 0)) or 0))
    except Exception:
        max_per_participant = 0
    return {
        "mode": mode,
        "best_n": best_n,
        "index": index,
        "ids": unique_positive_ints(cfg.get("ids", fb.get("ids", []))),
        "max_per_participant": max_per_participant,
    }


def normalize_exercicis_per_aparell(raw_map, *, fallback_cfg=None):
    out = {}
    for raw_key, raw_value in (raw_map.items() if isinstance(raw_map, dict) else []):
        app_id = to_positive_int(raw_key)
        if app_id is None:
            continue
        out[str(app_id)] = normalize_exercicis_cfg(raw_value, fallback=fallback_cfg)
    return out


def normalize_agregacio_exercicis_per_aparell(raw_map, *, fallback="sum"):
    out = {}
    for raw_key, raw_value in (raw_map.items() if isinstance(raw_map, dict) else []):
        app_id = to_positive_int(raw_key)
        if app_id is None:
            continue
        out[str(app_id)] = normalize_aggregation(raw_value, fallback=fallback)
    return out


def normalize_participants_cfg(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    mode = str(cfg.get("mode") or "tots").strip().lower()
    if mode not in ALLOWED_PARTICIPANT_MODES:
        mode = "tots"
    try:
        n_value = max(1, int(cfg.get("n") or 1))
    except Exception:
        n_value = 1
    out = {"mode": mode}
    if mode in {"millor_n", "pitjor_n"}:
        out["n"] = n_value
    return out


def default_pipeline_from_selected_app_ids(selected_app_ids, *, tipus="individual", team_mode=""):
    app_ids = unique_positive_ints(selected_app_ids)
    pipeline = {
        "aparells": {"mode": "seleccionar", "ids": app_ids},
        "camps_per_aparell": {str(app_id): ["total"] for app_id in app_ids},
        "agregacio_camps_per_aparell": {str(app_id): "sum" for app_id in app_ids},
        "agregacio_camps": "sum",
        "candidate_source_mode": "raw_exercise",
        "candidate_source_cfg": normalize_candidate_source_cfg({}),
        "candidate_source_per_aparell": {
            str(app_id): {"mode": "raw_exercise"}
            for app_id in app_ids
        },
        "exercicis": normalize_exercicis_cfg({"mode": "tots"}),
        "exercise_selection_scope": EXERCISE_SELECTION_SCOPE_PER_MEMBER,
        "mode_seleccio_exercicis": "per_aparell_global",
        "exercicis_per_aparell": {},
        "agregacio_exercicis_per_aparell": {},
        "agregacio_exercicis": "sum",
        "agregacio_aparells": "sum",
        "mode_resultat_aparells": "score",
        "ordre": "desc",
    }
    if str(tipus or "").strip().lower() == "equips" and normalize_team_mode(team_mode) == "derived_from_individual":
        pipeline["participants"] = {"mode": "tots"}
        pipeline["agregacio_participants"] = "sum"
    return pipeline


def resolve_pipeline_target_app_ids(pipeline):
    return unique_positive_ints((((pipeline or {}).get("aparells") or {}).get("ids")) or [])


def resolve_pipeline_ex_cfg_for_app(pipeline, app_id):
    ex_cfg = normalize_exercicis_cfg((pipeline or {}).get("exercicis"))
    mode_sel = str((pipeline or {}).get("mode_seleccio_exercicis") or "per_aparell_global").strip().lower()
    if mode_sel != "per_aparell_override":
        return ex_cfg
    raw_map = (pipeline or {}).get("exercicis_per_aparell") or {}
    raw = raw_map.get(str(app_id))
    if raw is None:
        raw = raw_map.get(app_id)
    return normalize_exercicis_cfg(raw, fallback=ex_cfg)


def resolve_pipeline_ex_agg_for_app(pipeline, app_id):
    agg_exercicis = normalize_aggregation((pipeline or {}).get("agregacio_exercicis"), "sum")
    mode_sel = str((pipeline or {}).get("mode_seleccio_exercicis") or "per_aparell_global").strip().lower()
    if mode_sel != "per_aparell_override":
        return agg_exercicis
    raw_map = (pipeline or {}).get("agregacio_exercicis_per_aparell") or {}
    raw = raw_map.get(str(app_id))
    if raw is None:
        raw = raw_map.get(app_id)
    return normalize_aggregation(raw, fallback=agg_exercicis)


__all__ = [
    "ALLOWED_AGGREGATIONS",
    "ALLOWED_CANDIDATE_SOURCE_MODES",
    "ALLOWED_EXERCISE_MODES",
    "ALLOWED_EXERCISE_SELECTION_MODES",
    "ALLOWED_PARTICIPANT_MODES",
    "default_pipeline_from_selected_app_ids",
    "normalize_agregacio_exercicis_per_aparell",
    "normalize_aggregation",
    "normalize_candidate_source_cfg",
    "normalize_candidate_source_entry",
    "normalize_candidate_source_mode",
    "normalize_candidate_source_per_aparell",
    "normalize_exercicis_cfg",
    "normalize_exercicis_per_aparell",
    "normalize_participants_cfg",
    "resolve_pipeline_ex_agg_for_app",
    "resolve_pipeline_ex_cfg_for_app",
    "resolve_pipeline_target_app_ids",
    "to_positive_int",
    "unique_nonempty_strings",
    "unique_positive_ints",
]
