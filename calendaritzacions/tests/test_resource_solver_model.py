import unittest

from calendaritzacions.domain.phases import PRIMERA_FASE
from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.model import build_solver_model, solve_context
from calendaritzacions.engine.variants.resource_solver.types import (
    BaseResource,
    Candidate,
    CapacityEstimate,
    GroupSpec,
    SolverContext,
    TeamRecord,
)


def make_team(index, entity=None):
    return TeamRecord(
        team_id=f"T{index}",
        name=f"Team {index}",
        entity=entity or f"Club {index}",
        league_name="League",
        venue="P",
        day="D",
        time="18:00",
    )


def make_candidate(team_id, group_id, number, resource="R"):
    return Candidate(
        candidate_id=f"{team_id}_{group_id}_{number}",
        team_id=team_id,
        group_id=group_id,
        number=number,
        seed_request_original="",
        potential_home_rounds=(1,) if number == 1 else (),
        opponent_number_by_round={1: 2},
        potential_resources=(resource,) if number == 1 else (),
    )


def make_context(teams, groups, numbers, config=None, capacity=10):
    candidates = [
        make_candidate(team.team_id, group.group_id, number)
        for team in teams
        for group in groups
        for number in numbers
    ]
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


class ResourceSolverModelTests(unittest.TestCase):
    def test_build_model_uses_fallback_cleanly_without_ortools(self):
        teams = [make_team(1), make_team(2)]
        groups = [GroupSpec("G1", 2, 2, 2, "primera_fase", numbers=(1, 2))]
        context = make_context(teams, groups, (1, 2))

        built = build_solver_model(context, use_ortools=False)

        self.assertEqual(built.backend, "fallback")
        self.assertEqual(built.summary["num_teams"], 2)
        self.assertEqual(built.summary["num_candidates"], 4)

    def test_simple_complete_group_solves(self):
        teams = [make_team(1), make_team(2)]
        groups = [GroupSpec("G1", 2, 2, 2, "primera_fase", numbers=(1, 2))]

        result = solve_context(make_context(teams, groups, (1, 2)), use_ortools=False)

        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual({assignment.number for assignment in result.assignments}, {1, 2})

    def test_two_groups_of_seven_are_balanced(self):
        teams = [make_team(index) for index in range(14)]
        groups = [
            GroupSpec("G1", 7, 7, 7, "primera_fase"),
            GroupSpec("G2", 7, 7, 7, "primera_fase"),
        ]
        context = make_context(teams, groups, tuple(range(1, 9)))

        result = solve_context(context, use_ortools=False)

        self.assertEqual(result.status, "OPTIMAL")
        counts = {group.group_id: 0 for group in groups}
        for assignment in result.assignments:
            counts[assignment.group_id] += 1
        self.assertEqual(set(counts.values()), {7})

    def test_exceptional_bucket_allows_unbalanced_split_across_two_templates(self):
        teams = [make_team(index) for index in range(9)]
        groups = [
            GroupSpec("G1A", 0, 8, 0, "primera_fase", size_bucket_id="G1", size_bucket_target=9),
            GroupSpec("G1B", 0, 8, 0, "primera_fase", size_bucket_id="G1", size_bucket_target=9),
        ]
        context = make_context(teams, groups, tuple(range(1, 9)))

        result = solve_context(context, use_ortools=False)

        self.assertEqual(result.status, "OPTIMAL")
        counts = {group.group_id: 0 for group in groups}
        for assignment in result.assignments:
            counts[assignment.group_id] += 1
        self.assertEqual(sum(counts.values()), 9)
        self.assertTrue(all(count <= 8 for count in counts.values()))

    def test_hard_capacity_impossible_is_infeasible_when_match_is_real(self):
        teams = [make_team(1), make_team(2)]
        groups = [GroupSpec("G1", 2, 2, 2, "primera_fase", numbers=(1, 2))]
        config = ResourceSolverConfig(capacity_mode="hard")
        context = make_context(teams, groups, (1, 2), config=config, capacity=0)

        result = solve_context(context, use_ortools=False)

        self.assertEqual(result.status, "INFEASIBLE")

    def test_soft_capacity_returns_minimal_excess(self):
        teams = [make_team(1), make_team(2)]
        groups = [GroupSpec("G1", 2, 2, 2, "primera_fase", numbers=(1, 2))]
        config = ResourceSolverConfig(capacity_mode="soft")
        context = make_context(teams, groups, (1, 2), config=config, capacity=0)

        result = solve_context(context, use_ortools=False)

        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(sum(result.resource_excess.values()), 1)


if __name__ == "__main__":
    unittest.main()
