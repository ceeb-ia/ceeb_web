from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable, Mapping


def build_phase_summary(
    phase_name: str,
    *,
    eligible_tutors: Iterable[Any] | None = None,
    pending_fragments_before: Iterable[Any] | None = None,
    route_candidates: Iterable[Any] | None = None,
    selected_routes: Iterable[Any] | None = None,
    pending_match_ids_after: Iterable[Any] | None = None,
) -> dict[str, Any]:
    candidates = [_object_to_dict(candidate) for candidate in (route_candidates or [])]
    selected = [_object_to_dict(route) for route in (selected_routes or [])]
    pending_before = list(pending_fragments_before or [])
    blocking_reason_counts: Counter[str] = Counter()
    for candidate in candidates:
        blocking_reason_counts.update(_normalize_ids(candidate.get("blocking_reasons")))
    return {
        "phase_name": phase_name,
        "eligible_tutor_count": len(list(eligible_tutors or [])),
        "pending_fragment_count_before": len(pending_before),
        "route_candidate_count": len(candidates),
        "viable_route_candidate_count": sum(1 for candidate in candidates if not candidate.get("blocking_reasons")),
        "selected_route_count": len(selected),
        "selected_match_count": len(_route_match_ids(selected)),
        "pending_match_count_after": len(_normalize_ids(pending_match_ids_after)),
        "selected_by_level_fit": selected_by_level_fit(selected),
        "load_penalty_total": sum(_load_penalty(route) for route in selected),
        "blocking_reason_counts": dict(sorted(blocking_reason_counts.items())),
        "peak_buckets_selected": _peak_buckets(selected),
        "peak_anchor_candidate_count": sum(1 for candidate in candidates if _score_breakdown(candidate).get("peak_anchor")),
        "peak_anchor_selected_match_count": len(_peak_anchor_selected_match_ids(selected)),
        "peak_anchor_uncovered_match_count": len(_peak_anchor_uncovered_match_ids(candidates, selected)),
    }


def build_engine_summary(
    *,
    engine_name: str = "phased_route_solver",
    phases: Iterable[Mapping[str, Any]] | None = None,
    selected_routes: Iterable[Any] | None = None,
    all_fragments: Iterable[Any] | None = None,
    unassigned_fragments: Iterable[Any] | None = None,
    rescue_summary: Mapping[str, Any] | None = None,
    swap_recommendations: Iterable[Any] | None = None,
) -> dict[str, Any]:
    selected = [_object_to_dict(route) for route in (selected_routes or [])]
    fragments = [_object_to_dict(fragment) for fragment in (all_fragments or [])]
    unassigned = [_object_to_dict(fragment) for fragment in (unassigned_fragments or [])]
    selected_ids = set(_route_match_ids(selected))
    all_ids = {match_id for fragment in fragments for match_id in _match_ids(fragment)}
    recommendation_payloads = [_json_safe(_object_to_dict(item)) for item in (swap_recommendations or [])]
    return {
        "engine_name": engine_name,
        "phase_summaries": [dict(phase) for phase in (phases or [])],
        "selected_route_count": len(selected),
        "selected_match_count": len(selected_ids),
        "total_match_count": len(all_ids),
        "unassigned_match_count": len(all_ids - selected_ids) if all_ids else len(_route_match_ids(unassigned)),
        "coverage_ratio": (len(selected_ids) / len(all_ids)) if all_ids else None,
        "coverage_by_level": coverage_by_level(fragments, selected_match_ids=selected_ids),
        "coverage_by_phase": coverage_by_phase(selected),
        "selected_by_level_fit": selected_by_level_fit(selected),
        "final_rescue_summary": dict(rescue_summary or {}),
        "swap_recommendation_count": len(recommendation_payloads),
        "swap_recommendations": recommendation_payloads,
    }


def build_load_distribution_summary(
    tutors: Iterable[Any],
    selected_routes: Iterable[Any],
    *,
    overload_threshold: int = 4,
) -> dict[str, Any]:
    tutor_list = list(tutors or [])
    routes = [_object_to_dict(route) for route in (selected_routes or [])]
    level_by_tutor = {
        _tutor_id(tutor): str(_get(tutor, "level", "nivell", default="unknown") or "unknown")
        for tutor in tutor_list
    }
    assigned_matches_by_tutor: dict[str, int] = defaultdict(int)
    for route in routes:
        assigned_matches_by_tutor[str(route.get("tutor_id") or "")] += len(_match_ids(route))

    assigned_matches_by_tutor_level: dict[str, int] = defaultdict(int)
    unused_tutors_by_level: dict[str, int] = defaultdict(int)
    for tutor_id, level in level_by_tutor.items():
        count = assigned_matches_by_tutor.get(tutor_id, 0)
        assigned_matches_by_tutor_level[level] += count
        if count == 0:
            unused_tutors_by_level[level] += 1

    return {
        "assigned_matches_by_tutor_level": dict(sorted(assigned_matches_by_tutor_level.items())),
        "assigned_matches_by_tutor": dict(sorted(assigned_matches_by_tutor.items())),
        "unused_tutors_by_level": dict(sorted(unused_tutors_by_level.items())),
        "overloaded_tutors": [
            {"tutor_id": tutor_id, "assigned_match_count": count}
            for tutor_id, count in sorted(assigned_matches_by_tutor.items())
            if count > overload_threshold
        ],
        "underused_viable_tutors": [
            {"tutor_id": tutor_id, "level": level}
            for tutor_id, level in sorted(level_by_tutor.items())
            if assigned_matches_by_tutor.get(tutor_id, 0) == 0
        ],
    }


def coverage_by_level(
    fragments: Iterable[Any],
    *,
    selected_match_ids: Iterable[Any] | None = None,
) -> dict[str, dict[str, Any]]:
    selected = set(_normalize_ids(selected_match_ids))
    totals: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "selected": 0})
    for fragment in fragments or []:
        data = _object_to_dict(fragment)
        level = str(data.get("level_demand") or data.get("level") or "unknown")
        for match_id in _match_ids(data):
            totals[level]["total"] += 1
            if match_id in selected:
                totals[level]["selected"] += 1
    return {
        level: {
            "total": counts["total"],
            "selected": counts["selected"],
            "unassigned": counts["total"] - counts["selected"],
            "coverage_ratio": (counts["selected"] / counts["total"]) if counts["total"] else None,
        }
        for level, counts in sorted(totals.items())
    }


def coverage_by_phase(selected_routes: Iterable[Any]) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = defaultdict(lambda: {"route_count": 0, "match_count": 0})
    for route in selected_routes or []:
        data = _object_to_dict(route)
        phase_name = str(data.get("phase_name") or data.get("stage") or "unknown")
        totals[phase_name]["route_count"] += 1
        totals[phase_name]["match_count"] += len(_match_ids(data))
    return {phase: dict(counts) for phase, counts in sorted(totals.items())}


def selected_by_level_fit(selected_routes: Iterable[Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for route in selected_routes or []:
        data = _object_to_dict(route)
        fit = str(data.get("level_fit") or data.get("level_fit_label") or "unknown")
        counts[fit] += len(_match_ids(data)) or 1
    return dict(sorted(counts.items()))


def _route_match_ids(routes: Iterable[Mapping[str, Any]]) -> list[str]:
    return [match_id for route in routes for match_id in _match_ids(route)]


def _match_ids(value: Mapping[str, Any]) -> list[str]:
    return _normalize_ids(value.get("new_match_ids") or value.get("match_ids") or value.get("assigned_match_ids"))


def _load_penalty(route: Mapping[str, Any]) -> float:
    breakdown = route.get("score_breakdown") or {}
    if not isinstance(breakdown, Mapping):
        return 0.0
    for key in ("load_penalty", "accumulated_load_penalty", "load_cost"):
        try:
            return float(breakdown.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _score_breakdown(route: Mapping[str, Any]) -> Mapping[str, Any]:
    breakdown = route.get("score_breakdown") or {}
    return breakdown if isinstance(breakdown, Mapping) else {}


def _peak_buckets(routes: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for route in routes or []:
        breakdown = _score_breakdown(route)
        bucket = str(breakdown.get("peak_bucket") or "")
        if not bucket:
            continue
        row = rows.setdefault(
            bucket,
            {
                "bucket": bucket,
                "selected_route_count": 0,
                "selected_match_count": 0,
                "peak_pressure_score": float(breakdown.get("peak_pressure_score") or 0.0),
            },
        )
        row["selected_route_count"] += 1
        row["selected_match_count"] += len(_match_ids(route))
        row["peak_pressure_score"] = max(row["peak_pressure_score"], float(breakdown.get("peak_pressure_score") or 0.0))
    return sorted(rows.values(), key=lambda item: (-item["peak_pressure_score"], item["bucket"]))


def _peak_anchor_selected_match_ids(selected: Iterable[Mapping[str, Any]]) -> set[str]:
    selected_ids = set(_route_match_ids(selected or []))
    anchor_ids = {
        match_id
        for route in selected or []
        for match_id in _normalize_ids(_score_breakdown(route).get("peak_anchor_match_ids"))
    }
    return selected_ids & anchor_ids


def _peak_anchor_uncovered_match_ids(candidates: Iterable[Mapping[str, Any]], selected: Iterable[Mapping[str, Any]]) -> set[str]:
    selected_ids = set(_route_match_ids(selected or []))
    anchor_ids = {
        match_id
        for candidate in candidates or []
        for match_id in _normalize_ids(_score_breakdown(candidate).get("peak_anchor_match_ids"))
    }
    return anchor_ids - selected_ids


def _tutor_id(tutor: Any) -> str:
    return str(_get(tutor, "id", "tutor_id", "persona_id", "code", "codi", default="")).strip()


def _get(source: Any, *keys: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, Mapping):
        for key in keys:
            if key in source:
                return source[key]
        return default
    for key in keys:
        if hasattr(source, key):
            return getattr(source, key)
    return default


def _normalize_ids(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [part.strip() for part in values.replace(";", ",").replace("|", ",").split(",") if part.strip()]
    try:
        return [str(value).strip() for value in values if str(value).strip()]
    except TypeError:
        value = str(values).strip()
        return [value] if value else []


def _object_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return dict(value.to_dict())
    if not hasattr(value, "__dict__"):
        return {"value": value}
    return {
        key: item
        for key, item in vars(value).items()
        if not key.startswith("_")
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return value.isoformat()
    return value
