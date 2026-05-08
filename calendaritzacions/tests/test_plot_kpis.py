import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "plot_kpis.py"


def load_module():
    spec = importlib.util.spec_from_file_location("plot_kpis", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PlotKpisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.sample_json = ROOT / "kpis_LlistatGlobal.json"

    def test_load_kpis_reads_existing_json(self):
        raw, frames = self.module.load_kpis(self.sample_json)
        self.assertIn("global_numbers", frames)
        self.assertIn("analysis_rows", frames)
        self.assertFalse(frames["global_numbers"].empty)
        self.assertEqual(raw["input_file"], "LlistatGlobal")

    def test_prepare_tables_builds_before_after_counts(self):
        raw, frames = self.module.load_kpis(self.sample_json)
        tables = self.module.prepare_tables(raw, frames, top_entities=10)
        analysis = tables["analysis_rows"]
        before_after = tables["before_after_global"]

        explicit_expected = int((analysis["tipus_peticio"] == "explicit").sum())
        effective_expected = int(analysis["te_peticio_efectiva"].sum())
        assigned_expected = int(analysis["numero_assignat"].between(1, 8).sum())

        explicit_total = int(before_after.loc[before_after["Serie"] == "Explicites originals", "Valor"].sum())
        effective_total = int(before_after.loc[before_after["Serie"] == "Esperat despres CASA/FORA", "Valor"].sum())
        assigned_total = int(before_after.loc[before_after["Serie"] == "Assignat final", "Valor"].sum())

        self.assertEqual(explicit_total, explicit_expected)
        self.assertEqual(effective_total, effective_expected)
        self.assertEqual(assigned_total, assigned_expected)

    def test_generate_plots_and_manifest(self):
        raw, frames = self.module.load_kpis(self.sample_json)
        tables = self.module.prepare_tables(raw, frames, top_entities=10)
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = self.module.generate_all_plots(raw, tables, tmpdir, top_entities=10, fmt="png", dpi=90, style="report")
            out_dir = Path(tmpdir)
            self.assertTrue((out_dir / "manifest.json").exists())
            self.assertTrue((out_dir / "01_expected_vs_assigned_global.png").exists())
            self.assertTrue((out_dir / "04_before_after_casa_fora_global.png").exists())
            self.assertTrue(any(item["status"] == "generated" for item in manifest))

    def test_missing_sections_are_skipped(self):
        payload = {
            "input_file": "fixture",
            "global_numbers": [
                {"Numero": 1, "Demanats": 2, "Assignats": 1, "Diferencia": -1},
                {"Numero": 2, "Demanats": 1, "Assignats": 2, "Diferencia": 1},
            ],
            "analysis_rows": [
                {
                    "Modalitat": "TEST",
                    "tipus_peticio": "explicit",
                    "numero_esperat": 1,
                    "numero_assignat": 2,
                    "te_peticio_efectiva": True,
                    "te_incidencia": True,
                    "casa_fora_complert": False,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "fixture.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            raw, frames = self.module.load_kpis(source)
            tables = self.module.prepare_tables(raw, frames, top_entities=5)
            manifest = self.module.generate_all_plots(raw, tables, tmpdir, top_entities=5, fmt="png", dpi=72, style="report")
            status_by_id = {item["id"]: item["status"] for item in manifest}
            self.assertEqual(status_by_id["01_expected_vs_assigned_global"], "generated")
            self.assertEqual(status_by_id["17_fairness_entities_total"], "skipped")

    def test_null_analysis_rows_do_not_break_prepare_tables(self):
        raw = {
            "analysis_rows": [
                {
                    "Modalitat": None,
                    "tipus_peticio": None,
                    "numero_esperat": None,
                    "numero_assignat": None,
                    "te_peticio_efectiva": None,
                    "te_incidencia": None,
                    "casa_fora_complert": None,
                }
            ]
        }
        frames = {key: self.module.pd.DataFrame(raw.get(key, [])) for key in self.module.SECTION_KEYS}
        tables = self.module.prepare_tables(raw, frames, top_entities=5)
        self.assertIn("before_after_global", tables)
        self.assertEqual(int(tables["before_after_global"]["Valor"].sum()), 0)


if __name__ == "__main__":
    unittest.main()
