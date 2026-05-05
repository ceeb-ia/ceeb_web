import os
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MEDIA_ROOT", str(ROOT / "tests"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import assignacions  # noqa: E402
import main  # noqa: E402


class LegacyGroupAndSlotTests(unittest.TestCase):
    def test_assignacions_crear_grups_equilibrats_keeps_current_small_group_behavior(self):
        self.assertEqual(assignacions.crear_grups_equilibrats(5), [5])
        self.assertEqual(assignacions.crear_grups_equilibrats(9), [5, 4])
        self.assertEqual(assignacions.crear_grups_equilibrats(17), [6, 6, 5])

    def test_main_crear_grups_equilibrats_keeps_current_balancing(self):
        self.assertEqual(main.crear_grups_equilibrats(8), [8])
        self.assertEqual(main.crear_grups_equilibrats(9), [5, 4])
        self.assertEqual(main.crear_grups_equilibrats(17), [6, 6, 5])

    def test_build_slots_uses_eight_positions_for_every_group(self):
        slots = assignacions.build_slots([3, 2])

        self.assertEqual(len(slots), 16)
        self.assertEqual(slots[:3], [(0, 0), (0, 1), (0, 2)])
        self.assertEqual(slots[7:10], [(0, 7), (1, 0), (1, 1)])
        self.assertEqual(slots[-1], (1, 7))


class LegacySeedAndCostTests(unittest.TestCase):
    def test_normalize_seed_value_accepts_numbers_and_casa_fora_labels(self):
        cases = [
            (" CASA ", "casa"),
            ("fora", "fora"),
            ("3.0", 3),
            (4, 4),
        ]

        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(assignacions.normalize_seed_value(raw), expected)
                self.assertEqual(main.normalize_seed_value(raw), expected)

        self.assertTrue(np.isnan(assignacions.normalize_seed_value("3.5")))
        self.assertTrue(np.isnan(assignacions.normalize_seed_value("")))
        self.assertTrue(np.isnan(main.normalize_seed_value("3.5")))
        self.assertTrue(np.isnan(main.normalize_seed_value("")))

    def test_build_disposicions_returns_home_away_sequence_per_seed_number(self):
        fase = [
            [(1, 2), (3, 4), (5, 6), (7, 8)],
            [(2, 1), (4, 3), (6, 5), (8, 7)],
        ]

        disposicions = assignacions.build_disposicions(fase)

        self.assertEqual(len(disposicions), 8)
        self.assertEqual(disposicions[0], ["casa", "fora"])
        self.assertEqual(disposicions[1], ["fora", "casa"])
        self.assertEqual(disposicions[6], ["casa", "fora"])
        self.assertEqual(disposicions[7], ["fora", "casa"])

    def test_cost_calc_penalizes_home_away_pattern_mismatches(self):
        fase = [
            [(1, 2), (3, 4), (5, 6), (7, 8)],
            [(2, 1), (4, 3), (6, 5), (8, 7)],
        ]
        disposicions = assignacions.build_disposicions(fase)

        exact_match = assignacions.cost_calc(
            "Equip A", 1, 0, 0, disposicions, {}, fase
        )
        opposite_pattern = assignacions.cost_calc(
            "Equip A", 1, 0, 1, disposicions, {}, fase
        )
        no_seed = assignacions.cost_calc(
            "Equip A", np.nan, 0, 1, disposicions, {}, fase
        )
        casa_request = assignacions.cost_calc(
            "Equip A", "casa", 0, 0, disposicions, {"Equip A": 1}, fase
        )

        self.assertEqual(exact_match, 1.0)
        self.assertEqual(opposite_pattern, 16.0)
        self.assertEqual(no_seed, 0.0)
        self.assertEqual(casa_request, -4.0)


class LegacyDummyTests(unittest.TestCase):
    def test_add_dummies_fills_to_eight_slots_per_group(self):
        df_cat = pd.DataFrame(
            [
                {
                    "Nom": "Equip A",
                    "Nom Lliga": "Lliga Test",
                    "NÃºm. sorteig": 1,
                    "Entitat": "Club A",
                    "Nivell": "A",
                    "Dia partit": "Dissabte",
                    "Id": "A",
                },
                {
                    "Nom": "Equip B",
                    "Nom Lliga": "Lliga Test",
                    "NÃºm. sorteig": 2,
                    "Entitat": "Club B",
                    "Nivell": "B",
                    "Dia partit": "Diumenge",
                    "Id": "B",
                },
            ]
        )

        result, added = assignacions.add_dummies(df_cat.copy(), [2])

        self.assertEqual(added, 6)
        self.assertEqual(len(result), 8)
        self.assertEqual(result.loc[2, "Nom"], "Descans 1")
        self.assertEqual(result.loc[7, "Nom"], "Descans 6")
        self.assertEqual(set(result.loc[2:, "Entitat"]), {"Descans"})
        self.assertEqual(result.loc[2, "Nom Lliga"], "Lliga Test")
        self.assertEqual(len(df_cat), 2)

    def test_add_dummies_in_segona_fase_fills_rows_but_keeps_existing_columns(self):
        df_cat = pd.DataFrame(
            [
                {
                    "Nom": "Equip A",
                    "Nom Lliga": "Lliga Test",
                    "NÃºm. sorteig": 1,
                    "Entitat": "Club A",
                    "Nivell": "A",
                    "Dia partit": "Dissabte",
                    "PosiciÃ³ ClassificaciÃ³": True,
                    "PosiciÃ³ ClassificaciÃ³ Num": 1,
                    "Id": "A",
                }
            ]
        )

        result, added = assignacions.add_dummies(
            df_cat.copy(), [1], segona_fase_bool=True
        )

        self.assertEqual(added, 7)
        self.assertEqual(len(result), 8)
        self.assertEqual(result.loc[1, "Nom"], "Descans 1")
        self.assertEqual(result.loc[1, "Entitat"], "Descans")
        self.assertIn("PosiciÃ³ ClassificaciÃ³", result.columns)
        self.assertIn("PosiciÃ³ ClassificaciÃ³ Num", result.columns)
        self.assertTrue(pd.isna(result.loc[1, "PosiciÃ³ ClassificaciÃ³"]))
        self.assertTrue(pd.isna(result.loc[1, "PosiciÃ³ ClassificaciÃ³ Num"]))


class LegacyAssignmentFacadeTests(unittest.TestCase):
    def test_assignar_grups_hungares_runs_small_numeric_category(self):
        seed_col = "Núm. sorteig"
        df_cat = pd.DataFrame(
            [
                {
                    "Nom": f"Equip {idx}",
                    "Nom Lliga": "Lliga Test",
                    seed_col: idx,
                    "Entitat": f"Club {idx}",
                    "Nivell": "Nivell A" if idx <= 4 else "Nivell B",
                    "Dia partit": "Dissabte",
                    "Id": f"EQ{idx}",
                }
                for idx in range(1, 9)
            ]
        )

        result, entity_costs, info = assignacions.assignar_grups_hungares(df_cat)

        self.assertEqual(len(result), 8)
        self.assertEqual(info["num_grups"], 1)
        self.assertEqual(info["num_equips_reals"], 8)
        self.assertEqual(info["num_dummies"], 0)
        self.assertIn("Núm. sorteig assignat", result.columns)
        self.assertIsInstance(entity_costs, dict)


if __name__ == "__main__":
    unittest.main()
