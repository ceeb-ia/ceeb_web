import importlib.util
import unittest
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
            ROOT_URLCONF="calendaritzacions.django.urls",
            ALLOWED_HOSTS=["testserver"],
        )
    if not apps.ready:
        import django

        django.setup()


@unittest.skipUnless(HAS_DJANGO, "django not installed")
class DjangoCalendarizationViewsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        configure_django()

    def test_create_view_form_valid_saves_and_enqueues(self):
        from calendaritzacions.django.views import RunCreateView

        view = RunCreateView()
        run = SimpleNamespace(pk=5)
        form = SimpleNamespace(save=lambda: run)

        with (
            patch("calendaritzacions.django.views.enqueue_run") as enqueue,
            patch("calendaritzacions.django.views.redirect") as redirect,
        ):
            redirect.return_value = SimpleNamespace(status_code=302, url="/runs/5/")
            response = view.form_valid(form)

        enqueue.assert_called_once_with(run)
        self.assertEqual(response.status_code, 302)
        redirect.assert_called_once_with("calendaritzacions:run_detail", pk=5)

    def test_audit_detail_uses_safe_storage_helper(self):
        from calendaritzacions.django.views import AuditDetailView

        view = AuditDetailView()
        view.object = SimpleNamespace()
        view.kwargs = {"artifact": "resource_solution"}

        from django.views.generic import DetailView

        with (
            patch.object(DetailView, "get_context_data", return_value={}),
            patch("calendaritzacions.django.views.ensure_run_audit_path", return_value="/tmp/resource_solution.json") as ensure,
            patch("calendaritzacions.django.views.read_json_file", return_value={"ok": True}) as read_json,
            patch("calendaritzacions.django.views.build_audit_presentation", return_value={"title": "Audit"}) as presenter,
        ):
            context = view.get_context_data()

        ensure.assert_called_once_with(view.object, "resource_solution")
        read_json.assert_called_once_with("/tmp/resource_solution.json")
        presenter.assert_called_once_with("resource_solution", {"ok": True}, related_payloads={})
        self.assertEqual(context["audit"]["payload"], {"ok": True})
        self.assertEqual(context["audit"]["presentation"], {"title": "Audit"})


if __name__ == "__main__":
    unittest.main()
