from copy import deepcopy

from ...filters import EXERCISE_SELECTION_SCOPE_PER_MEMBER, normalize_exercise_selection_scope
from ...pipeline_runtime import PIPELINE_VERSION


ALLOWED_AGGREGATIONS = {"sum", "avg", "median", "max", "min"}
ALLOWED_CANDIDATE_SOURCE_MODES = {"raw_exercise", "participant_aggregate", "team_aggregate"}
ALLOWED_EXERCISE_MODES = {
    "tots",
    "millor_1",
    "millor_n",
    "pitjor_1",
    "pitjor_n",
    "primer",
    "ultim",
    "index",
    "llista",
}
ALLOWED_PARTICIPANT_MODES = {"tots", "millor_1", "millor_n", "pitjor_1", "pitjor_n"}


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


def _normalize_candidate_source_entry(raw_entry, *, fallback_mode="raw_exercise", fallback_cfg=None):
    entry = raw_entry if isinstance(raw_entry, dict) else {}
    mode = _normalize_candidate_source_mode(entry.get("mode") or fallback_mode)
    out = {"mode": mode}
    if mode in {"participant_aggregate", "team_aggregate"}:
        out["cfg"] = _normalize_candidate_source_cfg(entry.get("cfg"), fallback=fallback_cfg)
    return out


def _compact_candidate_source_entry_for_persistence(raw_entry):
    entry = raw_entry if isinstance(raw_entry, dict) else {}
    mode = _normalize_candidate_source_mode(entry.get("mode") or "raw_exercise")
    out = {"mode": mode}
    if mode in {"participant_aggregate", "team_aggregate"}:
        out["cfg"] = _compact_candidate_source_cfg_for_persistence(entry.get("cfg"))
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


def _compact_exercicis_cfg_for_persistence(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    mode = str(cfg.get("mode") or "tots").strip().lower() or "tots"
    out = {"mode": mode}
    if mode in {"millor_n", "pitjor_n"}:
        out["best_n"] = max(1, int(cfg.get("best_n") or 1))
    elif mode == "index":
        out["index"] = max(1, int(cfg.get("index") or 1))
    elif mode == "llista":
        out["ids"] = _unique_positive_ints(cfg.get("ids"))
    try:
        max_per_participant = int(cfg.get("max_per_participant") or 0)
    except Exception:
        max_per_participant = 0
    if max_per_participant > 0:
        out["max_per_participant"] = max_per_participant
    return out


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


def resolve_pipeline_target_app_ids(pipeline):
    item = pipeline if isinstance(pipeline, dict) else {}
    app_cfg = item.get("aparells") if isinstance(item.get("aparells"), dict) else {}
    return _unique_positive_ints(app_cfg.get("ids"))


def compact_pipeline_for_save(raw_pipeline):
    pipeline = raw_pipeline if isinstance(raw_pipeline, dict) else {}
    selected_ids = resolve_pipeline_target_app_ids(pipeline)
    camps_map = pipeline.get("camps_per_aparell") if isinstance(pipeline.get("camps_per_aparell"), dict) else {}
    agg_map = pipeline.get("agregacio_camps_per_aparell") if isinstance(pipeline.get("agregacio_camps_per_aparell"), dict) else {}
    source_map = pipeline.get("candidate_source_per_aparell") if isinstance(pipeline.get("candidate_source_per_aparell"), dict) else {}
    ex_map = pipeline.get("exercicis_per_aparell") if isinstance(pipeline.get("exercicis_per_aparell"), dict) else {}
    agg_ex_map = pipeline.get("agregacio_exercicis_per_aparell") if isinstance(pipeline.get("agregacio_exercicis_per_aparell"), dict) else {}
    out = {
        "aparells": {
            "mode": "seleccionar",
            "ids": selected_ids,
        },
        "camps_per_aparell": {},
        "agregacio_camps_per_aparell": {},
        "agregacio_camps": _normalize_aggregation(pipeline.get("agregacio_camps"), "sum"),
        "candidate_source_mode": _normalize_candidate_source_mode(pipeline.get("candidate_source_mode")),
        "candidate_source_cfg": _compact_candidate_source_cfg_for_persistence(pipeline.get("candidate_source_cfg")),
        "candidate_source_per_aparell": {},
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
        out["exercise_selection_scope"] = normalize_exercise_selection_scope(
            pipeline.get("exercise_selection_scope")
        ) or EXERCISE_SELECTION_SCOPE_PER_MEMBER
    if isinstance(pipeline.get("participants"), dict):
        out["participants"] = _normalize_participants_cfg(pipeline.get("participants"))
        if "agregacio_participants" in pipeline:
            out["agregacio_participants"] = _normalize_aggregation(pipeline.get("agregacio_participants"), "sum")
    for app_id in selected_ids:
        key = str(app_id)
        out["camps_per_aparell"][key] = _unique_nonempty_strings(
            camps_map.get(key) or camps_map.get(app_id) or ["total"]
        )
        out["agregacio_camps_per_aparell"][key] = _normalize_aggregation(
            agg_map.get(key) or agg_map.get(app_id),
            fallback=out["agregacio_camps"],
        )
        out["candidate_source_per_aparell"][key] = _compact_candidate_source_entry_for_persistence(
            source_map.get(key) or source_map.get(app_id) or {}
        )
        if key in ex_map or app_id in ex_map:
            out["exercicis_per_aparell"][key] = _compact_exercicis_cfg_for_persistence(
                ex_map.get(key) or ex_map.get(app_id),
            )
        if key in agg_ex_map or app_id in agg_ex_map:
            out["agregacio_exercicis_per_aparell"][key] = _normalize_aggregation(
                agg_ex_map.get(key) or agg_ex_map.get(app_id),
                fallback=out["agregacio_exercicis"],
            )
    if not out["candidate_source_per_aparell"]:
        out["candidate_source_per_aparell"] = {
            str(app_id): {"mode": out["candidate_source_mode"]}
            for app_id in out["aparells"]["ids"]
        }
    if not out["agregacio_exercicis_per_aparell"]:
        out.pop("agregacio_exercicis_per_aparell", None)
    if not out["exercicis_per_aparell"]:
        out.pop("exercicis_per_aparell", None)
    return out


def strip_pipeline_keys(pipeline, *keys):
    out = dict(pipeline if isinstance(pipeline, dict) else {})
    for key in keys:
        out.pop(key, None)
    return out


class TieContractBase:
    name = "per_member"
    removed_pipeline_keys = ()

    def sanitize_pipeline_for_save(self, pipeline, context):
        out = compact_pipeline_for_save(pipeline)
        if self.removed_pipeline_keys:
            out = strip_pipeline_keys(out, *self.removed_pipeline_keys)
        return out

    def sanitize_item_for_save(self, item, context):
        out = deepcopy(item if isinstance(item, dict) else {})
        out["pipeline"] = self.sanitize_pipeline_for_save(out.get("pipeline"), context)
        out["pipeline_version"] = PIPELINE_VERSION
        return out
