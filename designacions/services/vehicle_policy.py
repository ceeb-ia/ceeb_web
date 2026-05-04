from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from .assignment_feasibility import MatchDescriptor, has_vehicle, normalize_cluster_id, normalize_cluster_status


VEHICLE_REQUIRED = "vehicle_required"
VEHICLE_PREFERRED = "vehicle_preferred"
VEHICLE_NOT_NEEDED = "vehicle_not_needed"
TRANSPORT_FIELD_CANDIDATES = ("Mitjà de Transport", "MitjÃ  de Transport", "MitjÃƒÂ  de Transport", "transport")


@dataclass(frozen=True)
class VehiclePolicyConfig:
    enabled: bool = True
    easy_segment_penalty: float = 250.0
    assignment_threshold: float = 1e5


@dataclass(frozen=True)
class VehiclePolicyContext:
    config: VehiclePolicyConfig
    vehicle_required_count: int
    vehicle_preferred_count: int
    vehicle_not_needed_count: int
    vehicle_referee_count: int

    @property
    def has_vehicle_pressure(self) -> bool:
        return (
            self.config.enabled
            and self.config.easy_segment_penalty > 0
            and self.vehicle_required_count > 0
            and self.vehicle_referee_count > 0
        )


def _bool_param(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on", "si", "sí"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def vehicle_policy_config_from_params(params: dict | None) -> VehiclePolicyConfig:
    params = params or {}
    enabled = _bool_param(params.get("vehicle_policy_enabled"), True)
    try:
        penalty = float(params.get("vehicle_easy_segment_penalty", 250.0))
    except (TypeError, ValueError):
        penalty = 250.0
    try:
        threshold = float(params.get("assignment_threshold", 1e5))
    except (TypeError, ValueError):
        threshold = 1e5
    return VehiclePolicyConfig(
        enabled=enabled,
        easy_segment_penalty=max(0.0, penalty),
        assignment_threshold=threshold,
    )


def _transport_from_row(row) -> str:
    for field in TRANSPORT_FIELD_CANDIDATES:
        try:
            value = row.get(field, "")
        except AttributeError:
            value = ""
        if value:
            return value
    return ""


def classify_assignable_unit(descriptors: Iterable[MatchDescriptor]) -> str:
    descriptors = list(descriptors or [])
    cluster_ids = {
        normalize_cluster_id(descriptor.cluster_id)
        for descriptor in descriptors
        if normalize_cluster_id(descriptor.cluster_id) is not None
    }
    if len(cluster_ids) > 1:
        return VEHICLE_REQUIRED

    for descriptor in descriptors:
        cluster_status = normalize_cluster_status(descriptor.cluster_status)
        if normalize_cluster_id(descriptor.cluster_id) is None or cluster_status in {"outlier", "missing_geocode"}:
            return VEHICLE_PREFERRED

    return VEHICLE_NOT_NEEDED


def build_vehicle_policy_context(
    assignable_units: Iterable[Iterable[MatchDescriptor]],
    referee_rows,
    params: dict | None = None,
) -> VehiclePolicyContext:
    config = vehicle_policy_config_from_params(params)
    counts = {VEHICLE_REQUIRED: 0, VEHICLE_PREFERRED: 0, VEHICLE_NOT_NEEDED: 0}
    for unit in assignable_units:
        counts[classify_assignable_unit(unit)] += 1

    vehicle_referee_count = 0
    if referee_rows is not None:
        for _, row in referee_rows.iterrows():
            if has_vehicle(_transport_from_row(row)):
                vehicle_referee_count += 1

    return VehiclePolicyContext(
        config=config,
        vehicle_required_count=counts[VEHICLE_REQUIRED],
        vehicle_preferred_count=counts[VEHICLE_PREFERRED],
        vehicle_not_needed_count=counts[VEHICLE_NOT_NEEDED],
        vehicle_referee_count=vehicle_referee_count,
    )


def has_viable_non_vehicle_alternative(
    candidate_referees,
    segment,
    raw_evaluator: Callable,
    *,
    assignment_threshold: float = 1e5,
) -> bool:
    if candidate_referees is None:
        return False
    for _, candidate_row in candidate_referees.iterrows():
        if has_vehicle(_transport_from_row(candidate_row)):
            continue
        evaluation = raw_evaluator(candidate_row, segment)
        if not evaluation.get("reason_codes") and float(evaluation.get("cost", assignment_threshold)) < assignment_threshold:
            return True
    return False


def vehicle_policy_penalty(
    tutor_row,
    segment,
    descriptors: Iterable[MatchDescriptor],
    context: VehiclePolicyContext | None,
    candidate_referees,
    raw_evaluator: Callable,
) -> tuple[float, dict]:
    if context is None or not context.has_vehicle_pressure:
        return 0.0, {"vehicle_unit_classification": classify_assignable_unit(descriptors)}

    classification = classify_assignable_unit(descriptors)
    diagnostics = {
        "vehicle_unit_classification": classification,
        "vehicle_pressure": True,
        "vehicle_policy_penalty": 0.0,
    }
    if classification != VEHICLE_NOT_NEEDED:
        return 0.0, diagnostics
    if not has_vehicle(_transport_from_row(tutor_row)):
        return 0.0, diagnostics
    if not has_viable_non_vehicle_alternative(
        candidate_referees,
        segment,
        raw_evaluator,
        assignment_threshold=context.config.assignment_threshold,
    ):
        diagnostics["vehicle_no_non_vehicle_alternative"] = True
        return 0.0, diagnostics

    penalty = float(context.config.easy_segment_penalty)
    diagnostics["vehicle_policy_penalty"] = penalty
    diagnostics["vehicle_easy_segment_with_alternative"] = True
    return penalty, diagnostics


def build_vehicle_assignment_record(tutor_row, segment, *, stage: str) -> dict:
    descriptors = [descriptor for descriptor in segment]
    classification = classify_assignable_unit(descriptors)
    return {
        "stage": stage,
        "tutor_id": tutor_row.get("ID"),
        "tutor_code": tutor_row.get("Codi Tutor de Joc", ""),
        "has_vehicle": has_vehicle(_transport_from_row(tutor_row)),
        "vehicle_unit_classification": classification,
        "match_ids": [descriptor.identifier for descriptor in descriptors],
        "match_count": len(descriptors),
    }


def summarize_vehicle_assignments(records: Iterable[dict], context: VehiclePolicyContext | None = None) -> dict:
    records = list(records or [])
    vehicle_records = [record for record in records if record.get("has_vehicle")]
    easy_vehicle_records = [
        record for record in vehicle_records if record.get("vehicle_unit_classification") == VEHICLE_NOT_NEEDED
    ]
    reserved_records = [
        record
        for record in vehicle_records
        if record.get("vehicle_unit_classification") in {VEHICLE_REQUIRED, VEHICLE_PREFERRED}
    ]
    summary = {
        "total_segments": len(records),
        "vehicle_segments": len(vehicle_records),
        "vehicle_required_segments": (
            int(context.vehicle_required_count) if context is not None else 0
        ),
        "vehicle_preferred_segments": (
            int(context.vehicle_preferred_count) if context is not None else 0
        ),
        "vehicle_not_needed_segments": (
            int(context.vehicle_not_needed_count) if context is not None else 0
        ),
        "vehicle_pressure": bool(context.has_vehicle_pressure) if context is not None else False,
        "vehicle_used_on_easy_segments_count": len(easy_vehicle_records),
        "vehicle_reserved_count": len(reserved_records),
        "vehicle_used_on_easy_segments": easy_vehicle_records,
    }
    return summary
