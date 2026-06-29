"""Pattern generation for resource/linkage microhubs."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from typing import Any, Iterable

from calendaritzacions.domain.phases import phase_calendar, slot_count_for_numbers
from calendaritzacions.engine.variants.resource_solver.constraints.resource_capacity import capacity_for_resource
from calendaritzacions.engine.variants.resource_solver.input_adapter import competition_key_for_team
from calendaritzacions.engine.variants.resource_solver.pattern_master.microhubs import linkage_key_for_team
from calendaritzacions.engine.variants.resource_solver.pattern_master.types import (
    HubPattern,
    MicroHub,
    PatternAssignment,
)
from calendaritzacions.engine.variants.resource_solver.types import Candidate, SolverContext

try:
    from calendaritzacions.engine.variants.resource_solver import linkage as linkage_domain
except Exception:  # pragma: no cover
    linkage_domain = None


def generate_initial_patterns(
    context: SolverContext,
    hubs: Iterable[MicroHub],
) -> tuple[HubPattern, ...]:
    return tuple(_pattern_for_hub(context, hub, offset=0, variant="base") for hub in hubs)


def generate_variants_for_hubs(
    context: SolverContext,
    hubs: Iterable[MicroHub],
    *,
    existing_patterns: Iterable[HubPattern] = (),
) -> tuple[HubPattern, ...]:
    existing = {pattern.pattern_id for pattern in existing_patterns}
    signatures = {_pattern_signature(pattern) for pattern in existing_patterns}
    patterns: list[HubPattern] = []
    numbers = _all_numbers(context)
    for hub in hubs:
        for offset in range(1, max(1, len(numbers))):
            pattern = _pattern_for_hub(context, hub, offset=offset, variant=f"shift_{offset}")
            signature = _pattern_signature(pattern)
            if pattern.pattern_id not in existing and signature not in signatures:
                existing.add(pattern.pattern_id)
                signatures.add(signature)
                patterns.append(pattern)
        for offset in range(0, max(1, len(numbers))):
            pattern = _pattern_for_hub(
                context,
                hub,
                offset=offset,
                variant=f"repair_shift_{offset}",
                respect_linkage=False,
            )
            signature = _pattern_signature(pattern)
            if pattern.pattern_id not in existing and signature not in signatures:
                existing.add(pattern.pattern_id)
                signatures.add(signature)
                patterns.append(pattern)
        for pattern in _local_search_patterns_for_hub(context, hub, existing=existing, signatures=signatures):
            existing.add(pattern.pattern_id)
            signatures.add(_pattern_signature(pattern))
            patterns.append(pattern)
    return tuple(patterns)


def overloaded_competitions_from_patterns(
    context: SolverContext,
    patterns: Iterable[HubPattern],
) -> tuple[str, ...]:
    selected = tuple(patterns)
    capacity = competition_number_capacity(context)
    counts: dict[str, Counter[int]] = defaultdict(Counter)
    for pattern in selected:
        for competition_key, number_counts in pattern.competition_number_counts.items():
            for number, count in number_counts.items():
                counts[competition_key][int(number)] += int(count)
    overloaded: set[str] = set()
    for competition_key, number_counts in counts.items():
        caps = capacity.get(competition_key, {})
        for number, count in number_counts.items():
            if count > caps.get(number, 0):
                overloaded.add(competition_key)
    return tuple(sorted(overloaded))


def overloaded_slot_domains_from_patterns(
    context: SolverContext,
    patterns: Iterable[HubPattern],
) -> tuple[str, ...]:
    selected = tuple(patterns)
    capacity = slot_domain_number_capacity(context)
    counts: dict[str, Counter[int]] = defaultdict(Counter)
    for pattern in selected:
        for domain_key, number_counts in pattern_slot_domain_number_counts(context, pattern).items():
            for number, count in number_counts.items():
                counts[domain_key][int(number)] += int(count)
    overloaded: set[str] = set()
    for domain_key, number_counts in counts.items():
        caps = capacity.get(domain_key, {})
        for number, count in number_counts.items():
            if count > caps.get(number, 0):
                overloaded.add(domain_key)
    return tuple(sorted(overloaded))


def hubs_touching_competitions(hubs: Iterable[MicroHub], competition_keys: Iterable[str]) -> tuple[MicroHub, ...]:
    wanted = {str(key) for key in competition_keys}
    return tuple(hub for hub in hubs if wanted.intersection(hub.competition_keys))


def hubs_touching_slot_domains(
    context: SolverContext,
    hubs: Iterable[MicroHub],
    domain_keys: Iterable[str],
) -> tuple[MicroHub, ...]:
    wanted = {str(key) for key in domain_keys}
    if not wanted:
        return ()
    domains_by_team = _slot_domains_by_team(context)
    return tuple(
        hub
        for hub in hubs
        if any(wanted.intersection(domains_by_team.get(team_id, ())) for team_id in hub.team_ids)
    )


def competition_number_capacity(context: SolverContext) -> dict[str, dict[int, int]]:
    competition_by_group = _competition_key_by_group(context)
    capacity: dict[str, Counter[int]] = defaultdict(Counter)
    for group in context.groups:
        competition_key = competition_by_group.get(group.group_id)
        if not competition_key:
            continue
        for number in group.numbers:
            capacity[competition_key][int(number)] += 1
    return {key: dict(counts) for key, counts in sorted(capacity.items())}


def slot_domain_number_capacity(context: SolverContext) -> dict[str, dict[int, int]]:
    """Capacity by real candidate group-domain and draw number.

    A competition can have several hard-level domains. Counting only
    competition+number may allow two teams to take the same number inside the
    same concrete level group while another level group keeps that number free.
    """

    group_by_id = {group.group_id: group for group in context.groups}
    domains: set[tuple[str, ...]] = set()
    candidate_groups: dict[tuple[str, int], set[str]] = defaultdict(set)
    for candidate in context.candidates:
        candidate_groups[(candidate.team_id, int(candidate.number))].add(candidate.group_id)
    domains.update(tuple(sorted(group_ids)) for group_ids in candidate_groups.values() if group_ids)

    capacity: dict[str, Counter[int]] = defaultdict(Counter)
    for group_ids in domains:
        key = _slot_domain_key(group_ids)
        for group_id in group_ids:
            group = group_by_id.get(group_id)
            if group is None:
                continue
            for number in group.numbers:
                capacity[key][int(number)] += 1
    return {key: dict(counts) for key, counts in sorted(capacity.items())}


def pattern_slot_domain_number_counts(context: SolverContext, pattern: HubPattern) -> dict[str, dict[int, int]]:
    candidate_groups = _candidate_group_ids_by_team_number(context)

    counts: dict[str, Counter[int]] = defaultdict(Counter)
    for assignment in pattern.assignments:
        number = int(assignment.number)
        group_ids = tuple(sorted(candidate_groups.get((assignment.team_id, number), ())))
        if not group_ids:
            continue
        counts[_slot_domain_key(group_ids)][number] += 1
    return {key: dict(value) for key, value in sorted(counts.items())}


def patterns_payload(patterns: Iterable[HubPattern]) -> dict[str, Any]:
    rows = [_pattern_payload(pattern) for pattern in patterns]
    by_hub = Counter(row["hub_id"] for row in rows)
    return {
        "artifact_type": "resource_solver_pattern_master_patterns",
        "pattern_count": len(rows),
        "hub_count": len(by_hub),
        "patterns_by_hub": dict(sorted(by_hub.items())),
        "patterns": rows,
    }


def _pattern_for_hub(
    context: SolverContext,
    hub: MicroHub,
    *,
    offset: int,
    variant: str,
    respect_linkage: bool = True,
) -> HubPattern:
    team_by_id = {team.team_id: team for team in context.teams}
    candidates_by_team = _candidates_by_team(context)
    candidate_groups = _candidate_group_ids_by_team_number(context)
    numbers = _all_numbers(context)
    number_by_team: dict[str, int] = {}
    used_by_competition: dict[str, Counter[int]] = defaultdict(Counter)
    used_by_slot_domain: Counter[tuple[str, int]] = Counter()

    if respect_linkage:
        for linkage_key, team_ids in _linkage_members(context, hub).items():
            anchor = _shift_number(_preferred_number(team_by_id[team_ids[0]], numbers), offset, numbers)
            for team_id in team_ids:
                team = team_by_id[team_id]
                side = _linkage_side(team)
                number = anchor
                if side == "fora":
                    number = _opposite_number(anchor) or _shift_number(anchor, len(numbers) // 2, numbers)
                number_by_team[team_id] = _nearest_candidate_number(number, candidates_by_team[team_id], numbers)
                _mark_number_usage(
                    context,
                    team,
                    number_by_team[team_id],
                    candidate_groups,
                    used_by_competition,
                    used_by_slot_domain,
                )

    for index, team_id in enumerate(hub.team_ids):
        if team_id in number_by_team:
            continue
        team = team_by_id[team_id]
        competition_key = _competition_key(team, context)
        preferred = _preferred_number(team, numbers)
        number = _shift_number(preferred, offset + index, numbers)
        number = _least_used_candidate_number(
            number,
            candidates_by_team[team_id],
            used_by_competition[competition_key],
            numbers,
            candidate_groups=candidate_groups,
            used_by_slot_domain=used_by_slot_domain,
            team_id=team_id,
        )
        number_by_team[team_id] = number
        _mark_number_usage(
            context,
            team,
            number,
            candidate_groups,
            used_by_competition,
            used_by_slot_domain,
        )

    assignments = tuple(
        PatternAssignment(team_id=team_id, number=int(number_by_team[team_id]))
        for team_id in sorted(number_by_team)
    )
    resource_usage = _resource_usage(context, assignments)
    competition_counts = _competition_number_counts(context, assignments)
    cost_breakdown = _cost_breakdown(context, hub, assignments, resource_usage)
    cost = _pattern_selection_cost(cost_breakdown)
    return HubPattern(
        pattern_id=f"{hub.hub_id}_{variant}",
        hub_id=hub.hub_id,
        assignments=assignments,
        cost=cost,
        cost_breakdown=cost_breakdown,
        resource_usage=resource_usage,
        competition_number_counts=competition_counts,
        variant=variant,
    )


def _resource_usage(context: SolverContext, assignments: tuple[PatternAssignment, ...]) -> dict[str, int]:
    candidate_by_team_number = {
        (candidate.team_id, int(candidate.number)): candidate
        for candidate in context.candidates
    }
    usage: Counter[str] = Counter()
    for assignment in assignments:
        candidate = candidate_by_team_number.get((assignment.team_id, int(assignment.number)))
        if candidate is None:
            continue
        for resource_id in candidate.potential_resources:
            usage[str(resource_id)] += 1
    return dict(sorted(usage.items()))


def _competition_number_counts(
    context: SolverContext,
    assignments: tuple[PatternAssignment, ...],
) -> dict[str, dict[int, int]]:
    team_by_id = {team.team_id: team for team in context.teams}
    counts: dict[str, Counter[int]] = defaultdict(Counter)
    for assignment in assignments:
        team = team_by_id.get(assignment.team_id)
        if team is None:
            continue
        counts[_competition_key(team, context)][int(assignment.number)] += 1
    return {key: dict(value) for key, value in sorted(counts.items())}


def _cost_breakdown(
    context: SolverContext,
    hub: MicroHub,
    assignments: tuple[PatternAssignment, ...],
    resource_usage: dict[str, int],
) -> dict[str, int]:
    by_team = {assignment.team_id: int(assignment.number) for assignment in assignments}
    team_by_id = {team.team_id: team for team in context.teams}
    seed_cost = 0
    for team_id, number in by_team.items():
        requested = _coerce_int(getattr(team_by_id[team_id], "seed_request_original", None))
        if requested is not None:
            seed_cost += abs(requested - number)
    number_linkage_cost = 0
    calendar_mismatch_cost = 0
    number_warning_weight = int(getattr(context.config, "linkage_number_warning_weight", 1_000) or 1_000)
    calendar_weight = int(getattr(context.config, "calendar_mismatch_weight", 1_000_000) or 1_000_000)
    candidate_groups_by_team_number = _candidate_group_ids_by_team_number(context)
    for _key, team_ids in _linkage_members(context, hub).items():
        for left_id in team_ids:
            for right_id in team_ids:
                if left_id >= right_id:
                    continue
                relation = _linkage_relation(team_by_id[left_id], team_by_id[right_id])
                if relation not in {"same", "opposite"}:
                    continue
                left_number = by_team.get(left_id)
                right_number = by_team.get(right_id)
                if left_number is None or right_number is None:
                    continue
                if _violates_relation(left_number, right_number, relation):
                    number_linkage_cost += number_warning_weight
                calendar_mismatch_cost += (
                    _minimum_calendar_mismatches_for_numbers(
                        context,
                        candidate_groups_by_team_number,
                        left_id,
                        left_number,
                        right_id,
                        right_number,
                        relation,
                    )
                    * calendar_weight
                )
    resource_cost = 0
    resource_weight = int(getattr(context.config, "resource_excess_weight", 100_000) or 100_000)
    for resource_id, count in resource_usage.items():
        resource_cost += max(0, int(count) - capacity_for_resource(context, resource_id)) * resource_weight
    diversity_cost = len({assignment.number for assignment in assignments})
    return {
        "seed_deviation": seed_cost,
        "calendar_mismatch": calendar_mismatch_cost,
        "linkage": number_linkage_cost,
        "resource_pressure": resource_cost,
        "diversity": diversity_cost,
    }


def _linkage_members(context: SolverContext, hub: MicroHub) -> dict[str, tuple[str, ...]]:
    hub_team_ids = set(hub.team_ids)
    buckets: dict[str, list[str]] = defaultdict(list)
    for team in context.teams:
        if team.team_id not in hub_team_ids:
            continue
        key = linkage_key_for_team(team)
        if key:
            buckets[key].append(team.team_id)
    return {key: tuple(sorted(ids)) for key, ids in sorted(buckets.items()) if len(ids) > 1}


def _all_numbers(context: SolverContext) -> tuple[int, ...]:
    numbers = sorted({int(candidate.number) for candidate in context.candidates})
    return tuple(numbers or range(1, 9))


def _candidates_by_team(context: SolverContext) -> dict[str, tuple[Candidate, ...]]:
    rows: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in context.candidates:
        rows[candidate.team_id].append(candidate)
    return {key: tuple(value) for key, value in rows.items()}


def _local_search_patterns_for_hub(
    context: SolverContext,
    hub: MicroHub,
    *,
    existing: set[str],
    signatures: set[tuple[tuple[str, int], ...]],
    max_patterns: int | None = None,
) -> tuple[HubPattern, ...]:
    cp_model = _load_cp_model()
    if cp_model is None or not hub.team_ids:
        return ()

    team_by_id = {team.team_id: team for team in context.teams}
    candidates_by_team = _candidates_by_team(context)
    allowed_numbers = {
        team_id: tuple(sorted({int(candidate.number) for candidate in candidates_by_team.get(team_id, ())}))
        for team_id in hub.team_ids
    }
    if any(not numbers for numbers in allowed_numbers.values()):
        return ()

    model = cp_model.CpModel()
    y: dict[tuple[str, int], Any] = {}
    for team_id, numbers in allowed_numbers.items():
        for number in numbers:
            y[(team_id, number)] = model.NewBoolVar(f"local_{_safe_name(hub.hub_id)}_{_safe_name(team_id)}_{number}")
        model.Add(sum(y[(team_id, number)] for number in numbers) == 1)

    objective_terms: list[Any] = []
    objective_coefficients: list[int] = []

    for team_id, numbers in allowed_numbers.items():
        requested = _coerce_int(getattr(team_by_id[team_id], "seed_request_original", None))
        if requested is None:
            continue
        for number in numbers:
            objective_terms.append(y[(team_id, number)])
            objective_coefficients.append(abs(requested - number))

    number_warning_weight = int(getattr(context.config, "linkage_number_warning_weight", 1_000) or 1_000)
    calendar_weight = int(getattr(context.config, "calendar_mismatch_weight", 1_000_000) or 1_000_000)
    candidate_groups = _candidate_group_ids_by_team_number(context)
    for _key, team_ids in _linkage_members(context, hub).items():
        for left_id in team_ids:
            for right_id in team_ids:
                if left_id >= right_id:
                    continue
                relation = _linkage_relation(team_by_id[left_id], team_by_id[right_id])
                if relation not in {"same", "opposite"}:
                    continue
                for left_number in allowed_numbers[left_id]:
                    for right_number in allowed_numbers[right_id]:
                        penalty = (
                            _minimum_calendar_mismatches_for_numbers(
                                context,
                                candidate_groups,
                                left_id,
                                left_number,
                                right_id,
                                right_number,
                                relation,
                            )
                            * calendar_weight
                        )
                        if _violates_relation(left_number, right_number, relation):
                            penalty += number_warning_weight
                        if penalty <= 0:
                            continue
                        var = model.NewBoolVar(
                            f"link_{_safe_name(left_id)}_{left_number}_{_safe_name(right_id)}_{right_number}"
                        )
                        model.Add(var <= y[(left_id, left_number)])
                        model.Add(var <= y[(right_id, right_number)])
                        model.Add(var >= y[(left_id, left_number)] + y[(right_id, right_number)] - 1)
                        objective_terms.append(var)
                        objective_coefficients.append(penalty)

    slot_capacity = slot_domain_number_capacity(context)
    domain_number_terms: dict[tuple[str, int], list[Any]] = defaultdict(list)
    for team_id, numbers in allowed_numbers.items():
        for number in numbers:
            group_ids = tuple(sorted(candidate_groups.get((team_id, number), ())))
            if group_ids:
                domain_number_terms[(_slot_domain_key(group_ids), number)].append(y[(team_id, number)])
    for (domain_key, number), terms in sorted(domain_number_terms.items()):
        cap = int(slot_capacity.get(domain_key, {}).get(number, 0))
        if not terms or cap <= 0:
            continue
        excess = model.NewIntVar(0, len(hub.team_ids), f"slot_{_safe_name(hub.hub_id)}_{len(objective_terms)}")
        model.Add(excess >= sum(terms) - cap)
        objective_terms.append(excess)
        objective_coefficients.append(calendar_weight)

    used_number_vars = []
    for number in sorted({number for numbers in allowed_numbers.values() for number in numbers}):
        users = [y[(team_id, number)] for team_id, numbers in allowed_numbers.items() if number in numbers]
        if not users:
            continue
        used = model.NewBoolVar(f"used_{_safe_name(hub.hub_id)}_{number}")
        for var in users:
            model.Add(used >= var)
        model.Add(used <= sum(users))
        used_number_vars.append(used)
    for var in used_number_vars:
        objective_terms.append(var)
        objective_coefficients.append(1)

    if objective_terms:
        model.Minimize(sum(coef * term for coef, term in zip(objective_coefficients, objective_terms)))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = _local_solve_time_limit(context, hub)
    workers = int(getattr(context.config, "num_search_workers", 0) or 0)
    if workers > 0:
        solver.parameters.num_search_workers = workers

    limit = _local_pattern_limit(context, hub) if max_patterns is None else max_patterns
    pool: list[HubPattern] = []
    attempts = 0
    max_attempts = max(limit * 6, limit + 1)
    while len(pool) < limit * 4 and attempts < max_attempts:
        attempts += 1
        status_code = solver.Solve(model)
        if status_code not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
            break
        number_by_team = {
            team_id: next(number for number in numbers if int(solver.Value(y[(team_id, number)])) > 0)
            for team_id, numbers in allowed_numbers.items()
        }
        assignments = tuple(
            PatternAssignment(team_id=team_id, number=int(number_by_team[team_id]))
            for team_id in sorted(number_by_team)
        )
        pattern = _pattern_from_assignments(
            context,
            hub,
            assignments,
            variant=f"local_{len(pool) + 1}",
        )
        signature = _pattern_signature(pattern)
        selected_terms = [y[(team_id, number)] for team_id, number in number_by_team.items()]
        model.Add(sum(selected_terms) <= len(selected_terms) - 1)
        if pattern.pattern_id in existing or signature in signatures:
            continue
        pool.append(pattern)
    return _select_diverse_patterns(pool, limit)


def _pattern_from_assignments(
    context: SolverContext,
    hub: MicroHub,
    assignments: tuple[PatternAssignment, ...],
    *,
    variant: str,
) -> HubPattern:
    resource_usage = _resource_usage(context, assignments)
    competition_counts = _competition_number_counts(context, assignments)
    cost_breakdown = _cost_breakdown(context, hub, assignments, resource_usage)
    cost = _pattern_selection_cost(cost_breakdown)
    return HubPattern(
        pattern_id=f"{hub.hub_id}_{variant}",
        hub_id=hub.hub_id,
        assignments=assignments,
        cost=cost,
        cost_breakdown=cost_breakdown,
        resource_usage=resource_usage,
        competition_number_counts=competition_counts,
        variant=variant,
    )


def _pattern_selection_cost(cost_breakdown: dict[str, int]) -> int:
    return sum(
        int(value)
        for key, value in cost_breakdown.items()
        if key != "resource_pressure"
    )


def _local_pattern_limit(context: SolverContext, hub: MicroHub) -> int:
    min_patterns = max(1, int(getattr(context.config, "pattern_master_local_min_patterns", 12) or 12))
    max_patterns = max(min_patterns, int(getattr(context.config, "pattern_master_local_max_patterns", 96) or 96))
    per_team = max(0, int(getattr(context.config, "pattern_master_local_patterns_per_team", 6) or 6))
    per_linkage = max(0, int(getattr(context.config, "pattern_master_local_patterns_per_linkage", 8) or 8))
    linkage_count = len(_linkage_members(context, hub))
    wanted = min_patterns + len(hub.team_ids) * per_team + linkage_count * per_linkage
    return max(min_patterns, min(max_patterns, wanted))


def _local_solve_time_limit(context: SolverContext, hub: MicroHub) -> float:
    base = max(0.1, float(getattr(context.config, "pattern_master_local_base_solve_seconds", 3.0) or 3.0))
    extra_per_team = max(
        0.0,
        float(getattr(context.config, "pattern_master_local_extra_seconds_per_team_over_8", 2.0) or 0.0),
    )
    scaled = base + max(0, len(hub.team_ids) - 8) * extra_per_team
    cap = float(getattr(context.config, "internal_solve_time_limit_seconds", 60.0) or 60.0)
    return max(0.1, min(scaled, cap))


def _select_diverse_patterns(patterns: list[HubPattern], limit: int) -> tuple[HubPattern, ...]:
    if len(patterns) <= limit:
        return tuple(patterns)
    remaining = sorted(patterns, key=_pattern_quality_key)
    selected: list[HubPattern] = []
    while remaining and len(selected) < limit:
        window = remaining[: max(20, min(len(remaining), limit * 2))]
        if not selected:
            chosen = window[0]
        else:
            chosen = min(
                window,
                key=lambda pattern: (
                    _pattern_quality_value(pattern) - 100 * _min_pattern_distance(pattern, selected),
                    pattern.pattern_id,
                ),
            )
        selected.append(chosen)
        remaining = [pattern for pattern in remaining if pattern.pattern_id != chosen.pattern_id]
    return tuple(selected)


def _pattern_quality_key(pattern: HubPattern) -> tuple[int, int, int, int, int, str]:
    breakdown = pattern.cost_breakdown
    return (
        int(breakdown.get("calendar_mismatch", 0)),
        int(breakdown.get("resource_pressure", 0)),
        int(breakdown.get("seed_deviation", 0)),
        int(breakdown.get("linkage", 0)),
        int(breakdown.get("diversity", 0)),
        pattern.pattern_id,
    )


def _pattern_quality_value(pattern: HubPattern) -> int:
    calendar, resource, seed, linkage, diversity, _pattern_id = _pattern_quality_key(pattern)
    return calendar + resource + seed * 100 + linkage + diversity


def _min_pattern_distance(pattern: HubPattern, selected: list[HubPattern]) -> int:
    signature = dict(_pattern_signature(pattern))
    distances = []
    for item in selected:
        other = dict(_pattern_signature(item))
        distances.append(
            sum(1 for team_id, number in signature.items() if other.get(team_id) != number)
        )
    return min(distances or [0])


def _candidate_group_ids_by_team_number(context: SolverContext) -> dict[tuple[str, int], set[str]]:
    candidate_groups: dict[tuple[str, int], set[str]] = defaultdict(set)
    for candidate in context.candidates:
        candidate_groups[(candidate.team_id, int(candidate.number))].add(candidate.group_id)
    return candidate_groups


def _slot_domains_by_team(context: SolverContext) -> dict[str, tuple[str, ...]]:
    domains: dict[str, set[str]] = defaultdict(set)
    for (team_id, _number), group_ids in _candidate_group_ids_by_team_number(context).items():
        if group_ids:
            domains[team_id].add(_slot_domain_key(tuple(sorted(group_ids))))
    return {team_id: tuple(sorted(keys)) for team_id, keys in domains.items()}


def _minimum_calendar_mismatches_for_numbers(
    context: SolverContext,
    candidate_groups: dict[tuple[str, int], set[str]],
    left_team_id: str,
    left_number: int,
    right_team_id: str,
    right_number: int,
    relation: str,
) -> int:
    left_candidates = candidate_groups.get((left_team_id, int(left_number)), set())
    right_candidates = candidate_groups.get((right_team_id, int(right_number)), set())
    if not left_candidates or not right_candidates:
        return 0
    best: int | None = None
    for left_group_id in left_candidates:
        for right_group_id in right_candidates:
            value = _calendar_mismatches_for_assignment_pair(
                context,
                left_group_id,
                int(left_number),
                right_group_id,
                int(right_number),
                relation,
            )
            best = value if best is None else min(best, value)
    return int(best or 0)


def _calendar_mismatches_for_assignment_pair(
    context: SolverContext,
    left_group_id: str,
    left_number: int,
    right_group_id: str,
    right_number: int,
    relation: str,
) -> int:
    left_rounds = {
        round_index: (side, opponent)
        for round_index, side, opponent in _calendar_rounds_for_group_number(context, left_group_id, left_number)
    }
    right_rounds = {
        round_index: (side, opponent)
        for round_index, side, opponent in _calendar_rounds_for_group_number(context, right_group_id, right_number)
    }
    mismatches = 0
    for round_index in sorted(set(left_rounds).union(right_rounds)):
        left_side, left_opponent = left_rounds.get(round_index, ("rest", 0))
        right_side, right_opponent = right_rounds.get(round_index, ("rest", 0))
        if "rest" in {left_side, right_side}:
            continue
        left_plays = _opponent_is_known_occupied(
            context,
            left_group_id,
            left_opponent,
            paired_group_id=right_group_id,
            paired_number=right_number,
        )
        right_plays = _opponent_is_known_occupied(
            context,
            right_group_id,
            right_opponent,
            paired_group_id=left_group_id,
            paired_number=left_number,
        )
        if not left_plays or not right_plays:
            continue
        if relation == "same" and left_side != right_side:
            mismatches += 1
        elif relation == "opposite" and {left_side, right_side} != {"home", "away"}:
            mismatches += 1
    return mismatches


def _calendar_rounds_for_group_number(
    context: SolverContext,
    group_id: str,
    number: int,
) -> tuple[tuple[int, str, int], ...]:
    group = next((item for item in context.groups if item.group_id == group_id), None)
    if group is None:
        phase = context.phase
    else:
        phase = phase_calendar(group.phase_name or context.phase_name, slot_count_for_numbers(group.numbers))
    rows: list[tuple[int, str, int]] = []
    for round_index, round_matches in enumerate(phase, start=1):
        for home_number, away_number in round_matches:
            if int(home_number) == int(number):
                rows.append((round_index, "home", int(away_number)))
                break
            if int(away_number) == int(number):
                rows.append((round_index, "away", int(home_number)))
                break
    return tuple(rows)


def _opponent_is_known_occupied(
    context: SolverContext,
    group_id: str,
    opponent_number: int,
    *,
    paired_group_id: str,
    paired_number: int,
) -> bool:
    if int(opponent_number) <= 0:
        return False
    if str(group_id) == str(paired_group_id) and int(opponent_number) == int(paired_number):
        return True
    group = next((item for item in context.groups if item.group_id == group_id), None)
    return group is not None and int(group.target_size) >= slot_count_for_numbers(group.numbers)


def _competition_key_by_group(context: SolverContext) -> dict[str, str]:
    team_by_id = {team.team_id: team for team in context.teams}
    result: dict[str, str] = {}
    for candidate in context.candidates:
        team = team_by_id.get(candidate.team_id)
        if team is not None:
            result[candidate.group_id] = _competition_key(team, context)
    return result


def _competition_key(team: Any, context: SolverContext) -> str:
    return "|".join(str(part) for part in competition_key_for_team(team, context.config))


def _preferred_number(team: Any, numbers: tuple[int, ...]) -> int:
    value = _coerce_int(getattr(team, "seed_request_original", None))
    if value in numbers:
        return int(value)
    side = _linkage_side(team)
    if side == "fora":
        return 5 if 5 in numbers else numbers[-1]
    return 1 if 1 in numbers else numbers[0]


def _shift_number(number: int, offset: int, numbers: tuple[int, ...]) -> int:
    if number not in numbers:
        return numbers[offset % len(numbers)]
    index = numbers.index(number)
    return numbers[(index + offset) % len(numbers)]


def _nearest_candidate_number(
    number: int,
    candidates: tuple[Candidate, ...],
    numbers: tuple[int, ...],
) -> int:
    allowed = sorted({int(candidate.number) for candidate in candidates}) or list(numbers)
    return min(allowed, key=lambda item: (abs(item - number), item))


def _least_used_candidate_number(
    number: int,
    candidates: tuple[Candidate, ...],
    used: Counter[int],
    numbers: tuple[int, ...],
    *,
    candidate_groups: dict[tuple[str, int], set[str]] | None = None,
    used_by_slot_domain: Counter[tuple[str, int]] | None = None,
    team_id: str | None = None,
) -> int:
    allowed = sorted({int(candidate.number) for candidate in candidates}) or list(numbers)
    if not candidate_groups or used_by_slot_domain is None or not team_id:
        return min(allowed, key=lambda item: (used[item], abs(item - number), item))
    return min(
        allowed,
        key=lambda item: (
            used_by_slot_domain[(_slot_domain_key(tuple(sorted(candidate_groups.get((team_id, item), ())))), item)],
            used[item],
            abs(item - number),
            item,
        ),
    )


def _mark_number_usage(
    context: SolverContext,
    team: Any,
    number: int,
    candidate_groups: dict[tuple[str, int], set[str]],
    used_by_competition: dict[str, Counter[int]],
    used_by_slot_domain: Counter[tuple[str, int]],
) -> None:
    used_by_competition[_competition_key(team, context)][int(number)] += 1
    group_ids = tuple(sorted(candidate_groups.get((team.team_id, int(number)), ())))
    if group_ids:
        used_by_slot_domain[(_slot_domain_key(group_ids), int(number))] += 1


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number


def _linkage_side(team: Any) -> str:
    helper = getattr(linkage_domain, "normalize_linkage_side_from_seed", None)
    if callable(helper):
        return str(helper(getattr(team, "linkage_side", "")) or "indiferent")
    text = str(getattr(team, "linkage_side", "") or "").strip().casefold()
    return text if text in {"casa", "fora"} else "indiferent"


def _linkage_relation(left: Any, right: Any) -> str | None:
    left_side = _linkage_side(left)
    right_side = _linkage_side(right)
    if "indiferent" in {left_side, right_side}:
        return None
    return "same" if left_side == right_side else "opposite"


def _opposite_number(number: Any) -> int | None:
    helper = getattr(linkage_domain, "opposite_number", None)
    if callable(helper):
        try:
            value = helper(number)
            return int(value) if value is not None else None
        except Exception:
            pass
    return {1: 5, 5: 1, 6: 2, 2: 6, 7: 3, 3: 7, 8: 4, 4: 8}.get(int(number or 0))


def _violates_relation(left_number: int, right_number: int, relation: str) -> bool:
    if relation == "same":
        return int(left_number) != int(right_number)
    if relation == "opposite":
        return _opposite_number(left_number) != int(right_number)
    return False


def _load_cp_model() -> Any | None:
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return None
    return cp_model


def _pattern_payload(pattern: HubPattern) -> dict[str, Any]:
    payload = asdict(pattern)
    payload["assignments"] = [asdict(item) for item in pattern.assignments]
    payload["competition_number_counts"] = {
        key: {str(number): count for number, count in counts.items()}
        for key, counts in pattern.competition_number_counts.items()
    }
    return payload


def _slot_domain_key(group_ids: tuple[str, ...]) -> str:
    return "groups|" + "|".join(group_ids)


def _pattern_signature(pattern: HubPattern) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((assignment.team_id, int(assignment.number)) for assignment in pattern.assignments))


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in str(value))


__all__ = [
    "competition_number_capacity",
    "generate_initial_patterns",
    "generate_variants_for_hubs",
    "hubs_touching_competitions",
    "hubs_touching_slot_domains",
    "overloaded_competitions_from_patterns",
    "overloaded_slot_domains_from_patterns",
    "pattern_slot_domain_number_counts",
    "patterns_payload",
    "slot_domain_number_capacity",
]
