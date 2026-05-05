from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ImportBoundaryTests(unittest.TestCase):
    def test_legacy_engine_modules_do_not_import_logs(self):
        legacy_dir = ROOT / "calendaritzacions" / "engine" / "legacy"
        offenders = []
        for path in legacy_dir.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "from logs import" in text or "import logs" in text:
                offenders.append(path.name)

        self.assertEqual(offenders, [])

    def test_classifications_uses_second_phase_ceeb_client_boundary(self):
        text = (ROOT / "calendaritzacions" / "second_phase" / "classifications.py").read_text(encoding="utf-8")

        self.assertIn("calendaritzacions.second_phase.ceeb_client", text)
        self.assertNotIn("consulta_resultats", text)
        self.assertNotIn("from logs import", text)

    def test_legacy_pipeline_uses_progress_boundary(self):
        text = (ROOT / "calendaritzacions" / "application" / "legacy_pipeline.py").read_text(encoding="utf-8")

        self.assertIn("calendaritzacions.application.progress", text)
        self.assertNotIn("from logs import", text)


if __name__ == "__main__":
    unittest.main()
