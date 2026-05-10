import unittest

from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.types import GroupSpec, TeamRecord


class ResourceSolverContractsTests(unittest.TestCase):
    def test_config_defaults_match_mvp_decisions(self):
        config = ResourceSolverConfig()

        self.assertEqual(config.capacity_mode, "soft")
        self.assertEqual(config.empty_number_balance_mode, "hard")
        self.assertEqual(config.phase_name, "primera_fase")
        self.assertEqual(config.resource_excess_weight, 100_000)

    def test_team_and_group_records_are_instantiable(self):
        team = TeamRecord(
            team_id="T1",
            name="Team 1",
            entity="Club",
            league_name="League",
        )
        group = GroupSpec(
            group_id="G1",
            min_size=7,
            max_size=7,
            target_size=7,
            phase_name="primera_fase",
        )

        self.assertEqual(team.team_id, "T1")
        self.assertEqual(group.numbers, (1, 2, 3, 4, 5, 6, 7, 8))


if __name__ == "__main__":
    unittest.main()
