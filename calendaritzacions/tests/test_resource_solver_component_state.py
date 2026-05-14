import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


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
class ResourceSolverComponentStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        configure_django()
        ensure_test_tables()

    def setUp(self):
        self.created_run_ids = []

    def tearDown(self):
        from django.db import connection

        from calendaritzacions.django.models import CalendarizationComponentRun, CalendarizationRun

        if not self.created_run_ids:
            return

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

    def create_run(self):
        from calendaritzacions.django.models import CalendarizationRun

        run = CalendarizationRun.objects.create(input_file="inputs/a.xlsx")
        self.created_run_ids.append(run.pk)
        return run

    def test_component_paths_are_stable(self):
        from calendaritzacions.django.services.component_runs import component_attempt_dir, component_manifest_path

        root = Path("/tmp/audit")

        self.assertEqual(component_attempt_dir(root, "C001"), root / "components" / "C001" / "attempt_001")
        self.assertEqual(component_attempt_dir(root, "C001", attempt=12), root / "components" / "C001" / "attempt_012")
        self.assertEqual(component_manifest_path(root), root / "components" / "manifest.json")

    def test_atomic_write_json_and_text_replace_complete_files(self):
        from calendaritzacions.django.services.component_runs import atomic_write_json, atomic_write_text

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / "nested" / "payload.json"
            text_path = root / "nested" / "logs.txt"

            atomic_write_json(json_path, {"component_id": "C001", "values": [2, 1]})
            atomic_write_text(text_path, "ready\n")

            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["component_id"], "C001")
            self.assertEqual(text_path.read_text(encoding="utf-8"), "ready\n")

    def test_atomic_write_json_does_not_create_target_when_serialization_fails(self):
        from calendaritzacions.django.services.component_runs import atomic_write_json

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "payload.json"

            with self.assertRaises(TypeError):
                atomic_write_json(target, {"bad": object()})

            self.assertFalse(target.exists())

    def test_create_or_update_component_run_is_idempotent(self):
        from calendaritzacions.django.models import CalendarizationComponentRun
        from calendaritzacions.django.services.component_runs import create_or_update_component_run

        run = self.create_run()

        first = create_or_update_component_run(
            run=run,
            component_id="C001",
            team_count=2,
            context_path="components/C001/attempt_001/context.json",
        )
        second = create_or_update_component_run(
            run=run,
            component_id="C001",
            candidate_count=7,
            context_path="components/C001/attempt_001/context.v2.json",
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(CalendarizationComponentRun.objects.count(), 1)
        self.assertEqual(second.status, CalendarizationComponentRun.STATUS_PENDING)
        self.assertEqual(second.attempt, 1)
        self.assertEqual(second.active_attempt, 1)
        self.assertEqual(second.team_count, 2)
        self.assertEqual(second.candidate_count, 7)
        self.assertEqual(second.context_path, "components/C001/attempt_001/context.v2.json")

    def test_unique_constraint_blocks_duplicate_attempts(self):
        from django.db import IntegrityError, transaction

        from calendaritzacions.django.models import CalendarizationComponentRun

        run = self.create_run()
        CalendarizationComponentRun.objects.create(run=run, component_id="C001", attempt=1)

        with self.assertRaises(IntegrityError), transaction.atomic():
            CalendarizationComponentRun.objects.create(run=run, component_id="C001", attempt=1)

    def test_heartbeat_only_updates_the_active_attempt(self):
        from calendaritzacions.django.models import CalendarizationComponentRun
        from calendaritzacions.django.services.component_runs import (
            create_or_update_component_run,
            heartbeat_component,
            mark_component_status,
        )

        run = self.create_run()
        first = create_or_update_component_run(run=run, component_id="C001", attempt=1)
        mark_component_status(first, CalendarizationComponentRun.STATUS_RUNNING)
        first_heartbeat = first.heartbeat_at

        second = create_or_update_component_run(run=run, component_id="C001", attempt=2, active_attempt=2)
        first.refresh_from_db()

        self.assertEqual(first.active_attempt, 2)
        self.assertFalse(heartbeat_component(first))
        first.refresh_from_db()
        self.assertEqual(first.heartbeat_at, first_heartbeat)

        self.assertTrue(heartbeat_component(second))
        second.refresh_from_db()
        self.assertIsNotNone(second.heartbeat_at)

    def test_mark_component_status_sets_timestamps_and_error_message(self):
        from calendaritzacions.django.models import CalendarizationComponentRun
        from calendaritzacions.django.services.component_runs import create_or_update_component_run, mark_component_status

        run = self.create_run()
        component_run = create_or_update_component_run(run=run, component_id="C001")

        mark_component_status(component_run, CalendarizationComponentRun.STATUS_QUEUED)
        self.assertIsNotNone(component_run.queued_at)

        mark_component_status(component_run, CalendarizationComponentRun.STATUS_RUNNING)
        self.assertIsNotNone(component_run.started_at)
        self.assertIsNotNone(component_run.heartbeat_at)
        self.assertIsNone(component_run.finished_at)

        mark_component_status(component_run, CalendarizationComponentRun.STATUS_ERROR, error_message="boom")
        self.assertEqual(component_run.error_message, "boom")
        self.assertIsNotNone(component_run.finished_at)


if __name__ == "__main__":
    unittest.main()
