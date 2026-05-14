"""Audit artifact discovery and reading for Django views."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


KNOWN_AUDIT_FILENAMES = (
    "resource_solution.json",
    "team_catalog.json",
    "resource_audit.json",
    "resource_pressure.json",
    "candidate_catalog.json",
    "solver_model_summary.json",
    "solver_explanations.json",
    "local_combinations.json",
    "dependency_component_summary.json",
    "dependency_components.json",
    "dependency_component_edges.json",
    "kpis.json",
)

KNOWN_AUDIT_PREFIXES = (
    "kpis_",
    "run_manifest_",
    "input_validation_",
    "input_demand_",
    "solver_trace_",
    "home_away_resolution_",
    "constraints_report_",
    "performance_",
)


def discover_audit_paths(output_path: str) -> dict[str, str]:
    if not output_path:
        return {}

    output = Path(output_path)
    directory = output.parent if output.suffix else output
    if not directory.exists() or not directory.is_dir():
        return {}

    discovered: dict[str, str] = {}
    for filename in KNOWN_AUDIT_FILENAMES:
        candidate = directory / filename
        if candidate.exists() and candidate.is_file():
            discovered[candidate.stem] = str(candidate)
    for candidate in directory.glob("*.json"):
        if candidate.name in KNOWN_AUDIT_FILENAMES:
            continue
        if any(candidate.name.startswith(prefix) for prefix in KNOWN_AUDIT_PREFIXES):
            discovered[candidate.stem] = str(candidate)
    return discovered


def read_json_file(path: str) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_audit_artifact(run, artifact: str) -> dict[str, Any]:
    audit_paths = run.audit_paths if isinstance(run.audit_paths, dict) else {}
    path = audit_paths.get(artifact)
    if not path:
        raise FileNotFoundError(f"Audit artifact not found: {artifact}")

    payload = read_json_file(path)
    return {
        "artifact": artifact,
        "path": path,
        "payload": payload,
    }
