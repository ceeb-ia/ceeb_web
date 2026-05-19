"""Pure dependency decomposition helpers for the resource solver."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from calendaritzacions.engine.variants.resource_solver.resources import (
    base_resource_id_for_team,
)
from calendaritzacions.engine.variants.resource_solver.types import SolverContext

try:
    from calendaritzacions.engine.variants.resource_solver.input_adapter import (
        competition_key_for_team as _competition_key_for_team,
    )
except ImportError:  # pragma: no cover - older checkouts expose only the private helper.
    _competition_key_for_team = None

try:
    from calendaritzacions.engine.variants.resource_solver import linkage as _linkage_helpers
except Exception:  # pragma: no cover - decomposition must stay usable without helpers.
    _linkage_helpers = None


INDIFFERENT_SIDES = {"", "indiferent", "indifferent", "none", "neutral", "neutre"}


@dataclass(frozen=True)
class DependencyNode:
    kind: str
    key: str
    label: str
    team_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DependencyEdge:
    kind: str
    source_kind: str
    source_key: str
    target_kind: str
    target_key: str
    team_ids: tuple[str, ...]


@dataclass(frozen=True)
class DependencyComponent:
    component_id: str
    team_ids: tuple[str, ...]
    competition_keys: tuple[str, ...]
    resource_keys: tuple[str, ...]
    linkage_keys: tuple[str, ...]
    node_count: int
    edge_count: int
    group_ids: tuple[str, ...] = ()
    candidate_count: int = 0
    estimated_x_variables: int = 0
    max_resource_pressure: float = 0.0
    edge_counts: dict[str, int] | None = None


@dataclass(frozen=True)
class DecompositionSummary:
    components: tuple[DependencyComponent, ...]
    nodes: tuple[DependencyNode, ...]
    edges: tuple[DependencyEdge, ...]
    team_count: int
    competition_count: int
    resource_count: int
    linkage_count: int
    group_count: int
    candidate_count: int
    estimated_x_variables: int
    max_resource_pressure: float
    edge_counts: dict[str, int]


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self._parent.setdefault(item, item)

    def find(self, item: str) -> str:
        self.add(item)
        parent = self._parent[item]
        if parent != item:
            self._parent[item] = self.find(parent)
        return self._parent[item]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if right_root < left_root:
            left_root, right_root = right_root, left_root
        self._parent[right_root] = left_root


def build_dependency_components(context: SolverContext) -> tuple[DependencyComponent, ...]:
    """Build connected components across team, competition, resource and linkage nodes."""

    return build_decomposition_summary(context).components


def build_decomposition_summary(context: SolverContext) -> DecompositionSummary:
    nodes, edges, uf = _build_graph(context)
    node_by_id = {_node_id(node.kind, node.key): node for node in nodes}
    edge_counts: dict[str, int] = defaultdict(int)
    for edge in edges:
        edge_counts[edge.kind] += 1

    node_ids_by_root: dict[str, list[str]] = defaultdict(list)
    edges_by_root: dict[str, list[DependencyEdge]] = defaultdict(list)
    for node_id in node_by_id:
        node_ids_by_root[uf.find(node_id)].append(node_id)
    for edge in edges:
        edges_by_root[uf.find(_node_id(edge.source_kind, edge.source_key))].append(edge)

    candidates_by_team: dict[str, list[Any]] = defaultdict(list)
    for candidate in context.candidates:
        candidates_by_team[str(candidate.team_id)].append(candidate)
    pressure_by_resource = {row.base_resource_id: row for row in context.pressure}

    components: list[DependencyComponent] = []
    for index, (_root, component_node_ids) in enumerate(
        sorted(node_ids_by_root.items(), key=lambda item: _component_sort_key(item[1], node_by_id)),
        start=1,
    ):
        component_nodes = [node_by_id[node_id] for node_id in sorted(component_node_ids)]
        team_ids = sorted(
            node.key for node in component_nodes if node.kind == "team"
        )
        competition_keys = sorted(
            node.key for node in component_nodes if node.kind == "competition"
        )
        resource_keys = sorted(
            node.key for node in component_nodes if node.kind == "resource"
        )
        linkage_keys = sorted(
            node.key for node in component_nodes if node.kind == "linkage"
        )
        component_edges = edges_by_root.get(uf.find(component_node_ids[0]), [])
        component_edge_counts: dict[str, int] = defaultdict(int)
        for edge in component_edges:
            component_edge_counts[edge.kind] += 1
        component_candidates = [
            candidate
            for team_id in team_ids
            for candidate in candidates_by_team.get(team_id, [])
        ]
        group_ids = sorted({str(candidate.group_id) for candidate in component_candidates})
        component_pressure = [
            float(getattr(pressure_by_resource[resource_key], "pressure", 0.0) or 0.0)
            for resource_key in resource_keys
            if resource_key in pressure_by_resource
        ]
        components.append(
            DependencyComponent(
                component_id=f"C{index:03d}",
                team_ids=tuple(team_ids),
                competition_keys=tuple(competition_keys),
                resource_keys=tuple(resource_keys),
                linkage_keys=tuple(linkage_keys),
                node_count=len(component_nodes),
                edge_count=len(component_edges),
                group_ids=tuple(group_ids),
                candidate_count=len(component_candidates),
                estimated_x_variables=len(component_candidates),
                max_resource_pressure=max(component_pressure, default=0.0),
                edge_counts=dict(sorted(component_edge_counts.items())),
            )
        )

    return DecompositionSummary(
        components=tuple(components),
        nodes=tuple(sorted(nodes, key=lambda node: (node.kind, node.key))),
        edges=tuple(sorted(edges, key=lambda edge: (edge.kind, edge.source_key, edge.target_key))),
        team_count=len(context.teams),
        competition_count=sum(1 for node in nodes if node.kind == "competition"),
        resource_count=sum(1 for node in nodes if node.kind == "resource"),
        linkage_count=sum(1 for node in nodes if node.kind == "linkage"),
        group_count=len(context.groups),
        candidate_count=len(context.candidates),
        estimated_x_variables=len(context.candidates),
        max_resource_pressure=_max_resource_pressure(context),
        edge_counts=dict(sorted(edge_counts.items())),
    )


def dependency_summary_payload(summary: DecompositionSummary) -> dict[str, Any]:
    components_by_size = [_component_payload(component) for component in summary.components]
    components_by_size.sort(
        key=lambda item: (int(item["team_count"]), int(item["candidate_count"]), str(item["component_id"])),
        reverse=True,
    )
    largest = components_by_size[0] if components_by_size else {}
    return {
        "artifact_type": "resource_solver_dependency_decomposition",
        "audit_guide": _audit_guide(),
        "total_teams": summary.team_count,
        "total_competitions": summary.competition_count,
        "total_resources": summary.resource_count,
        "total_linkages": summary.linkage_count,
        "total_edges": sum(summary.edge_counts.values()),
        "team_count": summary.team_count,
        "competition_count": summary.competition_count,
        "resource_count": summary.resource_count,
        "linkage_count": summary.linkage_count,
        "group_count": summary.group_count,
        "candidate_count": summary.candidate_count,
        "estimated_x_variables": summary.estimated_x_variables,
        "max_resource_pressure": summary.max_resource_pressure,
        "component_count": len(summary.components),
        "largest_component": {
            "component_id": largest.get("component_id", ""),
            "teams": largest.get("team_count", 0),
            "competitions": largest.get("competition_count", 0),
            "resources": largest.get("resource_count", 0),
            "linkages": largest.get("linkage_count", 0),
            "candidates": largest.get("candidate_count", 0),
        },
        "components_by_size": components_by_size,
        "edge_counts": dict(summary.edge_counts),
        "safe_to_split": True,
    }


def dependency_components_payload(summary: DecompositionSummary) -> list[dict[str, Any]]:
    return [_component_payload(component) for component in summary.components]


def dependency_edges_payload(
    summary: DecompositionSummary,
    max_edges_per_component: int | None = None,
) -> list[dict[str, Any]]:
    component_by_node: dict[tuple[str, str], str] = {}
    for component in summary.components:
        for team_id in component.team_ids:
            component_by_node[("team", team_id)] = component.component_id
        for key in component.competition_keys:
            component_by_node[("competition", key)] = component.component_id
        for key in component.resource_keys:
            component_by_node[("resource", key)] = component.component_id
        for key in component.linkage_keys:
            component_by_node[("linkage", key)] = component.component_id

    counts_by_component: dict[str, int] = defaultdict(int)
    payload: list[dict[str, Any]] = []
    for edge in summary.edges:
        component_id = component_by_node[(edge.source_kind, edge.source_key)]
        if (
            max_edges_per_component is not None
            and counts_by_component[component_id] >= max_edges_per_component
        ):
            continue
        row = _json_ready(asdict(edge))
        row["component_id"] = component_id
        payload.append(row)
        counts_by_component[component_id] += 1
    return payload


def _component_payload(component: DependencyComponent) -> dict[str, Any]:
    return _json_ready(
        {
            "component_id": component.component_id,
            "team_count": len(component.team_ids),
            "competition_count": len(component.competition_keys),
            "resource_count": len(component.resource_keys),
            "linkage_count": len(component.linkage_keys),
            "group_count": len(component.group_ids),
            "candidate_count": component.candidate_count,
            "estimated_x_variables": component.estimated_x_variables,
            "max_resource_pressure": component.max_resource_pressure,
            "edge_count": component.edge_count,
            "edge_counts": component.edge_counts or {},
            "team_ids": component.team_ids,
            "competition_keys": component.competition_keys,
            "resource_ids": component.resource_keys,
            "resource_keys": component.resource_keys,
            "linkage_keys": component.linkage_keys,
            "group_ids": component.group_ids,
            "team_ids_sample": component.team_ids[:50],
            "team_ids_count": len(component.team_ids),
            "interpretation": _component_interpretation(component),
        }
    )


def _audit_guide() -> dict[str, Any]:
    return {
        "component": (
            "Subdomini connex del graf. Si dos equips estan al mateix component, "
            "hi ha algun cami de dependencies que els pot acoblar."
        ),
        "candidate": (
            "Opcio binaria del solver: un equip assignat a un grup i numero concret. "
            "Mes candidats vol dir mes variables x a CP-SAT."
        ),
        "edge_reasons": {
            "competition": "L'equip pertany a una competicio que comparteix grups.",
            "resource": "L'equip demana la mateixa pista/dia/hora base que altres equips.",
            "linkage": "L'equip forma part d'un linkage actiu amb mateixa pista i grup de vinculacio.",
        },
        "safe_split_rule": (
            "La particio segura futura nomes pot tallar entre components connexos; "
            "aquesta fase nomes audita i no modifica el solve global."
        ),
        "plot_guide": {
            "component_team_count_histogram": "Distribucio de mides: moltes illes petites o una illa gegant.",
            "top_components_by_teams": "Components amb mes volum operatiu.",
            "components_resources_vs_competitions": "Detecta si un component creix per recursos, competicions o tots dos.",
            "candidate_pareto_by_component": "Mostra quins components concentren les variables candidates.",
            "component_network_*": "Xarxa tipada de nodes i arestes per entendre per que un subdomini queda connectat.",
        },
    }


def _component_interpretation(component: DependencyComponent) -> dict[str, Any]:
    return {
        "is_single_team": len(component.team_ids) == 1,
        "has_resource_bridge": bool(component.resource_keys and len(component.competition_keys) > 1),
        "has_linkage_bridge": bool(component.linkage_keys),
        "dominant_edge_reason": _dominant_edge_reason(component.edge_counts or {}),
        "read_as": (
            "Component independent candidat a split futur"
            if len(component.team_ids) > 1
            else "Component trivial d'un sol equip"
        ),
    }


def _dominant_edge_reason(edge_counts: dict[str, int]) -> str:
    if not edge_counts:
        return ""
    return max(edge_counts.items(), key=lambda item: (item[1], item[0]))[0]


def _build_graph(
    context: SolverContext,
) -> tuple[list[DependencyNode], list[DependencyEdge], _UnionFind]:
    uf = _UnionFind()
    nodes_by_id: dict[str, DependencyNode] = {}
    edges: list[DependencyEdge] = []

    def add_node(node: DependencyNode) -> None:
        node_id = _node_id(node.kind, node.key)
        existing = nodes_by_id.get(node_id)
        if existing is None:
            nodes_by_id[node_id] = node
        elif node.team_ids:
            nodes_by_id[node_id] = DependencyNode(
                kind=existing.kind,
                key=existing.key,
                label=existing.label,
                team_ids=tuple(sorted(set(existing.team_ids).union(node.team_ids))),
            )
        uf.add(node_id)

    def add_edge(kind: str, target_kind: str, target_key: str, team_ids: Iterable[str]) -> None:
        team_tuple = tuple(sorted(set(team_ids)))
        if not team_tuple:
            return
        for team_id in team_tuple:
            edge = DependencyEdge(
                kind=kind,
                source_kind="team",
                source_key=team_id,
                target_kind=target_kind,
                target_key=target_key,
                team_ids=(team_id,),
            )
            edges.append(edge)
            uf.union(_node_id("team", team_id), _node_id(target_kind, target_key))

    for team in context.teams:
        add_node(DependencyNode("team", team.team_id, team.name or team.team_id, (team.team_id,)))

    competition_members: dict[str, list[str]] = defaultdict(list)
    resource_members: dict[str, list[str]] = defaultdict(list)
    for team in context.teams:
        competition_key = _competition_key(team, context)
        resource_key = base_resource_id_for_team(team)
        competition_members[competition_key].append(team.team_id)
        resource_members[resource_key].append(team.team_id)

    for key, team_ids in sorted(competition_members.items()):
        add_node(DependencyNode("competition", key, key, tuple(sorted(team_ids))))
        add_edge("competition", "competition", key, team_ids)

    for key, team_ids in sorted(resource_members.items()):
        resource = context.base_resources.get(key)
        label = key
        if resource is not None:
            label = f"{resource.venue} / {resource.day} / {resource.hour_slot}"
        add_node(DependencyNode("resource", key, label, tuple(sorted(team_ids))))
        add_edge("resource", "resource", key, team_ids)

    for key, bucket in _valid_linkage_buckets(context).items():
        team_ids = tuple(team.team_id for team in bucket)
        add_node(DependencyNode("linkage", key, key, tuple(sorted(team_ids))))
        add_edge("linkage", "linkage", key, team_ids)

    return list(nodes_by_id.values()), edges, uf


def _competition_key(team: Any, context: SolverContext | None = None) -> str:
    if _competition_key_for_team is not None:
        try:
            return _string_key(_competition_key_for_team(team, getattr(context, "config", None)))
        except Exception:
            pass
    mode = str(getattr(getattr(context, "config", None), "competition_grouping", "auto") or "auto").strip().casefold()
    if mode == "league":
        league_name = str(getattr(team, "league_name", "") or "").strip() or "Sense lliga"
        return _string_key(("league", league_name))
    parts = (
        str(getattr(team, "modality", "") or "").strip(),
        str(getattr(team, "category", "") or "").strip(),
        str(getattr(team, "subcategory", "") or "").strip(),
    )
    if mode == "fields" or all(parts):
        return _string_key(("fields", *(part or "Sense valor" for part in parts)))
    league_name = str(getattr(team, "league_name", "") or "").strip() or "Sense lliga"
    return _string_key(("league", league_name))


def _valid_linkage_buckets(context: SolverContext) -> dict[str, tuple[Any, ...]]:
    buckets: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for team in context.teams:
        group = _normalize_linkage_group(getattr(team, "linkage_group", None))
        if not group or _is_indifferent_side(getattr(team, "linkage_side", None)):
            continue
        venue = _normalize_value(getattr(team, "venue", None))
        buckets[(venue, group)].append(team)
    return {
        _string_key(("venue", venue, "linkage", group)): tuple(
            sorted(teams, key=lambda team: team.team_id)
        )
        for (venue, group), teams in sorted(buckets.items())
        if len(teams) > 1
    }


def _normalize_linkage_group(value: Any) -> str:
    helper = getattr(_linkage_helpers, "normalize_linkage_group", None)
    if helper is not None:
        try:
            return str(helper(value) or "")
        except Exception:
            pass
    return _normalize_value(value)


def _is_indifferent_side(value: Any) -> bool:
    return _normalize_value(value) in INDIFFERENT_SIDES


def _normalize_value(value: Any) -> str:
    return str(value or "").strip().casefold()


def _string_key(parts: Any) -> str:
    if isinstance(parts, (list, tuple)):
        return "|".join(str(part) for part in parts)
    return str(parts)


def _node_id(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def _component_sort_key(node_ids: list[str], node_by_id: dict[str, DependencyNode]) -> tuple[str, str]:
    nodes = [node_by_id[node_id] for node_id in node_ids]
    team_ids = sorted(node.key for node in nodes if node.kind == "team")
    if team_ids:
        return ("team", team_ids[0])
    first = min(nodes, key=lambda node: (node.kind, node.key))
    return (first.kind, first.key)


def _max_resource_pressure(context: SolverContext) -> float:
    pressures = [float(getattr(row, "pressure", 0.0) or 0.0) for row in context.pressure]
    return max(pressures, default=0.0)


def _json_ready(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    return value


__all__ = [
    "DependencyComponent",
    "DependencyEdge",
    "DependencyNode",
    "DecompositionSummary",
    "build_decomposition_summary",
    "build_dependency_components",
    "dependency_components_payload",
    "dependency_edges_payload",
    "dependency_summary_payload",
]
