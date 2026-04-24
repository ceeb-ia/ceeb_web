# designacions_app/services/jobstore.py
import os

from asgiref.sync import async_to_sync
from django.conf import settings

from logs import _read_job, _write_job, read_logs_sync

PREVIEW_REL_DIR = os.path.join("designacions", "previews")

def write_job_sync(task_id: str, data: dict):
    async_to_sync(_write_job)(task_id, data)


def read_job_sync(task_id: str):
    return async_to_sync(_read_job)(task_id)


def read_job_logs_sync(task_id: str, limit: int = 200):
    return read_logs_sync(task_id, limit=limit)


def preview_map_rel_path(task_id: str) -> str:
    return os.path.join(PREVIEW_REL_DIR, f"{task_id}.html").replace("\\", "/")


def write_preview_map_html_sync(task_id: str, html: str) -> str:
    rel_path = preview_map_rel_path(task_id)
    abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as handle:
        handle.write(html or "")
    return rel_path


def read_preview_map_html_sync(task_id: str | None = None, *, rel_path: str | None = None) -> str | None:
    resolved_rel_path = rel_path or preview_map_rel_path(task_id or "")
    abs_path = os.path.join(settings.MEDIA_ROOT, resolved_rel_path)
    if not os.path.exists(abs_path):
        return None
    with open(abs_path, "r", encoding="utf-8") as handle:
        return handle.read()
