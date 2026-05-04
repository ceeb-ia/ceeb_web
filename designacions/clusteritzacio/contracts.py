from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PreviewAddressPoint:
    address_id: int | None
    adreca: str
    municipality: str
    lat: float | None
    lon: float | None
    geocode_status: str
    provider: str
    is_fresh_geocode: bool
    match_count: int
    venue_count: int
    modalities: list[str] = field(default_factory=list)
    cluster: int | None = None
    cluster_status: str = "pending"
    auto_cluster: int | None = None
    auto_cluster_status: str = "pending"
    is_manual: bool = False
    manual_role: str | None = None
    cluster_origin: str = "automatic"
    manual_override_ids: list[str] = field(default_factory=list)
    manual_override_kinds: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreviewClusterOverride:
    override_id: str
    kind: str
    source_address_id: int
    target_address_id: int | None = None
    target_cluster_id: int | None = None
    source_adreca: str = ""
    target_adreca: str = ""
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreviewMetrics:
    total_points: int
    geocoded_points: int
    missing_geocode_points: int
    clustered_points: int
    outlier_points: int
    cluster_count: int
    largest_cluster_size: int
    average_cluster_size: float
    median_cluster_size: float
    singleton_cluster_count: int
    clusters_over_threshold_count: int
    outlier_ratio: float
    total_matches: int
    total_unique_addresses: int
    total_unique_venues: int
    total_matches_with_cluster: int
    total_matches_without_cluster: int
    estimated_base_subgroups: int
    estimated_fused_subgroups: int
    estimated_cross_cluster_transitions: int
    score_outlier_penalty: float
    score_fragmentation_penalty: float
    score_oversized_cluster_penalty: float
    score_operational_balance: float
    scenario_score_total: float
    cluster_size_distribution: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreviewScenario:
    eps_m: int
    min_samples: int
    max_points_per_subcluster: int
    points: list[PreviewAddressPoint] = field(default_factory=list)
    metrics: PreviewMetrics | None = None
    modality_breakdown: list[dict[str, Any]] = field(default_factory=list)
    map_path: str | None = None
    recommended: bool = False
    selected: bool = False
    active_overrides: list[dict[str, Any]] = field(default_factory=list)
    manual_point_count: int = 0
    manual_cluster_count: int = 0
    override_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "eps_m": self.eps_m,
            "min_samples": self.min_samples,
            "max_points_per_subcluster": self.max_points_per_subcluster,
            "points": [point.to_dict() for point in self.points],
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "modality_breakdown": list(self.modality_breakdown),
            "map_path": self.map_path,
            "recommended": self.recommended,
            "selected": self.selected,
            "active_overrides": list(self.active_overrides),
            "manual_point_count": self.manual_point_count,
            "manual_cluster_count": self.manual_cluster_count,
            "override_summary": dict(self.override_summary),
        }
        return payload


@dataclass
class PreviewResult:
    params: dict[str, Any]
    selected_eps_m: int
    recommended_eps_m: int | None
    scenarios: list[PreviewScenario] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    map_path: str | None = None
    geocoding_issues: list[dict[str, Any]] = field(default_factory=list)
    preview_counts: dict[str, Any] = field(default_factory=dict)
    availability_counts: dict[str, Any] = field(default_factory=dict)
    cluster_overrides: list[PreviewClusterOverride] = field(default_factory=list)
    override_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "params": self.params,
            "selected_eps_m": self.selected_eps_m,
            "recommended_eps_m": self.recommended_eps_m,
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
            "summary": self.summary,
            "map_path": self.map_path,
            "geocoding_issues": list(self.geocoding_issues),
            "preview_counts": dict(self.preview_counts),
            "availability_counts": dict(self.availability_counts),
            "cluster_overrides": [override.to_dict() for override in self.cluster_overrides],
            "override_summary": dict(self.override_summary),
        }
