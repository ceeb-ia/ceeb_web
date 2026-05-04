from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Mapping


Scalar = str | int
DateLike = date | datetime | str | None


PACKAGE_KIND_BASE = "base"
PACKAGE_KIND_SPLIT = "split"
PACKAGE_KIND_CONTIGUOUS_SPLIT = "contiguous_split"
PACKAGE_KIND_MERGED_ROUTE = "merged_route"
PACKAGE_KIND_SPLIT_MERGED_ROUTE = "split_merged_route"
PACKAGE_KIND_SINGLE_MATCH = "single_match"

PACKAGE_KINDS = {
    PACKAGE_KIND_BASE,
    PACKAGE_KIND_SPLIT,
    PACKAGE_KIND_CONTIGUOUS_SPLIT,
    PACKAGE_KIND_MERGED_ROUTE,
    PACKAGE_KIND_SPLIT_MERGED_ROUTE,
    PACKAGE_KIND_SINGLE_MATCH,
}


def normalize_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_ids(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        if not values.strip():
            return []
        separators = [",", ";", "|"]
        chunks = [values]
        for separator in separators:
            chunks = [part for chunk in chunks for part in chunk.split(separator)]
        return [normalize_id(part) for part in chunks if normalize_id(part)]
    if isinstance(values, Mapping):
        return [normalize_id(value) for value in values.values() if normalize_id(value)]
    try:
        return [normalize_id(value) for value in values if normalize_id(value)]
    except TypeError:
        normalized = normalize_id(values)
        return [normalized] if normalized else []


def _first_value(source: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in source:
            return source[key]
    return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "si", "sí", "vehicle", "cotxe", "coche"}:
            return True
        return any(token in normalized for token in ("cotxe", "coche", "moto", "bicicleta", "bici", "patinet", "furgoneta"))
    return bool(value)


def _to_dict(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, list):
        return [_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_dict(item) for key, item in value.items()}
    return value


@dataclass
class BaseSubgroup:
    id: str
    match_ids: list[str]
    date: DateLike
    modality: str
    start_dt: DateLike
    end_dt: DateLike
    venue_ids: list[str] = field(default_factory=list)
    venues: list[str] = field(default_factory=list)
    cluster_ids: list[str] = field(default_factory=list)
    cluster_statuses: list[str] = field(default_factory=list)
    match_count: int = 0
    level_demand: dict[str, Any] = field(default_factory=dict)
    classification_pressure: float = 0.0
    classification_importance: float = 0.0
    weighted_coverage_value: float = 0.0
    rows: list[Any] = field(default_factory=list, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.id = normalize_id(self.id)
        self.match_ids = normalize_ids(self.match_ids)
        self.venue_ids = normalize_ids(self.venue_ids)
        self.venues = normalize_ids(self.venues)
        self.cluster_ids = normalize_ids(self.cluster_ids)
        self.cluster_statuses = normalize_ids(self.cluster_statuses)
        if not self.match_count:
            self.match_count = len(self.match_ids)

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "BaseSubgroup":
        match_ids = normalize_ids(_first_value(row, "match_ids", "partit_ids", "ids_partits", "partits"))
        subgroup_id = _first_value(row, "id", "subgroup_id", "grup_id", default="-".join(match_ids))
        return cls(
            id=subgroup_id,
            match_ids=match_ids,
            date=_first_value(row, "date", "data"),
            modality=normalize_id(_first_value(row, "modality", "modalitat")),
            start_dt=_first_value(row, "start_dt", "inici", "hora_inici"),
            end_dt=_first_value(row, "end_dt", "fi", "hora_fi"),
            venue_ids=normalize_ids(_first_value(row, "venue_ids", "pista_ids", "installacio_ids")),
            venues=normalize_ids(_first_value(row, "venues", "pistes", "installacions")),
            cluster_ids=normalize_ids(_first_value(row, "cluster_ids", "clusters")),
            cluster_statuses=normalize_ids(_first_value(row, "cluster_statuses", "estats_cluster")),
            match_count=int(_first_value(row, "match_count", "num_partits", default=len(match_ids)) or 0),
            level_demand=dict(_first_value(row, "level_demand", "demanda_nivell", default={}) or {}),
            classification_pressure=float(
                _first_value(row, "classification_pressure", "pressio_classificacio", default=0.0) or 0.0
            ),
            classification_importance=float(
                _first_value(row, "classification_importance", "importancia_classificacio", default=0.0) or 0.0
            ),
            weighted_coverage_value=float(
                _first_value(row, "weighted_coverage_value", "valor_cobertura_ponderat", default=0.0) or 0.0
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PackageCandidate:
    id: str
    kind: str
    subgroup_ids: list[str]
    match_ids: list[str]
    date: DateLike
    modality: str
    start_dt: DateLike
    end_dt: DateLike
    requires_vehicle: bool = False
    vehicle_preferred: bool = False
    warning_codes: list[str] = field(default_factory=list)
    pressure_relief_score: float = 0.0
    base_difficulty_score: float = 0.0
    coverage_value: float = 0.0
    route_score: float = 0.0
    cluster_ids: list[str | None] = field(default_factory=list)
    cluster_statuses: list[str | None] = field(default_factory=list)
    venues: list[str] = field(default_factory=list)
    component_ids: list[str] = field(default_factory=list)
    level_demand: Any = None
    classification_pressure: float = 0.0
    classification_importance: float = 0.0
    weighted_coverage_value: float = 0.0
    level_fit_summary: dict[str, int] = field(default_factory=dict)
    eligible_tutor_count: int = 0

    def __post_init__(self) -> None:
        self.id = normalize_id(self.id)
        self.kind = normalize_id(self.kind) or PACKAGE_KIND_BASE
        if self.kind not in PACKAGE_KINDS:
            raise ValueError(f"Unsupported package kind: {self.kind}")
        self.subgroup_ids = normalize_ids(self.subgroup_ids)
        self.match_ids = normalize_ids(self.match_ids)
        self.warning_codes = normalize_ids(self.warning_codes)
        self.cluster_ids = [None if value in (None, "") else normalize_id(value) for value in self.cluster_ids]
        self.cluster_statuses = normalize_ids(self.cluster_statuses)
        self.venues = normalize_ids(self.venues)
        self.component_ids = normalize_ids(self.component_ids)
        self.requires_vehicle = _as_bool(self.requires_vehicle)
        self.vehicle_preferred = _as_bool(self.vehicle_preferred)
        if not self.coverage_value:
            self.coverage_value = float(len(self.match_ids))
        if not self.weighted_coverage_value:
            self.weighted_coverage_value = self.coverage_value
        self.level_fit_summary = dict(self.level_fit_summary or {})
        self.eligible_tutor_count = int(self.eligible_tutor_count or 0)

    @classmethod
    def from_base_subgroup(cls, subgroup: BaseSubgroup) -> "PackageCandidate":
        return cls(
            id=subgroup.id,
            kind=PACKAGE_KIND_BASE,
            subgroup_ids=[subgroup.id],
            match_ids=list(subgroup.match_ids),
            date=subgroup.date,
            modality=subgroup.modality,
            start_dt=subgroup.start_dt,
            end_dt=subgroup.end_dt,
            base_difficulty_score=subgroup.classification_pressure,
            coverage_value=float(len(subgroup.match_ids)),
            route_score=float(len(subgroup.match_ids)),
            cluster_ids=list(subgroup.cluster_ids),
            cluster_statuses=list(subgroup.cluster_statuses),
            venues=list(subgroup.venues),
            component_ids=[subgroup.id],
            level_demand=subgroup.level_demand,
            classification_pressure=subgroup.classification_pressure,
            classification_importance=subgroup.classification_importance,
            weighted_coverage_value=subgroup.weighted_coverage_value or float(len(subgroup.match_ids)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TutorCandidate:
    id: str
    code: str
    modality: str
    level: str
    transport: str
    has_vehicle: bool
    availability_by_date: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = normalize_id(self.id)
        self.code = normalize_id(self.code)
        self.modality = normalize_id(self.modality)
        self.level = normalize_id(self.level)
        self.transport = normalize_id(self.transport)
        self.has_vehicle = _as_bool(self.has_vehicle)

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "TutorCandidate":
        tutor_id = _first_value(row, "id", "tutor_id", "persona_id", "code", "codi")
        transport = _first_value(row, "transport", "transport_type", "vehicle", "cotxe", default="")
        has_vehicle = _first_value(row, "has_vehicle", "te_vehicle", "vehicle", "cotxe", default=transport)
        return cls(
            id=tutor_id,
            code=normalize_id(_first_value(row, "code", "codi", default=tutor_id)),
            modality=normalize_id(_first_value(row, "modality", "modalitat")),
            level=normalize_id(_first_value(row, "level", "nivell")),
            transport=normalize_id(transport),
            has_vehicle=_as_bool(has_vehicle),
            availability_by_date=dict(
                _first_value(row, "availability_by_date", "disponibilitat_per_data", default={}) or {}
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AssignmentCandidate:
    tutor_id: str
    package_id: str
    match_ids: list[str]
    is_viable: bool
    blocking_reasons: list[str] = field(default_factory=list)
    warning_codes: list[str] = field(default_factory=list)
    cost: float = 0.0
    score_breakdown: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.tutor_id = normalize_id(self.tutor_id)
        self.package_id = normalize_id(self.package_id)
        self.match_ids = normalize_ids(self.match_ids)
        self.is_viable = _as_bool(self.is_viable)
        self.blocking_reasons = normalize_ids(self.blocking_reasons)
        self.warning_codes = normalize_ids(self.warning_codes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SolverResult:
    selected_assignments: list[AssignmentCandidate] = field(default_factory=list)
    unassigned_match_ids: list[str] = field(default_factory=list)
    rejected_candidates_summary: dict[str, Any] = field(default_factory=dict)
    objective_summary: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.unassigned_match_ids = normalize_ids(self.unassigned_match_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_assignments": [_to_dict(assignment) for assignment in self.selected_assignments],
            "unassigned_match_ids": list(self.unassigned_match_ids),
            "rejected_candidates_summary": dict(self.rejected_candidates_summary),
            "objective_summary": dict(self.objective_summary),
        }
