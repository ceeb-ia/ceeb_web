import unittest

import pandas as pd

from calendaritzacions.analysis.validation_tables import build_validation_tables


class ValidationTablesTests(unittest.TestCase):
    def test_build_validation_tables_counts_and_detects_conflicts(self):
        input_df = pd.DataFrame(
            [
                {"Nom Lliga": "Lliga 1"},
                {"Nom Lliga": "Lliga 1"},
                {"Nom Lliga": "Lliga 2"},
            ]
        )
        metrics_pack = {
            "analysis": pd.DataFrame(
                [
                    {"Categoria": "Lliga 1", "Grup": "G1", "Entitat": "Club A"},
                    {"Categoria": "Lliga 1", "Grup": "G1", "Entitat": "Club A"},
                    {"Categoria": "Lliga 2", "Grup": "G1", "Entitat": "Club B"},
                ]
            ),
            "levels_group": pd.DataFrame(
                [
                    {
                        "Categoria": "Lliga 1",
                        "Grup": "G1",
                        "Nivells presents": "A, D",
                        "Min nivell": 1,
                        "Max nivell": 4,
                        "Rang nivell": 3,
                    }
                ]
            ),
        }

        tables = build_validation_tables(input_df, metrics_pack)

        self.assertEqual(tables.count_summary.loc[0, "Valor"], 3)
        self.assertTrue(tables.count_by_category["OK"].all())
        self.assertEqual(tables.entity_conflicts.iloc[0]["Entitat"], "Club A")
        self.assertEqual(tables.level_spread.iloc[0]["Dif"], 3)


if __name__ == "__main__":
    unittest.main()
