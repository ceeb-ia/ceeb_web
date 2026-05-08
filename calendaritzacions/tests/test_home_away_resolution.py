import unittest

import pandas as pd

from calendaritzacions.engine.legacy import (
    HomeAwayResolutionError,
    resolve_home_away_requests,
)


SEED_COLUMN = "Núm. sorteig"


def _df(rows):
    return pd.DataFrame(rows)


class HomeAwayResolutionTests(unittest.TestCase):
    def test_home_request_gets_valid_home_number(self):
        result = resolve_home_away_requests(
            _df(
                [
                    {
                        "Id": "eq-home",
                        "Nom": "Equip Home",
                        "Entitat": "Club A",
                        "Nom Lliga": "Lliga 1",
                        SEED_COLUMN: "CASA",
                    }
                ]
            )
        )

        self.assertIn(result.equip_to_num_sorteig["eq-home"], {8, 7, 6, 1})

    def test_away_request_gets_valid_away_number(self):
        result = resolve_home_away_requests(
            _df(
                [
                    {
                        "Id": "eq-away",
                        "Nom": "Equip Away",
                        "Entitat": "Club B",
                        "Nom Lliga": "Lliga 1",
                        SEED_COLUMN: "FORA",
                    }
                ]
            )
        )

        self.assertIn(result.equip_to_num_sorteig["eq-away"], {5, 4, 3, 2})

    def test_same_team_with_home_and_away_raises_error(self):
        with self.assertRaises(HomeAwayResolutionError):
            resolve_home_away_requests(
                _df(
                    [
                        {
                            "Id": "same-eq",
                            "Nom": "Same Team",
                            "Entitat": "Club A",
                            "Nom Lliga": "Lliga 1",
                            SEED_COLUMN: "CASA",
                        },
                        {
                            "Id": "same-eq",
                            "Nom": "Same Team",
                            "Entitat": "Club A",
                            "Nom Lliga": "Lliga 2",
                            SEED_COLUMN: "FORA",
                        },
                    ]
                )
            )

    def test_pista_joc_is_used_as_assignment_key_when_present(self):
        result = resolve_home_away_requests(
            _df(
                [
                    {
                        "Id": "eq-1",
                        "Nom": "Equip 1",
                        "Entitat": "Club A",
                        "Pista joc": "Pista Compartida",
                        "Nom Lliga": "Lliga 1",
                        SEED_COLUMN: "CASA",
                    },
                    {
                        "Id": "eq-2",
                        "Nom": "Equip 2",
                        "Entitat": "Club B",
                        "Pista joc": "Pista Compartida",
                        "Nom Lliga": "Lliga 2",
                        SEED_COLUMN: "FORA",
                    },
                ]
            )
        )

        self.assertEqual(set(result.entitats_assigned), {"Pista Compartida"})

    def test_result_is_deterministic(self):
        data = _df(
            [
                {
                    "Id": "eq-1",
                    "Nom": "Equip 1",
                    "Entitat": "Club A",
                    "Nom Lliga": "Lliga 1",
                    SEED_COLUMN: "CASA",
                },
                {
                    "Id": "eq-2",
                    "Nom": "Equip 2",
                    "Entitat": "Club B",
                    "Nom Lliga": "Lliga 1",
                    SEED_COLUMN: "FORA",
                },
                {
                    "Id": "eq-3",
                    "Nom": "Equip 3",
                    "Entitat": "Club C",
                    "Nom Lliga": "Lliga 2",
                    SEED_COLUMN: 6,
                },
            ]
        )

        first = resolve_home_away_requests(data)
        second = resolve_home_away_requests(data)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
