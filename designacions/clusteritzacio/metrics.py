from __future__ import annotations

import statistics

import pandas as pd

from .contracts import PreviewMetrics


def _safe_cluster_values(df: pd.DataFrame) -> list[int]:
    values = []
    for raw_value in df.get("cluster", pd.Series(dtype="Int64")).dropna().tolist():
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            continue
        if parsed != -1:
            values.append(parsed)
    return values


def estimate_operational_metrics(
    matches_df: pd.DataFrame,
    *,
    gap_same_pitch_min: int,
    gap_diff_pitch_min: int,
    max_partits_subgrup: int,
) -> dict[str, int]:
    if matches_df.empty:
        return {
            "estimated_base_subgroups": 0,
            "estimated_fused_subgroups": 0,
            "estimated_cross_cluster_transitions": 0,
        }

    from ..main_fixed import _build_daily_subgroups_with_stats, _combine_date_time

    working = matches_df.copy()
    working["__match_datetime"] = working.apply(
        lambda row: _combine_date_time(row.get("Data"), row.get("Hora")),
        axis=1,
    )

    estimated_base_subgroups = 0
    estimated_fused_subgroups = 0
    estimated_cross_cluster_transitions = 0
    for _modalitat, group in working.groupby("Modalitat", dropna=False):
        stats = _build_daily_subgroups_with_stats(
            group,
            gap_same_pitch_min=gap_same_pitch_min,
            gap_diff_pitch_min=gap_diff_pitch_min,
            max_partits_subgrup=max_partits_subgrup,
        )
        estimated_base_subgroups += int(stats["base_subgroups"])
        estimated_fused_subgroups += int(stats["fused_subgroups"])
        for subgroup in stats["subgroups"]:
            cluster_values = set()
            for row in subgroup:
                raw_cluster = row.get("cluster")
                if raw_cluster is None or pd.isna(raw_cluster):
                    continue
                try:
                    parsed = int(raw_cluster)
                except (TypeError, ValueError):
                    continue
                if parsed == -1:
                    continue
                cluster_values.add(parsed)
            if len(cluster_values) > 1:
                estimated_cross_cluster_transitions += 1

    return {
        "estimated_base_subgroups": estimated_base_subgroups,
        "estimated_fused_subgroups": estimated_fused_subgroups,
        "estimated_cross_cluster_transitions": estimated_cross_cluster_transitions,
    }


def build_preview_metrics(
    scenario_points_df: pd.DataFrame,
    scenario_matches_df: pd.DataFrame,
    *,
    max_points_per_subcluster: int,
    gap_same_pitch_min: int,
    gap_diff_pitch_min: int,
    max_partits_subgrup: int,
) -> PreviewMetrics:
    total_points = len(scenario_points_df)
    geocoded_points = int(scenario_points_df[["lat", "lon"]].dropna().shape[0]) if total_points else 0
    missing_geocode_points = int((scenario_points_df.get("cluster_status") == "missing_geocode").sum()) if total_points else 0
    clustered_points = int((scenario_points_df.get("cluster_status") == "clustered").sum()) if total_points else 0
    outlier_points = int((scenario_points_df.get("cluster_status") == "outlier").sum()) if total_points else 0

    valid_clusters = _safe_cluster_values(scenario_points_df)
    cluster_count = len(set(valid_clusters))
    cluster_sizes_series = pd.Series(valid_clusters, dtype="int64").value_counts() if valid_clusters else pd.Series(dtype="int64")
    cluster_size_distribution = cluster_sizes_series.tolist()
    largest_cluster_size = int(cluster_sizes_series.max()) if not cluster_sizes_series.empty else 0
    average_cluster_size = float(cluster_sizes_series.mean()) if not cluster_sizes_series.empty else 0.0
    median_cluster_size = float(statistics.median(cluster_size_distribution)) if cluster_size_distribution else 0.0
    singleton_cluster_count = int((cluster_sizes_series == 1).sum()) if not cluster_sizes_series.empty else 0
    clusters_over_threshold_count = int((cluster_sizes_series > max(1, max_points_per_subcluster)).sum()) if not cluster_sizes_series.empty else 0
    outlier_ratio = float(outlier_points / geocoded_points) if geocoded_points else 0.0

    operational = estimate_operational_metrics(
        scenario_matches_df,
        gap_same_pitch_min=gap_same_pitch_min,
        gap_diff_pitch_min=gap_diff_pitch_min,
        max_partits_subgrup=max_partits_subgrup,
    )

    total_matches = int(len(scenario_matches_df))
    total_matches_with_cluster = int(
        scenario_matches_df["cluster"].notna().sum()
    ) if not scenario_matches_df.empty and "cluster" in scenario_matches_df.columns else 0
    total_matches_without_cluster = int(total_matches - total_matches_with_cluster)
    total_unique_venues = int(scenario_matches_df["Pista joc"].dropna().nunique()) if not scenario_matches_df.empty and "Pista joc" in scenario_matches_df.columns else 0

    score_outlier_penalty = float(outlier_points * 10 + missing_geocode_points * 12)
    score_fragmentation_penalty = float(singleton_cluster_count * 4)
    score_oversized_cluster_penalty = float(max(0, largest_cluster_size - max(1, max_points_per_subcluster)) * 6)
    score_operational_balance = float(
        operational["estimated_cross_cluster_transitions"] * 5
        + max(0, operational["estimated_fused_subgroups"] - operational["estimated_base_subgroups"]) * 2
    )
    scenario_score_total = float(
        1000.0
        - score_outlier_penalty
        - score_fragmentation_penalty
        - score_oversized_cluster_penalty
        - score_operational_balance
    )

    return PreviewMetrics(
        total_points=total_points,
        geocoded_points=geocoded_points,
        missing_geocode_points=missing_geocode_points,
        clustered_points=clustered_points,
        outlier_points=outlier_points,
        cluster_count=cluster_count,
        largest_cluster_size=largest_cluster_size,
        average_cluster_size=average_cluster_size,
        median_cluster_size=median_cluster_size,
        singleton_cluster_count=singleton_cluster_count,
        clusters_over_threshold_count=clusters_over_threshold_count,
        outlier_ratio=outlier_ratio,
        total_matches=total_matches,
        total_unique_addresses=total_points,
        total_unique_venues=total_unique_venues,
        total_matches_with_cluster=total_matches_with_cluster,
        total_matches_without_cluster=total_matches_without_cluster,
        estimated_base_subgroups=operational["estimated_base_subgroups"],
        estimated_fused_subgroups=operational["estimated_fused_subgroups"],
        estimated_cross_cluster_transitions=operational["estimated_cross_cluster_transitions"],
        score_outlier_penalty=score_outlier_penalty,
        score_fragmentation_penalty=score_fragmentation_penalty,
        score_oversized_cluster_penalty=score_oversized_cluster_penalty,
        score_operational_balance=score_operational_balance,
        scenario_score_total=scenario_score_total,
        cluster_size_distribution=cluster_size_distribution,
    )
