"""Recovery helpers for persistent resource-solver component runs."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

from django.apps import apps
from django.db import transaction
from django.db.models import Q
from django.utils import timezone


STATUS_PENDING = "pending"
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_STALE = "stale"
STATUS_SKIPPED = "skipped"
STATUS_MERGED = "merged"
STATUS_SUPERSEDED = "superseded"

TERMINAL_SUCCESS_STATUSES = {STATUS_SUCCESS, STATUS_SKIPPED, STATUS_MERGED}
RERUN_STATUSES_FAILED = {STATUS_ERROR}
RERUN_STATUSES_STALE = {STATUS_STALE}

EnqueueComponent = Callable[[Any], Any]


class ComponentRecoveryUnavailable(RuntimeError):
    """Raised when PCS-01 component persistence is not installed yet."""


@dataclass(slots=True)
class ComponentRecoveryResult:
    stale_marked: list[Any] = field(default_factory=list)
    requeued: list[Any] = field(default_factory=list)
    marked_error: list[Any] = field(default_factory=list)
    reruns_prepared: list[Any] = field(default_factory=list)
    manifest_path: str = ""


def get_component_run_model() -> Any:
    """Return CalendarizationComponentRun if PCS-01 has registered it."""

    last_error: Exception | None = None
    for app_label in ("calendaritzacions_django", "calendaritzacions"):
        try:
            return apps.get_model(app_label, "CalendarizationComponentRun")
        except (LookupError, RuntimeError) as exc:
            last_error = exc
    if last_error is not None:
        raise ComponentRecoveryUnavailable(
            "CalendarizationComponentRun is not available yet. "
            "Install PCS-01 before running component recovery against the DB."
        ) from last_error
    raise ComponentRecoveryUnavailable("CalendarizationComponentRun is not available yet.")


def mark_stale_components(
    *,
    run_id: int | None = None,
    stale_after_minutes: int = 30,
    now: Any | None = None,
    component_model: Any | None = None,
) -> list[Any]:
    """Mark running components with an old or missing heartbeat as stale."""

    model = component_model or get_component_run_model()
    current_time = now or timezone.now()
    cutoff = current_time - timedelta(minutes=stale_after_minutes)
    components = _list_running_components(model, run_id=run_id, cutoff=cutoff)
    stale_components: list[Any] = []
    for component in components:
        component.status = STATUS_STALE
        component.error_message = component.error_message or (
            f"Component marked stale by watchdog after {stale_after_minutes} minutes without heartbeat."
        )
        _save(component, ["status", "error_message"])
        stale_components.append(component)
    return stale_components


def reconcile_component_runs(
    *,
    run_id: int | None = None,
    all_running: bool = False,
    stale_after_minutes: int = 30,
    max_attempts: int = 3,
    enqueue_component: EnqueueComponent | None = None,
    component_model: Any | None = None,
    now: Any | None = None,
) -> ComponentRecoveryResult:
    """Run watchdog reconciliation and optionally requeue stale components."""

    if run_id is None and not all_running:
        raise ValueError("run_id is required unless all_running=True")

    model = component_model or get_component_run_model()
    result = ComponentRecoveryResult()
    result.stale_marked = mark_stale_components(
        run_id=None if all_running else run_id,
        stale_after_minutes=stale_after_minutes,
        now=now,
        component_model=model,
    )

    stale_components = _list_components_by_status(
        model,
        statuses=[STATUS_STALE],
        run_id=None if all_running else run_id,
    )
    for component in stale_components:
        if int(getattr(component, "attempt", 1) or 1) >= max_attempts:
            component.status = STATUS_ERROR
            component.error_message = component.error_message or "Component exceeded max recovery attempts."
            _save(component, ["status", "error_message"])
            result.marked_error.append(component)
            continue
        if enqueue_component is None:
            continue
        new_component = prepare_component_rerun(
            run_id=int(getattr(component, "run_id")),
            component_id=str(getattr(component, "component_id")),
            enqueue_component=enqueue_component,
            component_model=model,
        )
        result.requeued.append(new_component)

    run_ids = _affected_run_ids(result.stale_marked, result.requeued, result.marked_error, run_id)
    for affected_run_id in run_ids:
        manifest_path = rebuild_component_manifest(affected_run_id, component_model=model)
        if manifest_path:
            result.manifest_path = manifest_path
    return result


def prepare_component_rerun(
    *,
    run_id: int,
    component_id: str,
    enqueue_component: EnqueueComponent | None = None,
    component_model: Any | None = None,
) -> Any:
    """Create a new active attempt for a component without deleting old artifacts."""

    model = component_model or get_component_run_model()
    with transaction.atomic():
        current = _get_active_component(model, run_id=run_id, component_id=component_id)
        existing_components = _list_components(model, run_id=run_id, component_id=component_id)
        next_attempt = max(int(getattr(component, "attempt", 1) or 1) for component in existing_components) + 1
        previous_active_attempt = int(getattr(current, "active_attempt", getattr(current, "attempt", 1)) or 1)

        for component in existing_components:
            component.active_attempt = next_attempt
            _save(component, ["active_attempt"])

        new_component = _clone_component_for_attempt(
            model,
            current,
            attempt=next_attempt,
            active_attempt=next_attempt,
            previous_active_attempt=previous_active_attempt,
        )
    if enqueue_component is not None:
        enqueue_component(new_component)
    rebuild_component_manifest(run_id, component_model=model)
    return new_component


def rebuild_component_manifest(run_id: int, *, component_model: Any | None = None) -> str:
    """Regenerate components/manifest.json from DB when its path can be inferred."""

    model = component_model or get_component_run_model()
    components = _list_components(model, run_id=run_id)
    manifest_path = _infer_manifest_path(components)
    if not manifest_path:
        return ""

    payload = {
        "artifact_type": "resource_solver_component_manifest",
        "run_id": run_id,
        "updated_at": timezone.now().isoformat(),
        "components": [_component_manifest_entry(component) for component in components],
    }
    _atomic_write_json(Path(manifest_path), payload)
    return str(manifest_path)


def select_components_for_rerun(
    *,
    run_id: int,
    failed: bool = False,
    stale: bool = False,
    all_components: bool = False,
    component_model: Any | None = None,
) -> list[Any]:
    model = component_model or get_component_run_model()
    if all_components:
        return _list_active_components(model, run_id=run_id)
    statuses: set[str] = set()
    if failed:
        statuses.update(RERUN_STATUSES_FAILED)
    if stale:
        statuses.update(RERUN_STATUSES_STALE)
    if not statuses:
        return []
    return [
        component
        for component in _list_active_components(model, run_id=run_id)
        if getattr(component, "status", "") in statuses
    ]


def _list_running_components(model: Any, *, run_id: int | None, cutoff: Any) -> list[Any]:
    manager = model.objects
    query = manager.filter(status=STATUS_RUNNING)
    if run_id is not None:
        query = query.filter(run_id=run_id)
    query = query.filter(Q(heartbeat_at__lt=cutoff) | Q(heartbeat_at__isnull=True))
    return list(query)


def _list_components_by_status(model: Any, *, statuses: Iterable[str], run_id: int | None) -> list[Any]:
    query = model.objects.filter(status__in=list(statuses))
    if run_id is not None:
        query = query.filter(run_id=run_id)
    return list(query)


def _list_components(model: Any, *, run_id: int, component_id: str | None = None) -> list[Any]:
    query = model.objects.filter(run_id=run_id)
    if component_id is not None:
        query = query.filter(component_id=component_id)
    return list(query.order_by("component_id", "attempt"))


def _list_active_components(model: Any, *, run_id: int) -> list[Any]:
    components = _list_components(model, run_id=run_id)
    return [
        component
        for component in components
        if int(getattr(component, "attempt", 1) or 1)
        == int(getattr(component, "active_attempt", getattr(component, "attempt", 1)) or 1)
    ]


def _get_active_component(model: Any, *, run_id: int, component_id: str) -> Any:
    components = _list_components(model, run_id=run_id, component_id=component_id)
    for component in reversed(components):
        if int(getattr(component, "attempt", 1) or 1) == int(
            getattr(component, "active_attempt", getattr(component, "attempt", 1)) or 1
        ):
            return component
    if components:
        return components[-1]
    raise model.DoesNotExist(f"Component {component_id!r} for run {run_id} does not exist")


def _clone_component_for_attempt(
    model: Any,
    current: Any,
    *,
    attempt: int,
    active_attempt: int,
    previous_active_attempt: int,
) -> Any:
    clone_fields = {
        "run_id": getattr(current, "run_id"),
        "component_id": getattr(current, "component_id"),
        "status": STATUS_QUEUED,
        "attempt": attempt,
        "active_attempt": active_attempt,
        "queued_at": timezone.now(),
        "started_at": None,
        "heartbeat_at": None,
        "finished_at": None,
        "error_message": "",
    }
    for field in (
        "team_count",
        "candidate_count",
        "competition_count",
        "resource_count",
        "linkage_count",
        "context_path",
        "validation_path",
        "model_summary_path",
        "raw_result_path",
        "solution_path",
        "logs_path",
        "error_path",
    ):
        if hasattr(current, field):
            clone_fields[field] = _path_for_attempt(getattr(current, field), previous_active_attempt, attempt)
    clone = model.objects.create(**clone_fields)
    _copy_attempt_context(current, clone)
    return clone


def _path_for_attempt(value: Any, old_attempt: int, new_attempt: int) -> Any:
    if not isinstance(value, str) or not value:
        return value
    return value.replace(f"attempt_{old_attempt:03d}", f"attempt_{new_attempt:03d}")


def _copy_attempt_context(current: Any, clone: Any) -> None:
    source_value = getattr(current, "context_path", "")
    target_value = getattr(clone, "context_path", "")
    if not isinstance(source_value, str) or not isinstance(target_value, str) or not source_value or not target_value:
        return
    source = Path(source_value)
    target = Path(target_value)
    if not source.exists() or target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _infer_manifest_path(components: list[Any]) -> str:
    for component in components:
        for attr in ("context_path", "validation_path", "raw_result_path", "solution_path", "logs_path", "error_path"):
            value = getattr(component, attr, "")
            if not value:
                continue
            path = Path(str(value))
            parts = path.parts
            if "components" in parts:
                idx = parts.index("components")
                return str(Path(*parts[: idx + 1]) / "manifest.json")
    return ""


def _component_manifest_entry(component: Any) -> dict[str, Any]:
    return {
        "component_id": getattr(component, "component_id", ""),
        "status": getattr(component, "status", ""),
        "attempt": getattr(component, "attempt", None),
        "active_attempt": getattr(component, "active_attempt", None),
        "team_count": getattr(component, "team_count", 0),
        "candidate_count": getattr(component, "candidate_count", 0),
        "competition_count": getattr(component, "competition_count", 0),
        "resource_count": getattr(component, "resource_count", 0),
        "linkage_count": getattr(component, "linkage_count", 0),
        "context_path": getattr(component, "context_path", ""),
        "validation_path": getattr(component, "validation_path", ""),
        "model_summary_path": getattr(component, "model_summary_path", ""),
        "raw_result_path": getattr(component, "raw_result_path", ""),
        "solution_path": getattr(component, "solution_path", ""),
        "logs_path": getattr(component, "logs_path", ""),
        "error_path": getattr(component, "error_path", ""),
        "error_message": getattr(component, "error_message", ""),
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        from calendaritzacions.django.services.component_runs import atomic_write_json
    except ImportError:
        atomic_write_json = None
    if atomic_write_json is not None:
        atomic_write_json(path, payload)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _affected_run_ids(components: Iterable[Any], *more: Any) -> list[int]:
    run_ids: set[int] = set()
    for component in components:
        run_id = getattr(component, "run_id", None)
        if run_id is not None:
            run_ids.add(int(run_id))
    for item in more:
        if item is None:
            continue
        if isinstance(item, Iterable) and not isinstance(item, (str, bytes)):
            for component in item:
                run_id = getattr(component, "run_id", None)
                if run_id is not None:
                    run_ids.add(int(run_id))
        else:
            run_ids.add(int(item))
    return sorted(run_ids)


def _save(instance: Any, update_fields: list[str]) -> None:
    try:
        instance.save(update_fields=update_fields)
    except TypeError:
        instance.save()
