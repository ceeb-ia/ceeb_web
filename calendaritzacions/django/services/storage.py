"""Storage helpers for the optional Django views."""

from __future__ import annotations

from pathlib import Path

from django.core.exceptions import SuspiciousFileOperation
from django.http import FileResponse, Http404

from calendaritzacions.django.models import CalendarizationRun


def resolve_existing_file(path: str) -> Path:
    if not path:
        raise Http404("No file path is available.")

    resolved = Path(path).expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise Http404("File does not exist.")
    return resolved


def ensure_run_output_is_downloadable(run: CalendarizationRun) -> Path:
    if run.status != CalendarizationRun.STATUS_SUCCESS:
        raise Http404("Run output is not available.")
    return resolve_existing_file(run.output_path)


def ensure_run_audit_path(run: CalendarizationRun, artifact: str) -> Path:
    audit_paths = run.audit_paths if isinstance(run.audit_paths, dict) else {}
    path = audit_paths.get(artifact)
    if not path:
        raise Http404("Audit artifact does not exist.")

    resolved = resolve_existing_file(path)
    allowed = {Path(value).expanduser().resolve() for value in audit_paths.values() if value}
    if resolved not in allowed:
        raise SuspiciousFileOperation("Audit path is not registered for this run.")
    return resolved


def open_output_file(run: CalendarizationRun) -> FileResponse:
    path = ensure_run_output_is_downloadable(run)
    return FileResponse(path.open("rb"), as_attachment=True, filename=path.name)
