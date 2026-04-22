"""Victories-mode helpers extracted from the legacy classificacions engine."""

from __future__ import annotations


def _to_float(value):
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _median(values):
    ordered = sorted(_to_float(item) for item in (values or []))
    if not ordered:
        return 0.0
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def _apply_simple_agg(values, mode: str):
    normalized = [_to_float(item) for item in (values or [])]
    if not normalized:
        return 0.0
    agg_mode = str(mode or "sum").lower().strip()
    if agg_mode == "sum":
        return float(sum(normalized))
    if agg_mode == "avg":
        return float(sum(normalized) / len(normalized))
    if agg_mode == "max":
        return float(max(normalized))
    if agg_mode == "min":
        return float(min(normalized))
    if agg_mode == "median":
        return float(_median(normalized))
    return float(sum(normalized))


def _normalize_mode_resultat_aparells(raw_mode) -> str:
    mode = str(raw_mode or "score").lower().strip()
    if mode not in {"score", "victories"}:
        return "score"
    return mode


def _sanitize_victories_compare_ties(compare_ties):
    out = []
    for raw in compare_ties or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item.pop("aparell_id", None)
        item.pop("agregacio_participants", None)

        scope = item.get("scope") or {}
        scope_out = {}
        if isinstance(scope, dict):
            ex_scope = scope.get("exercicis")
            if isinstance(ex_scope, dict):
                scope_out["exercicis"] = dict(ex_scope)
        item["scope"] = scope_out
        out.append(item)
    return out


def _normalize_victories_cfg(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    try:
        punts_victoria = float(cfg.get("punts_victoria", 1))
    except Exception:
        punts_victoria = 1.0
    try:
        punts_empat = float(cfg.get("punts_empat", 0.5))
    except Exception:
        punts_empat = 0.5

    sense_nota_mode = str(cfg.get("sense_nota_mode") or "skip").lower().strip()
    if sense_nota_mode not in {"skip"}:
        sense_nota_mode = "skip"

    mode_camps = str(cfg.get("mode_camps") or "agregat").lower().strip()
    if mode_camps not in {"agregat", "separat"}:
        mode_camps = "agregat"

    mode_exercicis = str(cfg.get("mode_exercicis") or "agregat").lower().strip()
    if mode_exercicis not in {"agregat", "separat"}:
        mode_exercicis = "agregat"

    mode_sel_camps_sep = str(
        cfg.get("mode_seleccio_exercicis_camps_separats") or "per_camp"
    ).lower().strip()
    if mode_sel_camps_sep not in {"per_camp", "global"}:
        mode_sel_camps_sep = "per_camp"

    agg_victories_camps = str(cfg.get("agregacio_victories_camps") or "sum").lower().strip()
    if agg_victories_camps not in {"sum", "avg", "median", "max", "min"}:
        agg_victories_camps = "sum"

    agg_victories_exercicis = str(cfg.get("agregacio_victories_exercicis") or "sum").lower().strip()
    if agg_victories_exercicis not in {"sum", "avg", "median", "max", "min"}:
        agg_victories_exercicis = "sum"

    return {
        "punts_victoria": punts_victoria,
        "punts_empat": punts_empat,
        "sense_nota_mode": sense_nota_mode,
        "mode_camps": mode_camps,
        "mode_exercicis": mode_exercicis,
        "mode_seleccio_exercicis_camps_separats": mode_sel_camps_sep,
        "agregacio_victories_camps": agg_victories_camps,
        "agregacio_victories_exercicis": agg_victories_exercicis,
        "desempat_comparacio": _sanitize_victories_compare_ties(cfg.get("desempat_comparacio") or []),
    }


def _row_base_for_app(row, app_id):
    by_app_base = row.get("by_app_base") or {}
    if app_id in by_app_base:
        return _to_float(by_app_base.get(app_id))
    return _to_float(by_app_base.get(str(app_id)))


def _row_has_app(row, app_id):
    by_app_base = row.get("by_app_base") or {}
    return app_id in by_app_base or str(app_id) in by_app_base


def _compute_victory_points_for_entries(
    entries,
    ordre_principal,
    victories_cfg,
    metric_value_getter,
    *,
    forced_app_ids=None,
    forced_exercici_ids=None,
    forced_camps=None,
):
    punts_victoria = _to_float(victories_cfg.get("punts_victoria", 1.0))
    punts_empat = _to_float(victories_cfg.get("punts_empat", 0.5))
    compare_ties = victories_cfg.get("desempat_comparacio") or []
    entries = entries or []
    if not entries:
        return {}

    entries_enriched = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        row = entry.get("row") or {}
        ins_id = row.get("inscripcio_id")
        if ins_id in (None, ""):
            continue
        compare_vals = []
        for crit in compare_ties:
            compare_vals.append(
                _to_float(
                    metric_value_getter(
                        ins_id,
                        crit,
                        forced_app_ids=forced_app_ids,
                        forced_exercici_ids=forced_exercici_ids,
                        forced_camps=forced_camps,
                    )
                )
            )
        entries_enriched.append(
            {
                "row": row,
                "base": _to_float(entry.get("base")),
                "compare_vals": compare_vals,
            }
        )

    if not entries_enriched:
        return {}

    def _sort_key(entry):
        key = [(-entry["base"]) if ordre_principal == "desc" else entry["base"]]
        for idx, crit in enumerate(compare_ties):
            ordre = str((crit or {}).get("ordre") or "desc").lower().strip()
            value = _to_float(entry["compare_vals"][idx])
            key.append(-value if ordre == "desc" else value)
        return tuple(key)

    entries_sorted = sorted(entries_enriched, key=_sort_key)
    groups = []
    last_key = None
    current = []
    for entry in entries_sorted:
        cur_key = _sort_key(entry)
        if last_key is None or cur_key == last_key:
            current.append(entry)
        else:
            groups.append(current)
            current = [entry]
        last_key = cur_key
    if current:
        groups.append(current)

    points = {}
    total = len(entries_sorted)
    seen = 0
    for group in groups:
        group_size = len(group)
        worse_count = total - seen - group_size
        pts = float((punts_victoria * worse_count) + (punts_empat * max(0, group_size - 1)))
        for entry in group:
            ins_id = entry["row"].get("inscripcio_id")
            if ins_id in (None, ""):
                continue
            points[ins_id] = pts
        seen += group_size

    return points


def _apply_victories_per_app_to_rows(
    rows,
    app_ids,
    ordre_principal,
    agg_aparells,
    victories_cfg,
    metric_value_getter,
):
    rows = rows or []
    app_ids = [int(item) for item in (app_ids or [])]
    if not rows or not app_ids:
        for row in rows:
            row["by_app"] = {}
            row["score"] = 0.0
        return rows

    for row in rows:
        row["by_app"] = {}

    for app_id in app_ids:
        entries = []
        for row in rows:
            ins_id = row.get("inscripcio_id")
            if ins_id in (None, ""):
                continue
            if not _row_has_app(row, app_id):
                continue
            entries.append({"row": row, "base": _row_base_for_app(row, app_id)})

        points = _compute_victory_points_for_entries(
            entries,
            ordre_principal,
            victories_cfg,
            metric_value_getter,
            forced_app_ids=[app_id],
        )
        for row in rows:
            ins_id = row.get("inscripcio_id")
            if ins_id in points:
                row["by_app"][app_id] = points[ins_id]

    for row in rows:
        row["score"] = float(_apply_simple_agg(list((row.get("by_app") or {}).values()), agg_aparells))

    return rows


def build_victories_adapters(metric_value_getter):
    getter = metric_value_getter if callable(metric_value_getter) else (lambda _ins_id, _crit, **_kwargs: 0.0)

    def _compute(entries, ordre_principal, victories_cfg, **kwargs):
        return _compute_victory_points_for_entries(
            entries,
            ordre_principal,
            victories_cfg,
            getter,
            **kwargs,
        )

    def _apply(rows, app_ids, ordre_principal, agg_aparells, victories_cfg):
        return _apply_victories_per_app_to_rows(
            rows,
            app_ids,
            ordre_principal,
            agg_aparells,
            victories_cfg,
            getter,
        )

    return {
        "apply_victories_per_app_to_rows": _apply,
        "compute_victory_points_for_entries": _compute,
    }


__all__ = [
    "_apply_victories_per_app_to_rows",
    "_compute_victory_points_for_entries",
    "_normalize_mode_resultat_aparells",
    "_normalize_victories_cfg",
    "_row_base_for_app",
    "_row_has_app",
    "_sanitize_victories_compare_ties",
    "build_victories_adapters",
]
