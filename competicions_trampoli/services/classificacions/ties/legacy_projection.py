from .pipeline_builder import build_tie_pipeline_criterion
from .pipeline_helpers import (
    default_pipeline_from_selected_app_ids,
    normalize_agregacio_exercicis_per_aparell,
    normalize_aggregation,
    normalize_exercicis_cfg,
    normalize_exercicis_per_aparell,
    normalize_participants_cfg,
    resolve_pipeline_target_app_ids,
    unique_nonempty_strings,
)


def _materialize_legacy_mirrors_from_pipeline(item, *, allow_participants=True):
    pipeline = item.get("pipeline") if isinstance(item.get("pipeline"), dict) else {}
    app_ids = resolve_pipeline_target_app_ids(pipeline)
    camps_map = pipeline.get("camps_per_aparell") if isinstance(pipeline.get("camps_per_aparell"), dict) else {}
    agg_map = pipeline.get("agregacio_camps_per_aparell") if isinstance(pipeline.get("agregacio_camps_per_aparell"), dict) else {}
    visible_camps = []
    for app_id in app_ids:
        visible_camps = unique_nonempty_strings(camps_map.get(str(app_id)) or camps_map.get(app_id))
        if visible_camps:
            break
    item["camps"] = visible_camps
    if visible_camps:
        item["camp"] = visible_camps[0]
    if len(app_ids) == 1:
        item["aparell_id"] = app_ids[0]
    item["agregacio_camps"] = normalize_aggregation(
        next(
            (
                agg_map.get(str(app_id)) or agg_map.get(app_id)
                for app_id in app_ids
                if (agg_map.get(str(app_id)) or agg_map.get(app_id))
            ),
            pipeline.get("agregacio_camps", "sum"),
        ),
        fallback=pipeline.get("agregacio_camps", "sum"),
    )
    scope = {
        "aparells": {"mode": "seleccionar", "ids": app_ids} if app_ids else {"mode": "hereta"},
        "exercicis": normalize_exercicis_cfg(pipeline.get("exercicis")),
    }
    if allow_participants and isinstance(pipeline.get("participants"), dict):
        scope["participants"] = normalize_participants_cfg(pipeline.get("participants"))
        item["agregacio_participants"] = normalize_aggregation(pipeline.get("agregacio_participants"), "sum")
    else:
        item.pop("agregacio_participants", None)
    item["scope"] = scope
    item["exercise_selection_scope"] = pipeline.get("exercise_selection_scope")
    item["mode_seleccio_exercicis"] = pipeline.get("mode_seleccio_exercicis")
    item["exercicis_per_aparell"] = normalize_exercicis_per_aparell(
        pipeline.get("exercicis_per_aparell"),
        fallback_cfg=pipeline.get("exercicis"),
    )
    item["agregacio_exercicis_per_aparell"] = normalize_agregacio_exercicis_per_aparell(
        pipeline.get("agregacio_exercicis_per_aparell"),
        fallback=pipeline.get("agregacio_exercicis", "sum"),
    )
    item["agregacio_exercicis"] = normalize_aggregation(pipeline.get("agregacio_exercicis"), "sum")
    item["agregacio_aparells"] = normalize_aggregation(pipeline.get("agregacio_aparells"), "sum")
    return item


def project_tie_legacy_projection(
    tie,
    *,
    idx=0,
    tipus="individual",
    team_mode="",
    selected_app_ids=None,
    default_id=None,
    default_nom=None,
    allow_participants=True,
    fallback_pipeline=None,
):
    fallback = fallback_pipeline or default_pipeline_from_selected_app_ids(
        selected_app_ids,
        tipus=tipus,
        team_mode=team_mode,
    )
    item = build_tie_pipeline_criterion(
        tie,
        idx=idx,
        tipus=tipus,
        team_mode=team_mode,
        fallback_pipeline=fallback,
    )
    if default_id and not str(item.get("id") or "").strip():
        item["id"] = str(default_id).strip()
    if default_nom and not str(item.get("nom") or "").strip():
        item["nom"] = str(default_nom).strip()
    return _materialize_legacy_mirrors_from_pipeline(
        item,
        allow_participants=allow_participants,
    )


def project_ties_legacy_projection(
    ties,
    *,
    tipus="individual",
    team_mode="",
    selected_app_ids=None,
    allow_participants=True,
    fallback_pipeline=None,
):
    out = []
    for idx, tie in enumerate(ties if isinstance(ties, list) else []):
        if not isinstance(tie, dict):
            continue
        item = project_tie_legacy_projection(
            tie,
            idx=idx,
            tipus=tipus,
            team_mode=team_mode,
            selected_app_ids=selected_app_ids,
            default_id=f"tie_{idx + 1}",
            default_nom=f"Criteri {idx + 1}",
            allow_participants=allow_participants,
            fallback_pipeline=fallback_pipeline,
        )
        if item:
            out.append(item)
    return out


__all__ = [
    "project_tie_legacy_projection",
    "project_ties_legacy_projection",
]
