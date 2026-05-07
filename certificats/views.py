from __future__ import annotations

import logging
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.generic.edit import FormView

from .forms import CertificatsUploadForm
from .services.archive import create_certificats_zip
from .services.processor import processar_certificats

logger = logging.getLogger(__name__)


class CertificatsUploadView(FormView):
    template_name = "certificats/upload.html"
    form_class = CertificatsUploadForm

    def form_valid(self, form):
        uploaded_files = self.request.FILES.getlist("files")
        if not uploaded_files:
            return JsonResponse({"status": "error", "message": "No s'ha rebut cap fitxer."}, status=400)

        task = _load_celery_task()
        if task is not None:
            input_dir = _media_root() / "temp" / "certificats" / uuid4().hex
            input_dir.mkdir(parents=True, exist_ok=True)
            try:
                file_paths = _save_uploads(uploaded_files, input_dir)
            except zipfile.BadZipFile:
                return JsonResponse({"status": "error", "message": "El ZIP pujat no es valid."}, status=400)

            if not file_paths:
                return JsonResponse(
                    {"status": "error", "message": "No s'ha trobat cap PDF per processar."},
                    status=422,
                )

            async_result = task.delay([str(path) for path in file_paths])
            _add_message(self.request, messages.SUCCESS, "Fitxers pujats correctament. S'estan processant.")
            return JsonResponse({"status": "queued", "task_id": async_result.id})

        response = _process_uploads_sync(uploaded_files)
        if response.status_code == 200:
            _add_message(self.request, messages.SUCCESS, "Fitxers processats correctament.")
        return response

    def form_invalid(self, form):
        errors = form.errors.get_json_data()
        return JsonResponse({"status": "error", "message": "Revisa els fitxers pujats.", "errors": errors}, status=400)


@require_POST
def processar_pdfs(request):
    uploaded_files = request.FILES.getlist("files")
    if not uploaded_files:
        return JsonResponse({"status": "error", "message": "No s'ha rebut cap fitxer."}, status=400)

    return _process_uploads_sync(uploaded_files)


def _process_uploads_sync(uploaded_files):
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        input_dir = temp_path / "input"
        output_dir = temp_path / "output"
        input_dir.mkdir()
        output_dir.mkdir()

        try:
            saved_paths = _save_uploads(uploaded_files, input_dir)
        except zipfile.BadZipFile:
            return JsonResponse({"status": "error", "message": "El ZIP pujat no es valid."}, status=400)

        if not saved_paths:
            return JsonResponse(
                {"status": "error", "message": "No s'ha trobat cap PDF per processar."},
                status=422,
            )

        result_dir = processar_certificats(input_dir, output_dir, on_progress=None)
        if result_dir is None:
            return JsonResponse(
                {"status": "error", "message": "No s'ha pogut processar cap certificat."},
                status=422,
            )

        destination_dir = _media_root() / "certificats"
        zip_path = create_certificats_zip(result_dir, destination_dir)

    return JsonResponse({"status": "ok", **_zip_response_payload(zip_path)})


def _save_uploads(uploaded_files, destination_dir: Path) -> list[Path]:
    saved_paths: list[Path] = []
    destination_dir.mkdir(parents=True, exist_ok=True)

    for index, uploaded_file in enumerate(uploaded_files, start=1):
        filename = _safe_filename(uploaded_file.name, fallback=f"certificat_{index}.pdf")
        file_path = _unique_path(destination_dir / filename)

        with file_path.open("wb") as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        if file_path.suffix.lower() == ".zip":
            saved_paths.extend(_extract_pdf_members(file_path, destination_dir))
        elif file_path.suffix.lower() == ".pdf":
            saved_paths.append(file_path)

    return saved_paths


def _extract_pdf_members(zip_path: Path, destination_dir: Path) -> list[Path]:
    extracted_paths: list[Path] = []
    extract_root = (destination_dir / f"{zip_path.stem}_extret").resolve()
    extract_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zip_file:
        for index, member in enumerate(zip_file.infolist(), start=1):
            member_name = Path(member.filename)
            if member.is_dir() or member_name.suffix.lower() != ".pdf":
                continue

            filename = _safe_filename(member_name.name, fallback=f"certificat_zip_{index}.pdf")
            target_path = _unique_path(extract_root / filename)
            with zip_file.open(member) as source, target_path.open("wb") as destination:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    destination.write(chunk)
            extracted_paths.append(target_path)

    return extracted_paths


def _safe_filename(name: str, fallback: str) -> str:
    filename = Path(name or fallback).name
    filename = "".join(char for char in filename if char not in '<>:"/\\|?*\x00')
    filename = filename.strip(" ._")
    return filename or fallback


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    for counter in range(1, 10_000):
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"No s'ha pogut trobar un nom de fitxer lliure per a {path.name}.")


def _zip_response_payload(zip_path: Path) -> dict[str, str]:
    media_root = _media_root().resolve()
    resolved_zip_path = Path(zip_path).resolve()
    try:
        zip_relative_path = resolved_zip_path.relative_to(media_root)
        zip_path_value = zip_relative_path.as_posix()
    except ValueError:
        logger.warning("El ZIP generat no es troba dins MEDIA_ROOT: %s", resolved_zip_path)
        zip_path_value = resolved_zip_path.name

    media_url = getattr(settings, "MEDIA_URL", "/media/").rstrip("/") + "/"
    return {"zip_path": zip_path_value, "zip_url": media_url + zip_path_value}


def _media_root() -> Path:
    return Path(getattr(settings, "MEDIA_ROOT", tempfile.gettempdir()))


def _load_celery_task():
    try:
        from .tasks import process_certificats_task
    except Exception:
        return None
    return process_certificats_task


def _add_message(request, level: int, message: str) -> None:
    try:
        messages.add_message(request, level, message)
    except Exception:
        logger.debug("No s'ha pogut afegir el missatge de certificats.", exc_info=True)
