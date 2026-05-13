import importlib.util
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from calendaritzacions.analysis.input_demand import (
    build_input_demand_analysis,
    write_input_demand_plots,
)
from calendaritzacions.analysis.run_audit import build_input_demand_payload


class InputDemandAnalysisTests(unittest.TestCase):
    def test_build_input_demand_groups_by_venue_day_and_time(self):
        df = pd.DataFrame(
            [
                {
                    "Id": "A",
                    "Nom": "Equip A",
                    "Pista joc": " Pavello 1 ",
                    "Dia partit": "divendres",
                    "Horari partit": "18:00",
                    "Modalitat": "Futbol",
                    "Nom Lliga": "Lliga 1",
                    "Categoria": "Cat 1",
                    "Núm. sorteig": 1,
                },
                {
                    "Id": "B",
                    "Nom": "Equip B",
                    "Pista joc": "Pavello 1",
                    "Dia partit": "Divendres",
                    "Horari partit": 18.0,
                    "Modalitat": "Volei",
                    "Nom Lliga": "Lliga 2",
                    "Categoria": "Cat 2",
                    "Núm. sorteig": "CASA",
                },
                {
                    "Id": "C",
                    "Nom": "Equip C",
                    "Pista joc": "Pavello 1",
                    "Dia partit": "Dissabte",
                    "Horari partit": 0.75,
                    "Modalitat": "Futbol",
                    "Nom Lliga": "Lliga 1",
                    "Categoria": "Cat 1",
                    "Núm. sorteig": 2,
                },
                {
                    "Id": "D",
                    "Nom": "Equip D",
                    "Pista joc": "",
                    "Dia partit": None,
                    "Horari partit": "",
                    "Modalitat": "Futbol",
                    "Nom Lliga": "Lliga 3",
                    "Categoria": "Cat 3",
                    "Núm. sorteig": "",
                },
            ]
        )

        analysis = build_input_demand_analysis(df)

        self.assertEqual(analysis["summary"]["total_equips"], 4)
        self.assertEqual(analysis["summary"]["files_sense_pista"], 1)
        self.assertEqual(analysis["summary"]["files_sense_dia"], 1)
        self.assertEqual(analysis["summary"]["files_sense_hora"], 1)
        self.assertEqual(analysis["summary"]["max_demanda_slot"], 2)

        friday_slots = analysis["friday_by_venue_time"]
        self.assertEqual(len(friday_slots), 1)
        self.assertEqual(friday_slots[0]["pista_joc"], "Pavello 1")
        self.assertEqual(friday_slots[0]["dia_partit"], "Divendres")
        self.assertEqual(friday_slots[0]["horari_partit"], "18:00")
        self.assertEqual(friday_slots[0]["equips"], 2)
        self.assertEqual(friday_slots[0]["modalitats"], 2)

        saturday = [
            row
            for row in analysis["by_venue_day_time"]
            if row["pista_joc"] == "Pavello 1" and row["dia_partit"] == "Dissabte"
        ]
        self.assertEqual(saturday[0]["horari_partit"], "18:00")
        seed_rows = {
            (row["modalitat"], row["peticio"]): row["equips"]
            for row in analysis["seed_requests_by_modality"]
        }
        self.assertEqual(seed_rows[("Futbol", "1")], 1)
        self.assertEqual(seed_rows[("Futbol", "2")], 1)
        self.assertEqual(seed_rows[("Futbol", "Sense peticio")], 1)
        self.assertEqual(seed_rows[("Volei", "CASA")], 1)

    def test_build_input_demand_payload_is_json_ready(self):
        analysis = build_input_demand_analysis(
            pd.DataFrame(
                [
                    {
                        "Id": "A",
                        "Pista joc": "Pista A",
                        "Dia partit": "Divendres",
                        "Horari partit": "19:30",
                    }
                ]
            )
        )

        payload = build_input_demand_payload(**analysis, plots={"heatmap": "plot.png"})

        self.assertEqual(payload["artifact_type"], "input_demand")
        self.assertEqual(payload["summary"]["total_equips"], 1)
        self.assertEqual(payload["plots"], {"heatmap": "plot.png"})

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "matplotlib not installed")
    def test_write_input_demand_plots_creates_pngs(self):
        analysis = build_input_demand_analysis(
            pd.DataFrame(
                [
                    {"Id": "A", "Pista joc": "Pista A", "Dia partit": "Divendres", "Horari partit": "18:00"},
                    {"Id": "B", "Pista joc": "Pista A", "Dia partit": "Divendres", "Horari partit": "18:00"},
                    {"Id": "C", "Pista joc": "Pista B", "Dia partit": "Dissabte", "Horari partit": "19:00"},
                ]
            )
        )

        with tempfile.TemporaryDirectory() as tmp:
            plots = write_input_demand_plots(analysis, Path(tmp), stem="input_demand_test")

            self.assertIn("heatmap", plots)
            self.assertNotIn("friday", plots)
            self.assertIn("seed_requests_by_modality", plots)
            for path in plots.values():
                self.assertTrue(Path(path).exists())


if __name__ == "__main__":
    unittest.main()
