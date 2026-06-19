"""Ranking helpers extracted from the legacy classificacions engine."""

from __future__ import annotations

import json

from ..filters import normalize_exercise_selection_scope
from .selection import _normalize_exercicis_cfg


def _to_float(value):
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _json_clone(value):
    try:
        return json.loads(json.dumps(value))
    except Exception:
        return value


def _normalize_tie_camps(crit: dict) -> list[str]:
    raw = crit.get("camps", None)
    out = []

    if isinstance(raw, list):
        out = [str(item).strip() for item in raw if str(item).strip()]
    elif isinstance(raw, str):
        txt = raw.strip()
        if txt:
            out = [item.strip() for item in txt.split(",") if item.strip()]

    if not out:
        legacy = str(crit.get("camp") or "").strip()
        if legacy:
            out = [legacy]

    dedup = []
    seen = set()
    for item in out:
        if item in seen:
            continue
        seen.add(item)
        dedup.append(item)
    return dedup


def _is_pipeline_tie(crit: dict) -> bool:
    return isinstance(crit, dict) and isinstance(crit.get("pipeline"), dict)


def _pipeline_tie_signature(crit: dict) -> str:
    if not isinstance(crit, dict):
        return ""
    try:
        pipeline_version = int(crit.get("pipeline_version") or 1)
    except Exception:
        pipeline_version = 1
    payload = {
        "id": str(crit.get("id") or "").strip(),
        "nom": str(crit.get("nom") or "").strip(),
        "ordre": str(crit.get("ordre") or "desc").lower().strip() or "desc",
        "pipeline_version": pipeline_version,
        "pipeline": _json_clone(crit.get("pipeline") or {}),
    }
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return str(payload)


def _tie_key(crit: dict) -> str:
    if _is_pipeline_tie(crit):
        tie_id = str((crit or {}).get("id") or "").strip()
        if tie_id:
            return tie_id
        return _pipeline_tie_signature(crit)

    camps = _normalize_tie_camps(crit)
    if not camps:
        return ""

    scope = crit.get("scope") or {}
    apps = scope.get("aparells") or {}
    exercicis = scope.get("exercicis") or {}
    participants = scope.get("participants") or {}

    mode = str(apps.get("mode") or "").lower().strip()
    if mode == "seleccionar":
        ids = apps.get("ids") or []
        ids_norm = ",".join(str(int(item)) for item in ids) if ids else ""
        apps_sig = f"apps[{ids_norm}]"
    elif mode == "tots":
        apps_sig = "apps[all]"
    else:
        app_id = crit.get("aparell_id", None)
        apps_sig = f"app[{app_id}]" if app_id not in (None, "", 0, "0") else "apps[inherit]"

    ex_mode = str(exercicis.get("mode") or "hereta").lower().strip()
    ex_sig = ex_mode
    if ex_mode in ("millor_n", "pitjor_n"):
        ex_sig += f":{exercicis.get('best_n') or ''}"
    elif ex_mode == "index":
        ex_sig += f":{exercicis.get('index') or 1}"
    elif ex_mode == "llista":
        ex_ids = exercicis.get("ids") or []
        ex_sig += ":" + ",".join(str(int(item)) for item in ex_ids)
    try:
        ex_max_pp = int(exercicis.get("max_per_participant") or 0)
    except Exception:
        ex_max_pp = 0
    if ex_max_pp > 0:
        ex_sig += f":mpp={ex_max_pp}"

    ex_sel_mode = (
        crit.get("mode_seleccio_exercicis")
        or exercicis.get("mode_seleccio_exercicis")
        or "hereta"
    )
    ex_sel_mode = str(ex_sel_mode).lower().strip()
    if ex_sel_mode not in ("hereta", "per_aparell_global", "per_aparell_override", "global_pool"):
        ex_sel_mode = "hereta"

    ex_sel_scope = normalize_exercise_selection_scope(
        crit.get("exercise_selection_scope"),
        allow_inherit=True,
    )

    ex_per_app = crit.get("exercicis_per_aparell") or exercicis.get("exercicis_per_aparell") or {}
    ex_per_app_sig = ""
    if isinstance(ex_per_app, dict) and ex_per_app:
        chunks = []
        fallback_cfg = {"mode": "tots", "best_n": 1, "index": 1, "ids": [], "max_per_participant": 0}
        for key in sorted(ex_per_app.keys(), key=lambda item: str(item)):
            cfg = _normalize_exercicis_cfg(ex_per_app.get(key), fallback=fallback_cfg)
            chunk = f"{key}:{cfg.get('mode')}"
            if cfg.get("mode") in ("millor_n", "pitjor_n"):
                chunk += f":n={cfg.get('best_n')}"
            elif cfg.get("mode") == "index":
                chunk += f":i={cfg.get('index')}"
            elif cfg.get("mode") == "llista":
                ids_txt = ",".join(str(int(item)) for item in (cfg.get("ids") or []))
                chunk += f":ids={ids_txt}"
            if int(cfg.get("max_per_participant") or 0) > 0:
                chunk += f":mpp={int(cfg.get('max_per_participant') or 0)}"
            chunks.append(chunk)
        ex_per_app_sig = ";".join(chunks)

    agg_ex_per_app = crit.get("agregacio_exercicis_per_aparell") or {}
    agg_ex_per_app_sig = ""
    if isinstance(agg_ex_per_app, dict) and agg_ex_per_app:
        chunks = []
        for key in sorted(agg_ex_per_app.keys(), key=lambda item: str(item)):
            agg_value = str(agg_ex_per_app.get(key) or "sum").lower().strip()
            chunks.append(f"{key}:{agg_value}")
        agg_ex_per_app_sig = ";".join(chunks)

    p_mode = str(participants.get("mode") or "hereta").lower().strip()
    p_sig = p_mode
    if p_mode in ("millor_n", "pitjor_n"):
        p_sig += f":{participants.get('n') or 1}"

    camps_sig = ",".join(camps)
    agg_c = str(crit.get("agregacio_camps") or "hereta").lower().strip()
    agg_e = str(crit.get("agregacio_exercicis") or "hereta").lower().strip()
    agg_a = str(crit.get("agregacio_aparells") or "hereta").lower().strip()
    p_agg = str(crit.get("agregacio_participants") or "sum").lower().strip()
    return (
        f"camps[{camps_sig}]|{apps_sig}|ex[{ex_sig}]"
        f"|ex_sel[{ex_sel_mode}]|ex_scope[{ex_sel_scope}]|ex_app[{ex_per_app_sig}]|agg_ex_app[{agg_ex_per_app_sig}]"
        f"|agg_c[{agg_c}]|agg_e[{agg_e}]|agg_a[{agg_a}]"
        f"|parts[{p_sig}]|parts_agg[{p_agg}]"
    )


def _rank_v2(rows, desempat, presentacio, ordre_principal="desc", entity_mode=False):
    """Rank rows using the legacy score-plus-tiebreak ordering semantics."""

    sort_keys = [("score", ordre_principal)]

    for tie in desempat or []:
        key = _tie_key(tie)
        if not key:
            continue
        ordre = str((tie.get("ordre") or "desc")).lower().strip()
        sort_keys.append((key, ordre))

    def keyfunc(row):
        key = []
        for field, ordre in sort_keys:
            if field == "score":
                value = _to_float(row.get("score", 0.0))
            else:
                value = _to_float((row.get("tie") or {}).get(field, 0.0))
            key.append(-value if ordre == "desc" else value)
        return tuple(key)

    rows_sorted = sorted(rows, key=keyfunc)

    mostrar_empats = bool((presentacio or {}).get("mostrar_empats", True))
    top_n = int((presentacio or {}).get("top_n") or 0)

    ranked = []
    last_key = None
    posicio = 0
    shown = 0

    for idx, row in enumerate(rows_sorted, start=1):
        cur_key = keyfunc(row)
        if last_key is None or cur_key != last_key:
            posicio = idx
        last_key = cur_key

        row_out = dict(row)
        row_out["posicio"] = posicio
        row_out["punts"] = round(_to_float(row.get("score", 0.0)), 3)

        ranked.append(row_out)
        shown += 1

        if top_n and shown >= top_n:
            if mostrar_empats and idx < len(rows_sorted):
                if keyfunc(rows_sorted[idx]) == cur_key:
                    continue
            break

    for row in ranked:
        row.pop("tiebreak_reason", None)
        row.pop("definitive_tie", None)

    for idx in range(len(ranked) - 1):
        winner = ranked[idx]
        loser = ranked[idx + 1]
        if _to_float(winner.get("score")) != _to_float(loser.get("score")):
            continue

        for criterion_index, tie in enumerate(desempat or [], start=1):
            key = _tie_key(tie)
            if not key:
                continue
            winner_value = _to_float((winner.get("tie") or {}).get(key, 0.0))
            loser_value = _to_float((loser.get("tie") or {}).get(key, 0.0))
            if winner_value == loser_value:
                continue

            label = str((tie or {}).get("nom") or (tie or {}).get("label") or "").strip()
            winner["tiebreak_reason"] = {
                "criterion_number": criterion_index,
                "criterion_id": str((tie or {}).get("id") or key).strip(),
                "label": label,
                "order": "asc" if str((tie or {}).get("ordre") or "desc").strip().lower() == "asc" else "desc",
                "winner_value": winner_value,
                "loser_value": loser_value,
            }
            break

    idx = 0
    while idx < len(ranked):
        current_key = keyfunc(ranked[idx])
        end = idx + 1
        while end < len(ranked) and keyfunc(ranked[end]) == current_key:
            end += 1
        if end - idx > 1:
            for row in ranked[idx:end]:
                row["definitive_tie"] = True
        idx = end

    return ranked


__all__ = ["_rank_v2"]
