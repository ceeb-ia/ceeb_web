from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Iterable

from designacions.models import AddressCluster, Assignment, DesignationRun
from designacions.services.assignment_feasibility import DEFAULT_GAP_SAME_PITCH_MIN, has_vehicle
from designacions.services.manual_assignment import (
    build_manual_assignment_context,
    diagnose_assignment_for_referee,
)


DEFAULT_AVAILABILITY_END_BUFFER_MIN = 60


@dataclass(frozen=True)
class _Window:
    referee_id: int
    date: date | None
    start_min: int | None
    end_min: int | None
    effective_end_min: int | None


def build_run_analytics(run: DesignationRun) -> dict[str, Any]:
    assignments = list(
        run.assignments.select_related("match", "referee", "trace", "match__address").all()
    )
    assigned = [assignment for assignment in assignments if assignment.referee_id]
    unassigned = [assignment for assignment in assignments if not assignment.referee_id]
    availability_rows = list(run.availabilities.select_related("referee").all())
    availability_buffer = _config_int(run, "availability_end_buffer_min", DEFAULT_AVAILABILITY_END_BUFFER_MIN)
    windows = [_availability_window(row, availability_buffer) for row in availability_rows]
    unique_referee_ids = {row.referee_id for row in availability_rows}
    used_referee_ids = {assignment.referee_id for assignment in assigned if assignment.referee_id}

    total_matches = len(assignments)
    assigned_count = len(assigned)
    unassigned_count = len(unassigned)

    demand_by_hour = _demand_by_hour(run, assignments, windows)
    coverage_by_category = _coverage_rows(assignments, lambda item: _clean(item.match.category) or "Sense categoria")
    coverage_by_modality = _coverage_rows(assignments, lambda item: _clean(item.match.modality) or "Sense modalitat")
    geography_rows = _geography_rows(run, assignments)
    tutor_level_rows = _tutor_level_rows(availability_rows, used_referee_ids)
    load_distribution = _load_distribution(assigned, unique_referee_ids)
    origin_rows = _origin_rows(run, assigned, total_matches)
    vehicle_rows = _vehicle_rows(availability_rows, used_referee_ids)
    unassigned_analysis = _unassigned_analysis(run, unassigned)

    return {
        "kpis": [
            _kpi("Cobertura", f"{assigned_count}/{total_matches}", _percent(assigned_count, total_matches)),
            _kpi("Partits pendents", str(unassigned_count), None),
            _kpi("Tutors usats", f"{len(used_referee_ids)}/{len(unique_referee_ids)}", _percent(len(used_referee_ids), len(unique_referee_ids))),
            _kpi("Tutors amb vehicle", str(_count_vehicle_tutors(availability_rows)), None),
            _kpi("Partits amb 0 tutors viables", str(unassigned_analysis["zero_viable_count"]), None),
            _kpi("Outliers/missing", str(sum(row["total"] for row in geography_rows if row["status"] != "clustered")), None),
        ],
        "summary": {
            "total_matches": total_matches,
            "assigned_matches": assigned_count,
            "unassigned_matches": unassigned_count,
            "available_tutors": len(unique_referee_ids),
            "used_tutors": len(used_referee_ids),
            "availability_end_buffer_min": availability_buffer,
        },
        "demand_by_hour": demand_by_hour,
        "coverage_by_category": coverage_by_category,
        "coverage_by_modality": coverage_by_modality,
        "geography_rows": geography_rows,
        "tutor_level_rows": tutor_level_rows,
        "load_distribution": load_distribution,
        "origin_rows": origin_rows,
        "vehicle_rows": vehicle_rows,
        "unassigned_analysis": unassigned_analysis,
    }


def _demand_by_hour(run: DesignationRun, assignments: list[Assignment], windows: list[_Window]) -> list[dict[str, Any]]:
    same_pitch_gap_min = _config_int(run, "gap_same_pitch_min", DEFAULT_GAP_SAME_PITCH_MIN)
    cluster_lookup = {
        cluster.address_id: cluster
        for cluster in AddressCluster.objects.filter(run=run).select_related("address")
    }
    by_hour: dict[str, dict[str, Any]] = {}
    for assignment in assignments:
        minutes = _time_to_minutes(assignment.match.hour_raw)
        label = _hour_label(minutes)
        row = by_hour.setdefault(
            label,
            {
                "label": label,
                "minutes": minutes if minutes is not None else 10**9,
                "total": 0,
                "assigned": 0,
                "unassigned": 0,
                "raw_available_tutors": 0,
                "schedule_available_tutors": 0,
                "occupied_tutors": 0,
                "gap_blocked_tutors": 0,
                "free_effective_tutors": 0,
                "demand_clusters": 0,
                "served_clusters": 0,
                },
        )
        row["total"] += 1
        if assignment.referee_id:
            row["assigned"] += 1
        else:
            row["unassigned"] += 1

    match_dates_by_hour: dict[str, set[date]] = defaultdict(set)
    for assignment in assignments:
        label = _hour_label(_time_to_minutes(assignment.match.hour_raw))
        if assignment.match.date:
            match_dates_by_hour[label].add(assignment.match.date)

    for row in by_hour.values():
        minutes = row["minutes"] if row["minutes"] != 10**9 else None
        dates = match_dates_by_hour.get(row["label"]) or {None}
        raw_available = {
            _window_slot_key(window)
            for window in windows
            if _window_contains_any_date(window, dates) and _window_contains(window, minutes, effective=False)
        }
        schedule_available = {
            _window_slot_key(window)
            for window in windows
            if _window_contains_any_date(window, dates) and _window_contains(window, minutes, effective=True)
        }
        occupied = {
            (assignment.referee_id, assignment.match.date)
            for assignment in assignments
            if assignment.referee_id
            and _hour_label(_time_to_minutes(assignment.match.hour_raw)) == row["label"]
            and (not dates or assignment.match.date in dates)
        }
        gap_blocked = {
            (assignment.referee_id, assignment.match.date)
            for assignment in assignments
            if assignment.referee_id
            and (not dates or assignment.match.date in dates)
            and _is_within_gap(minutes, _time_to_minutes(assignment.match.hour_raw), same_pitch_gap_min)
        }
        occupied_available = schedule_available & occupied
        gap_blocked_available = schedule_available & gap_blocked
        demanded_clusters = set()
        served_clusters = set()
        for assignment in assignments:
            if _hour_label(_time_to_minutes(assignment.match.hour_raw)) != row["label"]:
                continue
            if dates and assignment.match.date not in dates:
                continue
            cluster_label = _assignment_cluster_label(assignment, cluster_lookup)
            demanded_clusters.add(cluster_label)
            if assignment.referee_id:
                served_clusters.add(cluster_label)
        row["raw_available_tutors"] = len(raw_available)
        row["schedule_available_tutors"] = len(schedule_available)
        row["occupied_tutors"] = len(occupied_available)
        row["gap_blocked_tutors"] = len(gap_blocked_available)
        row["free_effective_tutors"] = max(0, len(schedule_available - gap_blocked))
        row["demand_clusters"] = len(demanded_clusters)
        row["served_clusters"] = len(served_clusters)
        row["coverage_pct"] = _percent(row["assigned"], row["total"])
        row["demand_pct"] = 0.0

    max_total = max((row["total"] for row in by_hour.values()), default=0)
    for row in by_hour.values():
        row["demand_pct"] = _percent(row["total"], max_total)
    return sorted(by_hour.values(), key=lambda item: item["minutes"])


def _assignment_cluster_label(assignment: Assignment, cluster_lookup: dict[int, Any]) -> str:
    cluster = cluster_lookup.get(assignment.match.address_id)
    if cluster and cluster.cluster_id is not None:
        return f"cluster:{cluster.cluster_id}"
    status = cluster.cluster_status if cluster else "missing_geocode"
    return f"{status}:{assignment.match.address_id or assignment.match.venue or assignment.match.code}"


def _coverage_rows(assignments: list[Assignment], label_fn) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for assignment in assignments:
        label = label_fn(assignment)
        row = rows.setdefault(label, {"label": label, "total": 0, "assigned": 0, "unassigned": 0})
        row["total"] += 1
        if assignment.referee_id:
            row["assigned"] += 1
        else:
            row["unassigned"] += 1
    for row in rows.values():
        row["coverage_pct"] = _percent(row["assigned"], row["total"])
        row["bar_pct"] = row["coverage_pct"]
    return sorted(rows.values(), key=lambda item: (-item["total"], item["label"]))


def _geography_rows(run: DesignationRun, assignments: list[Assignment]) -> list[dict[str, Any]]:
    cluster_lookup = {
        cluster.address_id: cluster
        for cluster in AddressCluster.objects.filter(run=run).select_related("address")
    }
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for assignment in assignments:
        cluster = cluster_lookup.get(assignment.match.address_id)
        cluster_id = str(cluster.cluster_id) if cluster and cluster.cluster_id is not None else "sense cluster"
        status = cluster.cluster_status if cluster else "missing_geocode"
        key = (status, cluster_id)
        row = rows.setdefault(
            key,
            {"label": cluster_id, "status": status, "total": 0, "assigned": 0, "unassigned": 0},
        )
        row["total"] += 1
        if assignment.referee_id:
            row["assigned"] += 1
        else:
            row["unassigned"] += 1
    for row in rows.values():
        row["coverage_pct"] = _percent(row["assigned"], row["total"])
    return sorted(rows.values(), key=lambda item: (item["status"], -item["total"], item["label"]))


def _tutor_level_rows(availability_rows: Iterable[Any], used_referee_ids: set[int]) -> list[dict[str, Any]]:
    by_referee = _unique_availability_referees(availability_rows)
    rows: dict[str, dict[str, Any]] = {}
    for referee_id, referee in by_referee.items():
        label = _clean(referee.level) or "Sense nivell"
        row = rows.setdefault(label, {"label": label, "available": 0, "used": 0, "idle": 0})
        row["available"] += 1
        if referee_id in used_referee_ids:
            row["used"] += 1
        else:
            row["idle"] += 1
    for row in rows.values():
        row["used_pct"] = _percent(row["used"], row["available"])
    return sorted(rows.values(), key=lambda item: item["label"])


def _vehicle_rows(availability_rows: Iterable[Any], used_referee_ids: set[int]) -> list[dict[str, Any]]:
    by_referee = _unique_availability_referees(availability_rows)
    rows = {
        "with": {"label": "Amb vehicle", "available": 0, "used": 0, "idle": 0},
        "without": {"label": "Sense vehicle", "available": 0, "used": 0, "idle": 0},
    }
    for referee_id, referee in by_referee.items():
        key = "with" if has_vehicle(referee.transport) else "without"
        rows[key]["available"] += 1
        if referee_id in used_referee_ids:
            rows[key]["used"] += 1
        else:
            rows[key]["idle"] += 1
    for row in rows.values():
        row["used_pct"] = _percent(row["used"], row["available"])
    return list(rows.values())


def _load_distribution(assigned: list[Assignment], unique_referee_ids: set[int]) -> list[dict[str, Any]]:
    counts = Counter(assignment.referee_id for assignment in assigned if assignment.referee_id)
    distribution = Counter()
    for referee_id in unique_referee_ids:
        value = counts.get(referee_id, 0)
        label = "3+" if value >= 3 else str(value)
        distribution[label] += 1
    order = ["0", "1", "2", "3+"]
    max_count = max(distribution.values(), default=0)
    return [
        {"label": label, "tutors": distribution.get(label, 0), "bar_pct": _percent(distribution.get(label, 0), max_count)}
        for label in order
    ]


def _origin_rows(run: DesignationRun, assigned: list[Assignment], total_matches: int) -> list[dict[str, Any]]:
    summary_steps = _origin_steps_from_summary(run)
    if summary_steps:
        return _origin_timeline_rows(summary_steps, total_matches)

    rows: dict[str, dict[str, Any]] = {}
    for assignment in assigned:
        trace = getattr(assignment, "trace", None)
        key = _origin_key(trace)
        row = rows.setdefault(key, {"key": key, "matches": 0, "routes": set()})
        row["matches"] += 1
        route_id = getattr(trace, "route_id", "") if trace else ""
        row["routes"].add(route_id or f"assignment:{assignment.id}")
    return _origin_timeline_rows(
        [
            {
                "key": key,
                "matches": row["matches"],
                "routes": len(row["routes"]),
                "candidate_count": None,
                "viable_candidate_count": None,
            }
            for key, row in sorted(rows.items(), key=lambda item: _origin_order(item[0]))
        ],
        total_matches,
    )


def _origin_timeline_rows(steps: list[dict[str, Any]], total_matches: int) -> list[dict[str, Any]]:
    output = []
    covered = 0
    for step in sorted(steps, key=lambda item: _origin_order(str(item.get("key") or ""))):
        key = str(step.get("key") or "")
        matches = int(step.get("matches") or 0)
        routes = int(step.get("routes") or 0)
        pending_before = max(0, total_matches - covered)
        covered += matches
        pending_after = max(0, total_matches - covered)
        candidate_count = step.get("candidate_count")
        viable_candidate_count = step.get("viable_candidate_count")
        output.append(
            {
                "label": _origin_label(key),
                "description": _origin_description(key),
                "matches": matches,
                "routes": routes,
                "pending_before": pending_before,
                "pending_after": pending_after,
                "candidate_count": candidate_count,
                "viable_candidate_count": viable_candidate_count,
            }
        )
    return output


def _origin_steps_from_summary(run: DesignationRun) -> list[dict[str, Any]]:
    result_summary = getattr(run, "result_summary", None) or {}
    phase_solver_summaries = result_summary.get("phase_solver_summary") or []
    if not phase_solver_summaries:
        return []

    aggregated: dict[str, dict[str, Any]] = {}
    for solver_summary in phase_solver_summaries:
        if not isinstance(solver_summary, dict):
            continue
        for phase_summary in solver_summary.get("phase_summaries") or []:
            if not isinstance(phase_summary, dict):
                continue
            key = str(phase_summary.get("phase_name") or "")
            if key == "individual_rescue":
                continue
            _add_origin_step(aggregated, key, phase_summary)

        final_summary = solver_summary.get("final_rescue_summary") or {}
        if isinstance(final_summary, dict):
            existing_final = final_summary.get("existing_final_rescue") or {}
            if isinstance(existing_final, dict):
                _add_origin_step(aggregated, "final_rescue", existing_final)

            individual = final_summary.get("individual_rescue") or {}
            if isinstance(individual, dict):
                iteration_summaries = individual.get("iteration_summaries") or []
                if iteration_summaries:
                    for iteration_summary in iteration_summaries:
                        if not isinstance(iteration_summary, dict):
                            continue
                        iteration = iteration_summary.get("iteration")
                        key = f"individual_rescue:{iteration}" if iteration else "individual_rescue"
                        _add_origin_step(aggregated, key, iteration_summary)
                else:
                    _add_origin_step(aggregated, "individual_rescue", individual)

    return list(aggregated.values())


def _add_origin_step(target: dict[str, dict[str, Any]], key: str, source: dict[str, Any]) -> None:
    if not key:
        return
    row = target.setdefault(
        key,
        {
            "key": key,
            "matches": 0,
            "routes": 0,
            "candidate_count": 0,
            "viable_candidate_count": 0,
        },
    )
    row["matches"] += _summary_match_count(source)
    row["routes"] += int(source.get("selected_route_count") or source.get("selected_count") or 0)
    row["candidate_count"] += int(source.get("candidate_count") or source.get("route_candidate_count") or 0)
    row["viable_candidate_count"] += int(
        source.get("viable_candidate_count") or source.get("viable_route_candidate_count") or 0
    )


def _summary_match_count(source: dict[str, Any]) -> int:
    return int(
        source.get("selected_match_count")
        or source.get("recovered_match_count")
        or source.get("selected_count")
        or 0
    )


def _unassigned_analysis(run: DesignationRun, unassigned: list[Assignment]) -> dict[str, Any]:
    if not unassigned:
        return {
            "zero_viable_count": 0,
            "viability_bins": [],
            "blocking_reasons": [],
            "bottlenecks": [],
        }

    context = build_manual_assignment_context(run)
    availability_lookup = context["availability_lookup"]
    assignments_by_referee = context["assignments_by_referee"]
    cluster_by_match_id = context["cluster_by_match_id"]
    referees_by_assignment = context["referees_by_assignment"]

    viability_counter = Counter()
    blocking_counter = Counter()
    bottlenecks = []

    for assignment in unassigned:
        viable_count = 0
        candidate_count = 0
        for referee in referees_by_assignment.get(assignment.id, []):
            candidate_count += 1
            diagnosis = diagnose_assignment_for_referee(
                run,
                assignment,
                referee,
                availability_lookup=availability_lookup,
                assignments_by_referee=assignments_by_referee,
                cluster_by_match_id=cluster_by_match_id,
            )
            if diagnosis["is_valid"]:
                viable_count += 1
                continue
            for reason in diagnosis.get("blocking_reasons") or []:
                blocking_counter[reason] += 1
        bin_label = "0" if viable_count == 0 else "1" if viable_count == 1 else "2" if viable_count == 2 else "3+"
        viability_counter[bin_label] += 1
        bottlenecks.append(
            {
                "code": assignment.match.code,
                "hour": assignment.match.hour_raw or "-",
                "category": assignment.match.category or "-",
                "venue": assignment.match.venue or "-",
                "viable_count": viable_count,
                "candidate_count": candidate_count,
            }
        )

    order = ["0", "1", "2", "3+"]
    max_bin = max(viability_counter.values(), default=0)
    return {
        "zero_viable_count": viability_counter.get("0", 0),
        "viability_bins": [
            {"label": label, "matches": viability_counter.get(label, 0), "bar_pct": _percent(viability_counter.get(label, 0), max_bin)}
            for label in order
        ],
        "blocking_reasons": [
            {
                "short_label": _blocking_reason_short_label(key),
                "label": _blocking_reason_label(key),
                "code": key,
                "count": value,
                "bar_pct": _percent(value, max(blocking_counter.values(), default=0)),
            }
            for key, value in blocking_counter.most_common(8)
        ],
        "bottlenecks": sorted(bottlenecks, key=lambda item: (item["viable_count"], item["hour"], item["code"]))[:12],
    }


def _availability_window(row: Any, buffer_min: int) -> _Window:
    start_min = _time_to_minutes(row.raw.get("Hora Inici") if isinstance(row.raw, dict) else None)
    end_min = _time_to_minutes(row.raw.get("Hora Fi") if isinstance(row.raw, dict) else None)
    availability_date = _date_value(row.raw.get("Data") if isinstance(row.raw, dict) else None)
    effective_end = None if end_min is None else max(0, end_min - int(buffer_min or 0))
    return _Window(
        referee_id=row.referee_id,
        date=availability_date,
        start_min=start_min,
        end_min=end_min,
        effective_end_min=effective_end,
    )


def _window_contains_any_date(window: _Window, dates: set[date | None]) -> bool:
    if window.date is None:
        return True
    return window.date in dates


def _window_contains(window: _Window, minutes: int | None, *, effective: bool) -> bool:
    if minutes is None or window.start_min is None:
        return False
    end_min = window.effective_end_min if effective else window.end_min
    if end_min is None:
        return False
    return window.start_min <= minutes <= end_min


def _window_slot_key(window: _Window) -> tuple[int, date | None]:
    return (window.referee_id, window.date)


def _is_within_gap(target_minutes: int | None, assignment_minutes: int | None, gap_min: int) -> bool:
    if target_minutes is None or assignment_minutes is None:
        return False
    return abs(int(target_minutes) - int(assignment_minutes)) < int(gap_min or 0)


def _unique_availability_referees(availability_rows: Iterable[Any]) -> dict[int, Any]:
    referees = {}
    for row in availability_rows:
        if row.referee_id and row.referee_id not in referees:
            referees[row.referee_id] = row.referee
    return referees


def _count_vehicle_tutors(availability_rows: Iterable[Any]) -> int:
    return sum(1 for referee in _unique_availability_referees(availability_rows).values() if has_vehicle(referee.transport))


def _origin_key(trace: Any) -> str:
    if trace is None:
        return "missing_trace"
    raw = getattr(trace, "stage", "") or getattr(trace, "phase_name", "") or getattr(trace, "rescue_kind", "") or "unknown"
    raw = str(raw or "unknown")
    if raw.startswith("phase:"):
        raw = raw.split(":", 1)[1]
    return raw


def _origin_label(key: str) -> str:
    key = str(key or "")
    if key.startswith("individual_rescue:"):
        iteration = key.split(":", 1)[1]
        return f"Repesca individual {iteration}"
    labels = {
        "high": "Fase prioritaria",
        "medium": "Fase intermedia",
        "general": "Fase general",
        "partial_rescue": "Repesca parcial",
        "partial_rescue:high": "Repesca de la fase prioritaria",
        "partial_rescue:medium": "Repesca de la fase intermedia",
        "partial_rescue:general": "Repesca de la fase general",
        "final_rescue": "Repesca final",
        "new_route_rescue": "Repesca amb rutes noves",
        "individual_rescue": "Repesca individual",
        "package_solver": "Package solver",
        "manual_override": "Assignacio manual",
        "missing_trace": "Sense trace",
    }
    return labels.get(key, key.replace("_", " ").title())


def _origin_description(key: str) -> str:
    key = str(key or "")
    if key.startswith("individual_rescue:"):
        return "Passada individual iterativa sobre partits que continuen pendents."
    descriptions = {
        "high": "Primera passada: prioritza els partits de mes nivell amb tutors de nivell alt.",
        "partial_rescue": "Recuperacio immediata de pendents de la fase acabada.",
        "partial_rescue:high": "Recuperacio immediata dels pendents que han quedat de la fase prioritaria.",
        "medium": "Segona passada: amplia l'abast a nivells intermedis i tutors addicionals.",
        "partial_rescue:medium": "Recuperacio immediata dels pendents que han quedat de la fase intermedia.",
        "general": "Passada ampla: intenta resoldre la resta amb criteris generals de cost, nivell, carrega i mobilitat.",
        "partial_rescue:general": "Recuperacio immediata dels pendents que han quedat de la fase general.",
        "final_rescue": "Recuperacio conservadora sobre els pendents que encara encaixen amb assignacions existents.",
        "new_route_rescue": "Crea rutes noves nomes amb partits que encara estan pendents.",
        "individual_rescue": "Assigna pendents d'un en un quan les rutes anteriors ja no progressen.",
        "package_solver": "Assignacio feta pel motor de paquets anterior.",
        "manual_override": "Assignacio modificada manualment despres del motor.",
        "missing_trace": "Assignacio sense informacio de fase guardada.",
    }
    return descriptions.get(key, "Pas automatic del motor.")


def _origin_order(key: str) -> tuple[int, int, str]:
    key = str(key or "")
    order = {
        "high": 10,
        "partial_rescue:high": 20,
        "partial_rescue": 20,
        "medium": 30,
        "partial_rescue:medium": 40,
        "general": 50,
        "partial_rescue:general": 60,
        "final_rescue": 70,
        "new_route_rescue": 80,
        "individual_rescue": 90,
        "package_solver": 100,
        "manual_override": 110,
        "missing_trace": 120,
    }
    if key.startswith("individual_rescue:"):
        try:
            return (90, int(key.split(":", 1)[1]), key)
        except ValueError:
            return (90, 0, key)
    return (order.get(key, 1000), 0, key)


def _blocking_reason_label(code: str) -> str:
    labels = {
        "modality_mismatch": "Descartat per modalitat diferent",
        "missing_match_datetime": "Descartat per falta d'hora o data del partit",
        "missing_availability_for_day": "Descartat per falta de disponibilitat aquell dia",
        "outside_availability_window": "Descartat per estar fora de la disponibilitat declarada del tutor",
        "availability_end_buffer_warning": "Revisar: dins disponibilitat declarada pero massa a prop de l'hora final",
        "same_cluster_gap_violation": "Descartat per gap insuficient entre partits propers",
        "cross_cluster_without_vehicle": "Descartat per canvi de cluster sense vehicle",
        "cross_cluster_gap_violation": "Descartat per gap insuficient per canviar de cluster",
        "missing_cluster_for_mobility_validation": "Descartat per mobilitat amb seu sense cluster fiable",
        "outlier_cluster_for_mobility_validation": "Descartat per criteris de mobilitat a seus fora del cluster",
        "vehicle_required": "Descartat per requerir vehicle",
        "gap_too_short": "Descartat per gap horari insuficient",
    }
    return labels.get(code, code.replace("_", " "))


def _blocking_reason_short_label(code: str) -> str:
    labels = {
        "modality_mismatch": "Modalitat",
        "missing_match_datetime": "Sense hora/data",
        "missing_availability_for_day": "Sense disponibilitat",
        "outside_availability_window": "Fora disponibilitat",
        "availability_end_buffer_warning": "Warning buffer",
        "same_cluster_gap_violation": "Gap mateix cluster",
        "cross_cluster_without_vehicle": "Sense vehicle",
        "cross_cluster_gap_violation": "Gap entre clusters",
        "missing_cluster_for_mobility_validation": "Seu sense cluster",
        "outlier_cluster_for_mobility_validation": "Mobilitat fora cluster",
        "vehicle_required": "Vehicle requerit",
        "gap_too_short": "Gap insuficient",
    }
    return labels.get(code, code.replace("_", " ").title())


def _kpi(label: str, value: str, pct: float | None) -> dict[str, Any]:
    return {"label": label, "value": value, "pct": pct}


def _percent(value: float, total: float) -> float:
    if not total:
        return 0.0
    return round((float(value) / float(total)) * 100.0, 1)


def _config_int(run: DesignationRun, key: str, default: int) -> int:
    params = getattr(run, "params", None) or {}
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError):
        return default


def _time_to_minutes(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.time()
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    text = str(value).strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None


def _hour_label(minutes: int | None) -> str:
    if minutes is None:
        return "Sense hora"
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _date_value(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return None


def _clean(value: Any) -> str:
    return str(value or "").strip()
