from .ties.ui_projection import project_tie_ui_state, project_tie_with_ui_state


def project_builder_tie_rehydration(
    tie,
    *,
    main_pipeline=None,
    tipus="individual",
    team_mode="",
):
    return project_tie_with_ui_state(
        tie,
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
    return project_tie_ui_state(
        tie,
        main_pipeline=main_pipeline,
        tipus=tipus,
        team_mode=team_mode,
    )
