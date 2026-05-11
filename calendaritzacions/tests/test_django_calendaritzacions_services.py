import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


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
            CALENDARITZACIONS_ASYNC_BACKEND="sync",
        )
    if not apps.ready:
        import django

        django.setup()


class FakeRun:
    pk = 12

    def __init__(self):
        self.input_file = SimpleNamespace(path="input.xlsx")
        self.phase = "segona_fase"
        self.engine_name = "resource_solver"
        self.statuses = []

    def mark_running(self):
        self.statuses.append("running")

    def mark_success(self, **kwargs):
        self.statuses.append("success")
        self.success_kwargs = kwargs

    def mark_error(self, message, logs=None):
        self.statuses.append("error")
        self.error_message = message
        self.error_logs = logs


@unittest.skipUnless(HAS_DJANGO, "django not installed")
class DjangoCalendarizationServicesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        configure_django()

    def test_execute_run_calls_application_boundary(self):
        from calendaritzacions.django.services.runs import execute_run

        run = FakeRun()
        with patch(
            "calendaritzacions.django.services.runs.process_calendarization",
            return_value=("/tmp/output.xlsx", ["log"], {"audit": "/tmp/audit.json"}),
        ) as process:
            result = execute_run(run)

        self.assertIs(result, run)
        process.assert_called_once_with(
            input_path="input.xlsx",
            return_logs=True,
            return_artifacts=True,
            task_id="12",
            segona_fase_bool=True,
            engine_name="resource_solver",
        )
        self.assertEqual(run.statuses, ["running", "success"])
        self.assertEqual(run.success_kwargs["output_path"], "/tmp/output.xlsx")
        self.assertEqual(run.success_kwargs["logs"], ["log"])

    def test_execute_run_marks_error(self):
        from calendaritzacions.django.services.runs import execute_run

        run = FakeRun()
        with patch("calendaritzacions.django.services.runs.process_calendarization", side_effect=ValueError("boom")):
            execute_run(run)

        self.assertEqual(run.statuses, ["running", "error"])
        self.assertEqual(run.error_message, "boom")

    def test_worker_lost_signal_marks_run_error(self):
        from calendaritzacions.django import tasks

        run = SimpleNamespace(is_finished=False, logs=["abans"])
        run.mark_error = Mock()
        manager = SimpleNamespace(get=Mock(return_value=run))
        model = SimpleNamespace(objects=manager, DoesNotExist=Exception)
        sender = SimpleNamespace(name=tasks.execute_calendarization_run_task.name)

        with patch.dict("sys.modules", {"calendaritzacions.django.models": SimpleNamespace(CalendarizationRun=model)}):
            tasks.mark_calendarization_worker_lost(
                sender=sender,
                exception=Exception("WorkerLostError: signal 9 (SIGKILL)"),
                args=(12,),
            )

        manager.get.assert_called_once_with(pk=12)
        run.mark_error.assert_called_once()
        message = run.mark_error.call_args.args[0]
        logs = run.mark_error.call_args.kwargs["logs"]
        self.assertIn("falta de memòria", message)
        self.assertEqual(logs[0], "abans")
        self.assertIn("SIGKILL", logs[-1])

    def test_worker_lost_signal_ignores_other_tasks(self):
        from calendaritzacions.django import tasks

        sender = SimpleNamespace(name="other.task")

        with patch("calendaritzacions.django.models.CalendarizationRun.objects.get") as get:
            tasks.mark_calendarization_worker_lost(
                sender=sender,
                exception=Exception("WorkerLostError: signal 9"),
                args=(12,),
            )

        get.assert_not_called()

    def test_audit_reader_discovers_and_reads_json(self):
        from calendaritzacions.django.services.audit_reader import discover_audit_paths, read_audit_artifact

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "out.xlsx"
            output.write_bytes(b"x")
            audit = root / "resource_solution.json"
            audit.write_text(json.dumps({"ok": True}), encoding="utf-8")
            candidates = root / "candidate_catalog.json"
            candidates.write_text(json.dumps({"items": []}), encoding="utf-8")

            discovered = discover_audit_paths(str(output))
            payload = read_audit_artifact(SimpleNamespace(audit_paths=discovered), "resource_solution")

        self.assertEqual(payload["payload"], {"ok": True})
        self.assertIn("candidate_catalog", discovered)

    def test_storage_rejects_download_before_success(self):
        from django.http import Http404

        from calendaritzacions.django.services.storage import ensure_run_output_is_downloadable

        run = SimpleNamespace(status="pending", output_path="/tmp/out.xlsx")

        with self.assertRaises(Http404):
            ensure_run_output_is_downloadable(run)

    def test_storage_requires_registered_audit_artifact(self):
        from django.http import Http404

        from calendaritzacions.django.services.storage import ensure_run_audit_path

        run = SimpleNamespace(audit_paths={})

        with self.assertRaises(Http404):
            ensure_run_audit_path(run, "missing")


if __name__ == "__main__":
    unittest.main()
