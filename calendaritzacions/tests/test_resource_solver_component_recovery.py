import importlib.util
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
            USE_TZ=True,
        )
    if not apps.ready:
        import django

        django.setup()


class FakeQuerySet(list):
    def filter(self, *args, **kwargs):
        values = list(self)
        for key, expected in kwargs.items():
            if key == "status":
                values = [item for item in values if item.status == expected]
            elif key == "status__in":
                values = [item for item in values if item.status in expected]
            elif key == "run_id":
                values = [item for item in values if item.run_id == expected]
            elif key == "component_id":
                values = [item for item in values if item.component_id == expected]
        return FakeQuerySet(values)

    def order_by(self, *fields):
        return FakeQuerySet(sorted(self, key=lambda item: (item.component_id, item.attempt)))


class FakeManager:
    def __init__(self, items):
        self.items = FakeQuerySet(items)

    def filter(self, *args, **kwargs):
        return self.items.filter(*args, **kwargs)

    def create(self, **kwargs):
        item = component(**kwargs)
        self.items.append(item)
        return item


class FakeComponentModel:
    DoesNotExist = LookupError

    def __init__(self, items):
        self.objects = FakeManager(items)


def component(**kwargs):
    fields = {
        "run_id": 12,
        "component_id": "C001",
        "status": "running",
        "attempt": 1,
        "active_attempt": 1,
        "queued_at": None,
        "started_at": None,
        "heartbeat_at": None,
        "finished_at": None,
        "team_count": 2,
        "candidate_count": 4,
        "competition_count": 1,
        "resource_count": 1,
        "linkage_count": 0,
        "context_path": "",
        "validation_path": "",
        "model_summary_path": "",
        "raw_result_path": "",
        "solution_path": "",
        "logs_path": "",
        "error_path": "",
        "error_message": "",
    }
    fields.update(kwargs)
    item = SimpleNamespace(**fields)
    item.saved = []
    item.save = lambda **save_kwargs: item.saved.append(save_kwargs)
    return item


@unittest.skipUnless(HAS_DJANGO, "django not installed")
class ResourceSolverComponentRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        configure_django()

    def test_get_component_model_is_defensive_when_pcs01_is_absent(self):
        from calendaritzacions.django.services.component_recovery import (
            ComponentRecoveryUnavailable,
            get_component_run_model,
        )

        try:
            model = get_component_run_model()
        except ComponentRecoveryUnavailable:
            return
        self.assertEqual(model.__name__, "CalendarizationComponentRun")

    def test_mark_stale_components_updates_running_components(self):
        from calendaritzacions.django.services.component_recovery import mark_stale_components

        stale = component(status="running")
        model = FakeComponentModel([stale])

        result = mark_stale_components(run_id=12, component_model=model)

        self.assertEqual(result, [stale])
        self.assertEqual(stale.status, "stale")
        self.assertIn("watchdog", stale.error_message)
        self.assertEqual(stale.saved[-1], {"update_fields": ["status", "error_message"]})

    def test_reconcile_requeues_stale_component_with_injected_hook(self):
        from calendaritzacions.django.services.component_recovery import reconcile_component_runs

        stale = component(status="stale", attempt=1)
        model = FakeComponentModel([stale])
        enqueue = Mock()

        with patch("calendaritzacions.django.services.component_recovery.rebuild_component_manifest", return_value=""):
            result = reconcile_component_runs(run_id=12, component_model=model, enqueue_component=enqueue, max_attempts=3)

        self.assertEqual(len(result.requeued), 1)
        self.assertEqual(result.requeued[0].attempt, 2)
        self.assertEqual(stale.status, "stale")
        enqueue.assert_called_once_with(result.requeued[0])

    def test_reconcile_marks_stale_component_error_after_max_attempts(self):
        from calendaritzacions.django.services.component_recovery import reconcile_component_runs

        stale = component(status="stale", attempt=3)
        model = FakeComponentModel([stale])

        with patch("calendaritzacions.django.services.component_recovery.rebuild_component_manifest", return_value=""):
            result = reconcile_component_runs(run_id=12, component_model=model, max_attempts=3)

        self.assertEqual(result.marked_error, [stale])
        self.assertEqual(stale.status, "error")

    def test_prepare_component_rerun_creates_new_attempt_without_deleting_previous(self):
        from calendaritzacions.django.services.component_recovery import prepare_component_rerun

        previous = component(
            status="error",
            attempt=1,
            active_attempt=1,
            context_path=r"C:\audit\components\C001\attempt_001\context.json",
        )
        model = FakeComponentModel([previous])
        enqueue = Mock()

        new_component = prepare_component_rerun(
            run_id=12,
            component_id="C001",
            component_model=model,
            enqueue_component=enqueue,
        )

        self.assertEqual(previous.active_attempt, 2)
        self.assertEqual(previous.status, "error")
        self.assertEqual(new_component.attempt, 2)
        self.assertEqual(new_component.active_attempt, 2)
        self.assertEqual(new_component.status, "queued")
        self.assertIn("attempt_002", new_component.context_path)
        self.assertEqual(len(model.objects.items), 2)
        enqueue.assert_called_once_with(new_component)

    def test_prepare_component_rerun_uses_next_free_attempt_number(self):
        from calendaritzacions.django.services.component_recovery import prepare_component_rerun

        active = component(status="error", attempt=1, active_attempt=1)
        old_attempt = component(status="superseded", attempt=2, active_attempt=1)
        model = FakeComponentModel([active, old_attempt])

        new_component = prepare_component_rerun(run_id=12, component_id="C001", component_model=model)

        self.assertEqual(new_component.attempt, 3)
        self.assertEqual(active.active_attempt, 3)
        self.assertEqual(old_attempt.active_attempt, 3)

    def test_rebuild_component_manifest_writes_json_when_path_can_be_inferred(self):
        from calendaritzacions.django.services.component_recovery import rebuild_component_manifest

        with tempfile.TemporaryDirectory() as tmpdir:
            context_path = Path(tmpdir) / "components" / "C001" / "attempt_001" / "context.json"
            run_component = component(status="success", context_path=str(context_path))
            model = FakeComponentModel([run_component])

            manifest_path = rebuild_component_manifest(12, component_model=model)

            self.assertTrue(Path(manifest_path).exists())
            self.assertTrue(manifest_path.endswith("components\\manifest.json") or manifest_path.endswith("components/manifest.json"))
            self.assertIn('"component_id": "C001"', Path(manifest_path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
