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
            data={"engine_name": CalendarizationRun.ENGINE_LEGACY, "phase": CalendarizationRun.PHASE_SECOND},
            files={"input_file": SimpleUploadedFile("input.xlsx", b"data")},
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_form_rejects_unsupported_file_extension(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from calendaritzacions.django.forms import CalendarizationRunForm
        from calendaritzacions.django.models import CalendarizationRun

        form = CalendarizationRunForm(
            data={"engine_name": CalendarizationRun.ENGINE_RESOURCE_SOLVER, "phase": CalendarizationRun.PHASE_FIRST},
            files={"input_file": SimpleUploadedFile("input.txt", b"data")},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("input_file", form.errors)


if __name__ == "__main__":
    unittest.main()
