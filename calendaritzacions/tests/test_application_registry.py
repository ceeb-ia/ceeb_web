import importlib
import sys
import unittest
from unittest.mock import Mock, patch


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

    def test_process_calendarization_orchestrates_legacy_pipeline(self):
        from calendaritzacions.application.use_cases import process_calendarization

        with (
            patch("calendaritzacions.application.use_cases.read_excel", return_value="df") as read_excel,
            patch("calendaritzacions.application.legacy_pipeline.processar_dades_2", return_value="output.xlsx") as processar,
            patch("calendaritzacions.application.use_cases.finalize_result_path", return_value="final.xlsx") as finalize,
        ):
            result = process_calendarization(
                "input.xlsx",
                return_logs=True,
                task_id=None,
                segona_fase_bool=True,
            )

        self.assertEqual(result, ("final.xlsx", []))
        read_excel.assert_called_once_with("input.xlsx")
        processar.assert_called_once_with(
            "df",
            nom_fitxer="input.xlsx",
            task_id=None,
            segona_fase_bool=True,
        )
        finalize.assert_called_once()

    def test_process_calendarization_passes_resource_solver_modes_to_engine_config(self):
        from calendaritzacions.application.use_cases import process_calendarization

        engine = Mock()
        engine.run.return_value = Mock(
            output_path="out.xlsx",
            logs=["ok"],
            audit_paths={},
            kpis_path="",
        )

        with patch("calendaritzacions.engine.registry.get_engine", return_value=engine):
            result = process_calendarization(
                "input.xlsx",
                return_artifacts=True,
                engine_name="resource_solver",
                resource_solver_level_constraint_mode="soft",
                resource_solver_linkage_mode="simulated",
            )

        self.assertEqual(result, ("out.xlsx", ["ok"], {}, ""))
        config = engine.run.call_args.kwargs["config"]
        self.assertEqual(config.resource_solver_level_constraint_mode, "soft")
        self.assertEqual(config.resource_solver_linkage_mode, "simulated")

    def test_fastapi_app_uses_application_use_case(self):
        import calendaritzacions.app as app
        from calendaritzacions.application import process_calendarization

        self.assertIs(app.process_calendarization, process_calendarization)

    def test_noop_progress_reporter_report_does_not_fail(self):
        from calendaritzacions.application.progress import NoopProgressReporter

        self.assertIsNone(NoopProgressReporter().report("working", percent=50))


if __name__ == "__main__":
    unittest.main()
