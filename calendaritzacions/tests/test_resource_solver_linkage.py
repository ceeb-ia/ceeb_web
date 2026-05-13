import unittest
import sys
import importlib.util


if "pandas" not in sys.modules and importlib.util.find_spec("pandas") is None:
    class _PandasStub:
        NA = object()

        class DataFrame:
            pass

        class Series:
            pass

        @staticmethod
        def isna(value):
            return value is None

    sys.modules["pandas"] = _PandasStub()

from calendaritzacions.engine.variants.resource_solver.linkage import (
    CASA,
    FORA,
    INDIFERENT,
    are_opposite_numbers,
    linkage_sides_are_opposites,
    linkage_sides_match,
    normalize_linkage_group,
    normalize_linkage_side_from_seed,
    opposite_number,
    seed_request_matches_side,
    simulate_linkage_groups,
)
from calendaritzacions.engine.variants.resource_solver.types import TeamRecord


def _team(
    team_id,
    *,
    venue="Pavello",
    day="Divendres",
    time="18:00",
    seed="",
):
    return TeamRecord(
        team_id=team_id,
        name=f"Team {team_id}",
        entity=f"Club {team_id}",
        league_name="Lliga",
        venue=venue,
        day=day,
        time=time,
        seed_request_original=seed,
    )


class ResourceSolverLinkageTests(unittest.TestCase):
    def test_team_record_linkage_fields_default_to_empty_strings(self):
        team = TeamRecord("T1", "Team 1", "Club", "League")

        self.assertEqual(team.linkage_group, "")
        self.assertEqual(team.linkage_side, "")
        self.assertEqual(team.linkage_source, "")

    def test_normalizes_groups_and_seed_sides(self):
        self.assertEqual(normalize_linkage_group(" Grup A / Pista 1 "), "grup-a-pista-1")
        self.assertEqual(normalize_linkage_group(""), "")

        for value in (1, "6", "7.0", 7.0, "CASA"):
            self.assertEqual(normalize_linkage_side_from_seed(value), CASA)
        for value in (2, "3", 4.0, "fora"):
            self.assertEqual(normalize_linkage_side_from_seed(value), FORA)
        for value in ("", None, "neutral", 9):
            self.assertEqual(normalize_linkage_side_from_seed(value), INDIFERENT)

    def test_relation_helpers_cover_numbers_and_sides(self):
        self.assertEqual(opposite_number(1), 5)
        self.assertEqual(opposite_number("6"), 2)
        self.assertIsNone(opposite_number(9))
        self.assertTrue(are_opposite_numbers(7, 3))
        self.assertFalse(are_opposite_numbers(7, 4))

        self.assertTrue(linkage_sides_match(CASA, INDIFERENT))
        self.assertTrue(linkage_sides_match(CASA, CASA))
        self.assertFalse(linkage_sides_match(CASA, FORA))
        self.assertTrue(linkage_sides_are_opposites(CASA, FORA))
        self.assertTrue(seed_request_matches_side(1, CASA))
        self.assertFalse(seed_request_matches_side(1, FORA))

    def test_simulation_links_same_venue_day_with_consecutive_slots(self):
        teams = (
            _team("T3", time="20:00", seed="fora"),
            _team("T1", time="18:00", seed="casa"),
            _team("T4", time="21:00", seed=""),
            _team("T2", time="19:00", seed=1),
            _team("T5", venue="Altra", day="Divendres", time="18:00", seed="casa"),
        )

        updated, audit = simulate_linkage_groups(teams)

        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["pattern"], "CASA-CASA")
        self.assertEqual(audit[0]["team_ids"], ("T1", "T2"))
        self.assertTrue(audit[0]["consecutive_hour_slots"])
        self.assertEqual(audit[0]["venue"], "Pavello")
        self.assertEqual(audit[0]["day"], "Divendres")

        by_id = {team.team_id: team for team in updated}
        self.assertEqual(by_id["T1"].linkage_group, audit[0]["group"])
        self.assertEqual(by_id["T2"].linkage_side, CASA)
        self.assertEqual(by_id["T3"].linkage_group, "")
        self.assertEqual(by_id["T5"].linkage_group, "")

    def test_simulation_is_deterministic_and_keeps_majority_unlinked(self):
        teams = tuple(
            _team(f"T{index}", time=f"{17 + index:02d}:00", seed="")
            for index in range(1, 8)
        )

        first_updated, first_audit = simulate_linkage_groups(teams)
        second_updated, second_audit = simulate_linkage_groups(tuple(reversed(teams)))

        self.assertEqual(first_audit, second_audit)
        self.assertEqual(first_audit[0]["pattern"], "CASA-CASA-FORA")
        self.assertEqual(
            tuple(team.team_id for team in first_updated if team.linkage_group),
            ("T1", "T2", "T3"),
        )
        self.assertLess(
            len([team for team in first_updated if team.linkage_group]),
            len([team for team in first_updated if not team.linkage_group]),
        )


if __name__ == "__main__":
    unittest.main()
