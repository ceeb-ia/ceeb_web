import unittest

from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.config import coerce_resource_solver_config
from calendaritzacions.engine.variants.resource_solver.types import GroupSpec, TeamRecord


class ResourceSolverContractsTests(unittest.TestCase):
    def test_config_defaults_match_mvp_decisions(self):
        config = ResourceSolverConfig()

        self.assertEqual(config.capacity_mode, "soft")
        self.assertEqual(config.empty_number_balance_mode, "hard")
        self.assertEqual(config.phase_name, "primera_fase")
        self.assertEqual(config.resource_excess_weight, 100_000)
        self.assertEqual(config.time_limit_seconds, 1800.0)
        self.assertEqual(config.num_search_workers, 2)
        self.assertEqual(config.max_memory_mb, 0)
        self.assertEqual(config.level_constraint_mode, "off")
        self.assertEqual(config.level_a_mismatch_weight, 1_000_000)
        self.assertEqual(config.level_band_mismatch_weight, 200_000)

    def test_coerces_level_constraint_mode_from_engine_config(self):
        from calendaritzacions.engine.config import EngineConfig

        config = coerce_resource_solver_config(
            EngineConfig(
                name="resource_solver",
                phase_name="segona_fase",
                resource_solver_level_constraint_mode="soft",
                resource_solver_linkage_mode="simulated",
            )
        )

        self.assertEqual(config.phase_name, "segona_fase")
        self.assertEqual(config.level_constraint_mode, "soft")
        self.assertEqual(config.linkage_mode, "simulated")

    def test_coerces_aggregate_level_constraint_mode_from_engine_config(self):
        from calendaritzacions.engine.config import EngineConfig

        config = coerce_resource_solver_config(
            EngineConfig(
                name="resource_solver",
                resource_solver_level_constraint_mode="aggregate",
            )
        )

        self.assertEqual(config.level_constraint_mode, "aggregate")

    def test_coerces_hard_level_constraint_mode_from_engine_config(self):
        from calendaritzacions.engine.config import EngineConfig

        config = coerce_resource_solver_config(
            EngineConfig(
                name="resource_solver",
                resource_solver_level_constraint_mode="hard",
            )
        )

        self.assertEqual(config.level_constraint_mode, "hard")

    def test_coerces_competition_grouping_from_engine_config(self):
        from calendaritzacions.engine.config import EngineConfig

        config = coerce_resource_solver_config(
            EngineConfig(
                name="resource_solver",
                resource_solver_competition_grouping="league",
            )
        )

        self.assertEqual(config.competition_grouping, "league")

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
