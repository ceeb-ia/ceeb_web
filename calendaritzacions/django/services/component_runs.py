"""Persistent state and artifact helpers for resource solver components."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from calendaritzacions.django.models import CalendarizationComponentRun, CalendarizationRun


COUNT_FIELDS = (
    "team_count",
    "candidate_count",
    "competition_count",
    "resource_count",
    "linkage_count",
)
PATH_FIELDS = (
    "context_path",
    "validation_path",
    "model_summary_path",
    "raw_result_path",
    "solution_path",
    "logs_path",
    "error_path",
)
STATUS_FIELDS = {choice[0] for choice in CalendarizationComponentRun.STATUS_CHOICES}


def component_attempt_dir(audit_root: str | Path, component_id: str, attempt: int = 1) -> Path:
    return Path(audit_root) / "components" / component_id / f"attempt_{attempt:03d}"


def component_manifest_path(audit_root: str | Path) -> Path:
    return Path(audit_root) / "components" / "manifest.json"


def atomic_write_json(path: str | Path, payload: Any) -> Path:
    target = Path(path)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return atomic_write_text(target, f"{text}\n")


def atomic_write_text(path: str | Path, content: str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_name = tmp.name
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, target)
    except Exception:
        if tmp_name:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return target


def create_or_update_component_run(
    *,
    run: CalendarizationRun,
    component_id: str,
    attempt: int = 1,
    active_attempt: int | None = None,
    status: str | None = None,
    team_count: int | None = None,
    candidate_count: int | None = None,
    competition_count: int | None = None,
    resource_count: int | None = None,
    linkage_count: int | None = None,
    context_path: str | Path | None = None,
    validation_path: str | Path | None = None,
    model_summary_path: str | Path | None = None,
    raw_result_path: str | Path | None = None,
    solution_path: str | Path | None = None,
    logs_path: str | Path | None = None,
    error_path: str | Path | None = None,
    error_message: str | None = None,
) -> CalendarizationComponentRun:
    if status is not None and status not in STATUS_FIELDS:
        raise ValueError(f"Invalid component status: {status}")

    defaults: dict[str, Any] = {}
    optional_values = {
        "status": status,
        "team_count": team_count,
        "candidate_count": candidate_count,
        "competition_count": competition_count,
        "resource_count": resource_count,
        "linkage_count": linkage_count,
        "context_path": _path_to_str(context_path),
        "validation_path": _path_to_str(validation_path),
        "model_summary_path": _path_to_str(model_summary_path),
        "raw_result_path": _path_to_str(raw_result_path),
        "solution_path": _path_to_str(solution_path),
        "logs_path": _path_to_str(logs_path),
        "error_path": _path_to_str(error_path),
        "error_message": error_message,
    }
    defaults.update({field: value for field, value in optional_values.items() if value is not None})

    with transaction.atomic():
        component_runs = CalendarizationComponentRun.objects.filter(run=run, component_id=component_id)
        if active_attempt is None:
            active_attempt = (
                component_runs.order_by("-active_attempt").values_list("active_attempt", flat=True).first() or attempt
            )
        defaults["active_attempt"] = active_attempt

        component_run, _created = CalendarizationComponentRun.objects.update_or_create(
            run=run,
            component_id=component_id,
            attempt=attempt,
            defaults=defaults,
        )
        component_runs.exclude(active_attempt=active_attempt).update(active_attempt=active_attempt)
        component_run.refresh_from_db()
    return component_run


def mark_component_status(
    component_run: CalendarizationComponentRun,
    status: str,
    *,
    error_message: str | None = None,
    at=None,
) -> CalendarizationComponentRun:
    if status not in STATUS_FIELDS:
        raise ValueError(f"Invalid component status: {status}")

    now = at or timezone.now()
    update_fields = ["status"]
    component_run.status = status

    if status == CalendarizationComponentRun.STATUS_QUEUED and component_run.queued_at is None:
        component_run.queued_at = now
        update_fields.append("queued_at")
    elif status == CalendarizationComponentRun.STATUS_RUNNING:
        if component_run.started_at is None:
            component_run.started_at = now
            update_fields.append("started_at")
        component_run.heartbeat_at = now
        component_run.finished_at = None
        update_fields.extend(["heartbeat_at", "finished_at"])
    elif status in CalendarizationComponentRun.TERMINAL_STATUSES:
        component_run.finished_at = now
        update_fields.append("finished_at")

    if error_message is not None:
        component_run.error_message = error_message
        update_fields.append("error_message")

    component_run.save(update_fields=_dedupe(update_fields))
    return component_run


def heartbeat_component(component_run: CalendarizationComponentRun, *, at=None) -> bool:
    now = at or timezone.now()
    updated = CalendarizationComponentRun.objects.filter(
        pk=component_run.pk,
        attempt=F("active_attempt"),
    ).update(heartbeat_at=now)
    if not updated:
        return False
    component_run.heartbeat_at = now
    return True


def _path_to_str(value: str | Path | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _dedupe(fields: list[str]) -> list[str]:
    return list(dict.fromkeys(fields))
