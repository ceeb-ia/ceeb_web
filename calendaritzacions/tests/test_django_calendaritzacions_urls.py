import importlib.util
import unittest


HAS_DJANGO = importlib.util.find_spec("django") is not None


@unittest.skipUnless(HAS_DJANGO, "django not installed")
class DjangoCalendarizationUrlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from django.apps import apps
        from django.conf import settings
        from django.urls import clear_url_caches, include, path

        if not settings.configured:
            settings.configure(
                INSTALLED_APPS=["django.contrib.contenttypes", "calendaritzacions.django"],
                DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
                SECRET_KEY="tests",
                DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
                ROOT_URLCONF="calendaritzacions.django.urls",
            )
        if not apps.ready:
            import django

            django.setup()
        globals()["urlpatterns"] = [
            path("", include("calendaritzacions.django.urls", namespace="calendaritzacions")),
        ]
        settings.ROOT_URLCONF = __name__
        clear_url_caches()

    def test_urls_expose_expected_names(self):
        from calendaritzacions.django import urls

        self.assertEqual(urls.app_name, "calendaritzacions")
        names = {pattern.name for pattern in urls.urlpatterns}
        self.assertEqual(
            names,
            {
                "run_list",
                "run_create",
                "run_detail",
                "run_delete",
                "run_status",
                "run_download",
                "run_plot",
                "audit_detail",
                "resource_workspace",
                "resource_workspace_incident",
                "resource_workspace_team",
            },
        )

    def test_urls_reverse_with_expected_arguments(self):
        from django.urls import reverse

        self.assertEqual(reverse("calendaritzacions:run_list"), "/")
        self.assertEqual(reverse("calendaritzacions:run_create"), "/new/")
        self.assertEqual(reverse("calendaritzacions:run_detail", kwargs={"pk": 7}), "/runs/7/")
        self.assertEqual(reverse("calendaritzacions:run_delete", kwargs={"pk": 7}), "/runs/7/delete/")
        self.assertEqual(reverse("calendaritzacions:run_status", kwargs={"pk": 7}), "/runs/7/status/")
        self.assertEqual(reverse("calendaritzacions:run_download", kwargs={"pk": 7}), "/runs/7/download/")
        self.assertEqual(
            reverse(
                "calendaritzacions:run_plot",
                kwargs={"pk": 7, "artifact": "input_demand", "plot_id": "heatmap"},
            ),
            "/runs/7/plots/input_demand/heatmap/",
        )
        self.assertEqual(
            reverse("calendaritzacions:audit_detail", kwargs={"pk": 7, "artifact": "resource_solution"}),
            "/runs/7/audit/resource_solution/",
        )
        self.assertEqual(reverse("calendaritzacions:resource_workspace", kwargs={"pk": 7}), "/runs/7/workspace/")
        self.assertEqual(
            reverse("calendaritzacions:resource_workspace_incident", kwargs={"pk": 7, "incident_id": 3}),
            "/runs/7/workspace/incidents/3/",
        )
        self.assertEqual(
            reverse("calendaritzacions:resource_workspace_team", kwargs={"pk": 7, "team_id": "ABC"}),
            "/runs/7/workspace/teams/ABC/",
        )


if __name__ == "__main__":
    unittest.main()
