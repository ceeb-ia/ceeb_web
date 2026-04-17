from .legacy_projection import project_tie_legacy_projection
from .ui_projection import project_tie_with_ui_state


def project_tie_for_builder_rehydration(
    tie,
    *,
    idx=0,
    tipus="individual",
    team_mode="",
    selected_main_ids=None,
    allow_app_scope=True,
    allow_participants=True,
    fallback_pipeline=None,
):
    item = project_tie_legacy_projection(
        tie,
        idx=idx,
        tipus=tipus,
        team_mode=team_mode,
        selected_app_ids=selected_main_ids,
        allow_participants=allow_participants,
        fallback_pipeline=fallback_pipeline,
    )
    if not isinstance(item, dict):
        return None

    if not allow_app_scope:
        scope = item.get("scope") if isinstance(item.get("scope"), dict) else {}
        scope.pop("aparells", None)
        item["scope"] = scope

    return project_tie_with_ui_state(
        item,
        main_pipeline=fallback_pipeline,
        tipus=tipus,
        team_mode=team_mode,
    )
