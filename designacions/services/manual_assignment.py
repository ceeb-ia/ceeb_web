from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q
import pandas as pd

from ..main_fixed import _combine_date_time
from ..models import Address, AddressCluster, Assignment, Referee


DEFAULT_AVAILABILITY_END_BUFFER_MIN = 60
DEFAULT_GAP_SAME_PITCH_MIN = 60
DEFAULT_GAP_DIFF_PITCH_MIN = 75

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
    "time_conflict_same_pitch": "Conflicte horari amb un altre partit a la mateixa pista.",
    "time_conflict_diff_pitch": "Conflicte horari amb un altre partit en una altra pista.",
    "missing_availability_for_day": "Sense disponibilitat registrada per al dia del partit.",
    "missing_match_datetime": "No es pot validar l'horari del partit.",
}

REASON_MESSAGES = {
    **WARNING_MESSAGES,
    "missing_cost_inputs": "No es pot calcular el ranking per manca de dades de nivell o categoria.",
}

_FAVORITE_TUTOR_CODE_FRAGMENT = "5413"
_FAVORITE_CLUSTER_IDS = {"12", "13", "9", "6", "10", "15"}


def _normalize_text(value) -> str:
    return str(value or "").strip()


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
    return _combine_date_time(match.date, match.hour_raw)


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


def build_cluster_by_match_id(run):
    match_by_address = {}
    address_texts = set()
    for match in run.matches.all():
        address_text = f"{_normalize_text(match.domicile)}, {_normalize_text(match.municipality)}".strip(", ")
        if address_text:
            match_by_address[match.id] = address_text
            address_texts.add(address_text)

    if not address_texts:
        return {}

    addresses = {address.text: address.id for address in Address.objects.filter(text__in=address_texts)}
    clusters = {
        cluster.address_id: cluster.cluster_id
        for cluster in AddressCluster.objects.filter(run=run, address_id__in=addresses.values())
    }
    return {
        match_id: clusters.get(addresses.get(address_text))
        for match_id, address_text in match_by_address.items()
    }


def _availability_covers_match(raw: dict | None, match, availability_end_buffer_min: int) -> bool:
    if not isinstance(raw, dict):
        return False
    match_dt = _match_datetime(match)
    if match_dt is None or pd.isna(match_dt):
        return False

    start = _parse_time_value(raw.get("Hora Inici"))
    end = _parse_time_value(raw.get("Hora Fi"))
    availability_date = _parse_date_value(raw.get("Data"))
    if availability_date is None or availability_date != match.date or not start or not end:
        return False

    start_dt = datetime.combine(availability_date, start)
    end_dt = datetime.combine(availability_date, end)
    buffered_end_dt = end_dt - timedelta(minutes=availability_end_buffer_min)
    return start_dt <= match_dt.to_pydatetime() <= buffered_end_dt


def _same_pitch(match, other_match) -> bool:
    return _normalize_text(match.venue).lower() == _normalize_text(other_match.venue).lower()


def _detect_time_conflicts(
    assignment,
    referee_id: int,
    assignments_by_referee,
    gap_same_pitch_min: int,
    gap_diff_pitch_min: int,
):
    match = assignment.match
    match_dt = _match_datetime(match)
    if match_dt is None or pd.isna(match_dt):
        return []

    warnings = []
    for other_assignment in assignments_by_referee.get(referee_id, []):
        if other_assignment.id == assignment.id:
            continue
        other_match = other_assignment.match
        if match.date != other_match.date:
            continue
        other_dt = _match_datetime(other_match)
        if other_dt is None or pd.isna(other_dt):
            continue

        minutes = abs((match_dt.to_pydatetime() - other_dt.to_pydatetime()).total_seconds()) / 60.0
        same_pitch = _same_pitch(match, other_match)
        required_gap = gap_same_pitch_min if same_pitch else gap_diff_pitch_min
        if minutes < required_gap:
            warnings.append("time_conflict_same_pitch" if same_pitch else "time_conflict_diff_pitch")
    return warnings


def _compute_cost(match, referee, match_cluster_id):
    tutor_level = _normalize_text(referee.level).upper()
    match_category = _normalize_text(match.category).upper()
    if tutor_level not in TUTOR_LEVEL_ORDER or match_category not in MATCH_LEVEL_ORDER:
        return None

    tutor_idx = TUTOR_LEVEL_ORDER.index(tutor_level)
    match_idx = MATCH_LEVEL_ORDER.index(match_category)
    map_tutor = tutor_idx / (len(TUTOR_LEVEL_ORDER) - 1) if len(TUTOR_LEVEL_ORDER) > 1 else 0
    map_match = match_idx / (len(MATCH_LEVEL_ORDER) - 1) if len(MATCH_LEVEL_ORDER) > 1 else 0
    map_positions = (19 - 3) / (19 - 3)

    distance = abs(map_tutor - map_match)
    distance_classification = abs(map_positions - map_tutor)
    cost = distance * 1000 + distance_classification * 500 + 100

    if _FAVORITE_TUTOR_CODE_FRAGMENT in _normalize_text(referee.code) and match_cluster_id is not None:
        if str(match_cluster_id) in _FAVORITE_CLUSTER_IDS:
            cost *= 0.2
    return float(cost)


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
    cluster_by_match_id = cluster_by_match_id or build_cluster_by_match_id(run)

    gap_same_pitch_min = _config_int(run, "gap_same_pitch_min", DEFAULT_GAP_SAME_PITCH_MIN)
    gap_diff_pitch_min = _config_int(run, "gap_diff_pitch_min", DEFAULT_GAP_DIFF_PITCH_MIN)
    availability_end_buffer_min = _config_int(
        run,
        "availability_end_buffer_min",
        DEFAULT_AVAILABILITY_END_BUFFER_MIN,
    )

    match = assignment.match
    reason_codes = []
    warning_codes = []
    availability = availability_lookup.get((referee.id, match.date)) if match.date else None

    match_dt = _match_datetime(match)
    has_match_datetime = match_dt is not None and not pd.isna(match_dt)

    referee_modality = _normalize_text(referee.modality).lower()
    match_modality = _normalize_text(match.modality).lower()
    if referee_modality and match_modality and referee_modality != match_modality:
        warning_codes.append("modality_mismatch")

    if not has_match_datetime:
        warning_codes.append("missing_match_datetime")
    elif availability is None:
        warning_codes.append("missing_availability_for_day")
    elif not _availability_covers_match(availability, match, availability_end_buffer_min):
        warning_codes.append("outside_availability_window")

    warning_codes.extend(
        _detect_time_conflicts(
            assignment,
            referee.id,
            assignments_by_referee,
            gap_same_pitch_min=gap_same_pitch_min,
            gap_diff_pitch_min=gap_diff_pitch_min,
        )
    )

    seen_warning_codes = set()
    for code in warning_codes:
        if code not in seen_warning_codes:
            reason_codes.append(code)
            seen_warning_codes.add(code)

    cost = _compute_cost(match, referee, cluster_by_match_id.get(match.id))
    if cost is None:
        reason_codes.append("missing_cost_inputs")

    warning_messages = [WARNING_MESSAGES[code] for code in warning_codes if code in WARNING_MESSAGES]
    reason_messages = [REASON_MESSAGES[code] for code in reason_codes if code in REASON_MESSAGES]

    return {
        "assignment": assignment,
        "referee": referee,
        "availability": availability,
        "is_valid": not warning_codes,
        "warning_reasons": warning_codes,
        "warning_messages": warning_messages,
        "warning_text": "; ".join(warning_messages),
        "reason_codes": reason_codes,
        "reason_messages": reason_messages,
        "cost": cost,
        "is_suggested": False,
    }


def build_top_proposals_for_assignments(run, assignments, *, limit: int = 3):
    availability_lookup = build_availability_lookup_by_ref_and_date(run)
    assignments_by_referee = build_assigned_by_referee(run)
    cluster_by_match_id = build_cluster_by_match_id(run)
    candidate_referees = [ref for ref in get_run_referees_with_counts(run) if (ref.n or 0) == 0]

    proposals = {}
    for assignment in assignments:
        ranked = []
        for referee in candidate_referees:
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

        ranked.sort(key=lambda item: (item["cost"], item["referee"].code, item["referee"].name))
        top_ranked = ranked[:limit]
        for idx, diagnosis in enumerate(top_ranked, start=1):
            diagnosis["rank"] = idx
            diagnosis["is_suggested"] = True
        proposals[assignment.id] = top_ranked
    return proposals
