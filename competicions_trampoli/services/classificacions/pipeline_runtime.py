import hashlib
import json
from copy import deepcopy

from .filters import (
    EXERCISE_SELECTION_SCOPE_PER_MEMBER,
    EXERCISE_SELECTION_SCOPE_TEAM_POOL,
    normalize_exercise_selection_scope,
    normalize_team_mode,
)


PIPELINE_VERSION = 1

ALLOWED_AGGREGATIONS = {"sum", "avg", "median", "max", "min"}
ALLOWED_CANDIDATE_SOURCE_MODES = {"raw_exercise", "participant_aggregate", "team_aggregate"}
ALLOWED_EXERCISE_MODES = {"tots", "millor_1", "millor_n", "pitjor_1", "pitjor_n", "primer", "ultim", "index", "llista"}
ALLOWED_EXERCISE_SELECTION_MODES = {"per_aparell_global", "per_aparell_override", "global_pool"}
ALLOWED_PARTICIPANT_MODES = {"tots", "millor_1", "millor_n", "pitjor_1", "pitjor_n"}
ALLOWED_FIELD_MODES_PER_APP = {"comu", "per_exercici"}
ALLOWED_INPUT_SOURCE_MODES = {"raw_exercises", "main_selected_contributors"}
SCORING_PIPELINE_ALLOWED_KEYS = {
    "aparells",
    "camps_mode_per_aparell",
    "camps_per_aparell",
    "camps_per_exercici_per_aparell",
    "agregacio_camps_per_aparell",
    "agregacio_camps_per_exercici_per_aparell",
    "agregacio_camps",
    "candidate_source_mode",
    "candidate_source_cfg",
    "candidate_source_per_aparell",
    "exercicis",
    "exercise_selection_scope",
    "mode_seleccio_exercicis",
    "exercicis_per_aparell",
    "agregacio_exercicis_per_aparell",
    "agregacio_exercicis",
    "agregacio_aparells",
    "mode_resultat_aparells",
    "ordre",
    "participants_per_aparell",
    "agregacio_participants_per_aparell",
    "team_pool_mode_per_aparell",
    "team_pool_participants_per_exercici_per_aparell",
    "team_pool_agregacio_participants_per_exercici_per_aparell",
    "participants",
    "agregacio_participants",
}
SCORING_PIPELINE_FORBIDDEN_KEYS = {
    "victories",
    "desempat",
    "presentacio",
    "particions",
    "particions_v2",
    "particions_custom",
    "filtres",
    "equips",
}
def _to_positive_int(value):
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _unique_positive_ints(raw_values):
    out = []
    seen = set()
    for raw in raw_values if isinstance(raw_values, (list, tuple)) else []:
        parsed = _to_positive_int(raw)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        out.append(parsed)
    return out


def _unique_nonempty_strings(raw_values):
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


def _normalize_aggregation(raw_value, fallback="sum"):
    value = str(raw_value or fallback or "sum").strip().lower()
    if value not in ALLOWED_AGGREGATIONS:
        value = str(fallback or "sum").strip().lower()
    if value not in ALLOWED_AGGREGATIONS:
        value = "sum"
    return value


def _normalize_field_mode(raw_value, fallback="comu"):
    value = str(raw_value or fallback or "comu").strip().lower()
    if value not in ALLOWED_FIELD_MODES_PER_APP:
        value = str(fallback or "comu").strip().lower()
    if value not in ALLOWED_FIELD_MODES_PER_APP:
        value = "comu"
    return value


def _normalize_candidate_source_mode(raw_mode):
    mode = str(raw_mode or "raw_exercise").strip().lower()
    return mode if mode in ALLOWED_CANDIDATE_SOURCE_MODES else "raw_exercise"


def _normalize_candidate_source_cfg(raw_cfg, fallback=None):
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
    ids = _unique_positive_ints(cfg.get("ids", fb.get("ids", [])))
    return {
        "mode": mode,
        "best_n": best_n,
        "index": index,
        "ids": ids,
        "agregacio_exercicis": _normalize_aggregation(
            cfg.get("agregacio_exercicis"),
            fallback=fb.get("agregacio_exercicis", "sum"),
        ),
    }


def _normalize_candidate_source_entry(raw_entry, *, fallback_mode="raw_exercise", fallback_cfg=None):
    entry = raw_entry if isinstance(raw_entry, dict) else {}
    mode = _normalize_candidate_source_mode(entry.get("mode") or fallback_mode)
    out = {"mode": mode}
    if mode in {"participant_aggregate", "team_aggregate"}:
        out["cfg"] = _normalize_candidate_source_cfg(entry.get("cfg"), fallback=fallback_cfg)
    return out


def _normalize_candidate_source_per_aparell(raw_map, *, fallback_mode="raw_exercise", fallback_cfg=None):
    out = {}
    for raw_key, raw_value in (raw_map.items() if isinstance(raw_map, dict) else []):
        app_id = _to_positive_int(raw_key)
        if app_id is None:
            continue
        out[str(app_id)] = _normalize_candidate_source_entry(
            raw_value,
            fallback_mode=fallback_mode,
            fallback_cfg=fallback_cfg,
        )
    return out


def _normalize_camps_mode_per_aparell(raw_map, *, fallback="comu"):
    out = {}
    for raw_key, raw_value in (raw_map.items() if isinstance(raw_map, dict) else []):
        app_id = _to_positive_int(raw_key)
        if app_id is None:
            continue
        out[str(app_id)] = _normalize_field_mode(raw_value, fallback=fallback)
    return out


def _normalize_camps_per_exercici_entry(raw_value):
    out = {}
    for raw_key, raw_fields in (raw_value.items() if isinstance(raw_value, dict) else []):
        ex_idx = _to_positive_int(raw_key)
        if ex_idx is None:
            continue
        out[str(ex_idx)] = _unique_nonempty_strings(raw_fields)
    return out


def _normalize_camps_per_exercici_per_aparell(raw_map):
    out = {}
    for raw_key, raw_value in (raw_map.items() if isinstance(raw_map, dict) else []):
        app_id = _to_positive_int(raw_key)
        if app_id is None:
            continue
        out[str(app_id)] = _normalize_camps_per_exercici_entry(raw_value)
    return out


def _normalize_agregacio_camps_per_exercici_entry(raw_value, *, fallback="sum"):
    out = {}
    for raw_key, raw_agg in (raw_value.items() if isinstance(raw_value, dict) else []):
        ex_idx = _to_positive_int(raw_key)
        if ex_idx is None:
            continue
        out[str(ex_idx)] = _normalize_aggregation(raw_agg, fallback=fallback)
    return out


def _normalize_agregacio_camps_per_exercici_per_aparell(raw_map, *, fallback="sum"):
    out = {}
    for raw_key, raw_value in (raw_map.items() if isinstance(raw_map, dict) else []):
        app_id = _to_positive_int(raw_key)
        if app_id is None:
            continue
        out[str(app_id)] = _normalize_agregacio_camps_per_exercici_entry(raw_value, fallback=fallback)
    return out


def _normalize_exercicis_cfg(raw_cfg, fallback=None):
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
        "ids": _unique_positive_ints(cfg.get("ids", fb.get("ids", []))),
        "max_per_participant": max_per_participant,
    }


def _normalize_exercicis_per_aparell(raw_map, *, fallback_cfg=None):
    out = {}
    for raw_key, raw_value in (raw_map.items() if isinstance(raw_map, dict) else []):
        app_id = _to_positive_int(raw_key)
        if app_id is None:
            continue
        out[str(app_id)] = _normalize_exercicis_cfg(raw_value, fallback=fallback_cfg)
    return out


def _normalize_agregacio_exercicis_per_aparell(raw_map, *, fallback="sum"):
    out = {}
    for raw_key, raw_value in (raw_map.items() if isinstance(raw_map, dict) else []):
        app_id = _to_positive_int(raw_key)
        if app_id is None:
            continue
        out[str(app_id)] = _normalize_aggregation(raw_value, fallback=fallback)
    return out


def _normalize_participants_cfg(raw_cfg):
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


def _normalize_participants_per_aparell(raw_map):
    out = {}
    for raw_key, raw_value in (raw_map.items() if isinstance(raw_map, dict) else []):
        app_id = _to_positive_int(raw_key)
        if app_id is None:
            continue
        out[str(app_id)] = _normalize_participants_cfg(raw_value)
    return out


def _normalize_input_source(raw_value):
    raw = raw_value if isinstance(raw_value, dict) else {}
    mode = str(raw.get("mode") or "raw_exercises").strip().lower()
    if mode not in ALLOWED_INPUT_SOURCE_MODES:
        mode = "raw_exercises"
    return {"mode": mode}


def _normalize_agregacio_participants_per_aparell(raw_map, *, fallback="sum"):
    out = {}
    for raw_key, raw_value in (raw_map.items() if isinstance(raw_map, dict) else []):
        app_id = _to_positive_int(raw_key)
        if app_id is None:
            continue
        out[str(app_id)] = _normalize_aggregation(raw_value, fallback=fallback)
    return out


def build_main_scoring_pipeline_from_schema(schema_local, *, tipus="individual", team_mode=""):
    schema = schema_local if isinstance(schema_local, dict) else {}
    punt = schema.get("puntuacio") if isinstance(schema.get("puntuacio"), dict) else {}
    app_cfg = punt.get("aparells") if isinstance(punt.get("aparells"), dict) else {}
    selected_ids = _unique_positive_ints(app_cfg.get("ids"))
    pipeline = {
        "aparells": {"mode": "seleccionar", "ids": selected_ids},
        "camps_mode_per_aparell": {},
        "camps_per_aparell": {},
        "camps_per_exercici_per_aparell": {},
        "agregacio_camps_per_aparell": {},
        "agregacio_camps_per_exercici_per_aparell": {},
        "agregacio_camps": _normalize_aggregation(punt.get("agregacio_camps"), "sum"),
        "candidate_source_mode": _normalize_candidate_source_mode(punt.get("candidate_source_mode")),
        "candidate_source_cfg": _normalize_candidate_source_cfg(punt.get("candidate_source_cfg")),
        "candidate_source_per_aparell": {},
        "exercicis": _normalize_exercicis_cfg(punt.get("exercicis")),
        "mode_seleccio_exercicis": str(punt.get("mode_seleccio_exercicis") or "per_aparell_global").strip().lower(),
        "exercicis_per_aparell": {},
        "agregacio_exercicis_per_aparell": {},
        "agregacio_exercicis": _normalize_aggregation(punt.get("agregacio_exercicis"), "sum"),
        "agregacio_aparells": _normalize_aggregation(punt.get("agregacio_aparells"), "sum"),
        "mode_resultat_aparells": str(punt.get("mode_resultat_aparells") or "score").strip().lower() or "score",
        "ordre": "desc" if str(punt.get("ordre") or "desc").strip().lower() != "asc" else "asc",
    }
    pipeline["exercise_selection_scope"] = (
        normalize_exercise_selection_scope(punt.get("exercise_selection_scope"))
        or EXERCISE_SELECTION_SCOPE_PER_MEMBER
    )
    field_mode_map = punt.get("camps_mode_per_aparell") if isinstance(punt.get("camps_mode_per_aparell"), dict) else {}
    camps_map = punt.get("camps_per_aparell") if isinstance(punt.get("camps_per_aparell"), dict) else {}
    ex_camps_map = (
        punt.get("camps_per_exercici_per_aparell")
        if isinstance(punt.get("camps_per_exercici_per_aparell"), dict)
        else {}
    )
    agg_map = punt.get("agregacio_camps_per_aparell") if isinstance(punt.get("agregacio_camps_per_aparell"), dict) else {}
    ex_agg_camps_map = (
        punt.get("agregacio_camps_per_exercici_per_aparell")
        if isinstance(punt.get("agregacio_camps_per_exercici_per_aparell"), dict)
        else {}
    )
    ex_map = punt.get("exercicis_per_aparell") if isinstance(punt.get("exercicis_per_aparell"), dict) else {}
    agg_ex_map = punt.get("agregacio_exercicis_per_aparell") if isinstance(punt.get("agregacio_exercicis_per_aparell"), dict) else {}
    source_map = punt.get("candidate_source_per_aparell") if isinstance(punt.get("candidate_source_per_aparell"), dict) else {}
    part_map = punt.get("participants_per_aparell") if isinstance(punt.get("participants_per_aparell"), dict) else {}
    agg_part_map = (
        punt.get("agregacio_participants_per_aparell")
        if isinstance(punt.get("agregacio_participants_per_aparell"), dict)
        else {}
    )
    for app_id in selected_ids:
        key = str(app_id)
        pipeline["camps_mode_per_aparell"][key] = _normalize_field_mode(
            field_mode_map.get(key) or field_mode_map.get(app_id),
            fallback="comu",
        )
        pipeline["camps_per_aparell"][key] = _unique_nonempty_strings(camps_map.get(key) or camps_map.get(app_id) or ["total"])
        if key in ex_camps_map or app_id in ex_camps_map:
            pipeline["camps_per_exercici_per_aparell"][key] = _normalize_camps_per_exercici_entry(
                ex_camps_map.get(key) or ex_camps_map.get(app_id)
            )
        pipeline["agregacio_camps_per_aparell"][key] = _normalize_aggregation(
            agg_map.get(key) or agg_map.get(app_id),
            fallback=pipeline["agregacio_camps"],
        )
        if key in ex_agg_camps_map or app_id in ex_agg_camps_map:
            pipeline["agregacio_camps_per_exercici_per_aparell"][key] = _normalize_agregacio_camps_per_exercici_entry(
                ex_agg_camps_map.get(key) or ex_agg_camps_map.get(app_id),
                fallback=pipeline["agregacio_camps_per_aparell"][key],
            )
        pipeline["candidate_source_per_aparell"][key] = _normalize_candidate_source_entry(
            source_map.get(key) or source_map.get(app_id) or {},
            fallback_mode=pipeline["candidate_source_mode"],
            fallback_cfg=pipeline["candidate_source_cfg"],
        )
        if key in ex_map or app_id in ex_map:
            pipeline["exercicis_per_aparell"][key] = _normalize_exercicis_cfg(
                ex_map.get(key) or ex_map.get(app_id),
                fallback=pipeline["exercicis"],
            )
        if key in agg_ex_map or app_id in agg_ex_map:
            pipeline["agregacio_exercicis_per_aparell"][key] = _normalize_aggregation(
                agg_ex_map.get(key) or agg_ex_map.get(app_id),
                fallback=pipeline["agregacio_exercicis"],
            )
    if (
        str(tipus or "").strip().lower() == "equips"
        and normalize_team_mode(team_mode) == "derived_from_individual"
        and pipeline["exercise_selection_scope"] == EXERCISE_SELECTION_SCOPE_PER_MEMBER
        and pipeline["mode_seleccio_exercicis"] != "global_pool"
    ):
        pipeline["participants_per_aparell"] = _normalize_participants_per_aparell(part_map)
        pipeline["agregacio_participants_per_aparell"] = _normalize_agregacio_participants_per_aparell(
            agg_part_map,
            fallback=_normalize_aggregation(punt.get("agregacio_participants"), "sum"),
        )
    return pipeline


def normalize_scoring_pipeline(raw_pipeline, *, tipus="individual", team_mode="", strict=False):
    pipeline_in = raw_pipeline if isinstance(raw_pipeline, dict) else {}
    tipus_norm = str(tipus or "").strip().lower()
    team_mode_norm = normalize_team_mode(team_mode)
    app_cfg = pipeline_in.get("aparells") if isinstance(pipeline_in.get("aparells"), dict) else {}
    app_ids = _unique_positive_ints(app_cfg.get("ids"))
    agg_camps = _normalize_aggregation(pipeline_in.get("agregacio_camps"), "sum")
    candidate_source_mode = _normalize_candidate_source_mode(pipeline_in.get("candidate_source_mode"))
    candidate_source_cfg = _normalize_candidate_source_cfg(pipeline_in.get("candidate_source_cfg"))
    ex_cfg = _normalize_exercicis_cfg(pipeline_in.get("exercicis"))
    mode_seleccio = str(pipeline_in.get("mode_seleccio_exercicis") or "per_aparell_global").strip().lower()
    if mode_seleccio not in ALLOWED_EXERCISE_SELECTION_MODES:
        mode_seleccio = "per_aparell_global"
    selection_scope = normalize_exercise_selection_scope(pipeline_in.get("exercise_selection_scope"))
    if selection_scope not in {EXERCISE_SELECTION_SCOPE_PER_MEMBER, EXERCISE_SELECTION_SCOPE_TEAM_POOL}:
        selection_scope = EXERCISE_SELECTION_SCOPE_PER_MEMBER
    camps_map_raw = pipeline_in.get("camps_per_aparell") if isinstance(pipeline_in.get("camps_per_aparell"), dict) else {}
    field_mode_map_raw = (
        pipeline_in.get("camps_mode_per_aparell")
        if isinstance(pipeline_in.get("camps_mode_per_aparell"), dict)
        else {}
    )
    ex_camps_map_raw = (
        pipeline_in.get("camps_per_exercici_per_aparell")
        if isinstance(pipeline_in.get("camps_per_exercici_per_aparell"), dict)
        else {}
    )
    agg_map_raw = pipeline_in.get("agregacio_camps_per_aparell") if isinstance(pipeline_in.get("agregacio_camps_per_aparell"), dict) else {}
    ex_agg_camps_map_raw = (
        pipeline_in.get("agregacio_camps_per_exercici_per_aparell")
        if isinstance(pipeline_in.get("agregacio_camps_per_exercici_per_aparell"), dict)
        else {}
    )
    source_map_raw = pipeline_in.get("candidate_source_per_aparell") if isinstance(pipeline_in.get("candidate_source_per_aparell"), dict) else {}
    ex_map_raw = pipeline_in.get("exercicis_per_aparell") if isinstance(pipeline_in.get("exercicis_per_aparell"), dict) else {}
    agg_ex_map_raw = pipeline_in.get("agregacio_exercicis_per_aparell") if isinstance(pipeline_in.get("agregacio_exercicis_per_aparell"), dict) else {}
    part_map_raw = pipeline_in.get("participants_per_aparell") if isinstance(pipeline_in.get("participants_per_aparell"), dict) else {}
    agg_part_map_raw = (
        pipeline_in.get("agregacio_participants_per_aparell")
        if isinstance(pipeline_in.get("agregacio_participants_per_aparell"), dict)
        else {}
    )
    team_pool_mode_raw = (
        pipeline_in.get("team_pool_mode_per_aparell")
        if isinstance(pipeline_in.get("team_pool_mode_per_aparell"), dict)
        else {}
    )
    team_pool_participants_raw = (
        pipeline_in.get("team_pool_participants_per_exercici_per_aparell")
        if isinstance(pipeline_in.get("team_pool_participants_per_exercici_per_aparell"), dict)
        else {}
    )
    team_pool_agg_raw = (
        pipeline_in.get("team_pool_agregacio_participants_per_exercici_per_aparell")
        if isinstance(pipeline_in.get("team_pool_agregacio_participants_per_exercici_per_aparell"), dict)
        else {}
    )
    field_mode_map = {}
    camps_per_aparell = {}
    ex_camps_map = {}
    agg_map = {}
    ex_agg_camps_map = {}
    source_map = {}
    ex_map = {}
    agg_ex_map = {}
    part_map = {}
    agg_part_map = {}
    team_pool_mode_map = {}
    team_pool_participants_map = {}
    team_pool_agg_map = {}
    for app_id in app_ids:
        key = str(app_id)
        field_mode_map[key] = _normalize_field_mode(
            field_mode_map_raw.get(key) or field_mode_map_raw.get(app_id),
            fallback="comu",
        )
        if key in camps_map_raw or app_id in camps_map_raw:
            camps_per_aparell[key] = _unique_nonempty_strings(camps_map_raw.get(key) or camps_map_raw.get(app_id))
        else:
            camps_per_aparell[key] = []
        if key in ex_camps_map_raw or app_id in ex_camps_map_raw:
            ex_camps_map[key] = _normalize_camps_per_exercici_entry(
                ex_camps_map_raw.get(key) or ex_camps_map_raw.get(app_id)
            )
        agg_map[key] = _normalize_aggregation(
            agg_map_raw.get(key) or agg_map_raw.get(app_id),
            fallback=agg_camps,
        )
        if key in ex_agg_camps_map_raw or app_id in ex_agg_camps_map_raw:
            ex_agg_camps_map[key] = _normalize_agregacio_camps_per_exercici_entry(
                ex_agg_camps_map_raw.get(key) or ex_agg_camps_map_raw.get(app_id),
                fallback=agg_map[key],
            )
        source_map[key] = _normalize_candidate_source_entry(
            source_map_raw.get(key) or source_map_raw.get(app_id) or {},
            fallback_mode=candidate_source_mode,
            fallback_cfg=candidate_source_cfg,
        )
        if key in ex_map_raw or app_id in ex_map_raw:
            ex_map[key] = _normalize_exercicis_cfg(
                ex_map_raw.get(key) or ex_map_raw.get(app_id),
                fallback=ex_cfg,
            )
        if key in agg_ex_map_raw or app_id in agg_ex_map_raw:
            agg_ex_map[key] = _normalize_aggregation(
                agg_ex_map_raw.get(key) or agg_ex_map_raw.get(app_id),
                fallback=pipeline_in.get("agregacio_exercicis") or "sum",
            )
        if key in part_map_raw or app_id in part_map_raw:
            part_map[key] = _normalize_participants_cfg(part_map_raw.get(key) or part_map_raw.get(app_id))
        if key in agg_part_map_raw or app_id in agg_part_map_raw:
            agg_part_map[key] = _normalize_aggregation(
                agg_part_map_raw.get(key) or agg_part_map_raw.get(app_id),
                fallback="sum",
            )
        if selection_scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL:
            raw_team_pool_mode = str(team_pool_mode_raw.get(key) or team_pool_mode_raw.get(app_id) or "").strip().lower()
            if raw_team_pool_mode in {"flat", "per_exercici"}:
                team_pool_mode_map[key] = raw_team_pool_mode
                if raw_team_pool_mode == "per_exercici":
                    participants_by_ex = team_pool_participants_raw.get(key) or team_pool_participants_raw.get(app_id) or {}
                    if isinstance(participants_by_ex, dict):
                        team_pool_participants_map[key] = {}
                        for raw_ex_key, raw_cfg in participants_by_ex.items():
                            ex_key = _to_positive_int(raw_ex_key)
                            if ex_key is None:
                                continue
                            team_pool_participants_map[key][str(ex_key)] = _normalize_participants_cfg(raw_cfg)
                        if not team_pool_participants_map[key]:
                            team_pool_participants_map.pop(key, None)
                    agg_by_ex = team_pool_agg_raw.get(key) or team_pool_agg_raw.get(app_id) or {}
                    if isinstance(agg_by_ex, dict):
                        team_pool_agg_map[key] = {}
                        for raw_ex_key, raw_agg in agg_by_ex.items():
                            ex_key = _to_positive_int(raw_ex_key)
                            if ex_key is None:
                                continue
                            team_pool_agg_map[key][str(ex_key)] = _normalize_aggregation(raw_agg, "sum")
                        if not team_pool_agg_map[key]:
                            team_pool_agg_map.pop(key, None)
    ordre = "asc" if str(pipeline_in.get("ordre") or "desc").strip().lower() == "asc" else "desc"
    pipeline = {
        "aparells": {
            "mode": "seleccionar",
            "ids": app_ids,
        },
        "camps_mode_per_aparell": field_mode_map,
        "camps_per_aparell": camps_per_aparell,
        "camps_per_exercici_per_aparell": ex_camps_map,
        "agregacio_camps_per_aparell": agg_map,
        "agregacio_camps_per_exercici_per_aparell": ex_agg_camps_map,
        "agregacio_camps": agg_camps,
        "candidate_source_mode": candidate_source_mode,
        "candidate_source_cfg": candidate_source_cfg,
        "candidate_source_per_aparell": source_map,
        "exercicis": ex_cfg,
        "exercise_selection_scope": selection_scope,
        "mode_seleccio_exercicis": mode_seleccio,
        "exercicis_per_aparell": ex_map,
        "agregacio_exercicis": _normalize_aggregation(pipeline_in.get("agregacio_exercicis"), "sum"),
        "agregacio_exercicis_per_aparell": _normalize_agregacio_exercicis_per_aparell(
            agg_ex_map,
            fallback=_normalize_aggregation(pipeline_in.get("agregacio_exercicis"), "sum"),
        ),
        "agregacio_aparells": _normalize_aggregation(pipeline_in.get("agregacio_aparells"), "sum"),
        "mode_resultat_aparells": str(pipeline_in.get("mode_resultat_aparells") or "score").strip().lower() or "score",
        "ordre": ordre,
    }
    if "input_source" in pipeline_in:
        pipeline["input_source"] = _normalize_input_source(pipeline_in.get("input_source"))
    if "participants_per_aparell" in pipeline_in:
        pipeline["participants_per_aparell"] = part_map
    if "agregacio_participants_per_aparell" in pipeline_in:
        pipeline["agregacio_participants_per_aparell"] = agg_part_map
    if selection_scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL and team_pool_mode_map:
        pipeline["team_pool_mode_per_aparell"] = team_pool_mode_map
        if team_pool_participants_map:
            pipeline["team_pool_participants_per_exercici_per_aparell"] = team_pool_participants_map
        if team_pool_agg_map:
            pipeline["team_pool_agregacio_participants_per_exercici_per_aparell"] = team_pool_agg_map
    if (
        tipus_norm == "equips"
        and team_mode_norm == "derived_from_individual"
        and selection_scope == EXERCISE_SELECTION_SCOPE_PER_MEMBER
        and mode_seleccio != "global_pool"
    ):
        pipeline["participants"] = _normalize_participants_cfg(pipeline_in.get("participants"))
        pipeline["agregacio_participants"] = _normalize_aggregation(
            pipeline_in.get("agregacio_participants"),
            "sum",
        )
    elif "participants" in pipeline_in or "agregacio_participants" in pipeline_in:
        if not strict:
            pipeline.pop("participants", None)
            pipeline.pop("agregacio_participants", None)
    return pipeline


def _default_pipeline_from_selected_app_ids(selected_app_ids, *, tipus="individual", team_mode=""):
    app_ids = _unique_positive_ints(selected_app_ids)
    pipeline = {
        "aparells": {"mode": "seleccionar", "ids": app_ids},
        "camps_mode_per_aparell": {str(app_id): "comu" for app_id in app_ids},
        "camps_per_aparell": {str(app_id): ["total"] for app_id in app_ids},
        "camps_per_exercici_per_aparell": {},
        "agregacio_camps_per_aparell": {str(app_id): "sum" for app_id in app_ids},
        "agregacio_camps_per_exercici_per_aparell": {},
        "agregacio_camps": "sum",
        "candidate_source_mode": "raw_exercise",
        "candidate_source_cfg": _normalize_candidate_source_cfg({}),
        "candidate_source_per_aparell": {
            str(app_id): {"mode": "raw_exercise"}
            for app_id in app_ids
        },
        "exercicis": _normalize_exercicis_cfg({"mode": "tots"}),
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


def _normalize_legacy_tie_pipeline(raw_tie, *, tipus="individual", team_mode="", fallback_pipeline=None):
    tie = raw_tie if isinstance(raw_tie, dict) else {}
    base = json.loads(json.dumps(fallback_pipeline or {}))
    app_ids = []
    scope = tie.get("scope") if isinstance(tie.get("scope"), dict) else {}
    app_scope = scope.get("aparells") if isinstance(scope.get("aparells"), dict) else {}
    if str(app_scope.get("mode") or "").strip().lower() == "seleccionar":
        app_ids = _unique_positive_ints(app_scope.get("ids"))
    elif tie.get("aparell_id") not in (None, "", 0, "0"):
        parsed = _to_positive_int(tie.get("aparell_id"))
        app_ids = [parsed] if parsed is not None else []
    if not app_ids:
        app_ids = _unique_positive_ints(((base.get("aparells") or {}).get("ids")) or [])
    camps = _unique_nonempty_strings(tie.get("camps") or tie.get("camp"))
    camps_map = {}
    agg_map = {}
    for app_id in app_ids:
        key = str(app_id)
        camps_map[key] = list(camps or ((base.get("camps_per_aparell") or {}).get(key) or ["total"]))
        agg_map[key] = _normalize_aggregation(
            tie.get("agregacio_camps"),
            fallback=((base.get("agregacio_camps_per_aparell") or {}).get(key) or base.get("agregacio_camps", "sum")),
        )
    ex_scope = scope.get("exercicis") if isinstance(scope.get("exercicis"), dict) else {}
    ex_mode = str(ex_scope.get("mode") or "").strip().lower()
    use_base_ex = ex_mode in {"", "hereta"}
    ex_cfg = base.get("exercicis") or {"mode": "tots", "best_n": 1, "index": 1, "ids": [], "max_per_participant": 0}
    if not use_base_ex:
        ex_cfg = _normalize_exercicis_cfg(ex_scope, fallback=ex_cfg)
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
    agg_exercicis = _normalize_aggregation(tie.get("agregacio_exercicis"), fallback=base.get("agregacio_exercicis", "sum"))
    agg_ex_per_app = {}
    for app_id in app_ids:
        key = str(app_id)
        if key in raw_ex_map or app_id in raw_ex_map:
            ex_per_app[key] = _normalize_exercicis_cfg(
                raw_ex_map.get(key) or raw_ex_map.get(app_id),
                fallback=ex_cfg,
            )
        if key in raw_agg_ex_map or app_id in raw_agg_ex_map:
            agg_ex_per_app[key] = _normalize_aggregation(
                raw_agg_ex_map.get(key) or raw_agg_ex_map.get(app_id),
                fallback=agg_exercicis,
            )
    pipeline = {
        **base,
        "aparells": {"mode": "seleccionar", "ids": app_ids},
        "camps_per_aparell": camps_map,
        "agregacio_camps_per_aparell": agg_map,
        "agregacio_camps": _normalize_aggregation(tie.get("agregacio_camps"), fallback=base.get("agregacio_camps", "sum")),
        "exercicis": ex_cfg,
        "exercise_selection_scope": tie_scope,
        "mode_seleccio_exercicis": mode_seleccio if mode_seleccio in ALLOWED_EXERCISE_SELECTION_MODES else "per_aparell_global",
        "exercicis_per_aparell": ex_per_app,
        "agregacio_exercicis_per_aparell": agg_ex_per_app,
        "agregacio_exercicis": agg_exercicis,
        "agregacio_aparells": _normalize_aggregation(tie.get("agregacio_aparells"), fallback=base.get("agregacio_aparells", "sum")),
        "mode_resultat_aparells": "score",
        "ordre": "asc" if str(tie.get("ordre") or "desc").strip().lower() == "asc" else "desc",
    }
    if str(tipus or "").strip().lower() == "equips" and normalize_team_mode(team_mode) == "derived_from_individual":
        participants_scope = scope.get("participants") if isinstance(scope.get("participants"), dict) else {}
        pipeline["participants"] = _normalize_participants_cfg(participants_scope or {"mode": "tots"})
        pipeline["agregacio_participants"] = _normalize_aggregation(tie.get("agregacio_participants"), "sum")
    return normalize_scoring_pipeline(pipeline, tipus=tipus, team_mode=team_mode, strict=False)


def build_tie_pipeline_criterion(raw_tie, *, idx=0, tipus="individual", team_mode="", fallback_pipeline=None):
    from .ties.pipeline_builder import build_tie_pipeline_criterion as _build_tie_pipeline_criterion

    return _build_tie_pipeline_criterion(
        raw_tie,
        idx=idx,
        tipus=tipus,
        team_mode=team_mode,
        fallback_pipeline=fallback_pipeline,
    )


def _compact_exercicis_cfg_for_persistence(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    mode = str(cfg.get("mode") or "tots").strip().lower() or "tots"
    out = {"mode": mode}
    if mode in {"millor_n", "pitjor_n"}:
        out["best_n"] = max(1, int(cfg.get("best_n") or 1))
    elif mode == "index":
        out["index"] = max(1, int(cfg.get("index") or 1))
    elif mode == "llista":
        ids = _unique_positive_ints(cfg.get("ids"))
        out["ids"] = ids
    max_per_participant = cfg.get("max_per_participant")
    try:
        max_per_participant = int(max_per_participant or 0)
    except Exception:
        max_per_participant = 0
    if max_per_participant > 0:
        out["max_per_participant"] = max_per_participant
    return out


def _compact_candidate_source_cfg_for_persistence(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    mode = str(cfg.get("mode") or "tots").strip().lower() or "tots"
    out = {"mode": mode}
    if mode in {"millor_n", "pitjor_n"}:
        out["best_n"] = max(1, int(cfg.get("best_n") or 1))
    elif mode == "index":
        out["index"] = max(1, int(cfg.get("index") or 1))
    elif mode == "llista":
        out["ids"] = _unique_positive_ints(cfg.get("ids"))
    agg = _normalize_aggregation(cfg.get("agregacio_exercicis"), fallback="sum")
    if agg != "sum" or "agregacio_exercicis" in cfg:
        out["agregacio_exercicis"] = agg
    return out


def _compact_candidate_source_entry_for_persistence(raw_entry):
    entry = raw_entry if isinstance(raw_entry, dict) else {}
    mode = _normalize_candidate_source_mode(entry.get("mode") or "raw_exercise")
    out = {"mode": mode}
    if mode in {"participant_aggregate", "team_aggregate"}:
        out["cfg"] = _compact_candidate_source_cfg_for_persistence(entry.get("cfg"))
    return out


def _compact_pipeline_for_persistence(raw_pipeline):
    pipeline = raw_pipeline if isinstance(raw_pipeline, dict) else {}
    out = {
        "aparells": {
            "mode": "seleccionar",
            "ids": _resolve_pipeline_target_app_ids(pipeline),
        },
        "camps_mode_per_aparell": {},
        "camps_per_aparell": {
            str(app_id): _unique_nonempty_strings(
                ((pipeline.get("camps_per_aparell") or {}).get(str(app_id)))
                or ((pipeline.get("camps_per_aparell") or {}).get(app_id))
            )
            for app_id in _resolve_pipeline_target_app_ids(pipeline)
        },
        "camps_per_exercici_per_aparell": {},
        "agregacio_camps_per_aparell": {
            str(app_id): _normalize_aggregation(
                ((pipeline.get("agregacio_camps_per_aparell") or {}).get(str(app_id)))
                or ((pipeline.get("agregacio_camps_per_aparell") or {}).get(app_id)),
                fallback=pipeline.get("agregacio_camps", "sum"),
            )
            for app_id in _resolve_pipeline_target_app_ids(pipeline)
        },
        "agregacio_camps_per_exercici_per_aparell": {},
        "agregacio_camps": _normalize_aggregation(pipeline.get("agregacio_camps"), "sum"),
        "candidate_source_mode": _normalize_candidate_source_mode(pipeline.get("candidate_source_mode")),
        "candidate_source_cfg": _compact_candidate_source_cfg_for_persistence(pipeline.get("candidate_source_cfg")),
        "candidate_source_per_aparell": {},
        "team_pool_mode_per_aparell": {},
        "team_pool_participants_per_exercici_per_aparell": {},
        "team_pool_agregacio_participants_per_exercici_per_aparell": {},
        "exercicis": _compact_exercicis_cfg_for_persistence(pipeline.get("exercicis")),
        "mode_seleccio_exercicis": str(pipeline.get("mode_seleccio_exercicis") or "per_aparell_global").strip().lower() or "per_aparell_global",
        "exercicis_per_aparell": {},
        "agregacio_exercicis": _normalize_aggregation(pipeline.get("agregacio_exercicis"), "sum"),
        "agregacio_exercicis_per_aparell": {},
        "agregacio_aparells": _normalize_aggregation(pipeline.get("agregacio_aparells"), "sum"),
        "mode_resultat_aparells": str(pipeline.get("mode_resultat_aparells") or "score").strip().lower() or "score",
        "ordre": "asc" if str(pipeline.get("ordre") or "desc").strip().lower() == "asc" else "desc",
    }
    if "exercise_selection_scope" in pipeline:
        out["exercise_selection_scope"] = normalize_exercise_selection_scope(pipeline.get("exercise_selection_scope")) or EXERCISE_SELECTION_SCOPE_PER_MEMBER
    if isinstance(pipeline.get("participants"), dict):
        out["participants"] = _normalize_participants_cfg(pipeline.get("participants"))
        if "agregacio_participants" in pipeline:
            out["agregacio_participants"] = _normalize_aggregation(pipeline.get("agregacio_participants"), "sum")
    source_map = pipeline.get("candidate_source_per_aparell") if isinstance(pipeline.get("candidate_source_per_aparell"), dict) else {}
    field_mode_map = pipeline.get("camps_mode_per_aparell") if isinstance(pipeline.get("camps_mode_per_aparell"), dict) else {}
    ex_camps_map = (
        pipeline.get("camps_per_exercici_per_aparell")
        if isinstance(pipeline.get("camps_per_exercici_per_aparell"), dict)
        else {}
    )
    ex_agg_camps_map = (
        pipeline.get("agregacio_camps_per_exercici_per_aparell")
        if isinstance(pipeline.get("agregacio_camps_per_exercici_per_aparell"), dict)
        else {}
    )
    team_pool_mode_map = (
        pipeline.get("team_pool_mode_per_aparell")
        if isinstance(pipeline.get("team_pool_mode_per_aparell"), dict)
        else {}
    )
    team_pool_participants_map = (
        pipeline.get("team_pool_participants_per_exercici_per_aparell")
        if isinstance(pipeline.get("team_pool_participants_per_exercici_per_aparell"), dict)
        else {}
    )
    team_pool_agg_map = (
        pipeline.get("team_pool_agregacio_participants_per_exercici_per_aparell")
        if isinstance(pipeline.get("team_pool_agregacio_participants_per_exercici_per_aparell"), dict)
        else {}
    )
    for app_id in _resolve_pipeline_target_app_ids(pipeline):
        key = str(app_id)
        mode = _normalize_field_mode(field_mode_map.get(key) or field_mode_map.get(app_id), fallback="comu")
        ex_fields = _normalize_camps_per_exercici_entry(ex_camps_map.get(key) or ex_camps_map.get(app_id))
        ex_aggs = _normalize_agregacio_camps_per_exercici_entry(
            ex_agg_camps_map.get(key) or ex_agg_camps_map.get(app_id),
            fallback=((out.get("agregacio_camps_per_aparell") or {}).get(key) or out.get("agregacio_camps", "sum")),
        )
        if mode == "per_exercici":
            out["camps_mode_per_aparell"][key] = "per_exercici"
            if ex_fields:
                out["camps_per_exercici_per_aparell"][key] = ex_fields
            if ex_aggs:
                out["agregacio_camps_per_exercici_per_aparell"][key] = ex_aggs
        if out.get("exercise_selection_scope") == EXERCISE_SELECTION_SCOPE_TEAM_POOL:
            team_pool_mode = str(team_pool_mode_map.get(key) or team_pool_mode_map.get(app_id) or "").strip().lower()
            if team_pool_mode in {"flat", "per_exercici"}:
                out["team_pool_mode_per_aparell"][key] = team_pool_mode
                if team_pool_mode == "per_exercici":
                    participants_by_ex = team_pool_participants_map.get(key) or team_pool_participants_map.get(app_id)
                    if participants_by_ex:
                        out["team_pool_participants_per_exercici_per_aparell"][key] = deepcopy(participants_by_ex)
                    aggs_by_ex = team_pool_agg_map.get(key) or team_pool_agg_map.get(app_id)
                    if aggs_by_ex:
                        out["team_pool_agregacio_participants_per_exercici_per_aparell"][key] = deepcopy(aggs_by_ex)
    for raw_key, raw_value in source_map.items():
        app_id = _to_positive_int(raw_key)
        if app_id is None:
            continue
        out["candidate_source_per_aparell"][str(app_id)] = _compact_candidate_source_entry_for_persistence(raw_value)
    ex_map = pipeline.get("exercicis_per_aparell") if isinstance(pipeline.get("exercicis_per_aparell"), dict) else {}
    for raw_key, raw_value in ex_map.items():
        app_id = _to_positive_int(raw_key)
        if app_id is None:
            continue
        out["exercicis_per_aparell"][str(app_id)] = _compact_exercicis_cfg_for_persistence(raw_value)
    agg_ex_map = pipeline.get("agregacio_exercicis_per_aparell") if isinstance(pipeline.get("agregacio_exercicis_per_aparell"), dict) else {}
    for raw_key, raw_value in agg_ex_map.items():
        app_id = _to_positive_int(raw_key)
        if app_id is None:
            continue
        out["agregacio_exercicis_per_aparell"][str(app_id)] = _normalize_aggregation(
            raw_value,
            fallback=pipeline.get("agregacio_exercicis", "sum"),
        )
    if not out["candidate_source_per_aparell"]:
        out["candidate_source_per_aparell"] = {
            str(app_id): {"mode": out["candidate_source_mode"]}
            for app_id in out["aparells"]["ids"]
        }
    if not out["camps_mode_per_aparell"]:
        out.pop("camps_mode_per_aparell", None)
    if not out["camps_per_exercici_per_aparell"]:
        out.pop("camps_per_exercici_per_aparell", None)
    if not out["agregacio_camps_per_exercici_per_aparell"]:
        out.pop("agregacio_camps_per_exercici_per_aparell", None)
    if not out["team_pool_mode_per_aparell"]:
        out.pop("team_pool_mode_per_aparell", None)
    if not out["team_pool_participants_per_exercici_per_aparell"]:
        out.pop("team_pool_participants_per_exercici_per_aparell", None)
    if not out["team_pool_agregacio_participants_per_exercici_per_aparell"]:
        out.pop("team_pool_agregacio_participants_per_exercici_per_aparell", None)
    if not out["agregacio_exercicis_per_aparell"]:
        out.pop("agregacio_exercicis_per_aparell", None)
    if not out["exercicis_per_aparell"]:
        out.pop("exercicis_per_aparell", None)
    return out


def canonicalize_desempat_item_for_persistence(
    raw_tie,
    *,
    tipus="individual",
    team_mode="",
    selected_app_ids=None,
    default_id="tie_1",
    default_nom="",
    fallback_pipeline=None,
):
    allow_exercise_scope = (
        str(tipus or "").strip().lower() == "equips"
        and normalize_team_mode(team_mode) == "derived_from_individual"
    )
    fallback = fallback_pipeline or _default_pipeline_from_selected_app_ids(
        selected_app_ids,
        tipus=tipus,
        team_mode=team_mode,
    )
    item = build_tie_pipeline_criterion(
        raw_tie,
        idx=0,
        tipus=tipus,
        team_mode=team_mode,
        fallback_pipeline=fallback,
    )
    if default_id and not str(item.get("id") or "").strip():
        item["id"] = str(default_id).strip()
    if default_nom and not str(item.get("nom") or "").strip():
        item["nom"] = str(default_nom).strip()
    pipeline = _compact_pipeline_for_persistence(item.get("pipeline"))
    if not allow_exercise_scope:
        pipeline.pop("exercise_selection_scope", None)
    return {
        "id": str(item.get("id") or default_id).strip() or str(default_id).strip(),
        "nom": str(item.get("nom") or default_nom).strip(),
        "ordre": "asc" if str(item.get("ordre") or "desc").strip().lower() == "asc" else "desc",
        "pipeline_version": PIPELINE_VERSION,
        "pipeline": pipeline,
    }


def canonicalize_desempat_items_for_persistence(
    desempat,
    *,
    tipus="individual",
    team_mode="",
    selected_app_ids=None,
    fallback_pipeline=None,
):
    out = []
    for idx, tie in enumerate(desempat if isinstance(desempat, list) else []):
        if not isinstance(tie, dict):
            continue
        item = canonicalize_desempat_item_for_persistence(
            tie,
            tipus=tipus,
            team_mode=team_mode,
            selected_app_ids=selected_app_ids,
            default_id=f"tie_{idx + 1}",
            default_nom=f"Criteri {idx + 1}",
            fallback_pipeline=fallback_pipeline,
        )
        if item:
            out.append(item)
    return out


def materialize_desempat_item(
    raw_tie,
    *,
    tipus="individual",
    team_mode="",
    selected_app_ids=None,
    default_id="tie_1",
    default_nom="",
    allow_participants=True,
    fallback_pipeline=None,
):
    from .ties.legacy_projection import project_tie_legacy_projection

    return project_tie_legacy_projection(
        raw_tie,
        idx=0,
        tipus=tipus,
        team_mode=team_mode,
        selected_app_ids=selected_app_ids,
        default_id=default_id,
        default_nom=default_nom,
        allow_participants=allow_participants,
        fallback_pipeline=fallback_pipeline,
    )


def materialize_desempat_items(
    desempat,
    *,
    tipus="individual",
    team_mode="",
    selected_app_ids=None,
    allow_participants=True,
    fallback_pipeline=None,
):
    from .ties.legacy_projection import project_ties_legacy_projection

    return project_ties_legacy_projection(
        desempat,
        tipus=tipus,
        team_mode=team_mode,
        selected_app_ids=selected_app_ids,
        allow_participants=allow_participants,
        fallback_pipeline=fallback_pipeline,
    )


def pipeline_metric_key(tie):
    item_id = str((tie or {}).get("id") or "").strip()
    if item_id:
        return f"pipeline:{item_id}"
    payload = json.dumps((tie or {}).get("pipeline") or {}, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"pipeline:{digest}"


def _pipeline_selected_app_ids(pipeline):
    return _resolve_pipeline_target_app_ids(pipeline)


def _normalize_agg(raw_value, fallback="sum"):
    return _normalize_aggregation(raw_value, fallback=fallback)


def _resolve_pipeline_target_app_ids(pipeline):
    return _unique_positive_ints((((pipeline or {}).get("aparells") or {}).get("ids")) or [])


def _resolve_pipeline_ex_cfg_for_app(pipeline, app_id):
    ex_cfg = _normalize_exercicis_cfg((pipeline or {}).get("exercicis"))
    mode_sel = str((pipeline or {}).get("mode_seleccio_exercicis") or "per_aparell_global").strip().lower()
    if mode_sel != "per_aparell_override":
        return ex_cfg
    raw_map = (pipeline or {}).get("exercicis_per_aparell") or {}
    raw = raw_map.get(str(app_id))
    if raw is None:
        raw = raw_map.get(app_id)
    return _normalize_exercicis_cfg(raw, fallback=ex_cfg)


def _resolve_pipeline_ex_agg_for_app(pipeline, app_id):
    agg_exercicis = _normalize_aggregation((pipeline or {}).get("agregacio_exercicis"), "sum")
    mode_sel = str((pipeline or {}).get("mode_seleccio_exercicis") or "per_aparell_global").strip().lower()
    if mode_sel != "per_aparell_override":
        return agg_exercicis
    raw_map = (pipeline or {}).get("agregacio_exercicis_per_aparell") or {}
    raw = raw_map.get(str(app_id))
    if raw is None:
        raw = raw_map.get(app_id)
    return _normalize_aggregation(raw, fallback=agg_exercicis)


def _resolve_pipeline_fields_cfg_for_app_exercise(pipeline, app_id, ex_idx):
    app_key = str(app_id)
    ex_key = str(_to_positive_int(ex_idx) or 1)
    camps_map = (pipeline.get("camps_per_aparell") or {})
    agg_map = (pipeline.get("agregacio_camps_per_aparell") or {})
    base_fields = _unique_nonempty_strings(camps_map.get(app_key) or camps_map.get(app_id))
    base_agg = _normalize_aggregation(
        agg_map.get(app_key) or agg_map.get(app_id),
        fallback=pipeline.get("agregacio_camps", "sum"),
    )
    mode_map = (pipeline.get("camps_mode_per_aparell") or {})
    mode = _normalize_field_mode(mode_map.get(app_key) or mode_map.get(app_id), fallback="comu")
    if mode != "per_exercici":
        return base_fields, base_agg

    ex_camps_per_app = (pipeline.get("camps_per_exercici_per_aparell") or {})
    ex_aggs_per_app = (pipeline.get("agregacio_camps_per_exercici_per_aparell") or {})
    app_ex_fields = ex_camps_per_app.get(app_key)
    if app_ex_fields is None:
        app_ex_fields = ex_camps_per_app.get(app_id)
    app_ex_aggs = ex_aggs_per_app.get(app_key)
    if app_ex_aggs is None:
        app_ex_aggs = ex_aggs_per_app.get(app_id)
    resolved_fields = _unique_nonempty_strings(
        (app_ex_fields or {}).get(ex_key) if isinstance(app_ex_fields, dict) else []
    )
    raw_agg = (app_ex_aggs or {}).get(ex_key) if isinstance(app_ex_aggs, dict) else None
    resolved_agg = str(raw_agg or "").strip().lower()
    if resolved_agg and resolved_agg not in ALLOWED_AGGREGATIONS:
        resolved_agg = ""
    if not resolved_fields or not resolved_agg:
        return base_fields, base_agg
    return resolved_fields, resolved_agg


def resolve_fields_for_app_exercise(app_id, ex_idx, pipeline):
    fields, _agg = _resolve_pipeline_fields_cfg_for_app_exercise(pipeline or {}, app_id, ex_idx)
    return fields


def resolve_field_agg_for_app_exercise(app_id, ex_idx, pipeline):
    _fields, agg = _resolve_pipeline_fields_cfg_for_app_exercise(pipeline or {}, app_id, ex_idx)
    return agg


def _copy_row_with_value(ctx, row, value):
    item = ctx["copy_ex_row_with_value"](row, value)
    item["by_camp"] = dict((row or {}).get("by_camp") or {})
    return item


def _resolve_pipeline_input_source_mode(pipeline):
    return _normalize_input_source((pipeline or {}).get("input_source")).get("mode") or "raw_exercises"


def _pipeline_rows_for_source_rows(ctx, rows_ex, app_id, pipeline, *, participant_key):
    computed_rows = []
    for row in rows_ex or []:
        ex_idx = _to_positive_int((row or {}).get("exercici")) or _to_positive_int((row or {}).get("idx")) or 1
        camps, agg_camps = _resolve_pipeline_fields_cfg_for_app_exercise(pipeline, app_id, ex_idx)
        if not camps:
            continue
        by_camp = dict((row or {}).get("by_camp") or {})
        values = [ctx["to_float"](by_camp.get(code)) for code in camps]
        computed_rows.append(_copy_row_with_value(ctx, row, ctx["apply_simple_agg"](values, agg_camps)))
    source_map = pipeline.get("candidate_source_per_aparell") or {}
    source = source_map.get(str(app_id)) or source_map.get(app_id) or {}
    source_mode = _normalize_candidate_source_mode(source.get("mode") or pipeline.get("candidate_source_mode"))
    if source_mode not in {"participant_aggregate", "team_aggregate"}:
        return computed_rows
    source_cfg = _normalize_candidate_source_cfg(
        source.get("cfg"),
        fallback=pipeline.get("candidate_source_cfg"),
    )
    picked_rows = ctx["pick_exercicis_rows"](
        computed_rows,
        source_cfg["mode"],
        source_cfg["best_n"],
        index=source_cfg["index"],
        ids=source_cfg["ids"],
        max_per_participant=0,
        participant_key=participant_key,
    )
    if not picked_rows:
        return []
    agg_value = ctx["apply_simple_agg"](
        [ctx["to_float"](row.get("value")) for row in picked_rows],
        source_cfg["agregacio_exercicis"],
    )
    first_row = picked_rows[0]
    by_camp = {}
    for code in camps:
        by_camp[code] = ctx["apply_simple_agg"](
            [ctx["to_float"](dict((row or {}).get("by_camp") or {}).get(code)) for row in picked_rows],
            source_cfg["agregacio_exercicis"],
        )
    candidate_row = _copy_row_with_value(ctx, first_row, agg_value)
    candidate_row["by_camp"] = by_camp
    candidate_row["candidate_source_mode"] = source_mode
    candidate_row["candidate_source_count"] = len(picked_rows)
    return [candidate_row]


def _source_rows_by_app_for_individual(ctx, pipeline, inscripcio_id):
    input_source_mode = _resolve_pipeline_input_source_mode(pipeline)
    if input_source_mode == "main_selected_contributors" and callable(ctx.get("get_main_selected_contributors_for_individual")):
        return ctx["get_main_selected_contributors_for_individual"](inscripcio_id) or {}
    app_ex_rows_by_ins = ctx.get("app_ex_rows_by_ins") or {}
    return {
        app_id: (((app_ex_rows_by_ins.get(app_id) or {}).get(inscripcio_id)) or [])
        for app_id in _resolve_pipeline_target_app_ids(pipeline)
    }


def _source_rows_by_app_for_native_team(ctx, pipeline, equip_id):
    input_source_mode = _resolve_pipeline_input_source_mode(pipeline)
    if input_source_mode == "main_selected_contributors" and callable(ctx.get("get_main_selected_contributors_for_native_team")):
        return ctx["get_main_selected_contributors_for_native_team"](equip_id) or {}
    team_rows_by_equip = ctx.get("team_app_ex_rows_by_equip") or {}
    return {
        app_id: (((team_rows_by_equip.get(app_id) or {}).get(equip_id)) or [])
        for app_id in _resolve_pipeline_target_app_ids(pipeline)
    }


def _source_rows_by_member_for_group(ctx, pipeline, member_ids):
    mids = _unique_positive_ints(member_ids)
    if not mids:
        return {}
    input_source_mode = _resolve_pipeline_input_source_mode(pipeline)
    if input_source_mode == "main_selected_contributors" and callable(ctx.get("get_main_selected_contributors_for_group")):
        return ctx["get_main_selected_contributors_for_group"](mids) or {}
    app_ex_rows_by_ins = ctx.get("app_ex_rows_by_ins") or {}
    target_app_ids = _resolve_pipeline_target_app_ids(pipeline)
    out = {}
    for member_id in mids:
        rows_by_app = {}
        for app_id in target_app_ids:
            rows = (((app_ex_rows_by_ins.get(app_id) or {}).get(member_id)) or [])
            if rows:
                rows_by_app[app_id] = rows
        out[member_id] = rows_by_app
    return out


def _score_subject_from_source_rows_by_app(ctx, pipeline, source_rows_by_app, *, participant_key, target_app_ids=None):
    app_ids = list(target_app_ids or _resolve_pipeline_target_app_ids(pipeline))
    rows_by_app = {}
    for app_id in app_ids:
        rows_by_app[app_id] = _pipeline_rows_for_source_rows(
            ctx,
            (source_rows_by_app or {}).get(app_id, []),
            app_id,
            pipeline,
            participant_key=participant_key,
        )
    return _aggregate_rows_per_pipeline(
        ctx,
        rows_by_app,
        app_ids,
        pipeline,
        participant_key=participant_key,
    )


def _aggregate_rows_per_pipeline(ctx, rows_by_app, target_app_ids, pipeline, *, participant_key):
    if not target_app_ids:
        return 0.0
    agg_exercicis = _normalize_aggregation(pipeline.get("agregacio_exercicis"), "sum")
    agg_aparells = _normalize_aggregation(pipeline.get("agregacio_aparells"), "sum")
    mode_sel = str(pipeline.get("mode_seleccio_exercicis") or "per_aparell_global").strip().lower()
    if mode_sel not in ALLOWED_EXERCISE_SELECTION_MODES:
        mode_sel = "per_aparell_global"
    app_order = ctx.get("app_order") or {}
    vals_apps = []
    if mode_sel == "global_pool":
        pool_rows = []
        for app_id in target_app_ids:
            for row in rows_by_app.get(app_id, []):
                item = _copy_row_with_value(ctx, row, row.get("value"))
                item["app_id"] = app_id
                item["app_order"] = app_order.get(app_id, 0)
                pool_rows.append(item)
        pool_rows = sorted(
            pool_rows,
            key=lambda row: (row.get("app_order", 0), row.get("exercici", 0), row.get("app_id", 0)),
        )
        for idx, row in enumerate(pool_rows, start=1):
            row["idx"] = idx
        ex_cfg = _normalize_exercicis_cfg(pipeline.get("exercicis"))
        picked_rows = ctx["pick_exercicis_rows"](
            pool_rows,
            ex_cfg["mode"],
            ex_cfg["best_n"],
            index=ex_cfg["index"],
            ids=ex_cfg["ids"],
            max_per_participant=ex_cfg.get("max_per_participant", 0),
            participant_key=participant_key,
        )
        picked_by_app = {}
        for row in picked_rows:
            try:
                app_id = int(row.get("app_id"))
            except Exception:
                continue
            picked_by_app.setdefault(app_id, []).append(ctx["to_float"](row.get("value")))
        for app_id in target_app_ids:
            vals_apps.append(ctx["apply_simple_agg"](picked_by_app.get(app_id, []), agg_exercicis))
        return float(ctx["apply_simple_agg"](vals_apps, agg_aparells))
    for app_id in target_app_ids:
        rows = rows_by_app.get(app_id, [])
        ex_cfg = _resolve_pipeline_ex_cfg_for_app(pipeline, app_id)
        agg_exercicis_app = _resolve_pipeline_ex_agg_for_app(pipeline, app_id)
        picked = ctx["pick_exercicis_tuples"](
            [(int(row.get("exercici", row.get("idx", 1)) or 1), ctx["to_float"](row.get("value"))) for row in rows],
            ex_cfg["mode"],
            ex_cfg["best_n"],
            index=ex_cfg["index"],
            ids=ex_cfg["ids"],
            max_per_participant=ex_cfg.get("max_per_participant", 0),
            participant_key=participant_key,
        )
        vals_apps.append(ctx["apply_simple_agg"](picked, agg_exercicis_app))
    return float(ctx["apply_simple_agg"](vals_apps, agg_aparells))


def _score_individual_subject(ctx, pipeline, inscripcio_id):
    target_app_ids = _resolve_pipeline_target_app_ids(pipeline)
    return _score_subject_from_source_rows_by_app(
        ctx,
        pipeline,
        _source_rows_by_app_for_individual(ctx, pipeline, inscripcio_id),
        target_app_ids=target_app_ids,
        participant_key="inscripcio_id",
    )


def _score_individual_subject_for_app(ctx, pipeline, inscripcio_id, app_id):
    target_app_ids = _resolve_pipeline_target_app_ids(pipeline)
    if app_id not in target_app_ids:
        return 0.0
    return _score_subject_from_source_rows_by_app(
        ctx,
        pipeline,
        _source_rows_by_app_for_individual(ctx, pipeline, inscripcio_id),
        target_app_ids=[app_id],
        participant_key="inscripcio_id",
    )


def _score_group_subject(ctx, pipeline, member_ids):
    mids = _unique_positive_ints(member_ids)
    if not mids:
        return 0.0
    selection_scope = normalize_exercise_selection_scope(pipeline.get("exercise_selection_scope"))
    input_source_mode = _resolve_pipeline_input_source_mode(pipeline)
    participants_per_aparell = pipeline.get("participants_per_aparell") if isinstance(pipeline.get("participants_per_aparell"), dict) else None
    agregacio_participants_per_aparell = (
        pipeline.get("agregacio_participants_per_aparell")
        if isinstance(pipeline.get("agregacio_participants_per_aparell"), dict)
        else None
    )
    contributor_rows_by_member = None
    if input_source_mode == "main_selected_contributors":
        contributor_rows_by_member = _source_rows_by_member_for_group(ctx, pipeline, mids)
    if selection_scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL and callable(ctx.get("get_main_selected_rows_for_group")):
        if input_source_mode == "main_selected_contributors":
            target_app_ids = _resolve_pipeline_target_app_ids(pipeline)
            selected_rows_by_app = {}
            for rows_by_app in (contributor_rows_by_member or {}).values():
                for app_id, rows in (rows_by_app or {}).items():
                    selected_rows_by_app.setdefault(app_id, []).extend(rows or [])
            return _score_subject_from_source_rows_by_app(
                ctx,
                pipeline,
                selected_rows_by_app,
                target_app_ids=target_app_ids,
                participant_key="inscripcio_id",
            )
        target_app_ids = _resolve_pipeline_target_app_ids(pipeline)
        selected_rows_by_app = ctx["get_main_selected_rows_for_group"](mids)
        rows_by_app = {}
        for app_id in target_app_ids:
            rows_by_app[app_id] = _pipeline_rows_for_source_rows(
                ctx,
                selected_rows_by_app.get(app_id, []),
                app_id,
                pipeline,
                participant_key="inscripcio_id",
            )
        return _aggregate_rows_per_pipeline(
            ctx,
            rows_by_app,
            target_app_ids,
            pipeline,
            participant_key="inscripcio_id",
        )
    if selection_scope == EXERCISE_SELECTION_SCOPE_PER_MEMBER:
        target_app_ids = _resolve_pipeline_target_app_ids(pipeline)
        if not target_app_ids:
            return 0.0
        vals_apps = []
        has_per_app_participants = participants_per_aparell is not None or agregacio_participants_per_aparell is not None
        legacy_participants_cfg = _normalize_participants_cfg((pipeline or {}).get("participants"))
        legacy_agg_parts = _normalize_aggregation((pipeline or {}).get("agregacio_participants"), "sum")
        for app_id in target_app_ids:
            member_vals = []
            for member_id in mids:
                if contributor_rows_by_member is not None:
                    member_vals.append(
                        _score_subject_from_source_rows_by_app(
                            ctx,
                            pipeline,
                            (contributor_rows_by_member.get(member_id) or {}),
                            target_app_ids=[app_id],
                            participant_key="inscripcio_id",
                        )
                    )
                else:
                    member_vals.append(_score_individual_subject_for_app(ctx, pipeline, member_id, app_id))
            if has_per_app_participants:
                part_cfg = _normalize_participants_cfg((participants_per_aparell or {}).get(str(app_id)) or {})
                if not part_cfg:
                    part_cfg = {"mode": "tots"}
                agg_parts = _normalize_aggregation(
                    (agregacio_participants_per_aparell or {}).get(str(app_id)),
                    "sum",
                )
            else:
                part_cfg = legacy_participants_cfg
                agg_parts = legacy_agg_parts
            selected_vals = ctx["pick_participants"](member_vals, part_cfg["mode"], int(part_cfg.get("n") or 1))
            vals_apps.append(float(ctx["apply_simple_agg"](selected_vals, agg_parts)))
        return float(ctx["apply_simple_agg"](vals_apps, _normalize_aggregation((pipeline or {}).get("agregacio_aparells"), "sum")))
    part_cfg = _normalize_participants_cfg((pipeline or {}).get("participants"))
    agg_parts = _normalize_aggregation((pipeline or {}).get("agregacio_participants"), "sum")
    if contributor_rows_by_member is not None:
        vals = [
            _score_subject_from_source_rows_by_app(
                ctx,
                pipeline,
                (contributor_rows_by_member.get(member_id) or {}),
                participant_key="inscripcio_id",
            )
            for member_id in mids
        ]
    else:
        vals = [_score_individual_subject(ctx, pipeline, member_id) for member_id in mids]
    selected_vals = ctx["pick_participants"](vals, part_cfg["mode"], int(part_cfg.get("n") or 1))
    return float(ctx["apply_simple_agg"](selected_vals, agg_parts))


def _score_native_team_subject(ctx, pipeline, equip_id):
    target_app_ids = _resolve_pipeline_target_app_ids(pipeline)
    return _score_subject_from_source_rows_by_app(
        ctx,
        pipeline,
        _source_rows_by_app_for_native_team(ctx, pipeline, equip_id),
        target_app_ids=target_app_ids,
        participant_key="equip_id",
    )


def compute_metric_from_pipeline(runtime_ctx, pipeline, subject):
    ctx = runtime_ctx if isinstance(runtime_ctx, dict) else {}
    subject_obj = subject if isinstance(subject, dict) else {}
    kind = str(subject_obj.get("kind") or "individual").strip().lower()
    if kind == "native_team":
        return _score_native_team_subject(ctx, pipeline, _to_positive_int(subject_obj.get("equip_id")) or 0)
    if kind in {"group", "entity"}:
        return _score_group_subject(ctx, pipeline, subject_obj.get("member_ids") or [])
    return _score_individual_subject(ctx, pipeline, _to_positive_int(subject_obj.get("inscripcio_id")) or 0)


__all__ = [
    "PIPELINE_VERSION",
    "SCORING_PIPELINE_ALLOWED_KEYS",
    "SCORING_PIPELINE_FORBIDDEN_KEYS",
    "build_main_scoring_pipeline_from_schema",
    "build_tie_pipeline_criterion",
    "canonicalize_desempat_item_for_persistence",
    "canonicalize_desempat_items_for_persistence",
    "compute_metric_from_pipeline",
    "materialize_desempat_item",
    "materialize_desempat_items",
    "normalize_scoring_pipeline",
    "_normalize_agg",
    "_pipeline_selected_app_ids",
    "pipeline_metric_key",
    "resolve_field_agg_for_app_exercise",
    "resolve_fields_for_app_exercise",
]
