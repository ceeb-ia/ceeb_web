import importlib
import sys
import unittest
from unittest.mock import patch


class ApplicationRegistryCompatibilityTests(unittest.TestCase):
    def test_importing_registry_does_not_import_legacy_main(self):
        sys.modules.pop("calendaritzacions.engine.registry", None)
        sys.modules.pop("calendaritzacions.application.compatibility", None)
        sys.modules.pop("main", None)

        importlib.import_module("calendaritzacions.engine.registry")

        self.assertNotIn("main", sys.modules)

    def test_get_legacy_engine_returns_callable(self):
        from calendaritzacions.engine.registry import get_engine

        self.assertTrue(callable(get_engine("legacy")))

    def test_process_calendarization_delegates_to_imported_wrapper(self):
        from calendaritzacions.application.use_cases import process_calendarization

        with patch("calendaritzacions.application.use_cases.process_excel", return_value="output.xlsx") as process_excel:
            result = process_calendarization(
                "input.xlsx",
                return_logs=True,
                task_id="task-1",
                segona_fase_bool=True,
            )

        self.assertEqual(result, "output.xlsx")
        process_excel.assert_called_once_with(
            input_path="input.xlsx",
            return_logs=True,
            task_id="task-1",
            segona_fase_bool=True,
        )

    def test_noop_progress_reporter_report_does_not_fail(self):
        from calendaritzacions.application.progress import NoopProgressReporter

        self.assertIsNone(NoopProgressReporter().report("working", percent=50))


if __name__ == "__main__":
    unittest.main()
