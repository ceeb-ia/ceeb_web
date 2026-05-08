import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from calendaritzacions.reporting.json_writer import write_kpis_json


class JsonWriterTests(unittest.TestCase):
    def test_write_kpis_json_creates_formatted_utf8_file(self):
        payload = {"equip": "\u00c0gora", "nested": {"value": 1}}

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kpis.json"

            returned_path = write_kpis_json(path, payload)

            self.assertEqual(returned_path, str(path))
            self.assertTrue(path.exists())
            text = path.read_text(encoding="utf-8")
            self.assertIn('"equip": "\u00c0gora"', text)
            self.assertIn('\n  "nested": {', text)
            self.assertEqual(json.loads(text), payload)

    def test_write_kpis_json_serializes_pandas_and_numpy_values(self):
        payload = {
            "numpy_int": np.int64(7),
            "numpy_float": np.float64(2.5),
            "numpy_bool": np.bool_(True),
            "missing": pd.NA,
            "path": Path("resultats") / "kpis.json",
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kpis.json"

            write_kpis_json(path, payload)

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {
                    "numpy_int": 7,
                    "numpy_float": 2.5,
                    "numpy_bool": True,
                    "missing": None,
                    "path": str(Path("resultats") / "kpis.json"),
                },
            )


if __name__ == "__main__":
    unittest.main()
