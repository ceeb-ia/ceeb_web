import unittest

from calendaritzacions.domain.phases import PRIMERA_FASE, SEGONA_FASE
from calendaritzacions.engine.variants.resource_solver.candidates import (
    generate_candidates,
    home_rounds_for_number,
    opponent_by_round,
    potential_home_resource_ids,
)
from calendaritzacions.engine.variants.resource_solver.types import GroupSpec, TeamRecord


class ResourceSolverCandidatesTests(unittest.TestCase):
    def test_projects_home_rounds_and_opponents_from_phase(self):
        self.assertEqual(home_rounds_for_number(1, PRIMERA_FASE), (1, 3, 5, 7))
        self.assertEqual(
            opponent_by_round(1, PRIMERA_FASE),
            {1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8},
        )
        self.assertEqual(len(opponent_by_round(1, SEGONA_FASE)), 14)

    def test_generates_all_numbers_for_each_team_and_group(self):
        teams = (
            TeamRecord(
                team_id="A",
                name="Equip A",
                entity="Club",
                league_name="Lliga",
                venue="Pavello 1",
                day="Divendres",
                time="18:00",
                seed_request_original="CASA",
            ),
        )
        groups = (
            GroupSpec("G1", 7, 7, 7, "primera_fase"),
            GroupSpec("G2", 7, 7, 7, "primera_fase"),
        )

        candidates = generate_candidates(teams, groups, PRIMERA_FASE)

        self.assertEqual(len(candidates), 16)
        self.assertEqual(
            {(candidate.group_id, candidate.number) for candidate in candidates},
            {
                (group_id, number)
                for group_id in ("G1", "G2")
                for number in range(1, 9)
            },
        )
        self.assertTrue(all(candidate.seed_request_original == "CASA" for candidate in candidates))
        self.assertIn("A-G1-1", {candidate.candidate_id for candidate in candidates})

    def test_generates_ten_slot_projection_for_nine_team_group(self):
        team = TeamRecord(
            team_id="A",
            name="Equip A",
            entity="Club",
            league_name="Lliga",
            venue="Pavello 1",
            day="Divendres",
            time="18:00",
        )
        group = GroupSpec("G1", 9, 9, 9, "primera_fase")

        candidates = generate_candidates((team,), (group,), PRIMERA_FASE)
        by_number = {candidate.number: candidate for candidate in candidates}

        self.assertEqual(group.numbers, tuple(range(1, 11)))
        self.assertEqual(set(by_number), set(range(1, 11)))
        self.assertEqual(by_number[9].potential_home_rounds, (1, 3, 5, 8))
        self.assertEqual(by_number[9].opponent_number_by_round[9], 2)
        self.assertEqual(
            by_number[10].potential_resources,
            (
                "pavello-1|divendres|18-00|J1",
                "pavello-1|divendres|18-00|J3",
                "pavello-1|divendres|18-00|J5",
                "pavello-1|divendres|18-00|J7",
                "pavello-1|divendres|18-00|J8",
            ),
        )

    def test_potential_home_resources_use_team_base_resource_and_rounds(self):
        team = TeamRecord(
            team_id="A",
            name="Equip A",
            entity="Club",
            league_name="Lliga",
            venue="Pavello 1",
            day="Divendres",
            time="18:00",
        )

        self.assertEqual(
            potential_home_resource_ids(team, 1, PRIMERA_FASE),
            (
                "pavello-1|divendres|18-00|J1",
                "pavello-1|divendres|18-00|J3",
                "pavello-1|divendres|18-00|J5",
                "pavello-1|divendres|18-00|J7",
            ),
        )


if __name__ == "__main__":
    unittest.main()
