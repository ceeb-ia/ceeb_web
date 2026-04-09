from types import SimpleNamespace

from .builder import with_mode_resolution
from .compute import compute_classificacio
from .display import get_display_columns
from .partitions import normalize_schema_legacy_team_birth_partition
from .validation import (
    build_validation_error_details,
    validate_schema_for_competicio_detailed,
)


def _normalize_candidate_source_mode(raw_mode):
    mode = str(raw_mode or "raw_exercise").strip().lower()
    return mode if mode in {"raw_exercise", "participant_aggregate"} else "raw_exercise"


def _sanitize_candidate_source_cfg(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    mode = str(cfg.get("mode") or "tots").strip().lower()
    if mode not in {"tots", "millor_1", "millor_n", "pitjor_1", "pitjor_n", "primer", "ultim", "index", "llista"}:
        mode = "tots"
    try:
        best_n = max(1, int(cfg.get("best_n") or 1))
    except Exception:
        best_n = 1
    try:
        index = max(1, int(cfg.get("index") or 1))
    except Exception:
        index = 1
    raw_ids = cfg.get("ids") or []
    if isinstance(raw_ids, str):
        raw_ids = [x.strip() for x in raw_ids.split(",") if x and x.strip()]
    ids = []
    seen = set()
    if isinstance(raw_ids, (list, tuple)):
        for raw in raw_ids:
            try:
                value = int(raw)
            except Exception:
                continue
            if value > 0 and value not in seen:
                seen.add(value)
                ids.append(value)
    agg = str(cfg.get("agregacio_exercicis") or "sum").strip().lower()
    if agg not in {"sum", "avg", "median", "max", "min"}:
        agg = "sum"
    return {
        "mode": mode,
        "best_n": best_n,
        "index": index,
        "ids": ids,
        "agregacio_exercicis": agg,
    }


def _sync_per_app_puntuacio_legacy_mirrors(schema_local):
    schema = schema_local if isinstance(schema_local, dict) else {}
    punt = schema.get("puntuacio")
    if not isinstance(punt, dict):
        return schema_local
    app_ids = []
    seen = set()
    for raw in ((punt.get("aparells") or {}).get("ids") or []):
        try:
            app_id = int(raw)
        except Exception:
            continue
        if app_id > 0 and app_id not in seen:
            seen.add(app_id)
            app_ids.append(app_id)

    agg_map = punt.get("agregacio_camps_per_aparell") or {}
    if isinstance(agg_map, dict) and app_ids:
        values = []
        for app_id in app_ids:
            raw = agg_map.get(str(app_id))
            if raw is None:
                raw = agg_map.get(app_id)
            agg = str(raw or "sum").strip().lower()
            if agg not in {"sum", "avg", "median", "max", "min"}:
                agg = "sum"
            values.append(agg)
        punt["agregacio_camps"] = values[0] if values and all(value == values[0] for value in values) else "sum"

    candidate_map = punt.get("candidate_source_per_aparell") or {}
    if isinstance(candidate_map, dict) and app_ids:
        entries = []
        for app_id in app_ids:
            raw_entry = candidate_map.get(str(app_id))
            if raw_entry is None:
                raw_entry = candidate_map.get(app_id)
            entry = raw_entry if isinstance(raw_entry, dict) else {}
            mode = _normalize_candidate_source_mode(entry.get("mode") or "raw_exercise")
            cfg = _sanitize_candidate_source_cfg(entry.get("cfg") or {})
            entries.append({"mode": mode, "cfg": cfg})
        first = entries[0] if entries else {"mode": "raw_exercise", "cfg": _sanitize_candidate_source_cfg({})}
        if entries and all(entry == first for entry in entries):
            punt["candidate_source_mode"] = first["mode"]
            punt["candidate_source_cfg"] = first["cfg"]
        else:
            punt["candidate_source_mode"] = "raw_exercise"
            punt["candidate_source_cfg"] = _sanitize_candidate_source_cfg({})

    schema["puntuacio"] = punt
    return schema


def prepare_schema_for_persistence(competicio, schema_local, *, tipus="individual"):
    schema_local, validation_errors, validation_details = validate_schema_for_competicio_detailed(
        competicio,
        schema_local,
        tipus=tipus,
    )
    if validation_errors:
        return {
            "schema": schema_local,
            "errors": validation_errors,
            "error_details": build_validation_error_details(validation_details or validation_errors),
        }

    schema_local, _legacy_info = normalize_schema_legacy_team_birth_partition(
        competicio,
        schema_local,
        tipus=tipus,
        persist=True,
    )
    schema_local = _sync_per_app_puntuacio_legacy_mirrors(schema_local)
    schema_local = with_mode_resolution(competicio, tipus, schema_local)
    return {
        "schema": schema_local,
        "errors": [],
        "error_details": [],
    }


def execute_classificacio_runtime(
    competicio,
    *,
    schema_local,
    tipus="individual",
    compute_fn=compute_classificacio,
    invalid_message="Configuracio de classificacio invalida.",
    runtime_message="No s'ha pogut renderitzar la classificacio.",
):
    schema_local, validation_errors, validation_details = validate_schema_for_competicio_detailed(
        competicio,
        schema_local,
        tipus=tipus,
    )
    columns = get_display_columns(schema_local if isinstance(schema_local, dict) else (schema_local or {}))
    if validation_errors:
        return {
            "schema": schema_local,
            "columns": columns,
            "parts": [],
            "error": {
                "message": invalid_message,
                "errors": validation_errors,
                "error_details": build_validation_error_details(validation_details or validation_errors),
            },
        }

    try:
        data = compute_fn(
            competicio,
            SimpleNamespace(schema=schema_local, tipus=tipus),
        )
    except Exception as exc:
        errors = [str(exc or "").strip() or runtime_message]
        return {
            "schema": schema_local,
            "columns": columns,
            "parts": [],
            "error": {
                "message": runtime_message,
                "errors": errors,
                "error_details": build_validation_error_details(errors),
            },
        }

    return {
        "schema": schema_local,
        "columns": columns,
        "parts": [{"particio": key, "rows": data[key]} for key in sorted(data.keys())],
        "error": None,
    }


__all__ = [
    "execute_classificacio_runtime",
    "prepare_schema_for_persistence",
]
