import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


HAS_DJANGO = importlib.util.find_spec("django") is not None


def configure_django():
    from django.apps import apps
    from django.conf import settings

    if not settings.configured:
        settings.configure(
            INSTALLED_APPS=["django.contrib.contenttypes", "calendaritzacions.django"],
            DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
            SECRET_KEY="tests",
            DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
            USE_TZ=True,
            CALENDARITZACIONS_ASYNC_BACKEND="sync",
        )
    if not apps.ready:
        import django

        django.setup()


def ensure_test_tables():
    from django.db import connection

    from calendaritzacions.django.models import CalendarizationComponentRun, CalendarizationRun

    existing = set(connection.introspection.table_names())
    with connection.schema_editor() as schema_editor:
        if CalendarizationRun._meta.db_table not in existing:
            schema_editor.create_model(CalendarizationRun)
            existing.add(CalendarizationRun._meta.db_table)
        if CalendarizationComponentRun._meta.db_table not in existing:
            schema_editor.create_model(CalendarizationComponentRun)
            existing.add(CalendarizationComponentRun._meta.db_table)


@unittest.skipUnless(HAS_DJANGO, "django not installed")
class ResourceSolverComponentTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        configure_django()
        ensure_test_tables()

    def setUp(self):
        self.created_run_ids = []
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        from django.db import connection

        from calendaritzacions.django.models import CalendarizationComponentRun, CalendarizationRun

        if self.created_run_ids:
            placeholders = ", ".join(["%s"] * len(self.created_run_ids))
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {CalendarizationComponentRun._meta.db_table} WHERE run_id IN ({placeholders})",
                    self.created_run_ids,
                )
                cursor.execute(
                    f"DELETE FROM {CalendarizationRun._meta.db_table} WHERE id IN ({placeholders})",
                    self.created_run_ids,
                )
        self.tmp.cleanup()

    def create_run(self):
        from calendaritzacions.django.models import CalendarizationRun

        run = CalendarizationRun.objects.create(input_file="inputs/a.xlsx")
        self.created_run_ids.append(run.pk)
        return run

    def create_component(self, *, component_id="C001", attempt=1, active_attempt=1, status=None):
        from calendaritzacions.django.models import CalendarizationComponentRun

        run = self.create_run()
        attempt_dir = self.root / "components" / component_id / f"attempt_{attempt:03d}"
        attempt_dir.mkdir(parents=True)
        context_path = attempt_dir / "context.json"
        context_path.write_text(json.dumps({"context": {}}), encoding="utf-8")
        return CalendarizationComponentRun.objects.create(
            run=run,
            component_id=component_id,
            attempt=attempt,
            active_attempt=active_attempt,
            status=status or CalendarizationComponentRun.STATUS_PENDING,
            context_path=str(context_path),
            logs_path=str(attempt_dir / "logs.jsonl"),
            model_summary_path=str(attempt_dir / "model_summary.json"),
            raw_result_path=str(attempt_dir / "raw_result.json"),
            solution_path=str(attempt_dir / "solution_partial.json"),
        )

    def test_enqueue_component_uses_heavy_queue_for_celery_backend(self):
        from django.test import override_settings

        from calendaritzacions.django.models import CalendarizationComponentRun
        from calendaritzacions.django.services.component_tasks import enqueue_component

        component = self.create_component()
        with (
            override_settings(CALENDARITZACIONS_ASYNC_BACKEND="celery"),
            patch(
                "calendaritzacions.django.tasks.solve_resource_component_task.apply_async",
                return_value=SimpleNamespace(id="celery-1"),
            ) as apply_async,
        ):
            result = enqueue_component(component)

        apply_async.assert_called_once_with(
            args=(component.run_id, component.component_id, component.attempt),
            queue="heavy_queue",
        )
        self.assertEqual(result.status, CalendarizationComponentRun.STATUS_QUEUED)
        self.assertIsNotNone(result.queued_at)
        self.assertIn("queued", Path(result.logs_path).read_text(encoding="utf-8"))

    def test_enqueue_component_sync_executes_component_directly(self):
        from django.test import override_settings

        from calendaritzacions.django.models import CalendarizationComponentRun
        from calendaritzacions.django.services.component_tasks import enqueue_component

        component = self.create_component()

        with (
            override_settings(CALENDARITZACIONS_ASYNC_BACKEND="sync"),
            patch(
                "calendaritzacions.engine.variants.resource_solver.component_solver.solve_component_context",
                side_effect=_write_success_artifacts,
            ) as solve_component_context,
        ):
            result = enqueue_component(component)

        solve_component_context.assert_called_once()
        self.assertEqual(result.status, CalendarizationComponentRun.STATUS_SUCCESS)
        self.assertTrue(Path(result.raw_result_path).exists())
        self.assertTrue(Path(result.solution_path).exists())
        self.assertIsNotNone(result.started_at)
        self.assertIsNotNone(result.heartbeat_at)
        self.assertIsNotNone(result.finished_at)

    def test_solve_resource_component_skips_success_with_existing_artifacts(self):
        from calendaritzacions.django.models import CalendarizationComponentRun
        from calendaritzacions.django.services.component_tasks import _solve_resource_component

        component = self.create_component(status=CalendarizationComponentRun.STATUS_SUCCESS)
        Path(component.raw_result_path).write_text(json.dumps({"status": "OPTIMAL"}), encoding="utf-8")
        Path(component.solution_path).write_text(json.dumps({"status": "OPTIMAL"}), encoding="utf-8")

        with patch(
            "calendaritzacions.engine.variants.resource_solver.component_solver.solve_component_context"
        ) as solve_component_context:
            result = _solve_resource_component(component.run_id, component.component_id, component.attempt)

        solve_component_context.assert_not_called()
        self.assertEqual(result, "already_success")

    def test_solve_resource_component_rejects_inactive_attempt(self):
        from calendaritzacions.django.models import CalendarizationComponentRun
        from calendaritzacions.django.services.component_tasks import _solve_resource_component

        component = self.create_component(attempt=1, active_attempt=2)

        with patch(
            "calendaritzacions.engine.variants.resource_solver.component_solver.solve_component_context"
        ) as solve_component_context:
            result = _solve_resource_component(component.run_id, component.component_id, component.attempt)

        solve_component_context.assert_not_called()
        component.refresh_from_db()
        self.assertEqual(result, CalendarizationComponentRun.STATUS_SUPERSEDED)
        self.assertEqual(component.status, CalendarizationComponentRun.STATUS_SUPERSEDED)
        self.assertIn("Intent no actiu", component.error_message)

    def test_solve_resource_component_records_error_artifacts(self):
        from calendaritzacions.django.models import CalendarizationComponentRun
        from calendaritzacions.django.services.component_tasks import _solve_resource_component

        component = self.create_component()

        with patch(
            "calendaritzacions.engine.variants.resource_solver.component_solver.solve_component_context",
            side_effect=RuntimeError("boom"),
        ):
            result = _solve_resource_component(component.run_id, component.component_id, component.attempt)

        component.refresh_from_db()
        self.assertEqual(result, "error")
        self.assertEqual(component.status, CalendarizationComponentRun.STATUS_ERROR)
        self.assertEqual(component.error_message, "boom")
        self.assertTrue(Path(component.error_path).exists())
        self.assertIn("RuntimeError: boom", Path(component.error_path).read_text(encoding="utf-8"))
        self.assertIn('"event": "error"', Path(component.logs_path).read_text(encoding="utf-8"))

    def test_task_delegates_to_component_service(self):
        from calendaritzacions.django import tasks

        with patch(
            "calendaritzacions.django.services.component_tasks._solve_resource_component",
            return_value="success",
        ) as solve:
            result = tasks.solve_resource_component_task.run(12, "C001", 1)

        solve.assert_called_once_with(12, "C001", 1)
        self.assertEqual(result, "success")

    def test_finalize_components_aliases_merged_solution_for_workspace(self):
        from calendaritzacions.django.models import CalendarizationComponentRun, CalendarizationRun
        from calendaritzacions.django.services.component_tasks import _finalize_run_if_components_complete

        run = self.create_run()
        run.engine_name = CalendarizationRun.ENGINE_RESOURCE_SOLVER
        run.input_name = "input.xlsx"
        run.audit_paths = {"team_catalog": str(self.root / "team_catalog.json")}
        run.save(update_fields=["engine_name", "input_name", "audit_paths"])

        for component_id in ("C001", "C002"):
            attempt_dir = self.root / "components" / component_id / "attempt_001"
            attempt_dir.mkdir(parents=True)
            context_path = attempt_dir / "context.json"
            context_path.write_text(json.dumps({"context": {}}), encoding="utf-8")
            CalendarizationComponentRun.objects.create(
                run=run,
                component_id=component_id,
                attempt=1,
                active_attempt=1,
                status=CalendarizationComponentRun.STATUS_SUCCESS,
                context_path=str(context_path),
            )

        payload = {
            "solution": {
                "status": "FEASIBLE",
                "assignments": [{"team_id": "A", "group_id": "G1", "number": 1}],
                "real_matches": [],
                "resource_usage": [],
                "group_summary": [],
                "entity_excess": {},
                "logs": ["merged"],
            }
        }
        result = SimpleNamespace(status="FEASIBLE", logs=("merged",))

        with (
            patch("calendaritzacions.django.services.component_tasks._merge_active_components", return_value=payload),
            patch("calendaritzacions.django.services.component_tasks._resource_solver_result_from_payload", return_value=result),
            patch("calendaritzacions.django.services.component_tasks._combined_context_from_components", return_value=SimpleNamespace()),
            patch("calendaritzacions.reporting.resource_solver_excel_adapter.write_resource_solver_workbook"),
        ):
            finalized = _finalize_run_if_components_complete(run.pk)

        run.refresh_from_db()
        merged_solution = str(self.root / "merged" / "merged_solution.json")
        self.assertTrue(finalized)
        self.assertEqual(run.audit_paths["component_merged_solution"], merged_solution)
        self.assertEqual(run.audit_paths["resource_solution"], merged_solution)
        self.assertEqual(run.audit_paths["resource_solver_result"], merged_solution)


def _write_success_artifacts(_context_path, output_dir, *, component_id=None):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    model_summary_path = output_path / "model_summary.json"
    raw_result_path = output_path / "raw_result.json"
    solution_path = output_path / "solution_partial.json"
    model_summary_path.write_text(json.dumps({"component_id": component_id}), encoding="utf-8")
    raw_result_path.write_text(json.dumps({"status": "OPTIMAL"}), encoding="utf-8")
    solution_path.write_text(json.dumps({"status": "OPTIMAL"}), encoding="utf-8")
    return {
        "status": "OPTIMAL",
        "paths": {
            "model_summary": str(model_summary_path),
            "raw_result": str(raw_result_path),
            "solution_partial": str(solution_path),
        },
    }


if __name__ == "__main__":
    unittest.main()
