import importlib
import sys
import unittest
from unittest.mock import patch

from calendaritzacions.engine.base import EngineResult
from calendaritzacions.engine.config import EngineConfig


class EngineContractTests(unittest.TestCase):
    def test_engine_config_defaults_to_legacy(self):
        self.assertEqual(EngineConfig().name, "legacy")

    def test_engine_result_defaults_to_empty_optional_outputs(self):
        first = EngineResult(output_path="output.xlsx")
        second = EngineResult(output_path="other.xlsx")

        self.assertIsNone(first.kpis_path)
        self.assertEqual(first.audit_paths, {})
        self.assertEqual(first.logs, [])
        self.assertIsNot(first.audit_paths, second.audit_paths)
        self.assertIsNot(first.logs, second.logs)

    def test_importing_registry_does_not_import_main(self):
        sys.modules.pop("calendaritzacions.engine.registry", None)
        sys.modules.pop("calendaritzacions.application.compatibility", None)
        sys.modules.pop("main", None)

        importlib.import_module("calendaritzacions.engine.registry")

        self.assertNotIn("main", sys.modules)

    def test_legacy_engine_run_returns_normalized_result(self):
        from calendaritzacions.engine.registry import get_engine

        with patch(
            "calendaritzacions.application.compatibility.process_excel",
            return_value=("output.xlsx", ["started", "done"]),
        ) as process_excel:
            result = get_engine("legacy").run("input.xlsx", EngineConfig())

        self.assertEqual(
            result,
            EngineResult(output_path="output.xlsx", logs=["started", "done"]),
        )
        process_excel.assert_called_once_with(
            input_path="input.xlsx",
            return_logs=True,
            task_id=None,
            segona_fase_bool=False,
        )

    def test_legacy_engine_remains_callable(self):
        from calendaritzacions.engine.registry import get_engine

        with patch(
            "calendaritzacions.application.compatibility.process_excel",
            return_value="output.xlsx",
        ) as process_excel:
            result = get_engine("legacy")(
                "input.xlsx",
                True,
                "task-1",
                True,
            )

        self.assertEqual(result, "output.xlsx")
        process_excel.assert_called_once_with(
            input_path="input.xlsx",
            return_logs=True,
            task_id="task-1",
            segona_fase_bool=True,
        )


if __name__ == "__main__":
    unittest.main()
