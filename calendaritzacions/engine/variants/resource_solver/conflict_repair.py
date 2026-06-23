"""Conflict-repair decomposition helpers for the resource solver.

This module implements the split proposed for the experimental
``resource_solver_conflict_repair`` variant:

* initial components are built from competitions and linkages only;
* resources are used later to detect conflict hubs;
* repair blocks reconnect only the initial components that collide on hubs,
  expanded by linkage groups.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, is_dataclass, replace
from itertools import combinations
from typing import Any, Iterable

from calendaritzacions.domain.phases import phase_calendar, slot_count_for_numbers
from calendaritzacions.engine.variants.resource_solver.constraints.resource_capacity import (
    capacity_for_resource,
)
from calendaritzacions.engine.variants.resource_solver.input_adapter import (
    competition_key_for_team,
)
from calendaritzacions.engine.variants.resource_solver.groups import normalize_hard_level
from calendaritzacions.engine.variants.resource_solver.types import (
    Assignment,
    CapacityEstimate,
    ResourceSolverResult,
    SolverContext,
)

try:
    from calendaritzacions.engine.variants.resource_solver import linkage as _linkage_helpers
except Exception:  # pragma: no cover - linkage helpers are part of current package.
    _linkage_helpers = None


@dataclass(frozen=True)
class InitialComponent:
    component_id: str
    competition_keys: tuple[str, ...]
    team_ids: tuple[str, ...]
    linkage_keys: tuple[str, ...]
    candidate_count: int


@dataclass(frozen=True)
class ConflictHub:
    resource_id: str
    base_resource_id: str
    round_index: int
    locals_count: int
    capacity: int
    excess: int
    team_ids: tuple[str, ...]
    competition_keys: tuple[str, ...]
    component_ids: tuple[str, ...]


@dataclass(frozen=True)
class RepairBlock:
    block_id: str
    initial_component_ids: tuple[str, ...]
    team_ids: tuple[str, ...]
    conflict_resource_ids: tuple[str, ...]
    linkage_keys: tuple[str, ...]
    expanded_by_linkage: bool = False
    skipped_reason: str = ""


@dataclass(frozen=True)
class LinkageConflict:
    linkage_key: str
    relation: str
    team_ids: tuple[str, ...]
    component_ids: tuple[str, ...]
    mismatch_count: int
    checked_rounds: int
    pair_count: int


class _UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        self.parent = {item: item for item in items}

    def add(self, item: str) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: str) -> str:
        self.add(item)
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left == root_right:
            return
        if root_right < root_left:
            root_left, root_right = root_right, root_left
        self.parent[root_right] = root_left


def build_initial_components(context: SolverContext) -> tuple[InitialComponent, ...]:
    """Split teams by hard domain, leaving small cross-domain linkages repairable."""

    domain_by_team = team_initial_domain_keys(context)
    domains = sorted(set(domain_by_team.values()))
    uf = _UnionFind(domains)
    linkage_keys_by_domain: dict[str, set[str]] = defaultdict(set)
    small_linkage_max_size = _small_linkage_max_size(context)

    for linkage_key, team_ids in linkage_buckets(context).items():
        linked_domains = sorted(
            {
                domain_by_team[team_id]
                for team_id in team_ids
                if team_id in domain_by_team
            }
        )
        if not linked_domains:
            continue
        if len(team_ids) > small_linkage_max_size:
            first = linked_domains[0]
            for domain_key in linked_domains:
                uf.union(first, domain_key)
        for domain_key in linked_domains:
            linkage_keys_by_domain[domain_key].add(linkage_key)

    domains_by_root: dict[str, list[str]] = defaultdict(list)
    for domain_key in domains:
        domains_by_root[uf.find(domain_key)].append(domain_key)

    teams_by_domain: dict[str, list[str]] = defaultdict(list)
    for team_id, domain_key in domain_by_team.items():
        teams_by_domain[domain_key].append(team_id)

    candidate_count_by_team = Counter(candidate.team_id for candidate in context.candidates)
    components: list[InitialComponent] = []
    for index, domain_keys in enumerate(
        sorted((tuple(sorted(keys)) for keys in domains_by_root.values()), key=lambda keys: keys),
        start=1,
    ):
        team_ids = tuple(
            sorted(
                team_id
                for domain_key in domain_keys
                for team_id in teams_by_domain.get(domain_key, ())
            )
        )
        linkage_keys = tuple(
            sorted(
                linkage_key
                for domain_key in domain_keys
                for linkage_key in linkage_keys_by_domain.get(domain_key, set())
            )
        )
        components.append(
            InitialComponent(
                component_id=f"I{index:03d}",
                competition_keys=domain_keys,
                team_ids=team_ids,
                linkage_keys=linkage_keys,
                candidate_count=sum(candidate_count_by_team[team_id] for team_id in team_ids),
            )
        )
    return tuple(components)


def detect_conflict_hubs(
    context: SolverContext,
    result: ResourceSolverResult,
    team_to_component: dict[str, str] | None = None,
) -> tuple[ConflictHub, ...]:
    """Return resource slots where the merged assignment exceeds capacity."""

    competition_by_team = team_competition_keys(context)
    hubs: list[ConflictHub] = []
    for usage in result.resource_usage:
        excess = int(getattr(usage, "excess", 0) or 0)
        if excess <= 0:
            continue
        base_resource_id, round_index = split_timed_resource_id(usage.resource_id)
        team_ids = tuple(sorted(str(team_id) for team_id in usage.team_ids))
        hubs.append(
            ConflictHub(
                resource_id=str(usage.resource_id),
                base_resource_id=base_resource_id,
                round_index=round_index,
                locals_count=int(usage.locals_count),
                capacity=int(usage.capacity),
                excess=excess,
                team_ids=team_ids,
                competition_keys=tuple(
                    sorted({competition_by_team[team_id] for team_id in team_ids if team_id in competition_by_team})
                ),
                component_ids=tuple(
                    sorted({team_to_component[team_id] for team_id in team_ids if team_to_component and team_id in team_to_component})
                ),
            )
        )
    return tuple(sorted(hubs, key=lambda hub: (hub.resource_id, hub.team_ids)))


def detect_linkage_conflicts(
    context: SolverContext,
    result: ResourceSolverResult,
    initial_components: Iterable[InitialComponent],
) -> tuple[LinkageConflict, ...]:
    """Return cut linkages whose home/away pattern is not coordinated."""

    component_by_team = team_to_initial_component(initial_components)
    assignment_by_team = {assignment.team_id: assignment for assignment in result.assignments}
    conflicts: list[LinkageConflict] = []
    for linkage_key, team_ids in linkage_buckets(context).items():
        component_ids = tuple(sorted({component_by_team.get(team_id, "") for team_id in team_ids if component_by_team.get(team_id)}))
        if len(component_ids) <= 1:
            continue

        mismatch_count = 0
        checked_rounds = 0
        pair_count = 0
        teams = [team for team in context.teams if team.team_id in set(team_ids)]
        for left, right in combinations(sorted(teams, key=lambda team: team.team_id), 2):
            relation = _linkage_relation(getattr(left, "linkage_side", ""), getattr(right, "linkage_side", ""))
            if relation not in {"same", "opposite"}:
                continue
            left_assignment = assignment_by_team.get(left.team_id)
            right_assignment = assignment_by_team.get(right.team_id)
            if left_assignment is None or right_assignment is None:
                continue
            left_pattern = _home_away_pattern(left_assignment, context)
            right_pattern = _home_away_pattern(right_assignment, context)
            rounds = sorted(set(left_pattern).union(right_pattern))
            if not rounds:
                continue
            pair_count += 1
            checked_rounds += len(rounds)
            for round_index in rounds:
                left_side = left_pattern.get(round_index, "rest")
                right_side = right_pattern.get(round_index, "rest")
                if relation == "same" and left_side != right_side:
                    mismatch_count += 1
                elif relation == "opposite" and {left_side, right_side} != {"home", "away"}:
                    mismatch_count += 1
        if mismatch_count <= 0:
            continue
        conflicts.append(
            LinkageConflict(
                linkage_key=linkage_key,
                relation="mixed" if pair_count > 1 else "",
                team_ids=tuple(sorted(team_ids)),
                component_ids=component_ids,
                mismatch_count=mismatch_count,
                checked_rounds=checked_rounds,
                pair_count=pair_count,
            )
        )
    return tuple(sorted(conflicts, key=lambda conflict: (-conflict.mismatch_count, conflict.linkage_key)))


def build_linkage_repair_blocks(
    context: SolverContext,
    initial_components: Iterable[InitialComponent],
    linkage_conflicts: Iterable[LinkageConflict],
) -> tuple[RepairBlock, ...]:
    components = tuple(initial_components)
    component_by_id = {component.component_id: component for component in components}
    if not component_by_id:
        return ()
    uf = _UnionFind(component_by_id)
    linkage_keys_by_component: dict[str, set[str]] = defaultdict(set)
    for conflict in linkage_conflicts:
        component_ids = tuple(component_id for component_id in conflict.component_ids if component_id in component_by_id)
        if not component_ids:
            continue
        first = component_ids[0]
        for component_id in component_ids:
            uf.union(first, component_id)
            linkage_keys_by_component[component_id].add(conflict.linkage_key)

    grouped: dict[str, set[str]] = defaultdict(set)
    for conflict in linkage_conflicts:
        for component_id in conflict.component_ids:
            if component_id in component_by_id:
                grouped[uf.find(component_id)].add(component_id)

    blocks: list[RepairBlock] = []
    for index, component_ids in enumerate(sorted((tuple(sorted(ids)) for ids in grouped.values()), key=lambda ids: ids), start=1):
        team_ids = tuple(
            sorted(
                team_id
                for component_id in component_ids
                for team_id in component_by_id[component_id].team_ids
            )
        )
        linkage_keys = tuple(
            sorted(
                linkage_key
                for component_id in component_ids
                for linkage_key in linkage_keys_by_component.get(component_id, set())
            )
        )
        blocks.append(
            RepairBlock(
                block_id=f"L{index:03d}",
                initial_component_ids=component_ids,
                team_ids=team_ids,
                conflict_resource_ids=(),
                linkage_keys=linkage_keys,
            )
        )
    return tuple(blocks)


def build_repair_blocks(
    context: SolverContext,
    initial_components: Iterable[InitialComponent],
    conflict_hubs: Iterable[ConflictHub],
) -> tuple[RepairBlock, ...]:
    """Build repair blocks from conflict hubs, then close them by linkage."""

    components = tuple(initial_components)
    component_by_id = {component.component_id: component for component in components}
    component_by_team = {
        team_id: component.component_id
        for component in components
        for team_id in component.team_ids
    }
    hubs = tuple(conflict_hubs)
    if not hubs:
        return ()

    adjacency: dict[str, set[str]] = defaultdict(set)
    hub_ids_by_component: dict[str, set[str]] = defaultdict(set)
    for hub in hubs:
        component_ids = set(hub.component_ids)
        if not component_ids:
            component_ids = {
                component_by_team[team_id]
                for team_id in hub.team_ids
                if team_id in component_by_team
            }
        if not component_ids:
            continue
        for component_id in component_ids:
            adjacency[component_id].update(component_ids - {component_id})
            hub_ids_by_component[component_id].add(hub.resource_id)

    linkage_components: dict[str, set[str]] = defaultdict(set)
    linkage_keys_by_component: dict[str, set[str]] = defaultdict(set)
    for linkage_key, team_ids in linkage_buckets(context).items():
        ids = {component_by_team[team_id] for team_id in team_ids if team_id in component_by_team}
        if len(ids) < 2:
            continue
        linkage_components[linkage_key].update(ids)
        for component_id in ids:
            linkage_keys_by_component[component_id].add(linkage_key)

    visited: set[str] = set()
    raw_blocks: list[set[str]] = []
    for component_id in sorted(adjacency):
        if component_id in visited:
            continue
        block = _walk_component_graph(component_id, adjacency)
        visited.update(block)
        raw_blocks.append(block)

    blocks: list[RepairBlock] = []
    for index, component_ids in enumerate(raw_blocks, start=1):
        expanded = set(component_ids)
        expanded_by_linkage = False
        changed = True
        while changed:
            changed = False
            for linkage_key, linked_component_ids in linkage_components.items():
                if expanded.intersection(linked_component_ids) and not linked_component_ids.issubset(expanded):
                    expanded.update(linked_component_ids)
                    expanded_by_linkage = True
                    changed = True

        team_ids = tuple(
            sorted(
                team_id
                for component_id in expanded
                for team_id in component_by_id.get(component_id, InitialComponent("", (), (), (), 0)).team_ids
            )
        )
        conflict_resource_ids = tuple(
            sorted(
                resource_id
                for component_id in expanded
                for resource_id in hub_ids_by_component.get(component_id, set())
            )
        )
        linkage_keys = tuple(
            sorted(
                linkage_key
                for component_id in expanded
                for linkage_key in linkage_keys_by_component.get(component_id, set())
            )
        )
        blocks.append(
            RepairBlock(
                block_id=f"R{index:03d}",
                initial_component_ids=tuple(sorted(expanded)),
                team_ids=team_ids,
                conflict_resource_ids=conflict_resource_ids,
                linkage_keys=linkage_keys,
                expanded_by_linkage=expanded_by_linkage,
            )
        )
    return tuple(blocks)


def frozen_usage_by_resource(
    result: ResourceSolverResult,
    repair_team_ids: Iterable[str],
) -> dict[str, int]:
    """Count occupied timed resources used by teams outside the repair block."""

    repair_team_set = {str(team_id) for team_id in repair_team_ids}
    usage = Counter()
    for match in result.real_matches:
        if match.home_team_id not in repair_team_set:
            usage[match.resource_id] += 1
    return dict(sorted(usage.items()))


def context_with_residual_capacities(
    context: SolverContext,
    frozen_usage: dict[str, int],
) -> SolverContext:
    """Return a context where timed capacities are reduced by frozen matches."""

    if not frozen_usage:
        return context
    capacities = dict(context.capacities)
    relevant_resource_ids = {
        str(resource_id)
        for candidate in context.candidates
        for resource_id in candidate.potential_resources
    }
    relevant_resource_ids.update(frozen_usage)
    for resource_id in sorted(relevant_resource_ids):
        frozen = int(frozen_usage.get(resource_id, 0) or 0)
        if frozen <= 0:
            continue
        original_capacity = capacity_for_resource(context, resource_id)
        residual_capacity = max(0, original_capacity - frozen)
        capacities[resource_id] = CapacityEstimate(
            base_resource_id=resource_id,
            capacity=residual_capacity,
            method="conflict_repair_residual",
            demand_count=frozen,
        )
    return replace(context, capacities=capacities)


def merge_assignments(
    context: SolverContext,
    initial_assignments: Iterable[Assignment],
    repaired_assignments_by_block: dict[str, Iterable[Assignment]],
    repair_blocks: Iterable[RepairBlock],
) -> tuple[Assignment, ...]:
    """Replace initial assignments with repaired block assignments."""

    by_team = {assignment.team_id: assignment for assignment in initial_assignments}
    block_team_ids = {
        block.block_id: set(block.team_ids)
        for block in repair_blocks
        if block.block_id in repaired_assignments_by_block
    }
    for block_id, team_ids in block_team_ids.items():
        for team_id in team_ids:
            by_team.pop(team_id, None)
        for assignment in repaired_assignments_by_block[block_id]:
            by_team[assignment.team_id] = assignment

    validation = validate_assignments(context, by_team.values())
    if validation["status"] != "valid":
        raise ValueError(f"Invalid conflict-repair assignment merge: {validation['errors']}")
    return tuple(sorted(by_team.values(), key=lambda assignment: assignment.team_id))


def validate_assignments(
    context: SolverContext,
    assignments: Iterable[Assignment],
) -> dict[str, Any]:
    """Validate coverage and candidate membership for global assignments."""

    assignment_list = tuple(assignments)
    team_ids = {team.team_id for team in context.teams}
    owners: dict[str, list[Assignment]] = defaultdict(list)
    candidate_keys = {
        (candidate.team_id, candidate.group_id, int(candidate.number))
        for candidate in context.candidates
    }
    invalid_candidates: list[dict[str, Any]] = []
    for assignment in assignment_list:
        owners[assignment.team_id].append(assignment)
        key = (assignment.team_id, assignment.group_id, int(assignment.number))
        if key not in candidate_keys:
            invalid_candidates.append(asdict(assignment))

    duplicate_teams = {
        team_id: [asdict(item) for item in values]
        for team_id, values in sorted(owners.items())
        if len(values) > 1
    }
    missing_teams = sorted(team_ids.difference(owners))
    unknown_teams = sorted(set(owners).difference(team_ids))
    errors = []
    for code, payload in (
        ("duplicate_teams", duplicate_teams),
        ("missing_teams", missing_teams),
        ("unknown_teams", unknown_teams),
        ("invalid_candidates", invalid_candidates),
    ):
        if payload:
            errors.append({"code": code, "details": payload})
    return {
        "artifact_type": "resource_solver_conflict_repair_assignment_validation",
        "status": "valid" if not errors else "invalid",
        "assignment_count": len(assignment_list),
        "team_count": len(team_ids),
        "errors": errors,
    }


def team_competition_keys(context: SolverContext) -> dict[str, str]:
    return {
        team.team_id: _competition_key_to_string(competition_key_for_team(team, context.config))
        for team in context.teams
    }


def team_initial_domain_keys(context: SolverContext) -> dict[str, str]:
    return {
        team.team_id: _initial_domain_key(team, context.config)
        for team in context.teams
    }


def team_to_initial_component(
    components: Iterable[InitialComponent],
) -> dict[str, str]:
    return {
        team_id: component.component_id
        for component in components
        for team_id in component.team_ids
    }


def linkage_buckets(context: SolverContext) -> dict[str, tuple[str, ...]]:
    """Return input/simulated linkage groups that should keep teams together."""

    buckets: dict[str, set[str]] = defaultdict(set)
    for team in context.teams:
        group = _normalize_linkage_group(getattr(team, "linkage_group", ""))
        side = _normalize_linkage_side(getattr(team, "linkage_side", ""))
        if not group or side == "indiferent":
            continue
        venue_key = _normalize_linkage_group(getattr(team, "venue", ""))
        linkage_key = f"{venue_key or 'sense-venue'}|{group}"
        buckets[linkage_key].add(team.team_id)
    return {
        key: tuple(sorted(team_ids))
        for key, team_ids in sorted(buckets.items())
        if len(team_ids) > 1
    }


def linkage_conflicts_payload(conflicts: Iterable[LinkageConflict]) -> dict[str, Any]:
    rows = [_json_ready(conflict) for conflict in conflicts]
    return {
        "artifact_type": "resource_solver_conflict_repair_linkage_conflicts",
        "conflict_count": len(rows),
        "total_mismatches": sum(int(row.get("mismatch_count", 0) or 0) for row in rows),
        "conflicts": rows,
    }


def split_timed_resource_id(resource_id: str) -> tuple[str, int]:
    text = str(resource_id)
    if "|J" not in text:
        return text, 0
    base, round_text = text.rsplit("|J", 1)
    try:
        return base, int(round_text)
    except ValueError:
        return base, 0


def initial_components_payload(components: Iterable[InitialComponent]) -> dict[str, Any]:
    rows = [_json_ready(component) for component in components]
    return {
        "artifact_type": "resource_solver_conflict_repair_initial_components",
        "component_count": len(rows),
        "components": rows,
    }


def conflict_hubs_payload(hubs: Iterable[ConflictHub]) -> dict[str, Any]:
    rows = [_json_ready(hub) for hub in hubs]
    return {
        "artifact_type": "resource_solver_conflict_repair_hubs",
        "hub_count": len(rows),
        "total_excess": sum(int(row.get("excess", 0) or 0) for row in rows),
        "hubs": rows,
    }


def repair_blocks_payload(blocks: Iterable[RepairBlock]) -> dict[str, Any]:
    rows = [_json_ready(block) for block in blocks]
    return {
        "artifact_type": "resource_solver_conflict_repair_blocks",
        "block_count": len(rows),
        "blocks": rows,
    }


def _initial_domain_key(team: Any, config: Any | None) -> str:
    key = _competition_key_to_string(competition_key_for_team(team, config))
    if _hard_level_enabled(config):
        family = "A" if normalize_hard_level(getattr(team, "level", "")) == "A" else "no-A"
        key = f"{key}|level_family|{family}"
    return key


def _hard_level_enabled(config: Any | None) -> bool:
    return str(getattr(config, "level_constraint_mode", "off") if config is not None else "off").strip().casefold() == "hard"


def _small_linkage_max_size(context: SolverContext) -> int:
    try:
        return max(2, int(getattr(context.config, "linkage_max_group_size", 2) or 2))
    except (TypeError, ValueError):
        return 2


def _linkage_relation(left_side: Any, right_side: Any) -> str | None:
    if _normalize_linkage_side(left_side) == "indiferent" or _normalize_linkage_side(right_side) == "indiferent":
        return None
    same = getattr(_linkage_helpers, "linkage_sides_match", None)
    if callable(same):
        try:
            if bool(same(left_side, right_side)):
                return "same"
        except Exception:
            pass
    opposite = getattr(_linkage_helpers, "linkage_sides_are_opposites", None)
    if callable(opposite):
        try:
            if bool(opposite(left_side, right_side)):
                return "opposite"
        except Exception:
            pass
    return "same" if _normalize_linkage_side(left_side) == _normalize_linkage_side(right_side) else "opposite"


def _home_away_pattern(assignment: Assignment, context: SolverContext) -> dict[int, str]:
    group = next((item for item in context.groups if item.group_id == assignment.group_id), None)
    if group is None:
        phase = context.phase
    else:
        phase = phase_calendar(group.phase_name or context.phase_name, slot_count_for_numbers(group.numbers))
    pattern: dict[int, str] = {}
    for round_index, round_matches in enumerate(phase, start=1):
        side = "rest"
        for home_number, away_number in round_matches:
            if int(home_number) == int(assignment.number):
                side = "home"
                break
            if int(away_number) == int(assignment.number):
                side = "away"
                break
        pattern[round_index] = side
    return pattern


def iteration_summary_payload(
    *,
    initial_result: ResourceSolverResult,
    final_result: ResourceSolverResult,
    repair_records: Iterable[dict[str, Any]],
    validation: dict[str, Any],
) -> dict[str, Any]:
    records = tuple(repair_records)
    return {
        "artifact_type": "resource_solver_conflict_repair_iteration_summary",
        "initial_resource_excess": _total_resource_excess(initial_result),
        "final_resource_excess": _total_resource_excess(final_result),
        "initial_assignments": len(initial_result.assignments),
        "final_assignments": len(final_result.assignments),
        "repair_block_count": len(records),
        "successful_repair_blocks": sum(1 for record in records if record.get("accepted")),
        "repair_records": _json_ready(records),
        "assignment_validation": validation,
    }


def component_solve_payload(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = tuple(records)
    return {
        "artifact_type": "resource_solver_conflict_repair_component_solves",
        "solve_count": len(rows),
        "solves": _json_ready(rows),
    }


def _walk_component_graph(start: str, adjacency: dict[str, set[str]]) -> set[str]:
    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, set()):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append(neighbor)
    return seen


def _competition_key_to_string(key: Any) -> str:
    if isinstance(key, (list, tuple)):
        return "|".join(str(part) for part in key)
    return str(key)


def _normalize_linkage_group(value: Any) -> str:
    helper = getattr(_linkage_helpers, "normalize_linkage_group", None)
    if callable(helper):
        return str(helper(value))
    return str(value or "").strip().casefold()


def _normalize_linkage_side(value: Any) -> str:
    helper = getattr(_linkage_helpers, "normalize_linkage_side_from_seed", None)
    if callable(helper):
        return str(helper(value))
    text = str(value or "").strip().casefold()
    return text if text in {"casa", "fora"} else "indiferent"


def _total_resource_excess(result: ResourceSolverResult) -> int:
    return sum(int(usage.excess) for usage in result.resource_usage)


def _json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


__all__ = [
    "ConflictHub",
    "InitialComponent",
    "RepairBlock",
    "build_initial_components",
    "build_linkage_repair_blocks",
    "build_repair_blocks",
    "component_solve_payload",
    "conflict_hubs_payload",
    "context_with_residual_capacities",
    "detect_conflict_hubs",
    "detect_linkage_conflicts",
    "frozen_usage_by_resource",
    "initial_components_payload",
    "iteration_summary_payload",
    "linkage_conflicts_payload",
    "linkage_buckets",
    "merge_assignments",
    "repair_blocks_payload",
    "split_timed_resource_id",
    "team_competition_keys",
    "team_to_initial_component",
    "validate_assignments",
]
