import asyncio
import json
import os
import tempfile
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from openpyxl import Workbook

from .tasks import build_cluster_preview_task
from .views import (
    cluster_preview_create_view,
    cluster_preview_detail_view,
    cluster_preview_map_view,
    cluster_preview_run_view,
    cluster_preview_status_view,
)


def _xlsx_upload(name: str, headers: list[str], rows: list[list[object]]) -> SimpleUploadedFile:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    data = BytesIO()
    workbook.save(data)
    data.seek(0)
    return SimpleUploadedFile(
        name,
        data.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


class ClusterPreviewBackendViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.media_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_tmp.cleanup)

    def _matches_upload(self, name="partits.xlsx"):
        return _xlsx_upload(
            name,
            [
                "Codi",
                "Codis Tutor de Joc",
                "Club Local",
                "Equip local",
                "Equip visitant",
                "Lliga",
                "Categoria",
                "Modalitat",
                "Domicili",
                "Municipi",
                "Pista joc",
            ],
            [[
                "P1",
                "",
                "Club Local",
                "Equip Local",
                "Equip Visitant",
                "Lliga A",
                "ALEVI",
                "FUTBOL 5",
                "Carrer Prova 1",
                "Barcelona",
                "Pista 1",
            ]],
        )

    def _availability_upload(self, name="disponibilitats.xlsx"):
        return _xlsx_upload(
            name,
            ["Codi Tutor de Joc", "Nom", "Nivell", "Categoria", "Data", "Hora Inici", "Hora Fi"],
            [["5001 F5", "Tutor Prova", "NIVELL A", "TUTOR/TUTORA DE JOC", "2026-04-17", "18:00", "21:00"]],
        )

    def test_cluster_preview_create_view_returns_queued_job_payload(self):
        request = self.factory.post(
            reverse("designacions_cluster_preview_create"),
            data={
                "files": [self._availability_upload(), self._matches_upload()],
                "cluster_eps_m": "650",
                "cluster_min_samples": "3",
                "modalitats_csv": "FUTBOL 5, FUTBOL SALA",
                "date_from": "2026-04-17",
                "date_to": "2026-04-19",
                "fase": "FS2",
            },
        )

        with self.settings(MEDIA_ROOT=self.media_tmp.name), \
             patch("designacions.views.uuid.uuid4", return_value=SimpleNamespace(hex="preview-123")), \
             patch("designacions.views.write_job_sync") as write_job_sync_mock, \
             patch("designacions.views.build_cluster_preview_task.delay") as delay_mock:
            response = cluster_preview_create_view(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(payload["preview_id"], "preview-123")
        self.assertEqual(payload["task_id"], "preview-123")
        self.assertEqual(payload["status"], "queued")
        self.assertEqual(payload["params"]["cluster_eps_m"], 650.0)
        self.assertEqual(payload["params"]["cluster_min_samples"], 3)
        self.assertEqual(payload["params"]["modalitats"], ["FUTBOL 5", "FUTBOL SALA"])
        self.assertEqual(payload["params"]["fase"], "FS2")
        self.assertTrue(payload["detail_url"].endswith("/designacions/cluster-preview/preview-123/"))
        self.assertTrue(payload["status_url"].endswith("/designacions/cluster-preview/preview-123/status/"))
        self.assertTrue(payload["map_url"].endswith("/designacions/cluster-preview/preview-123/map/"))

        write_job_sync_mock.assert_called_once()
        delay_args = delay_mock.call_args.args
        self.assertEqual(delay_args[0], "preview-123")
        self.assertIn("preview-123__preview__disponibilitats", delay_args[1])
        self.assertIn("preview-123__preview__partits", delay_args[2])
        self.assertEqual(delay_args[3]["date_from"], "2026-04-17")

    def test_cluster_preview_detail_view_exposes_done_result(self):
        request = self.factory.get(reverse("designacions_cluster_preview_detail", args=["preview-123"]))
        job = {
            "status": "done",
            "progress": 100,
            "message": "Preview llest",
            "params": {"cluster_eps_m": 500.0},
            "detected_files": {"partits.xlsx": "partits"},
            "result": {"metrics": {"cluster_count": 4}},
            "map_path": "designacions/previews/preview-123.html",
        }

        with patch("designacions.views.read_job_sync", return_value=job), \
             patch("designacions.views.read_job_logs_sync", return_value=[{"message": "Log historic"}]), \
             patch("designacions.views.read_preview_map_html_sync", return_value="<html>map</html>"):
            response = cluster_preview_detail_view(request, "preview-123")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Previsualitzacio de geolocalitzacio", content)
        self.assertIn("Preview llest", content)
        self.assertIn("Obrir mapa", content)
        self.assertIn("Log historic", content)

    def test_cluster_preview_status_view_reports_processing_without_result(self):
        request = self.factory.get(reverse("designacions_cluster_preview_status", args=["preview-123"]))
        job = {
            "status": "processing",
            "progress": 42,
            "message": "Geocodificant",
            "params": {"cluster_eps_m": 500.0},
            "updated_at": 1000.0,
        }

        with patch("designacions.views.read_job_sync", return_value=job), \
             patch("designacions.views.time.time", return_value=1035.0), \
             patch("designacions.views.read_preview_map_html_sync", return_value=None):
            response = cluster_preview_status_view(request, "preview-123")

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "processing")
        self.assertEqual(payload["progress"], 42)
        self.assertFalse(payload["map_ready"])
        self.assertTrue(payload["stalled"])
        self.assertEqual(payload["seconds_since_update"], 35)
        self.assertNotIn("result", payload)

    def test_cluster_preview_map_view_returns_html_when_available(self):
        request = self.factory.get(reverse("designacions_cluster_preview_map", args=["preview-123"]))

        with patch("designacions.views.read_job_sync", return_value={"status": "done", "map_path": "designacions/previews/preview-123.html"}), \
             patch("designacions.views.read_preview_map_html_sync", return_value="<html><body>Mapa preview</body></html>"):
            response = cluster_preview_map_view(request, "preview-123")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertEqual(response["Referrer-Policy"], "strict-origin-when-cross-origin")
        self.assertIn("Mapa preview", response.content.decode("utf-8"))

    def test_cluster_preview_map_view_returns_requested_eps_map(self):
        request = self.factory.get(f"{reverse('designacions_cluster_preview_map', args=['preview-123'])}?eps_m=650")
        job = {
            "status": "done",
            "map_path": "designacions/previews/preview-123.html",
            "result": {
                "scenarios": [
                    {"eps_m": 500, "map_path": "designacions/previews/preview-123__eps_500.html"},
                    {"eps_m": 650, "map_path": "designacions/previews/preview-123__eps_650.html"},
                ]
            },
        }

        with patch("designacions.views.read_job_sync", return_value=job), \
             patch("designacions.views.read_preview_map_html_sync", return_value="<html><body>Mapa 650</body></html>") as read_map_mock:
            response = cluster_preview_map_view(request, "preview-123")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Mapa 650", response.content.decode("utf-8"))
        self.assertEqual(read_map_mock.call_args.kwargs["rel_path"], "designacions/previews/preview-123__eps_650.html")

    def test_cluster_preview_map_view_returns_conflict_while_processing(self):
        request = self.factory.get(reverse("designacions_cluster_preview_map", args=["preview-123"]))

        with patch("designacions.views.read_job_sync", return_value={"status": "processing", "message": "Encara treballant"}), \
             patch("designacions.views.read_preview_map_html_sync", return_value=None):
            response = cluster_preview_map_view(request, "preview-123")

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(payload["status"], "processing")
        self.assertEqual(payload["message"], "Encara treballant")

    def test_cluster_preview_run_view_queues_run_with_selected_eps(self):
        path_partits = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        path_disponibilitats = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        self.addCleanup(lambda: os.path.exists(path_partits.name) and os.remove(path_partits.name))
        self.addCleanup(lambda: os.path.exists(path_disponibilitats.name) and os.remove(path_disponibilitats.name))
        path_partits.close()
        path_disponibilitats.close()

        request = self.factory.post(
            reverse("designacions_cluster_preview_run", args=["preview-123"]),
            data={"selected_eps_m": "650"},
        )
        request.user = SimpleNamespace(is_authenticated=True)
        job = {
            "status": "done",
            "params": {"cluster_eps_m": 500.0, "modalitats": ["VOLEIBOL"]},
            "path_partits": path_partits.name,
            "path_disponibilitats": path_disponibilitats.name,
            "detected_files": {"partits.xlsx": "partits"},
            "result": {"scenarios": [{"eps_m": 500}, {"eps_m": 650}]},
        }

        with patch("designacions.views.read_job_sync", return_value=job), \
             patch("designacions.views.uuid.uuid4", return_value=SimpleNamespace(hex="run-123")), \
             patch("designacions.views.DesignationRun.objects.create", return_value=SimpleNamespace(id=77)) as create_run_mock, \
             patch("designacions.views.write_job_sync") as write_job_sync_mock, \
             patch("designacions.views.process_designacions_run.delay") as delay_mock:
            response = cluster_preview_run_view(request, "preview-123")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/designacions/run/77/"))
        create_run_mock.assert_called_once()
        self.assertEqual(create_run_mock.call_args.kwargs["params"]["cluster_eps_m"], 650)
        self.assertEqual(create_run_mock.call_args.kwargs["params"]["source_preview_id"], "preview-123")
        write_job_sync_mock.assert_called_once()
        delay_args = delay_mock.call_args.args
        self.assertEqual(delay_args[0], 77)
        self.assertEqual(delay_args[1], "run-123")
        self.assertEqual(delay_args[2], path_disponibilitats.name)
        self.assertEqual(delay_args[3], path_partits.name)
        self.assertEqual(delay_args[4]["cluster_eps_m"], 650)


class ClusterPreviewBackendTaskTests(SimpleTestCase):
    def _async_to_sync_wrapper(self, func):
        def wrapped(*args, **kwargs):
            return asyncio.run(func(*args, **kwargs))

        return wrapped

    def test_build_cluster_preview_task_stores_result_and_map(self):
        writes = []
        logs = []
        captured = {}

        async def fake_write_job(task_id, data):
            writes.append((task_id, data))

        async def fake_push_log(task_id, message, progress=None, status=None):
            logs.append({
                "task_id": task_id,
                "message": message,
                "progress": progress,
                "status": status,
            })

        def fake_builder(path_disponibilitats, path_partits, params, preview_id, out_map_abs):
            captured.update({
                "path_disponibilitats": path_disponibilitats,
                "path_partits": path_partits,
                "params": params,
                "preview_id": preview_id,
                "out_map_abs": out_map_abs,
            })
            return {
                "metrics": {"cluster_count": 5},
                "selected_scenario": {"radius_m": 500},
                "map_path": "designacions/previews/preview-123.html",
            }

        with patch("designacions.tasks.async_to_sync", side_effect=self._async_to_sync_wrapper), \
             patch("designacions.tasks._write_job", side_effect=fake_write_job), \
             patch("designacions.tasks.push_log", side_effect=fake_push_log), \
             patch("designacions.tasks._resolve_cluster_preview_builder", return_value=fake_builder), \
             patch("designacions.tasks.write_preview_map_html_sync", return_value="designacions/previews/preview-123.html") as write_map_mock, \
             patch("designacions.tasks.settings.MEDIA_ROOT", self.media_tmp.name):
            result = build_cluster_preview_task.run(
                "preview-123",
                "tmp/disponibilitats.xlsx",
                "tmp/partits.xlsx",
                {"cluster_eps_m": 500.0},
            )

        self.assertEqual(captured["preview_id"], "preview-123")
        self.assertEqual(captured["path_disponibilitats"], "tmp/disponibilitats.xlsx")
        self.assertEqual(captured["path_partits"], "tmp/partits.xlsx")
        self.assertEqual(captured["params"]["cluster_eps_m"], 500.0)
        self.assertTrue(captured["out_map_abs"].endswith("designacions\\previews\\preview-123.html"))
        write_map_mock.assert_not_called()
        self.assertEqual(writes[0][1]["status"], "processing")
        self.assertEqual(writes[-1][1]["status"], "done")
        self.assertEqual(writes[-1][1]["result"]["metrics"]["cluster_count"], 5)
        self.assertEqual(result["map_path"], "designacions/previews/preview-123.html")
        self.assertEqual(logs[-1]["status"], "done")
