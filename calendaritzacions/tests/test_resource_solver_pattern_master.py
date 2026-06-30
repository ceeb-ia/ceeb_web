import unittest

from calendaritzacions.domain.phases import PRIMERA_FASE
from calendaritzacions.engine.config import EngineConfig
from calendaritzacions.engine.variants.resource_solver.config import (
    ResourceSolverConfig,
    coerce_resource_solver_config,
)
from calendaritzacions.engine.variants.resource_solver.pattern_master.microhubs import build_microhubs
from calendaritzacions.engine.variants.resource_solver.pattern_master.incompatibilities import build_pattern_conflicts
from calendaritzacions.engine.variants.resource_solver.pattern_master.incompatibilities import compatibility_payload
from calendaritzacions.engine.variants.resource_solver.pattern_master.master_model import solve_master_selection
from calendaritzacions.engine.variants.resource_solver.pattern_master.materialization import (
    materialize_master_selection,
    materialize_patterns,
    selected_patterns_from_ids,
)
from calendaritzacions.engine.variants.resource_solver.pattern_master.patterns import (
    competition_number_capacity,
    generate_initial_patterns,
    generate_variants_for_hubs,
    hubs_touching_competitions,
    hubs_touching_slot_domains,
    overloaded_competitions_from_patterns,
    overloaded_slot_domains_from_patterns,
    pattern_slot_domain_number_counts,
    slot_domain_number_capacity,
    _calendar_mismatches_for_assignment_pair,
    _local_pattern_limit,
    _local_solve_time_limit,
)
from calendaritzacions.engine.variants.resource_solver.pattern_master.types import HubPattern, MicroHub, PatternAssignment
from calendaritzacions.engine.variants.resource_solver.types import (
    BaseResource,
    Candidate,
    CapacityEstimate,
    GroupSpec,
    SolverContext,
    TeamRecord,
)


class ResourceSolverPatternMasterTests(unittest.TestCase):
    def test_microhubs_do_not_connect_by_competition(self):
        context = _context_same_competition_different_resources()

        hubs = build_microhubs(context)

        self.assertEqual(len(hubs), 2)
        self.assertEqual([hub.team_ids for hub in hubs], [("T1", "T2"), ("T3", "T4")])
        self.assertEqual(len({hub.competition_keys for hub in hubs}), 1)

    def test_linkage_connects_across_resources(self):
        context = _context_same_competition_different_resources(linked=True)

        hubs = build_microhubs(context)

        self.assertEqual(len(hubs), 1)
        self.assertEqual(hubs[0].team_ids, ("T1", "T2", "T3", "T4"))

    def test_pattern_variants_are_skipped_when_competition_signature_is_compatible(self):
        context = _context_same_competition_different_resources()
        hubs = build_microhubs(context)
        patterns = generate_initial_patterns(context, hubs)
        overloaded = overloaded_competitions_from_patterns(context, patterns)
        variant_hubs = hubs_touching_competitions(hubs, overloaded)
        variants = generate_variants_for_hubs(context, variant_hubs, existing_patterns=patterns)

        self.assertEqual(overloaded, ())
        self.assertEqual(variant_hubs, ())
        self.assertEqual(variants, ())

    def test_pattern_master_engine_defaults_to_input_linkage(self):
        config = coerce_resource_solver_config(EngineConfig(name="resource_solver_pattern_master"))

        self.assertEqual(config.linkage_mode, "input")

    def test_master_selection_materializes_real_assignments(self):
        context = _context_same_competition_different_resources()
        hubs = build_microhubs(context)
        patterns = generate_initial_patterns(context, hubs)
        conflicts = build_pattern_conflicts(context, patterns)

        selection = solve_master_selection(context, patterns, conflicts)
        selected_patterns = selected_patterns_from_ids(patterns, selection.selected_pattern_ids)
        result, _raw, _built = materialize_patterns(context, selected_patterns)

        self.assertIn(selection.status, {"OPTIMAL", "FEASIBLE"})
        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertEqual(len(result.assignments), len(context.teams))

    def test_large_master_can_skip_inline_materialization(self):
        context = _context_same_competition_different_resources()
        context = SolverContext(
            **{
                **context.__dict__,
                "config": ResourceSolverConfig(
                    competition_grouping="league",
                    pattern_master_inline_materialization_max_terms=1,
                ),
            }
        )
        hubs = build_microhubs(context)
        patterns = generate_initial_patterns(context, hubs)
        conflicts = build_pattern_conflicts(context, patterns)

        selection = solve_master_selection(context, patterns, conflicts)
        selected_patterns = selected_patterns_from_ids(patterns, selection.selected_pattern_ids)
        result, _raw, _built = materialize_master_selection(context, selected_patterns, selection)

        self.assertIn(selection.status, {"OPTIMAL", "FEASIBLE"})
        self.assertEqual(selection.materialized_assignments, ())
        self.assertTrue(any("inline materialization skipped" in log for log in selection.logs))
        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertEqual(len(result.assignments), len(context.teams))

    def test_master_respects_slot_domain_capacity_before_materialization(self):
        context = _context_with_level_domains_needing_variants()
        hubs = build_microhubs(context)
        patterns = generate_initial_patterns(context, hubs)
        overloaded_competitions = overloaded_competitions_from_patterns(context, patterns)
        overloaded_domains = overloaded_slot_domains_from_patterns(context, patterns)
        variant_hubs = hubs_touching_slot_domains(context, hubs, overloaded_domains)
        variants = generate_variants_for_hubs(context, variant_hubs, existing_patterns=patterns)
        patterns = (*patterns, *variants)

        conflicts = build_pattern_conflicts(context, patterns)
        selection = solve_master_selection(context, patterns, conflicts)
        selected_patterns = selected_patterns_from_ids(patterns, selection.selected_pattern_ids)
        result, _raw, _built = materialize_patterns(context, selected_patterns)

        self.assertEqual(overloaded_competitions, ())
        self.assertEqual(set(overloaded_domains), {"groups|G_A", "groups|G_B"})
        self.assertIn(selection.status, {"OPTIMAL", "FEASIBLE"})
        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertEqual(len(result.assignments), len(context.teams))
        self.assertTrue(_slot_domain_capacity_ok(context, selected_patterns))

    def test_capacity_pressure_is_aggregated_not_pairwise_pruned(self):
        context = _context_with_level_domains_needing_variants()
        hubs = build_microhubs(context)
        patterns = generate_initial_patterns(context, hubs)
        conflicts = build_pattern_conflicts(context, patterns)
        payload = compatibility_payload(context, patterns, conflicts)

        self.assertEqual(conflicts, ())
        self.assertEqual(payload["conflict_count"], 0)
        self.assertTrue(
            any(row.get("type") == "competition_number_capacity" for row in payload["aggregate_constraints"])
        )
        self.assertTrue(
            any(row.get("type") == "slot_domain_number_capacity" for row in payload["aggregate_constraints"])
        )

    def test_local_resource_pressure_does_not_make_linkage_pattern_expensive(self):
        context = _context_linkage_with_local_resource_pressure()
        hubs = build_microhubs(context)
        patterns = generate_initial_patterns(context, hubs)
        variants = generate_variants_for_hubs(context, hubs, existing_patterns=patterns)
        rows = (*patterns, *variants)

        link_preserving = next(pattern for pattern in rows if pattern.cost_breakdown["linkage"] == 0)
        link_breaking = next(pattern for pattern in rows if pattern.cost_breakdown["linkage"] > 0)

        self.assertGreater(link_preserving.cost_breakdown["resource_pressure"], 0)
        self.assertEqual(
            link_preserving.cost,
            sum(
                value
                for key, value in link_preserving.cost_breakdown.items()
                if key != "resource_pressure"
            ),
        )
        self.assertLess(link_preserving.cost, link_breaking.cost)

    def test_local_pattern_limit_scales_with_hub_size_and_linkage(self):
        context = _context_same_competition_different_resources(linked=True)
        hubs = build_microhubs(context)

        self.assertGreater(_local_pattern_limit(context, hubs[0]), 12)

    def test_local_solve_time_limit_scales_after_eight_teams(self):
        context = _context_same_competition_different_resources()

        self.assertEqual(
            _local_solve_time_limit(context, MicroHub("H8", tuple(str(index) for index in range(8)))),
            3.0,
        )
        self.assertEqual(
            _local_solve_time_limit(context, MicroHub("H10", tuple(str(index) for index in range(10)))),
            7.0,
        )

    def test_calendar_mismatch_ignores_rounds_where_either_team_rests(self):
        context = _context_mixed_group_sizes()

        self.assertEqual(
            _calendar_mismatches_for_assignment_pair(context, "G4", 1, "G2", 1, "same"),
            0,
        )
        self.assertEqual(
            _calendar_mismatches_for_assignment_pair(context, "G2", 1, "G2", 2, "same"),
            1,
        )
        self.assertEqual(
            _calendar_mismatches_for_assignment_pair(context, "G2", 1, "G2", 2, "opposite"),
            0,
        )

    def test_master_resource_excess_uses_materialized_group_candidate(self):
        context = _context_materialization_avoids_phantom_resource_excess()
        competition_key = next(iter(competition_number_capacity(context)))
        pattern = HubPattern(
            pattern_id="H1_base",
            hub_id="H1",
            assignments=(
                PatternAssignment("T1", 1),
                PatternAssignment("T2", 1),
            ),
            cost=0,
            resource_usage={"Pista B|D|10:00|J1": 2},
            competition_number_counts={competition_key: {1: 2}},
        )

        selection = solve_master_selection(context, (pattern,), ())

        self.assertIn(selection.status, {"OPTIMAL", "FEASIBLE"})
        self.assertEqual(selection.selected_pattern_ids, ("H1_base",))
        self.assertEqual(selection.objective_value, 0.0)


def _context_same_competition_different_resources(linked=False) -> SolverContext:
    groups = (
        GroupSpec("G1", 2, 2, 2, "primera_fase", numbers=(1, 2)),
        GroupSpec("G2", 2, 2, 2, "primera_fase", numbers=(1, 2)),
    )
    teams = (
        TeamRecord("T1", "Team 1", "Club 1", "League A", venue="Pista", day="D", time="10:00", linkage_group="L1" if linked else "", linkage_side="casa" if linked else ""),
        TeamRecord("T2", "Team 2", "Club 2", "League A", venue="Pista", day="D", time="10:00"),
        TeamRecord("T3", "Team 3", "Club 3", "League A", venue="Pista", day="D", time="11:00", linkage_group="L1" if linked else "", linkage_side="fora" if linked else ""),
        TeamRecord("T4", "Team 4", "Club 4", "League A", venue="Pista", day="D", time="11:00"),
    )
    resources = {
        "Pista|D|10:00": BaseResource("Pista|D|10:00", "Pista", "D", "10:00"),
        "Pista|D|11:00": BaseResource("Pista|D|11:00", "Pista", "D", "11:00"),
    }
    candidates = tuple(
        Candidate(
            candidate_id=f"{team.team_id}-{group.group_id}-{number}",
            team_id=team.team_id,
            group_id=group.group_id,
            number=number,
            seed_request_original="",
            potential_home_rounds=(1,) if number == 1 else (),
            opponent_number_by_round={1: 2},
            potential_resources=(f"{team.venue}|D|{team.time}|J1",) if number == 1 else (),
        )
        for team in teams
        for group in groups
        for number in group.numbers
    )
    return SolverContext(
        teams=teams,
        phase=PRIMERA_FASE,
        phase_name="primera_fase",
        base_resources=resources,
        capacities={
            key: CapacityEstimate(key, 1, "test", 2)
            for key in resources
        },
        pressure=(),
        groups=groups,
        candidates=candidates,
        config=ResourceSolverConfig(competition_grouping="league"),
    )


def _context_materialization_avoids_phantom_resource_excess() -> SolverContext:
    groups = (
        GroupSpec("G1", 1, 1, 1, "primera_fase", numbers=(1,)),
        GroupSpec("G2", 1, 1, 1, "primera_fase", numbers=(1,)),
    )
    teams = (
        TeamRecord("T1", "Team 1", "Club 1", "League A", venue="Pista", day="D", time="10:00"),
        TeamRecord("T2", "Team 2", "Club 2", "League A", venue="Pista", day="D", time="10:00"),
    )
    resources = {
        "Pista A|D|10:00": BaseResource("Pista A|D|10:00", "Pista A", "D", "10:00"),
        "Pista B|D|10:00": BaseResource("Pista B|D|10:00", "Pista B", "D", "10:00"),
    }
    candidates = tuple(
        Candidate(
            candidate_id=f"{team.team_id}-{group.group_id}-1",
            team_id=team.team_id,
            group_id=group.group_id,
            number=1,
            seed_request_original="",
            potential_home_rounds=(1,),
            opponent_number_by_round={},
            potential_resources=(f"Pista {'A' if group.group_id == 'G1' else 'B'}|D|10:00|J1",),
        )
        for team in teams
        for group in groups
    )
    return SolverContext(
        teams=teams,
        phase=PRIMERA_FASE,
        phase_name="primera_fase",
        base_resources=resources,
        capacities={
            "Pista A|D|10:00": CapacityEstimate("Pista A|D|10:00", 1, "test", 1),
            "Pista B|D|10:00": CapacityEstimate("Pista B|D|10:00", 1, "test", 1),
        },
        pressure=(),
        groups=groups,
        candidates=candidates,
        config=ResourceSolverConfig(competition_grouping="league"),
    )


def _context_linkage_with_local_resource_pressure() -> SolverContext:
    groups = (
        GroupSpec("G1", 1, 1, 1, "primera_fase", numbers=(1, 2)),
        GroupSpec("G2", 1, 1, 1, "primera_fase", numbers=(1, 2)),
    )
    teams = (
        TeamRecord(
            "T1",
            "Team 1",
            "Club 1",
            "League A",
            venue="Pista",
            day="D",
            time="10:00",
            seed_request_original=1,
            linkage_group="L1",
            linkage_side="Casa",
        ),
        TeamRecord(
            "T2",
            "Team 2",
            "Club 2",
            "League A",
            venue="Pista",
            day="D",
            time="10:00",
            seed_request_original=1,
            linkage_group="L1",
            linkage_side="Casa",
        ),
    )
    resources = {
        "Pista|D|10:00": BaseResource("Pista|D|10:00", "Pista", "D", "10:00"),
    }
    candidates = (
        Candidate(
            candidate_id="T1-G1-1",
            team_id="T1",
            group_id="G1",
            number=1,
            seed_request_original=1,
            potential_home_rounds=(1,),
            opponent_number_by_round={},
            potential_resources=("Pista|D|10:00|J1",),
        ),
        Candidate(
            candidate_id="T1-G1-2",
            team_id="T1",
            group_id="G1",
            number=2,
            seed_request_original=1,
            potential_home_rounds=(),
            opponent_number_by_round={},
            potential_resources=(),
        ),
        Candidate(
            candidate_id="T2-G2-1",
            team_id="T2",
            group_id="G2",
            number=1,
            seed_request_original=1,
            potential_home_rounds=(1,),
            opponent_number_by_round={},
            potential_resources=("Pista|D|10:00|J1",),
        ),
        Candidate(
            candidate_id="T2-G2-2",
            team_id="T2",
            group_id="G2",
            number=2,
            seed_request_original=1,
            potential_home_rounds=(),
            opponent_number_by_round={},
            potential_resources=(),
        ),
    )
    return SolverContext(
        teams=teams,
        phase=PRIMERA_FASE,
        phase_name="primera_fase",
        base_resources=resources,
        capacities={"Pista|D|10:00": CapacityEstimate("Pista|D|10:00", 1, "test", 1)},
        pressure=(),
        groups=groups,
        candidates=candidates,
        config=ResourceSolverConfig(competition_grouping="league"),
    )


def _context_mixed_group_sizes() -> SolverContext:
    groups = (
        GroupSpec("G2", 2, 2, 2, "primera_fase", numbers=(1, 2)),
        GroupSpec("G4", 4, 4, 4, "primera_fase", numbers=(1, 2, 3, 4)),
    )
    return SolverContext(
        teams=(),
        phase=PRIMERA_FASE,
        phase_name="primera_fase",
        base_resources={},
        capacities={},
        pressure=(),
        groups=groups,
        candidates=(),
        config=ResourceSolverConfig(competition_grouping="league"),
    )


def _context_with_level_domains_needing_variants() -> SolverContext:
    groups = (
        GroupSpec("G_A", 2, 2, 2, "primera_fase", numbers=(1, 2)),
        GroupSpec("G_B", 2, 2, 2, "primera_fase", numbers=(1, 2)),
    )
    teams = (
        TeamRecord("T1", "Team 1", "Club 1", "League A", level="A", venue="Pista", day="D", time="10:00", seed_request_original=1),
        TeamRecord("T2", "Team 2", "Club 2", "League A", level="A", venue="Pista", day="D", time="11:00", seed_request_original=1),
        TeamRecord("T3", "Team 3", "Club 3", "League A", level="B", venue="Pista", day="D", time="12:00", seed_request_original=2),
        TeamRecord("T4", "Team 4", "Club 4", "League A", level="B", venue="Pista", day="D", time="13:00", seed_request_original=2),
    )
    resources = {
        f"Pista|D|{team.time}": BaseResource(f"Pista|D|{team.time}", "Pista", "D", team.time)
        for team in teams
    }
    group_by_team = {"T1": groups[0], "T2": groups[0], "T3": groups[1], "T4": groups[1]}
    candidates = tuple(
        Candidate(
            candidate_id=f"{team.team_id}-{group_by_team[team.team_id].group_id}-{number}",
            team_id=team.team_id,
            group_id=group_by_team[team.team_id].group_id,
            number=number,
            seed_request_original=team.seed_request_original,
            potential_home_rounds=(1,) if number == 1 else (),
            opponent_number_by_round={1: 2},
            potential_resources=(f"{team.venue}|D|{team.time}|J1",),
        )
        for team in teams
        for number in group_by_team[team.team_id].numbers
    )
    return SolverContext(
        teams=teams,
        phase=PRIMERA_FASE,
        phase_name="primera_fase",
        base_resources=resources,
        capacities={
            key: CapacityEstimate(key, 1, "test", 1)
            for key in resources
        },
        pressure=(),
        groups=groups,
        candidates=candidates,
        config=ResourceSolverConfig(competition_grouping="league"),
    )


def _slot_domain_capacity_ok(context: SolverContext, patterns) -> bool:
    capacity = slot_domain_number_capacity(context)
    counts = {}
    for pattern in patterns:
        for domain_key, number_counts in pattern_slot_domain_number_counts(context, pattern).items():
            for number, count in number_counts.items():
                key = (domain_key, int(number))
                counts[key] = counts.get(key, 0) + int(count)
                if counts[key] > int(capacity.get(domain_key, {}).get(int(number), 0)):
                    return False
    return True


if __name__ == "__main__":
    unittest.main()
