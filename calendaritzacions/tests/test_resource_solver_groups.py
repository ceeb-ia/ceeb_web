import unittest

from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.groups import (
    build_group_specs,
    empty_numbers_by_group,
    group_size_targets,
    validate_common_phase,
)
from calendaritzacions.engine.variants.resource_solver.types import GroupSpec, TeamRecord


def _teams(count: int):
    return tuple(
        TeamRecord(
            team_id=f"T{index}",
            name=f"Team {index}",
            entity=f"Club {index}",
            league_name="Lliga",
        )
        for index in range(count)
    )


class ResourceSolverGroupsTests(unittest.TestCase):
    def test_group_size_targets_are_balanced(self):
        self.assertEqual(group_size_targets(8), (8,))
        self.assertEqual(group_size_targets(14), (7, 7))
        self.assertEqual(group_size_targets(17), (6, 6, 5))
        self.assertEqual(group_size_targets(5), (5,))

    def test_build_group_specs_uses_common_phase_and_exact_targets(self):
        groups = build_group_specs(
            _teams(14),
            "segona_fase",
            ResourceSolverConfig(),
        )

        self.assertEqual([group.group_id for group in groups], ["G1", "G2"])
        self.assertEqual([group.target_size for group in groups], [7, 7])
        self.assertEqual({group.phase_name for group in groups}, {"segona_fase"})
        self.assertEqual(empty_numbers_by_group(groups), {"G1": 1, "G2": 1})

    def test_empty_numbers_remain_equivalent_for_unbalanced_total(self):
        groups = build_group_specs(
            _teams(17),
            "primera_fase",
            ResourceSolverConfig(),
        )
        empty_counts = list(empty_numbers_by_group(groups).values())

        self.assertEqual([group.target_size for group in groups], [6, 6, 5])
        self.assertLessEqual(max(empty_counts) - min(empty_counts), 1)

    def test_validate_common_phase_rejects_mixed_group_phases(self):
        with self.assertRaises(ValueError):
            validate_common_phase(
                [
                    GroupSpec("G1", 8, 8, 8, "primera_fase"),
                    GroupSpec("G2", 8, 8, 8, "segona_fase"),
                ],
                "primera_fase",
            )


if __name__ == "__main__":
    unittest.main()
