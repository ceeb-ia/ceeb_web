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
        )
    if not apps.ready:
        import django

        django.setup()


@unittest.skipUnless(HAS_DJANGO, "django not installed")
class DjangoCalendarizationRunFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        configure_django()

    def test_form_accepts_supported_engine_phase_and_file_extension(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from calendaritzacions.django.forms import CalendarizationRunForm
        from calendaritzacions.django.models import CalendarizationRun

        form = CalendarizationRunForm(
            data={
                "engine_name": CalendarizationRun.ENGINE_LEGACY,
                "phase": CalendarizationRun.PHASE_SECOND,
                "resource_solver_linkage_mode": CalendarizationRun.LINKAGE_MODE_SIMULATED,
                "resource_solver_level_constraint_mode": CalendarizationRun.LEVEL_CONSTRAINT_SOFT,
                "resource_solver_decomposition_mode": CalendarizationRun.RESOURCE_SOLVER_DECOMPOSITION_AUDIT_ONLY,
            },
            files={"input_file": SimpleUploadedFile("input.xlsx", b"data")},
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["resource_solver_level_constraint_mode"],
            CalendarizationRun.LEVEL_CONSTRAINT_SOFT,
        )
        self.assertEqual(
            form.cleaned_data["resource_solver_linkage_mode"],
            CalendarizationRun.LINKAGE_MODE_SIMULATED,
        )
        self.assertNotIn(
            CalendarizationRun.ENGINE_RESOURCE_SOLVER_VINCULACIO,
            dict(form.fields["engine_name"].choices),
        )

    def test_form_rejects_unsupported_file_extension(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from calendaritzacions.django.forms import CalendarizationRunForm
        from calendaritzacions.django.models import CalendarizationRun

        form = CalendarizationRunForm(
            data={
                "engine_name": CalendarizationRun.ENGINE_RESOURCE_SOLVER,
                "phase": CalendarizationRun.PHASE_FIRST,
                "resource_solver_linkage_mode": CalendarizationRun.LINKAGE_MODE_INPUT,
                "resource_solver_decomposition_mode": CalendarizationRun.RESOURCE_SOLVER_DECOMPOSITION_AUDIT_ONLY,
            },
            files={"input_file": SimpleUploadedFile("input.txt", b"data")},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("input_file", form.errors)

    def test_form_exposes_aggregate_level_constraint_mode(self):
        from calendaritzacions.django.forms import CalendarizationRunForm
        from calendaritzacions.django.models import CalendarizationRun

        form = CalendarizationRunForm()

        choices = dict(form.fields["resource_solver_level_constraint_mode"].choices)
        self.assertEqual(choices[CalendarizationRun.LEVEL_CONSTRAINT_AGGREGATE], "Suau agregat")


if __name__ == "__main__":
    unittest.main()
