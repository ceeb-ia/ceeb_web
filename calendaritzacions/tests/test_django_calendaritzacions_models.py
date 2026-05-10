import importlib.util
import unittest


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


@unittest.skipUnless(HAS_DJANGO, "django not installed")
class DjangoCalendarizationRunModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        configure_django()

    def test_model_defaults_and_helpers(self):
        from calendaritzacions.django.models import CalendarizationRun

        run = CalendarizationRun(input_file="inputs/a.xlsx", audit_paths={"resource_solution": "/tmp/a.json"})

        self.assertEqual(run.status, CalendarizationRun.STATUS_PENDING)
        self.assertEqual(run.engine_name, CalendarizationRun.ENGINE_RESOURCE_SOLVER)
        self.assertEqual(run.phase, CalendarizationRun.PHASE_FIRST)
        self.assertFalse(run.is_finished)
        self.assertEqual(run.available_audits, ["resource_solution"])

    def test_mark_methods_update_state_without_requiring_db_in_unit_test(self):
        from calendaritzacions.django.models import CalendarizationRun

        run = CalendarizationRun(input_file="inputs/a.xlsx")
        saved_fields = []
        run._save_status_fields = lambda fields: saved_fields.append(fields)

        run.mark_running()
        self.assertEqual(run.status, CalendarizationRun.STATUS_RUNNING)
        self.assertEqual(saved_fields[-1], ["status", "started_at", "finished_at", "error_message"])

        run.mark_success(output_path="/tmp/out.xlsx", logs=["ok"], audit_paths={"a": "/tmp/a.json"})
        self.assertEqual(run.status, CalendarizationRun.STATUS_SUCCESS)
        self.assertEqual(run.output_path, "/tmp/out.xlsx")
        self.assertEqual(run.logs, ["ok"])
        self.assertEqual(run.audit_paths, {"a": "/tmp/a.json"})

        run.mark_error("boom", logs=["x"])
        self.assertEqual(run.status, CalendarizationRun.STATUS_ERROR)
        self.assertEqual(run.error_message, "boom")
        self.assertEqual(run.logs, ["x"])


if __name__ == "__main__":
    unittest.main()
