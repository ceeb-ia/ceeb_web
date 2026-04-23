"""Metric and tie runtime helpers extracted from the legacy classificacions engine."""

from __future__ import annotations

import inspect
import json
import logging

from ..filters import EXERCISE_SELECTION_SCOPE_TEAM_POOL, normalize_team_mode
from ..pipeline_runtime import compute_metric_from_pipeline, materialize_desempat_item
from .common import json_clone_value, normalize_positive_int, normalized_text_token
from .ranking import _is_pipeline_tie, _normalize_tie_camps, _pipeline_tie_signature, _tie_key
from .score_values import _apply_simple_agg, _to_float
from .selection import _pick_exercicis_rows, _pick_exercicis_tuples, _pick_participants


logger = logging.getLogger(__name__)


def _copy_ex_row_with_value(row, value):
    item = dict(row or {})
    item["value"] = _to_float(value)
    item["by_camp"] = dict((row or {}).get("by_camp") or {})

    raw_sources = (row or {}).get("source_rows")
    if isinstance(raw_sources, list) and raw_sources:
        item["source_rows"] = [
            {
                "idx": int((src or {}).get("idx", 0) or 0),
                "app_id": int((src or {}).get("app_id", 0) or 0),
                "app_order": int((src or {}).get("app_order", 0) or 0),
                "exercici": int((src or {}).get("exercici", 1) or 1),
                "inscripcio_id": normalize_positive_int((src or {}).get("inscripcio_id")),
                "equip_id": normalize_positive_int((src or {}).get("equip_id")),
                "value": _to_float((src or {}).get("value")),
                "by_camp": dict((src or {}).get("by_camp") or {}),
            }
            for src in raw_sources
            if isinstance(src, dict)
        ]
    elif isinstance(row, dict):
        item["source_rows"] = [
            {
                "idx": int(row.get("idx", 0) or 0),
                "app_id": int(row.get("app_id", 0) or 0),
                "app_order": int(row.get("app_order", 0) or 0),
                "exercici": int(row.get("exercici", 1) or 1),
                "inscripcio_id": normalize_positive_int(row.get("inscripcio_id")),
                "equip_id": normalize_positive_int(row.get("equip_id")),
                "value": _to_float(row.get("value")),
                "by_camp": dict(row.get("by_camp") or {}),
            }
        ]
    return item


def _dedupe_int_ids_preserve_order(raw_ids):
    out = []
    seen = set()
    for raw_id in raw_ids or []:
        parsed = normalize_positive_int(raw_id)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        out.append(parsed)
    return out


def build_metrics_runtime(**kwargs):
    runtime = dict(kwargs)
    runtime["tipus"] = str(runtime.get("tipus") or "individual").strip().lower() or "individual"
    runtime["team_mode"] = normalize_team_mode(runtime.get("team_mode"))
    runtime["selected_app_ids"] = _dedupe_int_ids_preserve_order(runtime.get("selected_app_ids") or [])
    runtime.setdefault("metric_cache", {})
    runtime.setdefault("pipeline_metric_cache", {})
    runtime.setdefault("pipeline_metric_cache_ready", {})
    runtime.setdefault("pipeline_runtime_ctx_cache", {})
    return runtime


def _runtime_dict(runtime):
    if isinstance(runtime, dict):
        runtime.setdefault("metric_cache", {})
        runtime.setdefault("pipeline_metric_cache", {})
        runtime.setdefault("pipeline_metric_cache_ready", {})
        runtime.setdefault("pipeline_runtime_ctx_cache", {})
        runtime.setdefault("selected_app_ids", [])
        runtime.setdefault("tipus", "individual")
        runtime["team_mode"] = normalize_team_mode(runtime.get("team_mode"))
        return runtime
    return build_metrics_runtime()


def _required_positional_params(func):
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return None

    return sum(
        1
        for param in signature.parameters.values()
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and param.default is inspect.Parameter.empty
    )


def _resolve_group_cache_key(builder, member_ids):
    required = _required_positional_params(builder)
    if required is None:
        try:
            return builder(None, member_ids)
        except TypeError:
            return builder(member_ids)
    if required <= 1:
        return builder(member_ids)
    return builder(None, member_ids)


def _adapt_group_runtime_helper(runtime_dict, key):
    value = runtime_dict.get(key)
    if not callable(value):
        return None

    required = _required_positional_params(value)
    if required is None or required <= 1:
        return value

    cache_key_builder = runtime_dict.get("derived_team_cache_key")
    if not callable(cache_key_builder):
        return value

    def _wrapped(member_ids, _value=value, _cache_key_builder=cache_key_builder):
        mids = _dedupe_int_ids_preserve_order(member_ids or [])
        cache_key = _resolve_group_cache_key(_cache_key_builder, mids)
        return _value(cache_key, mids)

    return _wrapped


def build_pipeline_runtime_context(runtime):
    runtime_dict = _runtime_dict(runtime)
    cached = (runtime_dict.get("pipeline_runtime_ctx_cache") or {}).get("ctx")
    if cached is not None:
        return cached

    ctx = {
        "app_ex_rows_by_ins": runtime_dict.get("app_ex_rows_by_ins") or {},
        "team_app_ex_rows_by_equip": runtime_dict.get("team_app_ex_rows_by_equip") or {},
        "app_order": runtime_dict.get("app_order") or {},
        "copy_ex_row_with_value": runtime_dict.get("copy_ex_row_with_value") or _copy_ex_row_with_value,
        "to_float": runtime_dict.get("to_float") or _to_float,
        "apply_simple_agg": runtime_dict.get("apply_simple_agg") or _apply_simple_agg,
        "pick_exercicis_rows": runtime_dict.get("pick_exercicis_rows") or _pick_exercicis_rows,
        "pick_exercicis_tuples": runtime_dict.get("pick_exercicis_tuples") or _pick_exercicis_tuples,
        "pick_participants": runtime_dict.get("pick_participants") or _pick_participants,
    }

    for key in ("get_main_selected_contributors_for_individual", "get_main_selected_contributors_for_native_team"):
        value = runtime_dict.get(key)
        if callable(value):
            ctx[key] = value

    for key in ("get_main_selected_rows_for_group", "get_main_selected_contributors_for_group"):
        value = _adapt_group_runtime_helper(runtime_dict, key)
        if callable(value):
            ctx[key] = value

    runtime_dict["pipeline_runtime_ctx_cache"]["ctx"] = ctx
    return ctx


def _pipeline_subject_key(row: dict):
    if not isinstance(row, dict):
        return None

    ins_id = normalize_positive_int(row.get("inscripcio_id"))
    if ins_id is not None:
        return ("ins", ins_id)

    equip_id = normalize_positive_int(row.get("equip_id"))
    if equip_id is not None:
        return ("equip", equip_id)

    member_ids = row.get("_member_ids")
    if isinstance(member_ids, (list, tuple)) and member_ids:
        mids = _dedupe_int_ids_preserve_order(member_ids)
        if mids:
            return ("members", tuple(sorted(set(mids))))

    entitat_nom = str(row.get("entitat_nom") or "").strip()
    if entitat_nom:
        return ("entitat", normalized_text_token(entitat_nom))

    participant = str(row.get("participant") or row.get("nom") or "").strip()
    if participant:
        return ("nom", normalized_text_token(participant))

    return None


def _sanitize_desempat_for_tipus(desempat, tipus):
    out = []
    tipus_norm = str(tipus or "individual").strip().lower() or "individual"

    for raw in desempat or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        if tipus_norm != "equips":
            scope = item.get("scope")
            if isinstance(scope, dict):
                scope_out = dict(scope)
                scope_out.pop("participants", None)
                item["scope"] = scope_out
            item.pop("agregacio_participants", None)
        out.append(item)

    return out


def _metric_signature(crit: dict, forced_app_ids=None, forced_exercici_ids=None, forced_camps=None) -> str:
    payload = {"crit": crit or {}}
    if forced_app_ids is not None:
        payload["forced_app_ids"] = _dedupe_int_ids_preserve_order(forced_app_ids or [])
    if forced_exercici_ids is not None:
        payload["forced_exercici_ids"] = _dedupe_int_ids_preserve_order(forced_exercici_ids or [])
    if forced_camps is not None:
        payload["forced_camps"] = [str(item).strip() for item in (forced_camps or []) if str(item).strip()]
    try:
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return str(_tie_key(crit) or crit or "")


def _resolve_pipeline_app_ids(pipeline, fallback_ids=None):
    app_cfg = (pipeline or {}).get("aparells") if isinstance((pipeline or {}).get("aparells"), dict) else {}
    return _dedupe_int_ids_preserve_order((app_cfg or {}).get("ids") or fallback_ids or [])


def _prepare_metric_tie(
    runtime,
    crit: dict,
    *,
    allow_participants,
    forced_app_ids=None,
    forced_exercici_ids=None,
    forced_camps=None,
):
    runtime_dict = _runtime_dict(runtime)
    if not isinstance(crit, dict):
        return {}

    if forced_camps is not None:
        camps = [str(item).strip() for item in (forced_camps or []) if str(item).strip()]
        if not camps:
            return {}

    if _is_pipeline_tie(crit):
        item = json_clone_value(crit)
    else:
        item = materialize_desempat_item(
            crit,
            tipus=runtime_dict.get("tipus"),
            team_mode=runtime_dict.get("team_mode"),
            selected_app_ids=runtime_dict.get("selected_app_ids") or [],
            allow_participants=allow_participants,
            fallback_pipeline=runtime_dict.get("fallback_pipeline"),
        )
    if not isinstance(item, dict):
        return {}

    pipeline = item.get("pipeline")
    if not isinstance(pipeline, dict):
        return {}
    pipeline = json_clone_value(pipeline)

    target_app_ids = _resolve_pipeline_app_ids(pipeline, runtime_dict.get("selected_app_ids") or [])
    if forced_app_ids is not None:
        target_app_ids = _dedupe_int_ids_preserve_order(forced_app_ids or [])
        if not target_app_ids:
            return {}
        pipeline["aparells"] = {"mode": "seleccionar", "ids": target_app_ids}

    if forced_camps is not None:
        camps = [str(item).strip() for item in (forced_camps or []) if str(item).strip()]
        pipeline.setdefault("camps_mode_per_aparell", {})
        pipeline.setdefault("camps_per_aparell", {})
        for app_id in target_app_ids:
            app_key = str(app_id)
            pipeline["camps_mode_per_aparell"][app_key] = "comu"
            pipeline["camps_per_aparell"][app_key] = list(camps)

    if forced_exercici_ids is not None:
        exercici_ids = _dedupe_int_ids_preserve_order(forced_exercici_ids or [])
        if not exercici_ids:
            return {}
        pipeline["mode_seleccio_exercicis"] = "per_aparell_global"
        pipeline["exercicis"] = {
            "mode": "llista",
            "best_n": 1,
            "index": 1,
            "ids": exercici_ids,
            "max_per_participant": 0,
        }

    item["pipeline"] = pipeline
    return item


def calc_criterion_value(
    runtime,
    ins_id: int,
    crit: dict,
    forced_app_ids=None,
    forced_exercici_ids=None,
    forced_camps=None,
) -> float:
    runtime_dict = _runtime_dict(runtime)
    inscripcio_id = normalize_positive_int(ins_id)
    if inscripcio_id is None:
        return 0.0

    item = _prepare_metric_tie(
        runtime_dict,
        crit,
        allow_participants=False,
        forced_app_ids=forced_app_ids,
        forced_exercici_ids=forced_exercici_ids,
        forced_camps=forced_camps,
    )
    pipeline = item.get("pipeline") if isinstance(item, dict) else None
    if not isinstance(pipeline, dict):
        return 0.0

    return float(
        compute_metric_from_pipeline(
            build_pipeline_runtime_context(runtime_dict),
            pipeline,
            {"kind": "individual", "inscripcio_id": inscripcio_id},
        )
    )


def calc_metric_value_for_ins(
    runtime,
    ins_id: int,
    crit: dict,
    forced_app_ids=None,
    forced_exercici_ids=None,
    forced_camps=None,
) -> float:
    runtime_dict = _runtime_dict(runtime)
    inscripcio_id = normalize_positive_int(ins_id)
    if inscripcio_id is None:
        return 0.0

    sig = _metric_signature(
        crit,
        forced_app_ids=forced_app_ids,
        forced_exercici_ids=forced_exercici_ids,
        forced_camps=forced_camps,
    )
    cache_key = ("ins", inscripcio_id, sig)
    if cache_key in runtime_dict["metric_cache"]:
        return runtime_dict["metric_cache"][cache_key]

    value = float(
        calc_criterion_value(
            runtime_dict,
            inscripcio_id,
            crit,
            forced_app_ids=forced_app_ids,
            forced_exercici_ids=forced_exercici_ids,
            forced_camps=forced_camps,
        )
    )
    runtime_dict["metric_cache"][cache_key] = value
    return value


def calc_metric_value_for_group(runtime, member_ids, crit: dict) -> float:
    runtime_dict = _runtime_dict(runtime)
    mids = _dedupe_int_ids_preserve_order(member_ids or [])
    if not mids:
        return 0.0

    sig = _metric_signature(crit)
    cache_key = ("group", tuple(mids), sig)
    if cache_key in runtime_dict["metric_cache"]:
        return runtime_dict["metric_cache"][cache_key]

    item = _prepare_metric_tie(
        runtime_dict,
        crit,
        allow_participants=True,
    )
    pipeline = item.get("pipeline") if isinstance(item, dict) else None
    if not isinstance(pipeline, dict):
        return 0.0

    value = float(
        compute_metric_from_pipeline(
            build_pipeline_runtime_context(runtime_dict),
            pipeline,
            {"kind": "group", "member_ids": mids},
        )
    )
    runtime_dict["metric_cache"][cache_key] = value
    return value


def calc_metric_value_for_native_team(runtime, equip_id: int, crit: dict) -> float:
    runtime_dict = _runtime_dict(runtime)
    team_id = normalize_positive_int(equip_id)
    if team_id is None:
        return 0.0

    sig = _metric_signature(crit)
    cache_key = ("native_team", team_id, sig)
    if cache_key in runtime_dict["metric_cache"]:
        return runtime_dict["metric_cache"][cache_key]

    item = _prepare_metric_tie(
        runtime_dict,
        crit,
        allow_participants=False,
    )
    pipeline = item.get("pipeline") if isinstance(item, dict) else None
    if not isinstance(pipeline, dict):
        return 0.0

    value = float(
        compute_metric_from_pipeline(
            build_pipeline_runtime_context(runtime_dict),
            pipeline,
            {"kind": "native_team", "equip_id": team_id},
        )
    )
    runtime_dict["metric_cache"][cache_key] = value
    return value


def _member_id_from_group_item(item):
    if isinstance(item, (list, tuple)) and item:
        return normalize_positive_int(getattr(item[0], "id", item[0]))
    if isinstance(item, dict):
        return normalize_positive_int(item.get("id") or item.get("inscripcio_id"))
    return normalize_positive_int(getattr(item, "id", item))


def _iter_group_subjects(runtime):
    runtime_dict = _runtime_dict(runtime)
    explicit = runtime_dict.get("group_subjects")
    if isinstance(explicit, list):
        for subject in explicit:
            if not isinstance(subject, dict):
                continue
            mids = _dedupe_int_ids_preserve_order(subject.get("member_ids") or [])
            if not mids:
                continue
            yield {
                "equip_id": normalize_positive_int(subject.get("equip_id")),
                "member_ids": mids,
            }
        return

    grouped = runtime_dict.get("grouped") or {}
    seen = set()
    for teams in grouped.values() if isinstance(grouped, dict) else []:
        for team_id_key, members in (teams or {}).items():
            mids = []
            for member in members or []:
                member_id = _member_id_from_group_item(member)
                if member_id is not None:
                    mids.append(member_id)
            mids = _dedupe_int_ids_preserve_order(mids)
            if not mids:
                continue
            equip_id = normalize_positive_int(team_id_key)
            unique_key = (equip_id, tuple(sorted(set(mids))))
            if unique_key in seen:
                continue
            seen.add(unique_key)
            yield {"equip_id": equip_id, "member_ids": mids}


def _iter_native_team_ids(runtime):
    runtime_dict = _runtime_dict(runtime)
    explicit = _dedupe_int_ids_preserve_order(runtime_dict.get("native_team_ids") or [])
    if explicit:
        for team_id in explicit:
            yield team_id
        return

    rows_by_team = runtime_dict.get("team_app_ex_rows_by_equip") or {}
    seen = set()
    for teams in rows_by_team.values() if isinstance(rows_by_team, dict) else []:
        for team_id in (teams or {}).keys():
            parsed = normalize_positive_int(team_id)
            if parsed is None or parsed in seen:
                continue
            seen.add(parsed)
            yield parsed


def _iter_entity_subjects(runtime):
    runtime_dict = _runtime_dict(runtime)
    explicit = runtime_dict.get("entity_subjects")
    if isinstance(explicit, list):
        for subject in explicit:
            if not isinstance(subject, dict):
                continue
            mids = _dedupe_int_ids_preserve_order(subject.get("member_ids") or [])
            entitat = str(subject.get("entitat_nom") or "").strip()
            if not mids or not entitat:
                continue
            yield entitat, mids
        return

    per_particio = runtime_dict.get("per_particio") or {}
    seen = set()
    for rows in per_particio.values() if isinstance(per_particio, dict) else []:
        by_entity = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            entitat = str(row.get("entitat_nom") or "").strip()
            ins_id = normalize_positive_int(row.get("inscripcio_id"))
            if not entitat or ins_id is None:
                continue
            by_entity.setdefault(entitat, []).append(ins_id)
        for entitat, mids in by_entity.items():
            norm = normalized_text_token(entitat)
            if norm in seen:
                continue
            seen.add(norm)
            yield entitat, _dedupe_int_ids_preserve_order(mids)


def _pipeline_metric_cache_is_ready(runtime):
    runtime_dict = _runtime_dict(runtime)
    tipus = str(runtime_dict.get("tipus") or "individual").strip().lower() or "individual"
    if tipus == "individual":
        return True
    if tipus == "equips":
        if normalize_team_mode(runtime_dict.get("team_mode")) == "native_team":
            return bool(
                _dedupe_int_ids_preserve_order(runtime_dict.get("native_team_ids") or [])
                or runtime_dict.get("grouped")
                or runtime_dict.get("team_app_ex_rows_by_equip")
            )
        return bool(runtime_dict.get("group_subjects") or runtime_dict.get("grouped"))
    if tipus == "entitat":
        return bool(runtime_dict.get("entity_subjects") or runtime_dict.get("per_particio"))
    return True


def _pipeline_metric_map_for_crit(runtime, crit: dict):
    runtime_dict = _runtime_dict(runtime)
    item = _prepare_metric_tie(
        runtime_dict,
        crit,
        allow_participants=(runtime_dict.get("tipus") == "equips"),
    )
    pipeline = item.get("pipeline") if isinstance(item, dict) else None
    if not isinstance(pipeline, dict):
        return {}

    sig = _pipeline_tie_signature(item)
    cache_ready = _pipeline_metric_cache_is_ready(runtime_dict)
    cached = runtime_dict["pipeline_metric_cache"].get(sig)
    if cached is not None and (runtime_dict["pipeline_metric_cache_ready"].get(sig) or not cache_ready):
        return cached

    ctx = build_pipeline_runtime_context(runtime_dict)
    out = {}
    tipus = str(runtime_dict.get("tipus") or "individual").strip().lower() or "individual"
    team_mode = normalize_team_mode(runtime_dict.get("team_mode"))

    try:
        if tipus == "individual":
            individual_ids = _dedupe_int_ids_preserve_order(runtime_dict.get("individual_ids") or [])
            if not individual_ids:
                individual_ids = _dedupe_int_ids_preserve_order((runtime_dict.get("per_ins") or {}).keys())
            for inscripcio_id in individual_ids:
                out[("ins", inscripcio_id)] = float(
                    compute_metric_from_pipeline(
                        ctx,
                        pipeline,
                        {"kind": "individual", "inscripcio_id": inscripcio_id},
                    )
                )
        elif tipus == "equips" and team_mode == "native_team":
            for team_id in _iter_native_team_ids(runtime_dict):
                out[("equip", team_id)] = float(
                    compute_metric_from_pipeline(
                        ctx,
                        pipeline,
                        {"kind": "native_team", "equip_id": team_id},
                    )
                )
        elif tipus == "equips":
            for subject in _iter_group_subjects(runtime_dict):
                mids = subject["member_ids"]
                if (
                    str((pipeline or {}).get("exercise_selection_scope") or "").strip().lower()
                    == EXERCISE_SELECTION_SCOPE_TEAM_POOL
                ):
                    value = float(calc_metric_value_for_group(runtime_dict, mids, item))
                else:
                    value = float(
                        compute_metric_from_pipeline(
                            ctx,
                            pipeline,
                            {"kind": "group", "member_ids": mids},
                        )
                    )
                equip_id = subject.get("equip_id")
                if equip_id is not None:
                    out[("equip", equip_id)] = value
                out[("members", tuple(sorted(set(mids))))] = value
        elif tipus == "entitat":
            for entitat_nom, mids in _iter_entity_subjects(runtime_dict):
                out[("entitat", normalized_text_token(entitat_nom))] = float(
                    compute_metric_from_pipeline(
                        ctx,
                        pipeline,
                        {"kind": "group", "member_ids": mids},
                    )
                )
    except Exception as exc:
        logger.warning("Could not compute tie pipeline metric map %s: %s", sig, exc)
        runtime_dict["pipeline_metric_cache"][sig] = {}
        return {}

    runtime_dict["pipeline_metric_cache"][sig] = out
    runtime_dict["pipeline_metric_cache_ready"][sig] = cache_ready
    return out


def pipeline_metric_map_for_crit(runtime, crit: dict):
    return _pipeline_metric_map_for_crit(runtime, crit)


def build_metrics_runtime_adapters(runtime):
    runtime_dict = _runtime_dict(runtime)

    def _calc_metric_value_for_ins(ins_id, crit, **kwargs):
        return calc_metric_value_for_ins(runtime_dict, ins_id, crit, **kwargs)

    def _calc_metric_value_for_group(member_ids, crit):
        return calc_metric_value_for_group(runtime_dict, member_ids, crit)

    def _calc_metric_value_for_native_team(equip_id, crit):
        return calc_metric_value_for_native_team(runtime_dict, equip_id, crit)

    def _pipeline_metric_map(crit):
        return pipeline_metric_map_for_crit(runtime_dict, crit)

    return {
        "build_pipeline_runtime_context": lambda: build_pipeline_runtime_context(runtime_dict),
        "calc_metric_value_for_group": _calc_metric_value_for_group,
        "calc_metric_value_for_ins": _calc_metric_value_for_ins,
        "calc_metric_value_for_native_team": _calc_metric_value_for_native_team,
        "pipeline_metric_map_for_crit": _pipeline_metric_map,
    }


__all__ = [
    "_is_pipeline_tie",
    "_normalize_tie_camps",
    "_pipeline_metric_map_for_crit",
    "_pipeline_subject_key",
    "_pipeline_tie_signature",
    "_sanitize_desempat_for_tipus",
    "_tie_key",
    "build_metrics_runtime",
    "build_metrics_runtime_adapters",
    "build_pipeline_runtime_context",
    "calc_criterion_value",
    "calc_metric_value_for_group",
    "calc_metric_value_for_ins",
    "calc_metric_value_for_native_team",
    "pipeline_metric_map_for_crit",
]
