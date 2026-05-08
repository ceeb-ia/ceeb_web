from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd

from calendaritzacions.second_phase.classifications import enrich_second_phase_classifications


ROOT = Path(__file__).resolve().parents[1]


class FakeProgressReporter:
    def __init__(self) -> None:
        self.events = []

    def report(self, message: str, percent: int | None = None) -> None:
        self.events.append((message, percent))


async def _fake_fetch_ceeb_async(category_id: str, subcategory_id: str):
    return object()


class SecondPhaseProgressTests(unittest.TestCase):
    def test_enrich_second_phase_classifications_reports_progress_to_fake_reporter(self):
        df = pd.DataFrame(
            [
                {
                    "Id": 1,
                    "Nom": "Equip A",
                    "Nom Lliga": "Lliga A",
                    "Modalitat": "Futbol",
                    "Categoria": "Benjami",
                    "Subcategoria": "MIXT",
                }
            ]
        )
        map_modalitat_nom = pd.DataFrame(
            [{"Modalitat": "Futbol", "Nom": "Benjami", "Id Categoria": 123}]
        )
        progress = FakeProgressReporter()

        with (
            patch(
                "calendaritzacions.second_phase.classifications.fetch_ceeb_async",
                side_effect=_fake_fetch_ceeb_async,
            ),
            patch("calendaritzacions.second_phase.classifications.parse_ceeb_xml", return_value={}),
            patch(
                "calendaritzacions.second_phase.classifications.xml_to_dataframe",
                return_value=[pd.DataFrame([{"NomEquipMostrar": "Equip A"}])],
            ),
        ):
            result_df, missing, unused = enrich_second_phase_classifications(
                df,
                map_modalitat_nom,
                progress=progress,
            )

        self.assertEqual(progress.events, [("Consultant classificacions per equips... (això pot portar uns minuts)", 60)])
        self.assertEqual(missing, [])
        self.assertEqual(unused, [])
        self.assertEqual(result_df.loc[0, "Posició Classificació Num"], 1)
        self.assertTrue(result_df.loc[0, "Posició Classificació"])

    def test_classifications_module_does_not_import_logs_directly(self):
        text = (ROOT / "calendaritzacions" / "second_phase" / "classifications.py").read_text(encoding="utf-8")

        self.assertNotIn("from logs import", text)


if __name__ == "__main__":
    unittest.main()
