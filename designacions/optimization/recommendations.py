from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Iterable, Mapping


@dataclass
class SwapRecommendation:
    id: str
    type: str
    gain: int
    moves: list[dict[str, Any]]
    freed_resource: dict[str, Any]
    warnings: list[str]
    blocking_risks: list[str]
    score_delta: dict[str, Any]
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_swap_recommendations(
    unassigned_fragments: Iterable[Any],
    tutors: Iterable[Any],
    state: Any,
    config: Mapping[str, Any] | None = None,
) -> list[SwapRecommendation]:
    """Build conservative, non-applied swap recommendations."""

    cfg = dict(config or {})
    if cfg.get("allow_swap_recommendations", True) is False:
        return []

    max_recommendations = int(cfg.get("max_swap_recommendations", 20) or 20)
    tutor_list = list(tutors or [])
    loaded_routes = _loaded_routes(state)
    underused_tutors = [
        tutor
        for tutor in tutor_list
        if _assigned_count_for_tutor(loaded_routes, _tutor_id(tutor)) == 0
    ]
    loaded_tutors = sorted(
        [
            tutor
            for tutor in tutor_list
            if _assigned_count_for_tutor(loaded_routes, _tutor_id(tutor)) > 0
        ],
        key=lambda tutor: (-_assigned_count_for_tutor(loaded_routes, _tutor_id(tutor)), _tutor_id(tutor)),
    )

    recommendations: list[SwapRecommendation] = []
    for fragment in unassigned_fragments or []:
        pending_match_ids = _fragment_match_ids(fragment)
        if not pending_match_ids:
            continue
        pending_level = _get(fragment, "level_demand", "demanda_nivell", default=None)
        for loaded_tutor in loaded_tutors:
            loaded_tutor_id = _tutor_id(loaded_tutor)
            movable_match_id = _first_assigned_match_for_tutor(loaded_routes, loaded_tutor_id)
            if not movable_match_id:
                continue
            target_tutor = _best_underused_tutor(underused_tutors, exclude_tutor_id=loaded_tutor_id)
            if target_tutor is None:
                continue
            target_tutor_id = _tutor_id(target_tutor)
            recommendation_type = _recommendation_type(fragment, loaded_tutor, target_tutor)
            warnings = ["manual_validation_required"]
            blocking_risks = [
                "availability_not_rechecked",
                "mobility_not_rechecked",
                "level_fit_not_rechecked",
            ]
            recommendations.append(
                SwapRecommendation(
                    id=f"swap:{len(recommendations) + 1}",
                    type=recommendation_type,
                    gain=len(pending_match_ids),
                    moves=[
                        {
                            "match_id": movable_match_id,
                            "from_tutor_id": loaded_tutor_id,
                            "to_tutor_id": target_tutor_id,
                        },
                        {
                            "match_id": pending_match_ids[0],
                            "from_tutor_id": None,
                            "to_tutor_id": loaded_tutor_id,
                        },
                    ],
                    freed_resource={
                        "tutor_id": loaded_tutor_id,
                        "resource": _freed_resource(recommendation_type, loaded_tutor),
                    },
                    warnings=warnings,
                    blocking_risks=blocking_risks,
                    score_delta={
                        "covered_matches": len(pending_match_ids),
                        "level_exceptional_delta": 0,
                        "warning_delta": len(warnings),
                    },
                    explanation=_explanation(recommendation_type, pending_level),
                )
            )
            break
        if len(recommendations) >= max_recommendations:
            break
    return recommendations


def _recommendation_type(fragment: Any, loaded_tutor: Any, target_tutor: Any) -> str:
    clusters = _normalize_ids(_get(fragment, "cluster_ids", "clusters", default=[]))
    if len(set(clusters)) > 1 and _has_vehicle(loaded_tutor) and not _has_vehicle(target_tutor):
        return "vehicle_release"
    loaded_level = str(_get(loaded_tutor, "level", "nivell", default="")).upper()
    target_level = str(_get(target_tutor, "level", "nivell", default="")).upper()
    if loaded_level in {"A", "B"} and target_level in {"C", "D"}:
        return "level_release"
    return "one_swap_to_recover_pending"


def _explanation(recommendation_type: str, pending_level: Any) -> str:
    level_text = f" de nivell {pending_level}" if pending_level else ""
    if recommendation_type == "vehicle_release":
        return f"Allibera un tutor amb vehicle per revisar la cobertura d'un pendent{level_text}."
    if recommendation_type == "level_release":
        return f"Allibera un tutor de nivell alt per revisar la cobertura d'un pendent{level_text}."
    return f"Proposa moure una assignacio existent per revisar la cobertura d'un pendent{level_text}."


def _freed_resource(recommendation_type: str, tutor: Any) -> str:
    if recommendation_type == "vehicle_release":
        return "vehicle"
    if recommendation_type == "level_release":
        return str(_get(tutor, "level", "nivell", default="high_level_tutor"))
    return "tutor_capacity"


def _loaded_routes(state: Any) -> list[dict[str, Any]]:
    assignments_by_tutor_day = _get(state, "assignments_by_tutor_day", default={}) or {}
    routes: list[dict[str, Any]] = []
    items = assignments_by_tutor_day.items() if isinstance(assignments_by_tutor_day, Mapping) else []
    for key, route in items:
        route_dict = _object_to_dict(route)
        if isinstance(key, tuple) and key:
            route_dict.setdefault("tutor_id", key[0])
        routes.append(route_dict)
    return routes


def _assigned_count_for_tutor(routes: list[dict[str, Any]], tutor_id: str) -> int:
    return sum(
        len(_normalize_ids(route.get("assigned_match_ids") or route.get("match_ids")))
        for route in routes
        if str(route.get("tutor_id") or "") == str(tutor_id)
    )


def _first_assigned_match_for_tutor(routes: list[dict[str, Any]], tutor_id: str) -> str | None:
    for route in routes:
        if str(route.get("tutor_id") or "") != str(tutor_id):
            continue
        match_ids = _normalize_ids(route.get("assigned_match_ids") or route.get("match_ids"))
        if match_ids:
            return match_ids[0]
    return None


def _best_underused_tutor(tutors: list[Any], *, exclude_tutor_id: str) -> Any | None:
    for tutor in sorted(tutors, key=_tutor_id):
        if _tutor_id(tutor) != str(exclude_tutor_id):
            return tutor
    return None


def _fragment_match_ids(fragment: Any) -> list[str]:
    return _normalize_ids(_get(fragment, "match_ids", "new_match_ids", "partit_ids", default=[]))


def _tutor_id(tutor: Any) -> str:
    return str(_get(tutor, "id", "tutor_id", "persona_id", "code", "codi", default="")).strip()


def _has_vehicle(tutor: Any) -> bool:
    value = _get(tutor, "has_vehicle", "te_vehicle", "vehicle", "cotxe", default=False)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "si", "cotxe", "coche", "vehicle"}
    return bool(value)


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
