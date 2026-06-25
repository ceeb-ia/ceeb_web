import importlib.util
import unittest

from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.groups import (
    build_hard_level_group_plan,
    build_group_specs,
    empty_numbers_by_group,
    group_size_targets,
    normalize_hard_level,
    structural_group_size_targets,
    validate_common_phase,
)
from calendaritzacions.engine.variants.resource_solver.input_adapter import build_context_from_dataframe
from calendaritzacions.engine.variants.resource_solver.types import GroupSpec, TeamRecord

HAS_PANDAS = importlib.util.find_spec("pandas") is not None

if HAS_PANDAS:
    import pandas as pd


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


def _level_teams(prefix: str, count: int, level: str):
    return tuple(
        TeamRecord(
            team_id=f"{prefix}{index}",
            name=f"{prefix} {index}",
            entity=f"Club {prefix}{index}",
            league_name="Lliga",
            level=level,
        )
        for index in range(1, count + 1)
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

        self.assertEqual([group.target_size for group in groups], [9, 8])
        self.assertEqual(groups[0].numbers, tuple(range(1, 11)))
        self.assertLessEqual(max(empty_counts) - min(empty_counts), 1)

    def test_structural_group_size_targets_allow_exceptional_to_avoid_small_groups(self):
        self.assertEqual(structural_group_size_targets(8), (8,))
        self.assertEqual(structural_group_size_targets(9), (9,))
        self.assertEqual(structural_group_size_targets(10), (10,))
        self.assertEqual(structural_group_size_targets(11), (6, 5))
        self.assertEqual(structural_group_size_targets(17), (9, 8))
        self.assertEqual(structural_group_size_targets(18), (6, 6, 6))
        self.assertEqual(structural_group_size_targets(19), (7, 6, 6))
        self.assertEqual(structural_group_size_targets(20), (7, 7, 6))

    def test_normalize_hard_level_uses_a_to_e_transformation(self):
        self.assertEqual(normalize_hard_level("Nivell A"), "A")
        self.assertEqual(normalize_hard_level("Nivell B"), "B")
        self.assertEqual(normalize_hard_level("Nivell C"), "B/C")
        self.assertEqual(normalize_hard_level("Nivell D"), "B/C")
        self.assertEqual(normalize_hard_level("Nivell E"), "C")
        self.assertEqual(normalize_hard_level(""), "B/C")

    def test_hard_level_group_plan_allocates_b_c_capacity_without_mixing_a(self):
        teams = (
            *_level_teams("A", 6, "Nivell A"),
            *_level_teams("B", 5, "Nivell B"),
            *_level_teams("C", 5, "Nivell E"),
            *_level_teams("BC", 2, "B-C"),
        )

        plan = build_hard_level_group_plan(teams, "primera_fase", group_prefix="C1_G")

        self.assertEqual(
            {family: [group.target_size for group in groups] for family, groups in plan.groups_by_family.items()},
            {"A": [6], "B": [6], "C": [6]},
        )
        self.assertEqual([group.group_id for group in plan.groups_by_family["A"]], ["C1_G_A_G1"])
        self.assertEqual(plan.audit[-1]["type"], "level_flexible_allocation")
        self.assertEqual(plan.audit[-1]["assigned_to_B_capacity"], 1)
        self.assertEqual(plan.audit[-1]["assigned_to_C_capacity"], 1)

    def test_hard_level_group_plan_audits_unavoidable_small_groups(self):
        plan = build_hard_level_group_plan(
            _level_teams("B", 5, "B"),
            "primera_fase",
            group_prefix="C1_G",
        )

        self.assertEqual([group.target_size for group in plan.groups], [5])
        self.assertEqual(plan.audit[0]["type"], "level_group_size_warning")
        self.assertEqual(plan.audit[0]["reason"], "small_group_unavoidable")

    def test_hard_level_group_plan_uses_flexible_teams_to_avoid_unneeded_exceptional_group(self):
        teams = (
            *_level_teams("B", 10, "Nivell B"),
            *_level_teams("BC", 4, "B-C"),
            *_level_teams("C", 4, "Nivell E"),
        )

        plan = build_hard_level_group_plan(teams, "primera_fase", group_prefix="C1_G")

        self.assertEqual(
            {family: [group.target_size for group in groups] for family, groups in plan.groups_by_family.items()},
            {"A": [], "B": [6, 6], "C": [6]},
        )
        self.assertTrue(all(group.numbers == tuple(range(1, 9)) for group in plan.groups))
        self.assertEqual(plan.audit[-1]["assigned_to_B_capacity"], 2)
        self.assertEqual(plan.audit[-1]["assigned_to_C_capacity"], 2)

    @unittest.skipUnless(HAS_PANDAS, "pandas not installed")
    def test_hard_level_context_restricts_candidates_by_level_family(self):
        rows = []
        for prefix, count, level in (
            ("A", 6, "Nivell A"),
            ("B", 5, "Nivell B"),
            ("C", 5, "Nivell E"),
            ("BC", 2, "B-C"),
        ):
            for index in range(1, count + 1):
                rows.append(
                    {
                        "Id": f"{prefix}{index}",
                        "Nom": f"{prefix} {index}",
                        "Entitat": f"Club {prefix}{index}",
                        "Nom Lliga": "Lliga",
                        "Modalitat": "Futbol",
                        "Categoria": "Cat",
                        "Subcategoria": "Sub",
                        "Nivell": level,
                        "Pista joc": "Pista",
                        "Dia partit": "Divendres",
                        "Horari partit": "18:00",
                    }
                )

        context = build_context_from_dataframe(
            pd.DataFrame(rows),
            ResourceSolverConfig(level_constraint_mode="hard"),
        )
        candidate_groups_by_team = {}
        for candidate in context.candidates:
            candidate_groups_by_team.setdefault(candidate.team_id, set()).add(candidate.group_id)

        self.assertEqual([group.target_size for group in context.groups], [6, 6, 6])
        self.assertTrue(all("_A_" in group_id for group_id in candidate_groups_by_team["A1"]))
        self.assertTrue(all("_B_" in group_id for group_id in candidate_groups_by_team["B1"]))
        self.assertTrue(all("_C_" in group_id for group_id in candidate_groups_by_team["C1"]))
        self.assertEqual(
            {part for group_id in candidate_groups_by_team["BC1"] for part in ("B", "C") if f"_{part}_" in group_id},
            {"B", "C"},
        )
        self.assertEqual(context.config.level_group_size_audit[-1]["assigned_to_B_capacity"], 1)
        self.assertEqual(context.config.level_group_size_audit[-1]["assigned_to_C_capacity"], 1)

    def test_group_spec_uses_ten_numbers_for_nine_team_target(self):
        group = GroupSpec("G1", 9, 9, 9, "primera_fase")

        self.assertEqual(group.target_size, 9)
        self.assertEqual(group.numbers, tuple(range(1, 11)))
        self.assertEqual(empty_numbers_by_group((group,)), {"G1": 1})

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
