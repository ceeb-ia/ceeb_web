"""Build disjoint microhubs from resources and linkages only."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from calendaritzacions.engine.variants.resource_solver.input_adapter import competition_key_for_team
from calendaritzacions.engine.variants.resource_solver.resources import base_resource_id_for_team
from calendaritzacions.engine.variants.resource_solver.types import SolverContext
from calendaritzacions.engine.variants.resource_solver.pattern_master.types import MicroHub

try:
    from calendaritzacions.engine.variants.resource_solver import linkage as linkage_domain
except Exception:  # pragma: no cover
    linkage_domain = None


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: str) -> str:
        self.add(item)
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if right_root < left_root:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root


def build_microhubs(context: SolverContext) -> tuple[MicroHub, ...]:
    """Return max connected components over team-resource-linkage edges.

    Competitions are recorded on the resulting hubs, but they never connect hubs.
    """

    uf = _UnionFind()
    teams_by_resource: dict[str, list[str]] = defaultdict(list)
    teams_by_linkage: dict[str, list[str]] = defaultdict(list)
    team_by_id = {team.team_id: team for team in context.teams}

    for team in context.teams:
        uf.add(team.team_id)
        resource_key = base_resource_id_for_team(team)
        teams_by_resource[resource_key].append(team.team_id)
        linkage_key = linkage_key_for_team(team)
        if linkage_key:
            teams_by_linkage[linkage_key].append(team.team_id)

    for team_ids in [*teams_by_resource.values(), *teams_by_linkage.values()]:
        _union_all(uf, team_ids)

    roots: dict[str, list[str]] = defaultdict(list)
    for team in context.teams:
        roots[uf.find(team.team_id)].append(team.team_id)

    hubs: list[MicroHub] = []
    for index, team_ids in enumerate(sorted((tuple(sorted(ids)) for ids in roots.values()), key=lambda ids: ids), start=1):
        resource_keys = sorted(
            {
                key
                for key, ids in teams_by_resource.items()
                if set(ids).intersection(team_ids)
            }
        )
        linkage_keys = sorted(
            {
                key
                for key, ids in teams_by_linkage.items()
                if set(ids).intersection(team_ids)
            }
        )
        competition_keys = sorted(
            "|".join(str(part) for part in competition_key_for_team(team_by_id[team_id], context.config))
            for team_id in team_ids
            if team_id in team_by_id
        )
        hubs.append(
            MicroHub(
                hub_id=f"H{index:04d}",
                team_ids=team_ids,
                resource_keys=tuple(resource_keys),
                linkage_keys=tuple(linkage_keys),
                competition_keys=tuple(sorted(set(competition_keys))),
            )
        )
    return tuple(hubs)


def linkage_key_for_team(team: Any) -> str:
    group = _normalize_linkage_group(getattr(team, "linkage_group", ""))
    side = _normalize_linkage_side(getattr(team, "linkage_side", ""))
    if not group or side == "indiferent":
        return ""
    venue = _normalize_linkage_group(getattr(team, "venue", "")) or "sense-venue"
    return f"{venue}|{group}"


def microhubs_payload(hubs: Iterable[MicroHub]) -> dict[str, Any]:
    rows = [
        {
            "hub_id": hub.hub_id,
            "team_count": len(hub.team_ids),
            "resource_count": len(hub.resource_keys),
            "linkage_count": len(hub.linkage_keys),
            "competition_count": len(hub.competition_keys),
            "team_ids": list(hub.team_ids),
            "resource_keys": list(hub.resource_keys),
            "linkage_keys": list(hub.linkage_keys),
            "competition_keys": list(hub.competition_keys),
        }
        for hub in hubs
    ]
    return {
        "artifact_type": "resource_solver_pattern_master_microhubs",
        "hub_count": len(rows),
        "largest_hub_team_count": max((row["team_count"] for row in rows), default=0),
        "hubs": rows,
    }


def _union_all(uf: _UnionFind, team_ids: Iterable[str]) -> None:
    ids = tuple(str(team_id) for team_id in team_ids)
    if not ids:
        return
    first = ids[0]
    for team_id in ids:
        uf.union(first, team_id)


def _normalize_linkage_group(value: Any) -> str:
    helper = getattr(linkage_domain, "normalize_linkage_group", None)
    if callable(helper):
        return str(helper(value) or "")
    return str(value or "").strip().casefold()


def _normalize_linkage_side(value: Any) -> str:
    helper = getattr(linkage_domain, "normalize_linkage_side_from_seed", None)
    if callable(helper):
        return str(helper(value) or "indiferent")
    text = str(value or "").strip().casefold()
    return text if text in {"casa", "fora"} else "indiferent"


__all__ = ["build_microhubs", "linkage_key_for_team", "microhubs_payload"]
