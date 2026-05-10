import unittest
from types import SimpleNamespace

from calendaritzacions.domain.phases import PRIMERA_FASE
from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.solution import build_solution
from calendaritzacions.engine.variants.resource_solver.types import (
    Assignment,
    BaseResource,
    Candidate,
    CapacityEstimate,
    GroupSpec,
    SolverContext,
    TeamRecord,
)


class ResourceSolverSolutionTests(unittest.TestCase):
    def test_build_solution_excludes_rests_from_resource_usage(self):
        context = _context()
        raw_result = SimpleNamespace(
            status="OPTIMAL",
            objective_value=0,
            best_bound=0,
            wall_time=0.1,
            assignments=(
                Assignment("T1", "G1", 1),
                Assignment("T2", "G1", 2),
            ),
        )

        result = build_solution(raw_result, context)

        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(len(result.assignments), 2)
        self.assertEqual(
            [(match.round_index, match.home_team_id, match.away_team_id) for match in result.real_matches],
            [(1, "T1", "T2")],
        )
        self.assertEqual(len(result.resource_usage), 1)
        self.assertEqual(result.resource_usage[0].resource_id, "Court|Friday|18:00|J1")
        self.assertEqual(result.resource_usage[0].locals_count, 1)

        summary = result.group_summary[0]
        self.assertEqual(summary.empty_numbers, (3, 4, 5, 6, 7, 8))
        self.assertIn(3, summary.rests_by_team["T1"])
        self.assertIn(2, summary.rests_by_team["T2"])
        self.assertIn(3, summary.rests_by_team["T2"])

    def test_entity_excess_is_computed_when_same_entity_shares_group(self):
        context = _context()
        raw_result = SimpleNamespace(
            status="OPTIMAL",
            assignments=(
                Assignment("T1", "G1", 1),
                Assignment("T2", "G1", 2),
            ),
        )

        result = build_solution(raw_result, context)

        self.assertEqual(result.entity_excess, {("Club", "G1"): 1})
        self.assertEqual(result.group_summary[0].entity_excess, {"Club": 1})


def _context() -> SolverContext:
    base_resource = BaseResource(
        resource_id="Court|Friday|18:00",
        venue="Court",
        day="Friday",
        hour_slot="18:00",
    )
    return SolverContext(
        teams=(
            TeamRecord("T1", "Team 1", "Club", "League", venue="Court", day="Friday", time="18:00"),
            TeamRecord("T2", "Team 2", "Club", "League", venue="Court", day="Friday", time="18:00"),
        ),
        phase=PRIMERA_FASE,
        phase_name="primera_fase",
        base_resources={base_resource.resource_id: base_resource},
        capacities={
            base_resource.resource_id: CapacityEstimate(
                base_resource_id=base_resource.resource_id,
                capacity=1,
                method="test",
                demand_count=2,
            )
        },
        pressure=(),
        groups=(
            GroupSpec(
                group_id="G1",
                min_size=2,
                max_size=8,
                target_size=2,
                phase_name="primera_fase",
            ),
        ),
        candidates=(
            Candidate(
                candidate_id="T1-G1-1",
                team_id="T1",
                group_id="G1",
                number=1,
                seed_request_original="",
                potential_home_rounds=(1, 3, 5, 7),
                opponent_number_by_round={1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8},
                potential_resources=(
                    base_resource.resource_id,
                    base_resource.resource_id,
                    base_resource.resource_id,
                    base_resource.resource_id,
                ),
            ),
            Candidate(
                candidate_id="T2-G1-2",
                team_id="T2",
                group_id="G1",
                number=2,
                seed_request_original="",
                potential_home_rounds=(2, 3, 7),
                opponent_number_by_round={1: 1, 2: 8, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7},
                potential_resources=(
                    base_resource.resource_id,
                    base_resource.resource_id,
                    base_resource.resource_id,
                ),
            ),
        ),
        config=ResourceSolverConfig(),
    )


if __name__ == "__main__":
    unittest.main()
