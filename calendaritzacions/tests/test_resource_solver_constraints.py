import importlib.util
import unittest
from types import SimpleNamespace

from calendaritzacions.domain.phases import PRIMERA_FASE
from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.constraints.level_band import normalize_level
from calendaritzacions.engine.variants.resource_solver.constraints.resource_capacity import (
    candidate_resource_by_round,
)
from calendaritzacions.engine.variants.resource_solver.model import build_solver_model, solve_context
from calendaritzacions.engine.variants.resource_solver.types import (
    BaseResource,
    Candidate,
    CapacityEstimate,
    GroupSpec,
    SolverContext,
    TeamRecord,
)


def _team(team_id, entity=None):
    return TeamRecord(
        team_id=team_id,
        name=team_id,
        entity=entity or team_id,
        league_name="L",
        venue="P",
        day="D",
        time="18:00",
    )


def _level_team(team_id, level):
    return TeamRecord(
        team_id=team_id,
        name=team_id,
        entity=team_id,
        league_name="L",
        level=level,
        venue="P",
        day="D",
        time="18:00",
    )


def _candidate(team_id, group_id, number, resource="R"):
    return Candidate(
        candidate_id=f"{team_id}_{group_id}_{number}",
        team_id=team_id,
        group_id=group_id,
        number=number,
        seed_request_original="",
        potential_home_rounds=(1,),
        opponent_number_by_round={1: 2 if number == 1 else 1},
        potential_resources=(resource,),
    )


def _context(teams, groups, candidates, config=None, capacity=10):
    return SolverContext(
        teams=tuple(teams),
        phase=PRIMERA_FASE,
        phase_name="primera_fase",
        base_resources={"R": BaseResource("R", "P", "D", "18:00")},
        capacities={"R": CapacityEstimate("R", capacity, "fixture", len(teams))},
        pressure=(),
        groups=tuple(groups),
        candidates=tuple(candidates),
        config=config or ResourceSolverConfig(),
    )


class ResourceSolverConstraintTests(unittest.TestCase):
    def test_candidate_resource_by_round_allows_single_base_resource(self):
        candidate = _candidate("T1", "G1", 1)

        self.assertEqual(candidate_resource_by_round(candidate), {1: "R"})

    def test_one_assignment_per_team_and_unique_group_number(self):
        teams = [_team("T1"), _team("T2")]
        group = GroupSpec("G1", 2, 2, 2, "primera_fase")
        candidates = [
            _candidate("T1", "G1", 1),
            _candidate("T1", "G1", 2),
            _candidate("T2", "G1", 1),
            _candidate("T2", "G1", 2),
        ]

        result = solve_context(_context(teams, [group], candidates), use_ortools=False)

        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(len(result.assignments), 2)
        self.assertEqual({a.number for a in result.assignments}, {1, 2})

    def test_entity_separation_is_avoided_when_feasible(self):
        teams = [_team("A1", "ClubA"), _team("A2", "ClubA"), _team("B1", "ClubB"), _team("B2", "ClubB")]
        groups = [
            GroupSpec("G1", 2, 2, 2, "primera_fase"),
            GroupSpec("G2", 2, 2, 2, "primera_fase"),
        ]
        candidates = [
            _candidate(team.team_id, group.group_id, number)
            for team in teams
            for group in groups
            for number in (1, 2)
        ]

        result = solve_context(_context(teams, groups, candidates), use_ortools=False)

        self.assertEqual(result.status, "OPTIMAL")
        by_group = {}
        for assignment in result.assignments:
            by_group.setdefault(assignment.group_id, []).append(
                next(team.entity for team in teams if team.team_id == assignment.team_id)
            )
        self.assertTrue(all(len(entities) == len(set(entities)) for entities in by_group.values()))

    def test_entity_separation_is_soft_when_global_targets_force_collision(self):
        teams = [_team("A1", "ClubA"), _team("A2", "ClubA"), _team("B1", "ClubB"), _team("B2", "ClubB")]
        groups = [
            GroupSpec("G1", 2, 2, 2, "primera_fase", numbers=(1, 2)),
            GroupSpec("G2", 2, 2, 2, "primera_fase", numbers=(1, 2)),
        ]
        candidates = [
            *[
                _candidate(team_id, group_id, number)
                for team_id in ("A1", "A2")
                for group_id in ("G1", "G2")
                for number in (1, 2)
            ],
            *[_candidate(team_id, "G2", number) for team_id in ("B1", "B2") for number in (1, 2)],
        ]

        result = solve_context(_context(teams, groups, candidates))

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertEqual(len(result.assignments), 4)
        self.assertGreaterEqual(sum(result.entity_excess.values()), 1)

    def test_entity_separation_relaxes_only_inevitable_entity(self):
        teams = [_team("A1", "ClubA"), _team("A2", "ClubA"), _team("A3", "ClubA"), _team("B1", "ClubB")]
        groups = [
            GroupSpec("G1", 2, 2, 2, "primera_fase"),
            GroupSpec("G2", 2, 2, 2, "primera_fase"),
        ]
        candidates = [
            _candidate(team.team_id, group.group_id, number)
            for team in teams
            for group in groups
            for number in (1, 2)
        ]

        result = solve_context(_context(teams, groups, candidates), use_ortools=False)

        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(sum(result.entity_excess.values()), 1)
        self.assertTrue(all(key[0] == "ClubA" for key in result.entity_excess))

    def test_entity_separation_relaxes_when_entity_teams_share_only_one_accessible_group(self):
        teams = [
            _team("A1", "ClubA"),
            _team("A2", "ClubA"),
            _team("B1", "ClubB"),
            _team("C1", "ClubC"),
        ]
        groups = [
            GroupSpec("G_B", 2, 2, 2, "primera_fase", numbers=(1, 2)),
            GroupSpec("G_C", 2, 2, 2, "primera_fase", numbers=(1, 2)),
        ]
        candidates = [
            *[_candidate(team_id, "G_C", number) for team_id in ("A1", "A2") for number in (1, 2)],
            *[
                _candidate(team_id, group_id, number)
                for team_id in ("B1", "C1")
                for group_id in ("G_B", "G_C")
                for number in (1, 2)
            ],
        ]

        result = solve_context(_context(teams, groups, candidates), use_ortools=False)

        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(result.entity_excess, {("ClubA", "G_C"): 1})

    def test_capacity_ignores_rest_against_empty_number(self):
        teams = [_team("T1")]
        group = GroupSpec("G1", 1, 1, 1, "primera_fase")
        candidate = _candidate("T1", "G1", 1)
        config = ResourceSolverConfig(capacity_mode="hard")

        result = solve_context(_context(teams, [group], [candidate], config=config, capacity=0), use_ortools=False)

        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(result.resource_excess, {})

    def test_level_band_normalizes_prefixed_input_levels(self):
        self.assertEqual(normalize_level("Nivell A"), "A")
        self.assertEqual(normalize_level("Nivell B"), "B")
        self.assertEqual(normalize_level("Nivell C"), "B/C")
        self.assertEqual(normalize_level("Nivell D"), "B/C")
        self.assertEqual(normalize_level("Nivell E"), "C")

    def test_level_band_fallback_prefers_a_teams_together(self):
        teams = [_level_team("A1", "A"), _level_team("A2", "A"), _level_team("B1", "B")]
        groups = [
            GroupSpec("G1", 1, 2, 2, "primera_fase", numbers=(1, 2)),
            GroupSpec("G2", 1, 2, 1, "primera_fase", numbers=(1, 2)),
        ]
        candidates = [
            _candidate(team.team_id, group.group_id, number)
            for team in teams
            for group in groups
            for number in group.numbers
        ]
        config = SimpleNamespace(
            level_constraint_mode="soft",
            level_a_mismatch_weight=1000,
            level_band_mismatch_weight=100,
        )

        result = solve_context(_context(teams, groups, candidates, config=config), use_ortools=False)

        self.assertEqual(result.status, "OPTIMAL")
        by_group = {}
        for assignment in result.assignments:
            by_group.setdefault(assignment.group_id, set()).add(assignment.team_id)
        self.assertIn({"A1", "A2"}, by_group.values())
        self.assertEqual(result.objective_value, 0.0)

    def test_level_band_fallback_treats_blank_as_b_c_compatible_band(self):
        teams = [_level_team("B1", "B"), _level_team("U1", ""), _level_team("C1", "E")]
        groups = [
            GroupSpec("G1", 1, 2, 2, "primera_fase", numbers=(1, 2)),
            GroupSpec("G2", 1, 2, 1, "primera_fase", numbers=(1, 2)),
        ]
        candidates = [
            _candidate(team.team_id, group.group_id, number)
            for team in teams
            for group in groups
            for number in group.numbers
        ]
        config = SimpleNamespace(
            level_constraint_mode="soft",
            level_a_mismatch_weight=1000,
            level_band_mismatch_weight=100,
        )

        result = solve_context(_context(teams, groups, candidates, config=config), use_ortools=False)

        self.assertEqual(result.status, "OPTIMAL")
        by_group = {}
        for assignment in result.assignments:
            by_group.setdefault(assignment.group_id, set()).add(assignment.team_id)
        self.assertIn({"B1", "U1"}, by_group.values())
        self.assertEqual(result.objective_value, 0.0)

    def test_aggregate_level_band_fallback_penalizes_group_presence_once(self):
        teams = [_level_team("A1", "A"), _level_team("A2", "A"), _level_team("B1", "B")]
        groups = [GroupSpec("G1", 1, 3, 3, "primera_fase", numbers=(1, 2, 3))]
        candidates = [
            _candidate(team.team_id, "G1", number)
            for team in teams
            for number in groups[0].numbers
        ]
        config = SimpleNamespace(
            level_constraint_mode="aggregate",
            level_a_mismatch_weight=1000,
            level_band_mismatch_weight=100,
        )

        result = solve_context(_context(teams, groups, candidates, config=config), use_ortools=False)

        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(result.objective_value, 1000.0)
        self.assertEqual(
            result.level_band_violations,
            {("__aggregate_a_non_a__", "G1", "A"): "level_a_mismatch"},
        )

    @unittest.skipUnless(importlib.util.find_spec("ortools") is not None, "ortools not installed")
    def test_aggregate_level_band_builds_fewer_implications_than_pairwise(self):
        teams = [
            *[_level_team(f"A{index}", "A") for index in range(1, 7)],
            *[_level_team(f"B{index}", "B") for index in range(1, 7)],
            *[_level_team(f"C{index}", "E") for index in range(1, 7)],
        ]
        groups = [GroupSpec("G1", 1, 18, 18, "primera_fase", numbers=tuple(range(1, 19)))]
        candidates = [
            _candidate(team.team_id, "G1", number)
            for team in teams
            for number in groups[0].numbers
        ]
        pairwise = build_solver_model(
            _context(
                teams,
                groups,
                candidates,
                config=SimpleNamespace(
                    level_constraint_mode="soft",
                    level_a_mismatch_weight=1000,
                    level_band_mismatch_weight=100,
                ),
            )
        )
        aggregate = build_solver_model(
            _context(
                teams,
                groups,
                candidates,
                config=SimpleNamespace(
                    level_constraint_mode="aggregate",
                    level_a_mismatch_weight=1000,
                    level_band_mismatch_weight=100,
                ),
            )
        )

        self.assertGreater(pairwise.summary["constraints"].get("level_band_violation_implication", 0), 0)
        self.assertEqual(aggregate.summary["constraints"].get("level_band_violation_implication", 0), 0)
        self.assertLess(
            aggregate.summary["constraints"].get("aggregate_level_presence", 0)
            + aggregate.summary["constraints"].get("aggregate_level_band_violation", 0),
            pairwise.summary["constraints"]["level_band_violation_implication"],
        )


if __name__ == "__main__":
    unittest.main()
