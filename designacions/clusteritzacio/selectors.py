from __future__ import annotations

from .contracts import PreviewScenario


DEFAULT_PREVIEW_EPS_OPTIONS = [300, 400, 500, 650, 800]


def build_eps_options(base_eps_m: int | float | None, raw_values=None) -> list[int]:
    values = []
    if raw_values:
        for raw_value in raw_values:
            try:
                parsed = int(float(str(raw_value).strip()))
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                values.append(parsed)
    if base_eps_m is not None:
        try:
            values.append(int(float(base_eps_m)))
        except (TypeError, ValueError):
            pass
    if not values:
        values = list(DEFAULT_PREVIEW_EPS_OPTIONS)
    return sorted(set(values))


def pick_recommended_scenario(scenarios: list[PreviewScenario]) -> PreviewScenario | None:
    if not scenarios:
        return None
    return max(
        scenarios,
        key=lambda scenario: (
            scenario.metrics.scenario_score_total if scenario.metrics else float("-inf"),
            -(scenario.metrics.outlier_points if scenario.metrics else 0),
            -(scenario.metrics.cluster_count if scenario.metrics else 0),
            -scenario.eps_m,
        ),
    )
