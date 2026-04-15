from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import unicodedata

import pandas as pd


DEFAULT_AVAILABILITY_END_BUFFER_MIN = 60
DEFAULT_GAP_SAME_PITCH_MIN = 60
DEFAULT_GAP_DIFF_PITCH_MIN = 75
DEFAULT_GAP_DIFF_CLUSTER_MIN = 100

TIME_CONFLICT_REASON_CODES = {
    "time_conflict_same_pitch",
    "time_conflict_diff_pitch",
}

REASON_PRIORITY = [
    "outside_availability_window",
    "missing_availability_for_day",
    "cross_cluster_without_vehicle",
    "cross_cluster_gap_violation",
    "same_cluster_gap_violation",
    "outlier_cluster_for_mobility_validation",
    "missing_cluster_for_mobility_validation",
    "time_conflict_same_pitch",
    "time_conflict_diff_pitch",
    "missing_match_datetime",
    "missing_cost_inputs",
    "modality_mismatch",
]


@dataclass(frozen=True)
class MatchDescriptor:
    identifier: str
    date: date | None
    match_datetime: pd.Timestamp | None
    venue: str
    modality: str
    category: str
    cluster_id: str | None = None
    address_id: int | None = None
    cluster_status: str | None = None


@dataclass(frozen=True)
class MobilityTransitionIssue:
    reason_code: str
    left_identifier: str
    right_identifier: str
    match_date: date | None
    left_cluster_id: str | None
    right_cluster_id: str | None
    required_gap_min: int | None
    actual_gap_min: float | None
    same_pitch: bool


def normalize_text(value) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def normalize_text_key(value) -> str:
    text = normalize_text(value)
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def parse_date_value(value):
    if normalize_text(value) == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    raw = normalize_text(value)
    if not raw or raw.lower() == "nat":
        return None

    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_time_value(value):
    if normalize_text(value) == "":
        return None
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    if isinstance(value, time):
        return value.replace(microsecond=0)

    raw = normalize_text(value)
    if not raw or raw == "-":
        return None

    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


def combine_date_time(date_value, time_value):
    normalized_date = parse_date_value(date_value)
    normalized_time = parse_time_value(time_value)
    if normalized_date is None or normalized_time is None:
        return pd.NaT
    return pd.Timestamp(datetime.combine(normalized_date, normalized_time))


def build_match_descriptor(
    *,
    identifier,
    date_value,
    time_value,
    venue,
    modality,
    category="",
    cluster_id=None,
    address_id=None,
    cluster_status=None,
):
    match_datetime = combine_date_time(date_value, time_value)
    if pd.isna(match_datetime):
        match_datetime = None

    return MatchDescriptor(
        identifier=normalize_text(identifier),
        date=parse_date_value(date_value),
        match_datetime=match_datetime,
        venue=normalize_text(venue),
        modality=normalize_text(modality),
        category=normalize_text(category),
        cluster_id=normalize_cluster_id(cluster_id),
        address_id=address_id,
        cluster_status=normalize_text(cluster_status) or None,
    )


def _segment_date(descriptors: list[MatchDescriptor]):
    dates = {descriptor.date for descriptor in descriptors if descriptor.date is not None}
    if len(dates) != 1:
        return None
    return next(iter(dates))


def _dedupe_preserve_order(values):
    ordered = []
    seen = set()
    for value in values:
        if value not in seen:
            ordered.append(value)
            seen.add(value)
    return ordered


def availability_covers_descriptors(
    raw: dict | None,
    descriptors: list[MatchDescriptor],
    availability_end_buffer_min: int,
) -> bool:
    if not isinstance(raw, dict) or not descriptors:
        return False

    segment_date = _segment_date(descriptors)
    if segment_date is None:
        return False

    start = parse_time_value(raw.get("Hora Inici"))
    end = parse_time_value(raw.get("Hora Fi"))
    availability_date = parse_date_value(raw.get("Data"))
    if availability_date is None or availability_date != segment_date or not start or not end:
        return False

    if any(descriptor.match_datetime is None or pd.isna(descriptor.match_datetime) for descriptor in descriptors):
        return False

    start_dt = datetime.combine(availability_date, start)
    buffered_end_dt = datetime.combine(availability_date, end) - timedelta(minutes=availability_end_buffer_min)
    return all(start_dt <= descriptor.match_datetime.to_pydatetime() <= buffered_end_dt for descriptor in descriptors)


def same_pitch(left: MatchDescriptor, right: MatchDescriptor) -> bool:
    return normalize_text(left.venue).lower() == normalize_text(right.venue).lower()


def normalize_cluster_id(value):
    raw = normalize_text(value)
    if not raw:
        return None
    if raw == "-1":
        return None

    try:
        parsed = float(raw.replace(",", "."))
    except ValueError:
        return raw

    if pd.isna(parsed):
        return None
    if int(parsed) == -1:
        return None
    if float(parsed).is_integer():
        return str(int(parsed))
    return raw


def has_vehicle(transport_value) -> bool:
    normalized = normalize_text_key(transport_value)
    if not normalized:
        return False
    vehicle_tokens = (
        "cotxe",
        "coche",
        "moto",
        "motocicleta",
        "furgoneta",
        "bicicleta",
        "bici",
        "patinet electric",
        "patinete electrico",
    )
    return any(token in normalized for token in vehicle_tokens)


def normalize_cluster_status(value):
    normalized = normalize_text_key(value)
    return normalized or None


def detect_time_conflicts(
    descriptors: list[MatchDescriptor],
    existing_descriptors: list[MatchDescriptor],
    *,
    gap_same_pitch_min: int,
    gap_diff_pitch_min: int,
):
    warnings = []
    for descriptor in descriptors:
        if descriptor.match_datetime is None or pd.isna(descriptor.match_datetime):
            continue

        for other in existing_descriptors:
            if descriptor.identifier and other.identifier and descriptor.identifier == other.identifier:
                continue
            if descriptor.date is None or descriptor.date != other.date:
                continue
            if other.match_datetime is None or pd.isna(other.match_datetime):
                continue

            minutes = abs(
                (descriptor.match_datetime.to_pydatetime() - other.match_datetime.to_pydatetime()).total_seconds()
            ) / 60.0
            if same_pitch(descriptor, other):
                if minutes < gap_same_pitch_min:
                    warnings.append("time_conflict_same_pitch")
            elif minutes < gap_diff_pitch_min:
                warnings.append("time_conflict_diff_pitch")

    return _dedupe_preserve_order(warnings)


def inspect_mobility_transitions(
    descriptors: list[MatchDescriptor],
    existing_descriptors: list[MatchDescriptor] | None = None,
    *,
    transport,
    gap_same_pitch_min: int,
    gap_diff_pitch_min: int,
    gap_diff_cluster_min: int,
    candidate_identifiers=None,
):
    candidate_identifiers = {
        normalize_text(identifier)
        for identifier in (candidate_identifiers or [descriptor.identifier for descriptor in descriptors])
        if normalize_text(identifier)
    }
    combined = []
    for descriptor in list(existing_descriptors or []) + list(descriptors):
        if descriptor.match_datetime is None or pd.isna(descriptor.match_datetime) or descriptor.date is None:
            continue
        combined.append(descriptor)
    combined.sort(
        key=lambda descriptor: (
            descriptor.date,
            descriptor.match_datetime.to_pydatetime(),
            descriptor.identifier,
        )
    )

    issues = []
    vehicle_enabled = has_vehicle(transport)
    for left, right in zip(combined, combined[1:]):
        if left.date is None or right.date is None or left.date != right.date:
            continue
        if candidate_identifiers and left.identifier not in candidate_identifiers and right.identifier not in candidate_identifiers:
            continue

        same_pitch_transition = same_pitch(left, right)
        base_gap = gap_same_pitch_min if same_pitch_transition else gap_diff_pitch_min
        minutes = abs(
            (right.match_datetime.to_pydatetime() - left.match_datetime.to_pydatetime()).total_seconds()
        ) / 60.0

        left_cluster_id = normalize_cluster_id(left.cluster_id)
        right_cluster_id = normalize_cluster_id(right.cluster_id)
        left_cluster_status = normalize_cluster_status(left.cluster_status)
        right_cluster_status = normalize_cluster_status(right.cluster_status)

        if left_cluster_id is None or right_cluster_id is None:
            if left.address_id is not None and left.address_id == right.address_id:
                if minutes < base_gap:
                    issues.append(
                        MobilityTransitionIssue(
                            reason_code="same_cluster_gap_violation",
                            left_identifier=left.identifier,
                            right_identifier=right.identifier,
                            match_date=left.date,
                            left_cluster_id=left_cluster_id,
                            right_cluster_id=right_cluster_id,
                            required_gap_min=base_gap,
                            actual_gap_min=minutes,
                            same_pitch=same_pitch_transition,
                        )
                    )
                continue

            reason_code = "missing_cluster_for_mobility_validation"
            if left_cluster_status == "outlier" or right_cluster_status == "outlier":
                reason_code = "outlier_cluster_for_mobility_validation"
            issues.append(
                MobilityTransitionIssue(
                    reason_code=reason_code,
                    left_identifier=left.identifier,
                    right_identifier=right.identifier,
                    match_date=left.date,
                    left_cluster_id=left_cluster_id,
                    right_cluster_id=right_cluster_id,
                    required_gap_min=None,
                    actual_gap_min=minutes,
                    same_pitch=same_pitch_transition,
                )
            )
            continue

        if left_cluster_id == right_cluster_id:
            if minutes < base_gap:
                issues.append(
                    MobilityTransitionIssue(
                        reason_code="same_cluster_gap_violation",
                        left_identifier=left.identifier,
                        right_identifier=right.identifier,
                        match_date=left.date,
                        left_cluster_id=left_cluster_id,
                        right_cluster_id=right_cluster_id,
                        required_gap_min=base_gap,
                        actual_gap_min=minutes,
                        same_pitch=same_pitch_transition,
                    )
                )
            continue

        if not vehicle_enabled:
            issues.append(
                MobilityTransitionIssue(
                    reason_code="cross_cluster_without_vehicle",
                    left_identifier=left.identifier,
                    right_identifier=right.identifier,
                    match_date=left.date,
                    left_cluster_id=left_cluster_id,
                    right_cluster_id=right_cluster_id,
                    required_gap_min=max(base_gap, gap_diff_cluster_min),
                    actual_gap_min=minutes,
                    same_pitch=same_pitch_transition,
                )
            )
            continue

        required_gap = max(base_gap, gap_diff_cluster_min)
        if minutes < required_gap:
            issues.append(
                MobilityTransitionIssue(
                    reason_code="cross_cluster_gap_violation",
                    left_identifier=left.identifier,
                    right_identifier=right.identifier,
                    match_date=left.date,
                    left_cluster_id=left_cluster_id,
                    right_cluster_id=right_cluster_id,
                    required_gap_min=required_gap,
                    actual_gap_min=minutes,
                    same_pitch=same_pitch_transition,
                )
            )

    return issues


def mobility_reason_codes(
    descriptors: list[MatchDescriptor],
    existing_descriptors: list[MatchDescriptor] | None = None,
    *,
    transport,
    gap_same_pitch_min: int,
    gap_diff_pitch_min: int,
    gap_diff_cluster_min: int,
    candidate_identifiers=None,
):
    return _dedupe_preserve_order(
        issue.reason_code
        for issue in inspect_mobility_transitions(
            descriptors,
            existing_descriptors,
            transport=transport,
            gap_same_pitch_min=gap_same_pitch_min,
            gap_diff_pitch_min=gap_diff_pitch_min,
            gap_diff_cluster_min=gap_diff_cluster_min,
            candidate_identifiers=candidate_identifiers,
        )
    )


def diagnose_segment_feasibility(
    *,
    referee_modality,
    availability,
    transport,
    descriptors: list[MatchDescriptor],
    existing_descriptors: list[MatchDescriptor],
    gap_same_pitch_min: int,
    gap_diff_pitch_min: int,
    gap_diff_cluster_min: int,
    availability_end_buffer_min: int,
):
    reason_codes = []

    normalized_referee_modality = normalize_text(referee_modality).lower()
    segment_modalities = {
        normalize_text(descriptor.modality).lower()
        for descriptor in descriptors
        if normalize_text(descriptor.modality)
    }
    if (
        normalized_referee_modality
        and segment_modalities
        and any(modality != normalized_referee_modality for modality in segment_modalities)
    ):
        reason_codes.append("modality_mismatch")

    if any(descriptor.match_datetime is None or pd.isna(descriptor.match_datetime) for descriptor in descriptors):
        reason_codes.append("missing_match_datetime")
    else:
        segment_date = _segment_date(descriptors)
        if segment_date is None or availability is None:
            reason_codes.append("missing_availability_for_day")
        elif not availability_covers_descriptors(
            availability,
            descriptors,
            availability_end_buffer_min=availability_end_buffer_min,
        ):
            reason_codes.append("outside_availability_window")

    reason_codes.extend(
        mobility_reason_codes(
            descriptors,
            existing_descriptors,
            transport=transport,
            gap_same_pitch_min=gap_same_pitch_min,
            gap_diff_pitch_min=gap_diff_pitch_min,
            gap_diff_cluster_min=gap_diff_cluster_min,
        )
    )
    return _dedupe_preserve_order(reason_codes)


def summarize_reason_code(reason_code: str) -> str:
    if reason_code in TIME_CONFLICT_REASON_CODES:
        return "time_conflict_with_existing_assignment"
    return reason_code


def primary_reason_code(reason_codes, *, default: str = "no_viable_referee_after_segmentation") -> str:
    if not reason_codes:
        return default

    for reason_code in REASON_PRIORITY:
        if reason_code in reason_codes:
            return summarize_reason_code(reason_code)
    return summarize_reason_code(reason_codes[0])
