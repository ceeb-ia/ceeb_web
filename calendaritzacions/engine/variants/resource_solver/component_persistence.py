"""Persist resource-solver component contexts and manifests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from calendaritzacions.engine.variants.resource_solver.audit import json_ready
from calendaritzacions.engine.variants.resource_solver.component_context import (
    split_context_by_components,
    validate_component_split,
)
from calendaritzacions.engine.variants.resource_solver.types import SolverContext


def persist_component_subcontexts(
    *,
    run: Any | None,
    output_dir: str | Path,
    context: SolverContext,
    summary: Any,
    mode: str = "persist_components",
) -> dict[str, Any]:
    """Validate and persist component subcontexts without solving them."""

    audit_root = Path(output_dir)
    components_root = audit_root / "components"
    components_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json, component_attempt_dir, component_manifest_path, create_or_update_component_run = (
        _component_run_helpers()
    )
    pending_status = _component_pending_status()

    components = tuple(getattr(summary, "components", summary) or ())
    subcontexts = split_context_by_components(context, components)
    split_validation = validate_component_split(context, subcontexts)
    split_validation_path = components_root / "split_validation.json"
    atomic_write_json(split_validation_path, split_validation)

    if split_validation.get("status") != "valid":
        manifest = build_component_manifest(
            run=run,
            mode=mode,
            split_validation=split_validation,
            split_validation_path=_relative_path(audit_root, split_validation_path),
            components=[],
        )
        manifest_path = component_manifest_path(audit_root)
        atomic_write_json(manifest_path, manifest)
        return {
            "status": "invalid",
            "split_validation": split_validation,
            "split_validation_path": str(split_validation_path),
            "manifest": manifest,
            "manifest_path": str(manifest_path),
            "component_count": 0,
        }

    component_entries: list[dict[str, Any]] = []
    component_meta = {
        str(getattr(component, "component_id", f"C{index:03d}")): component
        for index, component in enumerate(components, start=1)
    }

    for component_id, subcontext in sorted(subcontexts.items()):
        attempt = 1
        attempt_dir = component_attempt_dir(audit_root, component_id, attempt=attempt)
        context_path = attempt_dir / "context.json"
        validation_path = attempt_dir / "validation.json"
        context_payload = _component_context_payload(component_id, attempt, subcontext)
        validation_payload = _component_validation_payload(component_id, attempt, split_validation)
        atomic_write_json(context_path, context_payload)
        atomic_write_json(validation_path, validation_payload)

        counts = _component_counts(subcontext, component_meta.get(component_id))
        relative_context_path = _relative_path(audit_root, context_path)
        relative_validation_path = _relative_path(audit_root, validation_path)
        component_run = None
        if run is not None:
            component_run = create_or_update_component_run(
                run=run,
                component_id=component_id,
                attempt=attempt,
                active_attempt=attempt,
                status=pending_status,
                team_count=counts["team_count"],
                candidate_count=counts["candidate_count"],
                competition_count=counts["competition_count"],
                resource_count=counts["resource_count"],
                linkage_count=counts["linkage_count"],
                context_path=context_path,
                validation_path=validation_path,
            )

        component_entries.append(
            {
                "component_id": component_id,
                "status": getattr(component_run, "status", pending_status),
                "active_attempt": attempt,
                **counts,
                "context_path": relative_context_path,
                "validation_path": relative_validation_path,
                "result_path": "",
            }
        )

    manifest = build_component_manifest(
        run=run,
        mode=mode,
        split_validation=split_validation,
        split_validation_path=_relative_path(audit_root, split_validation_path),
        components=component_entries,
    )
    manifest_path = component_manifest_path(audit_root)
    atomic_write_json(manifest_path, manifest)
    return {
        "status": "valid",
        "split_validation": split_validation,
        "split_validation_path": str(split_validation_path),
        "manifest": manifest,
        "manifest_path": str(manifest_path),
        "component_count": len(component_entries),
    }


def build_component_manifest(
    *,
    run: Any | None,
    mode: str,
    split_validation: dict[str, Any],
    split_validation_path: str,
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "artifact_type": "resource_solver_component_manifest",
        "run_id": getattr(run, "pk", None) or getattr(run, "id", None),
        "mode": mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "split_validation": {
            "status": split_validation.get("status", "unknown"),
            "path": split_validation_path,
        },
        "components": components,
    }


def _component_context_payload(component_id: str, attempt: int, context: SolverContext) -> dict[str, Any]:
    return {
        "artifact_type": "resource_solver_component_context",
        "component_id": component_id,
        "attempt": attempt,
        "counts": {
            "teams": len(context.teams),
            "groups": len(context.groups),
            "candidates": len(context.candidates),
            "resources": len(context.base_resources),
        },
        "context": json_ready(context),
    }


def _component_validation_payload(component_id: str, attempt: int, split_validation: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_type": "resource_solver_component_validation",
        "component_id": component_id,
        "attempt": attempt,
        "split_validation_status": split_validation.get("status", "unknown"),
        "split_validation": split_validation,
    }


def _component_counts(context: SolverContext, component: Any | None) -> dict[str, int]:
    return {
        "team_count": len(context.teams),
        "candidate_count": len(context.candidates),
        "competition_count": len(getattr(component, "competition_keys", ()) or ()),
        "resource_count": len(context.base_resources),
        "linkage_count": len(getattr(component, "linkage_keys", ()) or ()),
    }


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _component_run_helpers():
    from calendaritzacions.django.services.component_runs import (
        atomic_write_json,
        component_attempt_dir,
        component_manifest_path,
        create_or_update_component_run,
    )

    return atomic_write_json, component_attempt_dir, component_manifest_path, create_or_update_component_run


def _component_pending_status() -> str:
    try:
        from calendaritzacions.django.models import CalendarizationComponentRun

        return str(CalendarizationComponentRun.STATUS_PENDING)
    except Exception:
        return "pending"


__all__ = [
    "build_component_manifest",
    "persist_component_subcontexts",
]
