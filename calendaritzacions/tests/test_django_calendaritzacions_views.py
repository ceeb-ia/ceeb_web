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

    def test_delete_view_deletes_finished_run_and_redirects(self):
        from calendaritzacions.django.views import RunDeleteView

        request = SimpleNamespace()
        input_file = SimpleNamespace(delete=lambda save=False: None)
        run = SimpleNamespace(is_finished=True, input_file=input_file, delete=lambda: None)

        with (
            patch("calendaritzacions.django.views.get_object_or_404", return_value=run) as get_object,
            patch.object(input_file, "delete") as delete_file,
            patch.object(run, "delete") as delete_run,
            patch("calendaritzacions.django.views.redirect") as redirect,
        ):
            redirect.return_value = SimpleNamespace(status_code=302, url="/")
            response = RunDeleteView().post(request, pk=7)

        get_object.assert_called_once()
        delete_file.assert_called_once_with(save=False)
        delete_run.assert_called_once_with()
        redirect.assert_called_once_with("calendaritzacions:run_list")
        self.assertEqual(response.status_code, 302)

    def test_delete_view_rejects_unfinished_run(self):
        from calendaritzacions.django.views import RunDeleteView

        request = SimpleNamespace()
        run = SimpleNamespace(is_finished=False)

        with patch("calendaritzacions.django.views.get_object_or_404", return_value=run):
            response = RunDeleteView().post(request, pk=7)

        self.assertEqual(response.status_code, 400)

    def test_build_plot_galleries_reads_registered_plot_artifacts(self):
        from calendaritzacions.django.views import _build_plot_galleries

        run = SimpleNamespace(pk=7)
        payloads = {
            "input_demand": {"plots": {"heatmap": "/tmp/heatmap.png", "manifest": "/tmp/manifest.json"}},
            "resource_solver_final_plots": {"plots": {"group_sizes": "/tmp/group_sizes.png"}},
        }

        with (
            patch("calendaritzacions.django.views.ensure_run_audit_path", side_effect=lambda _run, artifact: artifact),
            patch("calendaritzacions.django.views.read_json_file", side_effect=lambda path: payloads[path]),
            patch(
                "calendaritzacions.django.views.reverse",
                side_effect=lambda _name, kwargs: f"/runs/{kwargs['pk']}/plots/{kwargs['artifact']}/{kwargs['plot_id']}/",
            ),
        ):
            galleries = _build_plot_galleries(run)

        self.assertEqual([gallery["title"] for gallery in galleries], ["Plots pre-run", "Plots post-run"])
        self.assertEqual(galleries[0]["plots"][0]["id"], "heatmap")
        self.assertIn("/runs/7/plots/input_demand/heatmap/", galleries[0]["plots"][0]["url"])
        self.assertEqual(galleries[1]["plots"][0]["id"], "group_sizes")

    def test_status_view_uses_db_progress_logs_when_redis_has_no_progress(self):
        from calendaritzacions.django.views import RunStatusJsonView

        run = SimpleNamespace(
            pk=7,
            status="running",
            is_finished=False,
            logs=["[5%] Preparant motor resource_solver...", "[20%] Construint context resource_solver..."],
            error_message="",
            output_path="",
            available_audits=[],
        )

        with (
            patch("calendaritzacions.django.views.get_object_or_404", return_value=run),
            patch("logs.read_logs_sync", return_value=[]),
        ):
            response = RunStatusJsonView().get(SimpleNamespace(), pk=7)

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["progress"], 20)

    def test_plot_view_serves_registered_png_inside_audit_directory(self):
        from calendaritzacions.django.views import RunPlotView

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plot_path = root / "plots_input_demand" / "heatmap.png"
            plot_path.parent.mkdir()
            plot_path.write_bytes(b"png")
            audit_path = root / "input_demand.json"
            audit_path.write_text(json.dumps({"plots": {"heatmap": str(plot_path)}}), encoding="utf-8")
            run = SimpleNamespace()

            with (
                patch("calendaritzacions.django.views.get_object_or_404", return_value=run),
                patch("calendaritzacions.django.views.ensure_run_audit_path", return_value=audit_path),
            ):
                response = RunPlotView().get(SimpleNamespace(), pk=7, artifact="input_demand", plot_id="heatmap")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/png")
            response.close()


if __name__ == "__main__":
    unittest.main()
