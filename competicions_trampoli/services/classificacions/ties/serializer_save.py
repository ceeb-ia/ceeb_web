from ..pipeline_runtime import build_main_scoring_pipeline_from_schema
from .context import resolve_tie_context
from .pipeline_builder import build_tie_pipeline_criterion
from .registry import resolve_tie_contract


def _build_fallback_pipeline(selected_app_ids, *, tipus="individual", team_mode=""):
    if not selected_app_ids:
        return None
    return build_main_scoring_pipeline_from_schema(
        {
            "puntuacio": {
                "aparells": {"mode": "seleccionar", "ids": list(selected_app_ids)},
            }
        },
        tipus=tipus,
        team_mode=team_mode,
    )


def serialize_tie_for_save(
    raw_tie,
    *,
    idx=0,
    tipus="individual",
    team_mode="",
    selected_app_ids=None,
    fallback_pipeline=None,
):
    fallback = fallback_pipeline
    if fallback is None:
        fallback = _build_fallback_pipeline(selected_app_ids, tipus=tipus, team_mode=team_mode)
    item = build_tie_pipeline_criterion(
        raw_tie,
        idx=idx,
        tipus=tipus,
        team_mode=team_mode,
        fallback_pipeline=fallback,
    )
    context = resolve_tie_context(item, tipus=tipus, team_mode=team_mode, main_pipeline=fallback)
    contract = resolve_tie_contract(context)
    serialized = contract.sanitize_item_for_save(item, context)
    serialized_pipeline = serialized.get("pipeline") if isinstance(serialized.get("pipeline"), dict) else {}
    raw_pipeline = item.get("pipeline") if isinstance(item.get("pipeline"), dict) else {}
    if raw_pipeline and "exercise_selection_scope" in raw_pipeline:
        serialized_pipeline["exercise_selection_scope"] = raw_pipeline.get("exercise_selection_scope")
    else:
        serialized_pipeline.pop("exercise_selection_scope", None)
    serialized["pipeline"] = serialized_pipeline
    return serialized


def serialize_ties_for_save(
    raw_ties,
    *,
    tipus="individual",
    team_mode="",
    selected_app_ids=None,
    fallback_pipeline=None,
):
    out = []
    for idx, tie in enumerate(raw_ties if isinstance(raw_ties, list) else []):
        if not isinstance(tie, dict):
            continue
        out.append(
            serialize_tie_for_save(
                tie,
                idx=idx,
                tipus=tipus,
                team_mode=team_mode,
                selected_app_ids=selected_app_ids,
                fallback_pipeline=fallback_pipeline,
            )
        )
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
    item = serialize_tie_for_save(
        raw_tie,
        idx=0,
        tipus=tipus,
        team_mode=team_mode,
        selected_app_ids=selected_app_ids,
        fallback_pipeline=fallback_pipeline,
    )
    if default_id and not str(item.get("id") or "").strip():
        item["id"] = str(default_id).strip()
    if default_nom and not str(item.get("nom") or "").strip():
        item["nom"] = str(default_nom).strip()
    return item


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
