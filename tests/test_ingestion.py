import hashlib
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from calendaritzacions.ingestion import (
    InputValidationError,
    ensure_team_ids,
    load_modalitat_map,
    prepare_legacy_input,
    validate_no_mixed_home_away_requests,
    validate_required_columns,
)


SEED_COLUMN = "Núm. sorteig"


def _minimal_df(**overrides):
    data = {
        "Nom": ["  Equip À  "],
        "Entitat": ["Club"],
        "Nom Lliga": [" Lliga  1 "],
        "Nivell": ["Nivell A"],
        SEED_COLUMN: ["1"],
        "Dia partit": ["Dissabte"],
        "Categoria": [" ALEVÍ "],
    }
    data.update(overrides)
    return pd.DataFrame(data)


class IngestionTests(unittest.TestCase):
    def test_ensure_team_ids_generates_stable_legacy_id(self):
        df = _minimal_df()

        result = ensure_team_ids(df)

        expected_key = "equip à|lliga 1|aleví"
        expected = hashlib.sha1(expected_key.encode("utf-8")).hexdigest()[:10].upper()
        self.assertEqual(result.loc[0, "Id"], expected)
        self.assertNotIn("Id", df.columns)

    def test_ensure_team_ids_preserves_existing_id_values(self):
        df = _minimal_df(Id=["EXISTING"])

        result = ensure_team_ids(df)

        self.assertIs(result, df)
        self.assertEqual(result["Id"].tolist(), ["EXISTING"])

    def test_validate_required_columns_accepts_unicode_seed_column(self):
        df = _minimal_df()

        self.assertIs(validate_required_columns(df), df)

    def test_validate_required_columns_reports_missing_columns(self):
        df = _minimal_df().drop(columns=[SEED_COLUMN])

        with self.assertRaises(InputValidationError) as cm:
            validate_required_columns(df)

        self.assertEqual(cm.exception.details, {"missing_columns": [SEED_COLUMN]})

    def test_validate_no_mixed_home_away_requests_reports_conflict(self):
        df = pd.DataFrame(
            {
                "Id": ["TEAM1", "TEAM1", "TEAM2"],
                "Nom": ["Equip", "Equip", "Altre"],
                "Nom Lliga": ["Lliga A", "Lliga B", "Lliga A"],
                SEED_COLUMN: ["Casa", "FORA", "CASA"],
            }
        )

        with self.assertRaises(InputValidationError) as cm:
            validate_no_mixed_home_away_requests(df)

        self.assertEqual(cm.exception.details["conflicts"][0]["id"], "TEAM1")
        self.assertEqual(cm.exception.details["conflicts"][0]["requests"], ["casa", "fora"])

    def test_load_modalitat_map_reads_semicolon_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "map_modalitat_nom.csv"
            csv_path.write_text("Modalitat;Nom\nFUTBOL 5;ALEVÍ\n", encoding="utf-8")

            result = load_modalitat_map(csv_path)

        self.assertEqual(result.to_dict("records"), [{"Modalitat": "FUTBOL 5", "Nom": "ALEVÍ"}])

    def test_prepare_legacy_input_copies_loads_map_and_regenerates_existing_id(self):
        df = _minimal_df(Id=["EXISTING"])
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "map_modalitat_nom.csv"
            csv_path.write_text("Modalitat;Nom\nFUTBOL 5;INFANTIL\n", encoding="utf-8")

            prepared, modalitat_map = prepare_legacy_input(df, csv_path)

        expected = ensure_team_ids(df.drop(columns=["Id"]))["Id"].iloc[0]
        self.assertIsNot(prepared, df)
        self.assertEqual(df["Id"].tolist(), ["EXISTING"])
        self.assertEqual(prepared["Id"].tolist(), [expected])
        self.assertEqual(modalitat_map.to_dict("records"), [{"Modalitat": "FUTBOL 5", "Nom": "INFANTIL"}])

    def test_prepare_legacy_input_fails_when_entitat_missing(self):
        df = _minimal_df().drop(columns=["Entitat"])

        with self.assertRaises(InputValidationError) as cm:
            prepare_legacy_input(df, "unused.csv")

        self.assertEqual(cm.exception.details, {"missing_columns": ["Entitat"]})


if __name__ == "__main__":
    unittest.main()
