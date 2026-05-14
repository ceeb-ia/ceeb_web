"""Component context split and validation helpers for the resource solver."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from calendaritzacions.engine.variants.resource_solver.decomposition import (
    build_decomposition_summary,
)
from calendaritzacions.engine.variants.resource_solver.resources import (
    base_resource_id_for_team,
)
from calendaritzacions.engine.variants.resource_solver.types import SolverContext


def filter_context_by_team_ids(
    context: SolverContext,
    team_ids: Iterable[str],
) -> SolverContext:
    """Return a SolverContext restricted to the selected teams and their data."""

    selected_team_ids = {str(team_id) for team_id in team_ids}
    teams = tuple(team for team in context.teams if team.team_id in selected_team_ids)
    team_ids_in_context = {team.team_id for team in teams}
    candidates = tuple(
        candidate
        for candidate in context.candidates
        if str(candidate.team_id) in team_ids_in_context
    )
    group_ids = {str(candidate.group_id) for candidate in candidates}
    groups = tuple(group for group in context.groups if str(group.group_id) in group_ids)

    resource_ids = {base_resource_id_for_team(team) for team in teams}
    resource_ids.update(
        str(resource_id)
        for candidate in candidates
        for resource_id in candidate.potential_resources
        if str(resource_id) in context.base_resources
    )
    base_resources = {
        resource_id: resource
        for resource_id, resource in context.base_resources.items()
        if str(resource_id) in resource_ids
    }
    capacities = {
        resource_id: capacity
        for resource_id, capacity in context.capacities.items()
        if str(resource_id) in resource_ids
    }
    pressure = tuple(
        replace(row, team_ids=tuple(team_id for team_id in row.team_ids if team_id in team_ids_in_context))
        for row in context.pressure
        if str(row.base_resource_id) in resource_ids
    )

    return replace(
        context,
        teams=teams,
        base_resources=base_resources,
        capacities=capacities,
        pressure=pressure,
        groups=groups,
        candidates=candidates,
    )


def split_context_by_components(
    context: SolverContext,
    components: Iterable[Any],
) -> dict[str, SolverContext]:
    """Build one filtered SolverContext per dependency component."""

    subcontexts: dict[str, SolverContext] = {}
    for index, component in enumerate(components, start=1):
        component_id = _component_id(component, index)
        subcontexts[component_id] = filter_context_by_team_ids(
            context,
            _component_team_ids(component),
        )
    return subcontexts


def validate_component_split(
    context: SolverContext,
    components_or_subcontexts: Iterable[Any] | dict[str, Any],
) -> dict[str, Any]:
    """Validate that components form a safe independent split of the context."""

    errors: list[dict[str, Any]] = []
    declared_unknown_teams = _declared_unknown_teams(context, components_or_subcontexts)
    subcontexts = _coerce_subcontexts(context, components_or_subcontexts)
    global_summary = build_decomposition_summary(context)

    global_team_ids = {team.team_id for team in context.teams}
    component_team_ids: dict[str, tuple[str, ...]] = {}
    team_owners: dict[str, list[str]] = defaultdict(list)
    unknown_teams: dict[str, list[str]] = {}

    for component_id, subcontext in subcontexts.items():
        ids = tuple(team.team_id for team in subcontext.teams)
        component_team_ids[component_id] = ids
        for team_id in ids:
            team_owners[team_id].append(component_id)
        unknown = sorted(team_id for team_id in ids if team_id not in global_team_ids)
        if unknown:
            unknown_teams[component_id] = unknown

    duplicate_teams = {
        team_id: owners
        for team_id, owners in sorted(team_owners.items())
        if len(owners) > 1
    }
    missing_teams = sorted(global_team_ids.difference(team_owners))

    _add_error(errors, "duplicate_teams", duplicate_teams)
    _add_error(errors, "missing_teams", missing_teams)
    _add_error(errors, "unknown_declared_teams", declared_unknown_teams)
    _add_error(errors, "unknown_teams", unknown_teams)

    orphan_candidates = sorted(
        candidate.candidate_id
        for candidate in context.candidates
        if str(candidate.team_id) not in team_owners
    )
    _add_error(errors, "orphan_candidates", orphan_candidates)

    candidate_team_mismatches: dict[str, list[dict[str, str]]] = {}
    team_to_component = {
        team_id: owners[0]
        for team_id, owners in team_owners.items()
        if len(owners) == 1
    }
    for component_id, subcontext in subcontexts.items():
        local_team_ids = set(component_team_ids[component_id])
        rows = [
            {
                "candidate_id": str(candidate.candidate_id),
                "team_id": str(candidate.team_id),
                "expected_component_id": str(team_to_component.get(str(candidate.team_id), "")),
            }
            for candidate in subcontext.candidates
            if str(candidate.team_id) not in local_team_ids
        ]
        if rows:
            candidate_team_mismatches[component_id] = rows
    _add_error(errors, "candidate_team_mismatches", candidate_team_mismatches)

    shared_groups = _shared_values(
        {
            component_id: (str(group.group_id) for group in subcontext.groups)
            for component_id, subcontext in subcontexts.items()
        }
    )
    shared_resources = _shared_values(
        {
            component_id: (str(resource_id) for resource_id in subcontext.base_resources)
            for component_id, subcontext in subcontexts.items()
        }
    )
    global_linkage_keys_by_team = _global_linkage_keys_by_team(global_summary)
    linkage_keys_by_component: dict[str, tuple[str, ...]] = {}
    for component_id, subcontext in subcontexts.items():
        keys = {
            linkage_key
            for team in subcontext.teams
            for linkage_key in global_linkage_keys_by_team.get(team.team_id, ())
        }
        keys.update(_all_linkage_keys(subcontext))
        linkage_keys_by_component[component_id] = tuple(sorted(keys))
    shared_linkages = _shared_values(linkage_keys_by_component)

    _add_error(errors, "shared_groups", shared_groups)
    _add_error(errors, "shared_resources", shared_resources)
    _add_error(errors, "shared_linkages", shared_linkages)

    totals = _counts_payload(context, subcontexts, global_summary, linkage_keys_by_component)
    for key in ("teams", "candidates", "groups", "resources", "linkages"):
        if totals["global"][key] != totals["subcontexts"][key]:
            _add_error(
                errors,
                "total_mismatch",
                {
                    "field": key,
                    "global": totals["global"][key],
                    "subcontexts": totals["subcontexts"][key],
                },
            )

    serialization_errors: dict[str, str] = {}
    for component_id, subcontext in subcontexts.items():
        try:
            json.loads(json.dumps(_json_ready(subcontext), sort_keys=True))
        except (TypeError, ValueError) as exc:
            serialization_errors[component_id] = str(exc)
    _add_error(errors, "serialization_failed", serialization_errors)

    payload = {
        "artifact_type": "resource_solver_component_split_validation",
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "counts": totals,
        "components": [
            {
                "component_id": component_id,
                "team_count": len(subcontext.teams),
                "candidate_count": len(subcontext.candidates),
                "group_count": len(subcontext.groups),
                "resource_count": len(subcontext.base_resources),
                "linkage_count": len(linkage_keys_by_component.get(component_id, ())),
                "team_ids": [team.team_id for team in subcontext.teams],
            }
            for component_id, subcontext in sorted(subcontexts.items())
        ],
    }
    json.dumps(_json_ready(payload), sort_keys=True)
    return payload


def _coerce_subcontexts(
    context: SolverContext,
    components_or_subcontexts: Iterable[Any] | dict[str, Any],
) -> dict[str, SolverContext]:
    if isinstance(components_or_subcontexts, dict):
        items = list(components_or_subcontexts.items())
    else:
        items = list(enumerate(components_or_subcontexts, start=1))

    if all(isinstance(item[1], SolverContext) for item in items):
        return {
            str(key) if not isinstance(key, int) else f"C{key:03d}": value
            for key, value in items
        }

    components = [item[1] for item in items]
    if isinstance(components_or_subcontexts, dict):
        wrapped = [
            {"component_id": str(key), "team_ids": _component_team_ids(value)}
            for key, value in items
        ]
        return split_context_by_components(context, wrapped)
    return split_context_by_components(context, components)


def _declared_unknown_teams(
    context: SolverContext,
    components_or_subcontexts: Iterable[Any] | dict[str, Any],
) -> dict[str, list[str]]:
    global_team_ids = {team.team_id for team in context.teams}
    if isinstance(components_or_subcontexts, dict):
        items = list(components_or_subcontexts.items())
    else:
        items = list(enumerate(components_or_subcontexts, start=1))
    unknown: dict[str, list[str]] = {}
    for index, (key, value) in enumerate(items, start=1):
        if isinstance(value, SolverContext):
            continue
        component_id = str(key) if not isinstance(key, int) else _component_id(value, index)
        missing = sorted(set(_component_team_ids(value)).difference(global_team_ids))
        if missing:
            unknown[component_id] = missing
    return unknown


def _component_id(component: Any, index: int) -> str:
    if isinstance(component, dict):
        value = component.get("component_id")
    else:
        value = getattr(component, "component_id", None)
    return str(value or f"C{index:03d}")


def _component_team_ids(component: Any) -> tuple[str, ...]:
    if isinstance(component, SolverContext):
        return tuple(team.team_id for team in component.teams)
    if isinstance(component, dict):
        values = component.get("team_ids", ())
    else:
        values = getattr(component, "team_ids", ())
    return tuple(str(value) for value in values)


def _shared_values(values_by_component: dict[str, Iterable[str]]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = defaultdict(list)
    for component_id, values in values_by_component.items():
        for value in sorted(set(str(item) for item in values)):
            owners[value].append(component_id)
    return {
        value: sorted(component_ids)
        for value, component_ids in sorted(owners.items())
        if len(component_ids) > 1
    }


def _all_linkage_keys(context: SolverContext) -> tuple[str, ...]:
    keys: set[str] = set()
    for component in build_decomposition_summary(context).components:
        keys.update(str(key) for key in component.linkage_keys)
    return tuple(sorted(keys))


def _global_linkage_keys_by_team(global_summary: Any) -> dict[str, tuple[str, ...]]:
    keys_by_team: dict[str, set[str]] = defaultdict(set)
    for edge in getattr(global_summary, "edges", ()):
        if getattr(edge, "kind", "") != "linkage":
            continue
        linkage_key = str(getattr(edge, "target_key", ""))
        for team_id in getattr(edge, "team_ids", ()):
            keys_by_team[str(team_id)].add(linkage_key)
    return {
        team_id: tuple(sorted(keys))
        for team_id, keys in sorted(keys_by_team.items())
    }


def _counts_payload(
    context: SolverContext,
    subcontexts: dict[str, SolverContext],
    global_summary: Any,
    linkage_keys_by_component: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    return {
        "global": {
            "teams": len(context.teams),
            "candidates": len(context.candidates),
            "groups": len(context.groups),
            "resources": len(context.base_resources),
            "linkages": int(global_summary.linkage_count),
            "components": len(subcontexts),
        },
        "subcontexts": {
            "teams": sum(len(subcontext.teams) for subcontext in subcontexts.values()),
            "candidates": sum(len(subcontext.candidates) for subcontext in subcontexts.values()),
            "groups": sum(len(subcontext.groups) for subcontext in subcontexts.values()),
            "resources": sum(len(subcontext.base_resources) for subcontext in subcontexts.values()),
            "linkages": sum(len(keys) for keys in linkage_keys_by_component.values()),
            "components": len(subcontexts),
        },
    }


def _add_error(errors: list[dict[str, Any]], code: str, details: Any) -> None:
    if details:
        errors.append({"code": code, "details": _json_ready(details)})


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return str(value)


__all__ = [
    "filter_context_by_team_ids",
    "split_context_by_components",
    "validate_component_split",
]
