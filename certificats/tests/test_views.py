import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import django
    from django.conf import settings
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.test import RequestFactory, override_settings
except ModuleNotFoundError:
    django = None


def setup_minimal_django():
    if django is None:
        raise unittest.SkipTest("Django is not installed")

    if not settings.configured:
        settings.configure(
            DEFAULT_CHARSET="utf-8",
            INSTALLED_APPS=["certificats"],
            MEDIA_ROOT=tempfile.gettempdir(),
            MEDIA_URL="/media/",
            ROOT_URLCONF="certificats.urls",
            SECRET_KEY="test-secret-key",
            TEMPLATES=[
                {
                    "BACKEND": "django.template.backends.django.DjangoTemplates",
                    "APP_DIRS": True,
                    "OPTIONS": {"context_processors": []},
                }
            ],
            USE_TZ=True,
        )
        django.setup()


@unittest.skipIf(django is None, "Django is not installed")
class CertificatsUploadViewTests(unittest.TestCase):
    def setUp(self):
        setup_minimal_django()
        from certificats import views

        self.views = views
        self.factory = RequestFactory()

    def test_get_uses_upload_template_and_form(self):
        request = self.factory.get("/certificats/")

        response = self.views.CertificatsUploadView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.template_name, ["certificats/upload.html"])
        self.assertIn("form", response.context_data)

    def test_processar_pdfs_without_files_returns_400_error(self):
        request = self.factory.post("/certificats/processar/", data={})

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root, MEDIA_URL="/media/"):
                response = self.views.processar_pdfs(request)

        self.assertEqual(response.status_code, 400)

        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload["status"], "error")
        self.assertIn("fitxer", payload["message"].lower())

    def test_post_with_file_returns_zip_url_when_celery_task_is_unavailable(self):
        upload = SimpleUploadedFile("entrada.pdf", b"%PDF-test", content_type="application/pdf")
        request = self.factory.post("/certificats/", data={"files": [upload]})

        with tempfile.TemporaryDirectory() as media_root:
            media_path = Path(media_root)
            fake_result_dir = media_path / "result"
            fake_result_dir.mkdir()
            fake_zip = media_path / "certificats" / "certificats_generats_test.zip"
            fake_zip.parent.mkdir()
            fake_zip.write_bytes(b"zip")

            with override_settings(MEDIA_ROOT=media_root, MEDIA_URL="/media/"):
                with patch.object(self.views, "_load_celery_task", return_value=None):
                    with patch.object(self.views, "processar_certificats", return_value=fake_result_dir):
                        with patch.object(self.views, "create_certificats_zip", return_value=fake_zip):
                            response = self.views.CertificatsUploadView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["zip_path"], "certificats/certificats_generats_test.zip")
        self.assertEqual(payload["zip_url"], "/media/certificats/certificats_generats_test.zip")


if __name__ == "__main__":
    unittest.main()
