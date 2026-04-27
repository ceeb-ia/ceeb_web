from __future__ import annotations

from collections import defaultdict
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time

from django.db.models import Count, Q
import pandas as pd

from ..models import AddressCluster, Assignment, Referee
from .assignment_feasibility import (
    DEFAULT_AVAILABILITY_END_BUFFER_MIN,
    DEFAULT_GAP_DIFF_CLUSTER_MIN,
    DEFAULT_GAP_DIFF_PITCH_MIN,
    DEFAULT_GAP_SAME_PITCH_MIN,
    availability_covers_descriptors,
    build_match_descriptor,
    combine_date_time,
    inspect_mobility_transitions,
)

TUTOR_LEVEL_ORDER = ["NIVELLA1", "NIVELLB1", "NIVELLC1", "NIVELLD1", "D"]
MATCH_LEVEL_ORDER = [
    "S\u00c8NIOR",
    "J\u00daNIOR",
    "JUVENIL",
    "CADET",
    "INFANTIL",
    "PREINFANTIL",
    "ALEV\u00cd",
    "PREALEV\u00cd",
    "BENJAM\u00cd",
    "PREBENJAM\u00cd",
    "MENUDETS",
    "MENUTS",
]

WARNING_MESSAGES = {
    "modality_mismatch": "Modalitat diferent de la del partit.",
    "outside_availability_window": "Fora de la franja de disponibilitat del tutor.",
    "same_cluster_gap_violation": "Gap insuficient per atendre dos partits dins del mateix cluster.",
    "same_cluster_pitch_change_warning": "Canvi de pista dins del mateix cluster. Assignacio viable, pendent de revisio.",
    "cross_cluster_with_vehicle_warning": "Canvi de cluster amb vehicle i gap suficient. Assignacio viable, pendent de revisio.",
    "cross_cluster_gap_violation": "Gap insuficient per canviar de cluster.",
    "cross_cluster_without_vehicle": "Canvi de cluster no permes per a un tutor sense vehicle.",
    "missing_cluster_for_mobility_validation": "Falta cluster per validar la mobilitat del tutor.",
    "missing_cluster_mobility_warning": "Falta cluster o geocodificacio per validar completament el canvi de pista.",
    "outlier_cluster_for_mobility_validation": "La ubicacio ha quedat fora de cluster i no es pot validar la mobilitat del tutor.",
    "outlier_mobility_warning": "Almenys una ubicacio del canvi de pista no te cluster fiable.",
    "missing_availability_for_day": "Sense disponibilitat registrada per al dia del partit.",
    "missing_match_datetime": "No es pot validar l'horari del partit.",
    "time_conflict_same_pitch": "Solapament o gap insuficient entre partits a la mateixa pista.",
    "time_conflict_diff_pitch": "Solapament o gap insuficient entre partits en pistes diferents.",
}

REASON_MESSAGES = {
    **WARNING_MESSAGES,
    "missing_cost_inputs": "No es pot calcular el ranking per manca de dades de nivell o categoria.",
}

_FAVORITE_TUTOR_CODE_FRAGMENT = "5413"
_FAVORITE_CLUSTER_IDS = {"12", "13", "9", "6", "10", "15"}
LOAD_BALANCING_PENALTY_PER_ASSIGNMENT = 50

INFORMATIONAL_MOBILITY_REASON_CODES = {
    "same_cluster_pitch_change_warning",
    "cross_cluster_with_vehicle_warning",
    "missing_cluster_mobility_warning",
    "outlier_mobility_warning",
}
PITCH_CHANGE_WARNING_REASON_CODES = {
    "same_cluster_pitch_change_warning",
    "cross_cluster_with_vehicle_warning",
    "missing_cluster_mobility_warning",
    "outlier_mobility_warning",
}


@dataclass(frozen=True)
class RunScopedRefereeSummary:
    referee: Referee
    id: int
    code: str
    name: str
    level: str
    modality: str
    transport: str
    n: int


def _normalize_text(value) -> str:
    return str(value or "").strip()


def _normalized_modality(value) -> str:
    return _normalize_text(value).lower()


def _referee_instance(referee_like):
    return getattr(referee_like, "referee", referee_like)


def _referee_field(referee_like, field: str, default=""):
    value = getattr(referee_like, field, None)
    if value not in (None, ""):
        return value
    return getattr(_referee_instance(referee_like), field, default)


def _ordered_run_availability_rows(run):
    rows = []
    for availability in run.availabilities.select_related("referee").all():
        raw = availability.raw or {}
        availability_date = _parse_date_value(raw.get("Data"))
        start = _parse_time_value(raw.get("Hora Inici"))
        rows.append((availability.referee_id, availability_date or date.max, start or time.max, availability.id, raw))
    rows.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    grouped = defaultdict(list)
    for referee_id, _availability_date, _start, _availability_id, raw in rows:
        grouped[referee_id].append(raw)
    return grouped


def _resolve_run_scoped_field(raw_rows: list[dict], key: str | tuple[str, ...], fallback: str = "") -> str:
    if not raw_rows:
        return _normalize_text(fallback)

    keys = (key,) if isinstance(key, str) else key
    present_entries = []
    for index, raw in enumerate(raw_rows):
        for candidate in keys:
            if candidate in raw:
                present_entries.append((_normalize_text(raw.get(candidate)), index))
                break

    if not present_entries:
        if any("transport" in _normalize_text(candidate).lower() for candidate in keys):
            for index, raw in enumerate(raw_rows):
                for raw_key, raw_value in raw.items():
                    normalized_key = _normalize_text(raw_key).lower()
                    if "mitj" in normalized_key and "transport" in normalized_key:
                        present_entries.append((_normalize_text(raw_value), index))
                        break
        if not present_entries:
            return _normalize_text(fallback)

    non_empty_values = [value for value, _index in present_entries if value]
    if not non_empty_values:
        return ""

    counts = Counter(non_empty_values)
    first_indexes = {}
    for value, index in present_entries:
        if value and value not in first_indexes:
            first_indexes[value] = index
    max_count = max(counts.values())
    candidates = [value for value, count in counts.items() if count == max_count]
    candidates.sort(key=lambda value: (first_indexes.get(value, float("inf")), value))
    return candidates[0]


def _parse_date_value(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = _normalize_text(value)
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


def _parse_time_value(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    if isinstance(value, time):
        return value.replace(microsecond=0)
    raw = _normalize_text(value)
    if not raw or raw == "-":
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


def _match_datetime(match):
    return combine_date_time(match.date, match.hour_raw)


def _config_int(run, key: str, default: int) -> int:
    params = getattr(run, "params", None) or {}
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError):
        return default


def get_run_referees_with_counts(run):
    return (
        Referee.objects.filter(active=True, availabilities__run=run)
        .annotate(n=Count("assignments", filter=Q(assignments__run=run), distinct=True))
        .distinct()
        .order_by("code", "name")
    )


def _build_run_scoped_referee_summaries_legacy(run, referees_with_counts=None):
    return build_run_scoped_referee_summaries(run, referees_with_counts=referees_with_counts)

    referees_with_counts = list(referees_with_counts or get_run_referees_with_counts(run))
    availability_rows_by_ref = _ordered_run_availability_rows(run)
    summaries = []
    for referee in referees_with_counts:
        raw_rows = availability_rows_by_ref.get(referee.id, [])
        summaries.append(
            RunScopedRefereeSummary(
                referee=referee,
                id=referee.id,
                code=referee.code or "",
                name=referee.name or "",
                level=_resolve_run_scoped_field(raw_rows, "Nivell", fallback=referee.level or ""),
                modality=_resolve_run_scoped_field(raw_rows, "Modalitat", fallback=referee.modality or ""),
                transport=_resolve_run_scoped_field(raw_rows, "Mitjà de Transport", fallback=referee.transport or ""),
                n=referee.n or 0,
            )
        )
    return summaries


def build_run_scoped_referee_summaries(run, referees_with_counts=None):
    referees_with_counts = list(referees_with_counts or get_run_referees_with_counts(run))
    availability_rows_by_ref = _ordered_run_availability_rows(run)
    summaries = []
    for referee in referees_with_counts:
        raw_rows = availability_rows_by_ref.get(referee.id, [])
        summaries.append(
            RunScopedRefereeSummary(
                referee=referee,
                id=referee.id,
                code=referee.code or "",
                name=referee.name or "",
                level=_resolve_run_scoped_field(raw_rows, "Nivell", fallback=referee.level or ""),
                modality=_resolve_run_scoped_field(raw_rows, "Modalitat", fallback=referee.modality or ""),
                transport=_resolve_run_scoped_field(
                    raw_rows,
                    ("Mitjà de Transport", "MitjÃ  de Transport"),
                    fallback=referee.transport or "",
                ),
                n=referee.n or 0,
            )
        )
    return summaries


def build_run_scoped_referee_summary_by_id(run, referees_with_counts=None):
    summaries = build_run_scoped_referee_summaries(run, referees_with_counts=referees_with_counts)
    return {summary.id: summary for summary in summaries}


def build_availability_lookup_by_ref_and_date(run):
    lookup = {}
    for availability in run.availabilities.select_related("referee").all():
        raw = availability.raw or {}
        availability_date = _parse_date_value(raw.get("Data"))
        if availability_date is None:
            continue
        key = (availability.referee_id, availability_date)
        current = lookup.get(key)
        current_score = sum(bool((current or {}).get(field)) for field in ("Hora Inici", "Hora Fi"))
        new_score = sum(bool(raw.get(field)) for field in ("Hora Inici", "Hora Fi"))
        if current is None or new_score >= current_score:
            lookup[key] = raw
    return lookup


def build_availability_display_by_ref(run):
    by_ref = defaultdict(list)
    for availability in run.availabilities.select_related("referee").all():
        raw = availability.raw or {}
        availability_date = _parse_date_value(raw.get("Data"))
        start = _parse_time_value(raw.get("Hora Inici"))
        end = _parse_time_value(raw.get("Hora Fi"))

        parts = []
        if availability_date is not None:
            parts.append(availability_date.strftime("%d/%m/%Y"))
        if start and end:
            parts.append(f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
        elif start:
            parts.append(f"des de {start.strftime('%H:%M')}")
        elif end:
            parts.append(f"fins {end.strftime('%H:%M')}")

        summary = " ".join(parts).strip() or "-"
        by_ref[availability.referee_id].append((availability_date or date.min, summary))

    display = {}
    for referee_id, items in by_ref.items():
        ordered = [summary for _, summary in sorted(items, key=lambda item: item[0])]
        display[referee_id] = " | ".join(ordered)
    return display


def build_assignment_availability_by_assignment(assignments, availability_lookup):
    result = {}
    for assignment in assignments:
        if assignment.referee_id and assignment.match.date:
            result[assignment.id] = availability_lookup.get((assignment.referee_id, assignment.match.date))
        else:
            result[assignment.id] = None
    return result


def build_assigned_by_referee(run):
    assigned = defaultdict(list)
    for assignment in run.assignments.select_related("match", "referee").filter(referee__isnull=False):
        assigned[assignment.referee_id].append(assignment)
    return assigned


def build_match_location_by_match_id(run):
    matches = list(run.matches.select_related("address").all())
    address_ids = {match.address_id for match in matches if match.address_id}
    cluster_by_address_id = {
        cluster.address_id: {
            "cluster_id": cluster.cluster_id,
            "cluster_status": cluster.cluster_status,
        }
        for cluster in AddressCluster.objects.filter(run=run, address_id__in=address_ids)
    }

    locations = {}
    for match in matches:
        cluster_info = cluster_by_address_id.get(match.address_id, {})
        locations[match.id] = {
            "address_id": match.address_id,
            "cluster_id": cluster_info.get("cluster_id"),
            "cluster_status": cluster_info.get("cluster_status"),
        }
    return locations


def build_cluster_by_match_id(run):
    return {
        match_id: location.get("cluster_id")
        for match_id, location in build_match_location_by_match_id(run).items()
    }


def build_referee_options_by_assignment(run, assignments, referees_with_counts=None):
    referees_with_counts = list(referees_with_counts or build_run_scoped_referee_summaries(run))
    by_modality = defaultdict(list)
    for referee in referees_with_counts:
        by_modality[_normalized_modality(referee.modality)].append(referee)

    options = {}
    for assignment in assignments:
        match_modality = _normalized_modality(assignment.match.modality)
        options[assignment.id] = by_modality.get(match_modality, []) if match_modality else referees_with_counts
    return options


def build_manual_assignment_context(run, referees_with_counts=None):
    referees_with_counts = list(referees_with_counts or get_run_referees_with_counts(run))
    referee_summaries = build_run_scoped_referee_summaries(run, referees_with_counts=referees_with_counts)
    availability_lookup = build_availability_lookup_by_ref_and_date(run)
    assignments_by_referee = build_assigned_by_referee(run)
    match_location_by_match_id = build_match_location_by_match_id(run)
    cluster_by_match_id = {
        match_id: location.get("cluster_id")
        for match_id, location in match_location_by_match_id.items()
    }
    referees_by_assignment = build_referee_options_by_assignment(
        run,
        run.assignments.select_related("match").all(),
        referees_with_counts=referee_summaries,
    )
    return {
        "referees_with_counts": referees_with_counts,
        "referee_summaries": referee_summaries,
        "referee_summaries_by_id": {summary.id: summary for summary in referee_summaries},
        "availability_lookup": availability_lookup,
        "assignments_by_referee": assignments_by_referee,
        "cluster_by_match_id": cluster_by_match_id,
        "match_location_by_match_id": match_location_by_match_id,
        "referees_by_assignment": referees_by_assignment,
    }


def _availability_covers_match(raw: dict | None, match, availability_end_buffer_min: int) -> bool:
    descriptor = build_match_descriptor(
        identifier=match.id,
        date_value=match.date,
        time_value=match.hour_raw,
        venue=match.venue,
        modality=match.modality,
        category=match.category,
    )
    return availability_covers_descriptors(raw, [descriptor], availability_end_buffer_min)


def _build_assignment_descriptor(assignment, match_location_by_match_id):
    match = assignment.match
    location = match_location_by_match_id.get(match.id, {})
    return build_match_descriptor(
        identifier=assignment.id,
        date_value=match.date,
        time_value=match.hour_raw,
        venue=match.venue,
        modality=match.modality,
        category=match.category,
        cluster_id=location.get("cluster_id"),
        address_id=location.get("address_id"),
        cluster_status=location.get("cluster_status"),
    )


def _detect_mobility_conflicts(
    assignment,
    referee,
    assignments_by_referee,
    match_location_by_match_id,
    gap_same_pitch_min: int,
    gap_diff_pitch_min: int,
    gap_diff_cluster_min: int,
):
    match_descriptor = _build_assignment_descriptor(assignment, match_location_by_match_id)
    existing_descriptors = []
    for other_assignment in assignments_by_referee.get(referee.id, []):
        if other_assignment.id == assignment.id:
            continue
        existing_descriptors.append(_build_assignment_descriptor(other_assignment, match_location_by_match_id))
    return inspect_mobility_transitions(
        [match_descriptor],
        existing_descriptors,
        transport=_referee_field(referee, "transport"),
        gap_same_pitch_min=gap_same_pitch_min,
        gap_diff_pitch_min=gap_diff_pitch_min,
        gap_diff_cluster_min=gap_diff_cluster_min,
    )


def _is_informational_mobility_issue(issue) -> bool:
    reason_code = _normalize_text(getattr(issue, "reason_code", ""))
    return reason_code in INFORMATIONAL_MOBILITY_REASON_CODES or reason_code.endswith("_warning")


def _is_pitch_change_warning(reason_code: str) -> bool:
    normalized = _normalize_text(reason_code)
    return normalized in PITCH_CHANGE_WARNING_REASON_CODES or "pitch_change" in normalized


def _mobility_issue_summary_item(issue, referee_id, referee, left_assignment, right_assignment) -> dict:
    return {
        "referee_id": referee_id,
        "referee_code": _referee_field(referee, "code"),
        "referee_name": _referee_field(referee, "name"),
        "reason_code": issue.reason_code,
        "message": WARNING_MESSAGES.get(issue.reason_code, issue.reason_code),
        "clusters": [cluster for cluster in [issue.left_cluster_id, issue.right_cluster_id] if cluster is not None],
        "match_codes": [
            left_assignment.match.code if left_assignment else str(issue.left_identifier),
            right_assignment.match.code if right_assignment else str(issue.right_identifier),
        ],
        "assignment_ids": [
            left_assignment.id if left_assignment else None,
            right_assignment.id if right_assignment else None,
        ],
        "manual_override": bool(
            (left_assignment and left_assignment.manual_override_warning)
            or (right_assignment and right_assignment.manual_override_warning)
        ),
        "required_gap_min": issue.required_gap_min,
        "actual_gap_min": issue.actual_gap_min,
        "same_pitch": issue.same_pitch,
        "severity": getattr(issue, "severity", "blocking"),
    }


def classify_level_fit(match, referee) -> dict:
    tutor_level = _normalize_text(_referee_field(referee, "level")).upper()
    match_category = _normalize_text(match.category).upper()
    if tutor_level not in TUTOR_LEVEL_ORDER or match_category not in MATCH_LEVEL_ORDER:
        return {
            "label": "unscorable",
            "tutor_level": tutor_level,
            "match_category": match_category,
            "tutor_index": None,
            "expected_tutor_index": None,
            "band_delta": None,
        }

    tutor_idx = TUTOR_LEVEL_ORDER.index(tutor_level)
    match_idx = MATCH_LEVEL_ORDER.index(match_category)
    map_tutor = tutor_idx / (len(TUTOR_LEVEL_ORDER) - 1) if len(TUTOR_LEVEL_ORDER) > 1 else 0
    map_match = match_idx / (len(MATCH_LEVEL_ORDER) - 1) if len(MATCH_LEVEL_ORDER) > 1 else 0
    expected_tutor_idx = int(round(map_match * (len(TUTOR_LEVEL_ORDER) - 1)))
    band_delta = tutor_idx - expected_tutor_idx

    if band_delta == 0:
        label = "ideal"
    elif band_delta == 1:
        label = "slightly_underleveled"
    elif band_delta == -1:
        label = "slightly_overleveled"
    elif band_delta >= 2:
        label = "clearly_underleveled"
    else:
        label = "clearly_overleveled"

    return {
        "label": label,
        "tutor_level": tutor_level,
        "match_category": match_category,
        "tutor_index": tutor_idx,
        "expected_tutor_index": expected_tutor_idx,
        "band_delta": band_delta,
        "normalized_tutor_position": map_tutor,
        "normalized_match_position": map_match,
    }


def compute_cost_breakdown(match, referee, match_cluster_id) -> dict:
    level_fit = classify_level_fit(match, referee)
    if level_fit["label"] == "unscorable":
        return {
            "base_level_cost": None,
            "cluster_adjustment": None,
            "cost": None,
        }

    map_tutor = level_fit["normalized_tutor_position"]
    map_match = level_fit["normalized_match_position"]
    map_positions = (19 - 3) / (19 - 3)

    distance = abs(map_tutor - map_match)
    distance_classification = abs(map_positions - map_tutor)
    base_level_cost = float(distance * 1000 + distance_classification * 500 + 100)
    cost = base_level_cost

    if _FAVORITE_TUTOR_CODE_FRAGMENT in _normalize_text(_referee_field(referee, "code")) and match_cluster_id is not None:
        if str(match_cluster_id) in _FAVORITE_CLUSTER_IDS:
            cost *= 0.2
    final_cost = float(cost)
    return {
        "base_level_cost": base_level_cost,
        "cluster_adjustment": float(final_cost - base_level_cost),
        "cost": final_cost,
    }


def _compute_cost(match, referee, match_cluster_id):
    return compute_cost_breakdown(match, referee, match_cluster_id)["cost"]


def diagnose_assignment_for_referee(
    run,
    assignment: Assignment,
    referee: Referee,
    *,
    availability_lookup=None,
    assignments_by_referee=None,
    cluster_by_match_id=None,
):
    availability_lookup = availability_lookup or build_availability_lookup_by_ref_and_date(run)
    assignments_by_referee = assignments_by_referee or build_assigned_by_referee(run)
    match_location_by_match_id = build_match_location_by_match_id(run)
    if cluster_by_match_id is None:
        cluster_by_match_id = {
            match_id: location.get("cluster_id")
            for match_id, location in match_location_by_match_id.items()
        }

    gap_same_pitch_min = _config_int(run, "gap_same_pitch_min", DEFAULT_GAP_SAME_PITCH_MIN)
    gap_diff_pitch_min = _config_int(run, "gap_diff_pitch_min", DEFAULT_GAP_DIFF_PITCH_MIN)
    gap_diff_cluster_min = _config_int(run, "gap_diff_cluster_min", DEFAULT_GAP_DIFF_CLUSTER_MIN)
    availability_end_buffer_min = _config_int(
        run,
        "availability_end_buffer_min",
        DEFAULT_AVAILABILITY_END_BUFFER_MIN,
    )

    match = assignment.match
    reason_codes = []
    blocking_codes = []
    advisory_codes = []
    availability = availability_lookup.get((referee.id, match.date)) if match.date else None

    match_dt = _match_datetime(match)
    has_match_datetime = match_dt is not None and not pd.isna(match_dt)

    referee_modality = _normalize_text(_referee_field(referee, "modality")).lower()
    match_modality = _normalize_text(match.modality).lower()
    if referee_modality and match_modality and referee_modality != match_modality:
        blocking_codes.append("modality_mismatch")

    if not has_match_datetime:
        blocking_codes.append("missing_match_datetime")
    elif availability is None:
        blocking_codes.append("missing_availability_for_day")
    elif not _availability_covers_match(availability, match, availability_end_buffer_min):
        blocking_codes.append("outside_availability_window")

    mobility_issues = _detect_mobility_conflicts(
        assignment,
        referee,
        assignments_by_referee,
        match_location_by_match_id,
        gap_same_pitch_min=gap_same_pitch_min,
        gap_diff_pitch_min=gap_diff_pitch_min,
        gap_diff_cluster_min=gap_diff_cluster_min,
    )
    for issue in mobility_issues:
        if _is_informational_mobility_issue(issue):
            advisory_codes.append(issue.reason_code)
        else:
            blocking_codes.append(issue.reason_code)

    warning_codes = []
    seen_warning_codes = set()
    for code in [*blocking_codes, *advisory_codes]:
        if code not in seen_warning_codes:
            warning_codes.append(code)
            reason_codes.append(code)
            seen_warning_codes.add(code)

    cost = _compute_cost(match, referee, cluster_by_match_id.get(match.id))
    if cost is None:
        reason_codes.append("missing_cost_inputs")

    n_assignments_in_run = len(assignments_by_referee.get(referee.id, []))
    effective_cost = (cost + (n_assignments_in_run * LOAD_BALANCING_PENALTY_PER_ASSIGNMENT)) if cost is not None else None

    warning_messages = [WARNING_MESSAGES[code] for code in warning_codes if code in WARNING_MESSAGES]
    reason_messages = [REASON_MESSAGES[code] for code in reason_codes if code in REASON_MESSAGES]

    return {
        "assignment": assignment,
        "referee": referee,
        "availability": availability,
        "is_valid": not blocking_codes,
        "blocking_reasons": list(dict.fromkeys(blocking_codes)),
        "advisory_reasons": list(dict.fromkeys(advisory_codes)),
        "warning_reasons": warning_codes,
        "warning_messages": warning_messages,
        "warning_text": "; ".join(warning_messages),
        "reason_codes": reason_codes,
        "reason_messages": reason_messages,
        "cost": cost,
        "n_assignments_in_run": n_assignments_in_run,
        "effective_cost": effective_cost,
        "is_suggested": False,
        "mobility_issues": mobility_issues,
    }


def build_run_mobility_summary(run, *, context=None):
    context = context or build_manual_assignment_context(run)
    assignments_by_referee = context["assignments_by_referee"]
    match_location_by_match_id = context["match_location_by_match_id"]
    referee_summary_by_id = context["referee_summaries_by_id"]

    gap_same_pitch_min = _config_int(run, "gap_same_pitch_min", DEFAULT_GAP_SAME_PITCH_MIN)
    gap_diff_pitch_min = _config_int(run, "gap_diff_pitch_min", DEFAULT_GAP_DIFF_PITCH_MIN)
    gap_diff_cluster_min = _config_int(run, "gap_diff_cluster_min", DEFAULT_GAP_DIFF_CLUSTER_MIN)

    warnings = []
    errors = []
    pitch_change_warnings = []
    warning_assignment_ids = defaultdict(list)
    error_assignment_ids = defaultdict(list)
    warning_counts_by_referee = Counter()
    error_counts_by_referee = Counter()

    for referee_id, assignments in assignments_by_referee.items():
        if not assignments:
            continue

        descriptors = [_build_assignment_descriptor(assignment, match_location_by_match_id) for assignment in assignments]
        descriptors_by_id = {str(descriptor.identifier): descriptor for descriptor in descriptors}
        referee = referee_summary_by_id.get(referee_id)
        issues = inspect_mobility_transitions(
            descriptors,
            transport=_referee_field(referee, "transport"),
            gap_same_pitch_min=gap_same_pitch_min,
            gap_diff_pitch_min=gap_diff_pitch_min,
            gap_diff_cluster_min=gap_diff_cluster_min,
            candidate_identifiers=[],
        )

        assignment_by_id = {str(assignment.id): assignment for assignment in assignments}
        valid_clusters = sorted(
            {
                descriptor.cluster_id
                for descriptor in descriptors
                if descriptor.cluster_id is not None
            }
        )
        sorted_match_codes = [
            assignment.match.code
            for assignment in sorted(
                assignments,
                key=lambda item: (item.match.date or date.max, item.match.hour_raw or "", item.match.code or ""),
            )
        ]

        if len(valid_clusters) > 1 and not issues:
            warning = {
                "referee_id": referee_id,
                "referee_code": _referee_field(referee, "code"),
                "referee_name": _referee_field(referee, "name"),
                "reason_code": "cross_cluster_with_vehicle_warning",
                "clusters": valid_clusters,
                "match_codes": sorted_match_codes,
                "assignment_ids": [assignment.id for assignment in assignments],
                "message": WARNING_MESSAGES["cross_cluster_with_vehicle_warning"],
            }
            warnings.append(warning)
            pitch_change_warnings.append(warning)
            warning_counts_by_referee[referee_id] += 1
            for assignment in assignments:
                warning_assignment_ids[assignment.id].append(warning)

        for issue in issues:
            left_assignment = assignment_by_id.get(str(issue.left_identifier))
            right_assignment = assignment_by_id.get(str(issue.right_identifier))
            item = _mobility_issue_summary_item(issue, referee_id, referee, left_assignment, right_assignment)
            if _is_informational_mobility_issue(issue):
                warnings.append(item)
                if _is_pitch_change_warning(issue.reason_code):
                    pitch_change_warnings.append(item)
                warning_counts_by_referee[referee_id] += 1
                if left_assignment is not None:
                    warning_assignment_ids[left_assignment.id].append(item)
                if right_assignment is not None:
                    warning_assignment_ids[right_assignment.id].append(item)
                continue

            errors.append(item)
            error_counts_by_referee[referee_id] += 1
            if left_assignment is not None:
                error_assignment_ids[left_assignment.id].append(item)
            if right_assignment is not None:
                error_assignment_ids[right_assignment.id].append(item)

    return {
        "mobility_warning_count": len(warnings),
        "mobility_error_count": len(errors),
        "mobility_warnings": warnings,
        "mobility_errors": errors,
        "pitch_change_warning_count": len(pitch_change_warnings),
        "pitch_change_warnings": pitch_change_warnings,
        "warning_assignment_ids": dict(warning_assignment_ids),
        "error_assignment_ids": dict(error_assignment_ids),
        "warning_counts_by_referee": dict(warning_counts_by_referee),
        "error_counts_by_referee": dict(error_counts_by_referee),
    }


def update_run_mobility_summary(run, *, context=None, save: bool = True):
    summary = build_run_mobility_summary(run, context=context)
    merged = dict(getattr(run, "result_summary", None) or {})
    merged.update(
        {
            "mobility_warning_count": summary["mobility_warning_count"],
            "mobility_error_count": summary["mobility_error_count"],
            "mobility_warnings": summary["mobility_warnings"],
            "mobility_errors": summary["mobility_errors"],
            "pitch_change_warning_count": summary["pitch_change_warning_count"],
            "pitch_change_warnings": summary["pitch_change_warnings"],
        }
    )
    run.result_summary = merged
    if save and getattr(run, "pk", None):
        run.save(update_fields=["result_summary"])
    return summary


def build_top_proposals_for_assignments(run, assignments, *, limit: int = 3, context=None):
    context = context or build_manual_assignment_context(run)
    availability_lookup = context["availability_lookup"]
    assignments_by_referee = context["assignments_by_referee"]
    cluster_by_match_id = context["cluster_by_match_id"]
    referees_by_assignment = context["referees_by_assignment"]

    proposals = {}
    for assignment in assignments:
        ranked = []
        for referee in referees_by_assignment.get(assignment.id, []):
            diagnosis = diagnose_assignment_for_referee(
                run,
                assignment,
                referee,
                availability_lookup=availability_lookup,
                assignments_by_referee=assignments_by_referee,
                cluster_by_match_id=cluster_by_match_id,
            )
            if diagnosis["is_valid"] and diagnosis["cost"] is not None:
                ranked.append(diagnosis)

        ranked.sort(
            key=lambda item: (
                item["effective_cost"],
                item["cost"],
                item["n_assignments_in_run"],
                _referee_field(item["referee"], "code"),
                _referee_field(item["referee"], "name"),
            )
        )
        top_ranked = ranked[:limit]
        for idx, diagnosis in enumerate(top_ranked, start=1):
            diagnosis["rank"] = idx
            diagnosis["is_suggested"] = True
        proposals[assignment.id] = top_ranked
    return proposals


def availability_label(raw: dict | None) -> str:
    if not isinstance(raw, dict):
        return "-"

    availability_date = _parse_date_value(raw.get("Data"))
    start = _parse_time_value(raw.get("Hora Inici"))
    end = _parse_time_value(raw.get("Hora Fi"))

    parts = []
    if availability_date is not None:
        parts.append(availability_date.strftime("%d/%m/%Y"))
    if start and end:
        parts.append(f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
    elif start:
        parts.append(f"des de {start.strftime('%H:%M')}")
    elif end:
        parts.append(f"fins {end.strftime('%H:%M')}")
    return " ".join(parts).strip() or "-"


def serialize_proposal(diagnosis: dict) -> dict:
    referee = diagnosis["referee"]
    return {
        "rank": diagnosis.get("rank"),
        "referee_id": referee.id,
        "code": _referee_field(referee, "code"),
        "name": _referee_field(referee, "name"),
        "level": _referee_field(referee, "level") or "",
        "availability_label": availability_label(diagnosis.get("availability")),
        "cost": diagnosis.get("cost"),
        "effective_cost": diagnosis.get("effective_cost"),
        "level_fit": diagnosis.get("level_fit"),
        "quality_label": diagnosis.get("quality_label"),
        "selection_reason_summary": diagnosis.get("selection_reason_summary", ""),
    }


def serialize_referee_option(referee: Referee) -> dict:
    return {
        "id": referee.id,
        "code": _referee_field(referee, "code"),
        "name": _referee_field(referee, "name"),
        "level": _referee_field(referee, "level") or "",
    }
