from copy import deepcopy

from .filters import normalize_exercise_selection_scope, normalize_team_mode


ALLOWED_EXERCISE_SELECTION_MODES = {
    "per_aparell_global",
    "per_aparell_override",
    "global_pool",
}


def project_builder_tie_rehydration(
    tie,
    *,
    main_pipeline=None,
    tipus="individual",
    team_mode="",
):
    if not isinstance(tie, dict):
        return tie

    item = deepcopy(tie)
    item["_builder_ui"] = build_builder_tie_ui_projection(
        item,
        main_pipeline=main_pipeline,
        tipus=tipus,
        team_mode=team_mode,
    )
    return item


def build_builder_tie_ui_projection(
    tie,
    *,
    main_pipeline=None,
    tipus="individual",
    team_mode="",
):
    item = tie if isinstance(tie, dict) else {}
    pipeline = item.get("pipeline") if isinstance(item.get("pipeline"), dict) else {}
    main = main_pipeline if isinstance(main_pipeline, dict) else {}

    ui = {
        "app_scope": _project_app_scope(item, pipeline, main),
        "camps": _copy_camps(item),
        "agregacio_camps": _normalize_aggregation(
            item.get("agregacio_camps") or pipeline.get("agregacio_camps")
        ),
        "mode_seleccio_exercicis_ui": _project_mode_seleccio_exercicis_ui(pipeline, main),
        "scope_exercicis_ui": _project_scope_exercicis_ui(pipeline, main),
    }

    if ui["mode_seleccio_exercicis_ui"] != "hereta":
        ui["exercicis_per_aparell_ui"] = deepcopy(pipeline.get("exercicis_per_aparell") or {})
        ui["agregacio_exercicis_per_aparell_ui"] = deepcopy(
            pipeline.get("agregacio_exercicis_per_aparell") or {}
        )

    if _is_derived_team_scope_enabled(tipus=tipus, team_mode=team_mode):
        _populate_derived_team_projection(ui, pipeline, main)

    return ui


def _is_derived_team_scope_enabled(*, tipus="individual", team_mode=""):
    return (
        str(tipus or "").strip().lower() == "equips"
        and normalize_team_mode(team_mode) == "derived_from_individual"
    )


def _project_app_scope(item, pipeline, main_pipeline):
    scope = item.get("scope") if isinstance(item.get("scope"), dict) else {}
    app_scope = scope.get("aparells") if isinstance(scope.get("aparells"), dict) else {}
    projected = app_scope if app_scope else {
        "mode": "seleccionar",
        "ids": list((((pipeline.get("aparells") or {}).get("ids")) or [])),
    }
    main_ids = list((((main_pipeline.get("aparells") or {}).get("ids")) or []))
    if list(projected.get("ids") or []) == main_ids:
        return {"mode": "hereta"}
    return deepcopy(projected)


def _copy_camps(item):
    raw = item.get("camps")
    if isinstance(raw, list):
        camps = [str(code).strip() for code in raw if str(code).strip()]
    elif isinstance(raw, str):
        camps = [code.strip() for code in raw.split(",") if code.strip()]
    else:
        legacy = str(item.get("camp") or "").strip()
        camps = [legacy] if legacy else []

    out = []
    seen = set()
    for code in camps:
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _normalize_aggregation(raw_value):
    agg = str(raw_value or "sum").strip().lower()
    if agg not in {"sum", "avg", "median", "max", "min"}:
        return "sum"
    return agg


def _normalize_order(raw_value):
    return "asc" if str(raw_value or "desc").strip().lower() == "asc" else "desc"


def _normalize_mode(raw_value):
    mode = str(raw_value or "per_aparell_global").strip().lower()
    if mode not in ALLOWED_EXERCISE_SELECTION_MODES:
        return "per_aparell_global"
    return mode


def _populate_derived_team_projection(ui, pipeline, main_pipeline):
    main_scope = normalize_exercise_selection_scope(main_pipeline.get("exercise_selection_scope"))
    tie_scope = normalize_exercise_selection_scope(pipeline.get("exercise_selection_scope"))
    ui["exercise_selection_scope_ui"] = "hereta" if tie_scope == main_scope else tie_scope

    participants = pipeline.get("participants")
    if isinstance(participants, dict) and participants:
        ui["participants_ui"] = deepcopy(participants)


def _project_mode_seleccio_exercicis_ui(pipeline, main_pipeline):
    main_mode = _normalize_mode(main_pipeline.get("mode_seleccio_exercicis"))
    tie_mode = _normalize_mode(pipeline.get("mode_seleccio_exercicis"))
    return "hereta" if tie_mode == main_mode else tie_mode


def _project_scope_exercicis_ui(pipeline, main_pipeline):
    if pipeline.get("exercicis") == main_pipeline.get("exercicis"):
        return {"mode": "hereta"}
    return deepcopy(pipeline.get("exercicis") or {})
