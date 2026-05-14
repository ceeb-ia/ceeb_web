"""Pure merge helpers for resource solver component results."""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import asdict, is_dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable

class ComponentMergeValidationError(ValueError):
    """Raised when partial component results cannot be merged safely."""

    def __init__(self, message: str, payload: dict[str, Any]):
        super().__init__(message)
        self.payload = payload


def merge_component_results(
    context: Any,
    component_results_or_paths: Iterable[Any],
    component_ids: Iterable[str] | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Load and merge component raw/solution artifacts into JSON-ready payloads.

    The function is intentionally independent from service.py, Django and
    OR-Tools. Inputs may be PCS-05 return payloads, attempt directories, paths
    to either partial JSON artifact, or dictionaries containing raw/solution
    payloads.
    """

    expected_component_ids = tuple(str(item) for item in (component_ids or ()))
    expected_team_ids = _context_team_ids(context)
    known_assignment_keys = _context_assignment_keys(context)

    loaded = [_load_component_result(item) for item in component_results_or_paths]
    loaded = sorted(loaded, key=lambda item: item["component_id"])

    raw_payloads = [item["raw_result"] for item in loaded]
    solution_payloads = [item["solution_partial"] for item in loaded]
    component_statuses = [
        {
            "component_id": item["component_id"],
            "status": _status(raw_payloads[index], solution_payloads[index]),
            "objective_value": _numeric_or_none(raw_payloads[index].get("objective_value")),
            "wall_time": _numeric_or_none(raw_payloads[index].get("wall_time")) or 0.0,
        }
        for index, item in enumerate(loaded)
    ]

    assignments = _merged_list(solution_payloads, "assignments")
    real_matches = _merged_list(solution_payloads, "real_matches")
    resource_usage = _merged_list(solution_payloads, "resource_usage")
    group_summary = _merged_list(solution_payloads, "group_summary")
    logs = _merged_logs(raw_payloads, solution_payloads)

    status = _merged_status(item["status"] for item in component_statuses)
    objective_value = _sum_objectives(raw_payloads)
    wall_time = sum(float(item["wall_time"]) for item in component_statuses)

    validation = _build_validation_payload(
        expected_component_ids=expected_component_ids,
        actual_component_ids=[item["component_id"] for item in loaded],
        expected_team_ids=expected_team_ids,
        known_assignment_keys=known_assignment_keys,
        assignments=assignments,
        merged_status=status,
    )

    merged_raw_result = {
        "artifact_type": "resource_solver_merged_raw_result",
        "status": status,
        "objective_value": objective_value,
        "best_bound": None,
        "wall_time": wall_time,
        "component_count": len(loaded),
        "component_statuses": component_statuses,
        "logs": logs,
    }
    merged_solution = {
        "artifact_type": "resource_solver_merged_solution",
        "status": status,
        "objective_value": objective_value,
        "best_bound": None,
        "wall_time": wall_time,
        "assignments": assignments,
        "real_matches": real_matches,
        "resource_usage": resource_usage,
        "group_summary": group_summary,
        "entity_excess": _merge_entity_excess(solution_payloads),
        "audit_payloads": {
            "component_statuses": component_statuses,
        },
        "logs": logs,
    }
    payload = _json_ready(
        {
            "artifact_type": "resource_solver_component_merge",
            "status": status,
            "validation": validation,
            "raw_result": merged_raw_result,
            "solution": merged_solution,
        }
    )

    if output_dir is not None:
        output_path = Path(output_dir)
        _atomic_write_json(output_path / "component_merge_validation.json", payload["validation"])
        if validation["status"] == "valid":
            _atomic_write_json(output_path / "merged_raw_result.json", payload["raw_result"])
            _atomic_write_json(output_path / "merged_solution.json", payload["solution"])

    if validation["status"] != "valid":
        raise ComponentMergeValidationError("invalid component merge results", payload)

    return payload


def _load_component_result(source: Any) -> dict[str, Any]:
    if isinstance(source, (str, Path)):
        return _load_component_result_from_path(Path(source))
    if not isinstance(source, dict):
        raise TypeError("component result must be a path or JSON object")

    raw_result = source.get("raw_result") or source.get("raw")
    solution = source.get("solution_partial") or source.get("solution") or source.get("merged_solution")
    paths = source.get("paths") if isinstance(source.get("paths"), dict) else {}
    if raw_result is None and paths.get("raw_result"):
        raw_result = _read_json(paths["raw_result"])
    if solution is None and (paths.get("solution_partial") or paths.get("solution")):
        solution = _read_json(paths.get("solution_partial") or paths.get("solution"))

    if _is_raw_artifact(source):
        raw_result = source
    if _is_solution_artifact(source):
        solution = source

    if not isinstance(raw_result, dict) or not isinstance(solution, dict):
        raise ValueError("component result must include raw_result and solution_partial payloads")

    component_id = _component_id(source, raw_result, solution)
    return {
        "component_id": component_id,
        "raw_result": raw_result,
        "solution_partial": solution,
    }


def _load_component_result_from_path(path: Path) -> dict[str, Any]:
    if path.is_dir():
        raw_path = path / "raw_result.json"
        solution_path = path / "solution_partial.json"
    elif path.name == "raw_result.json":
        raw_path = path
        solution_path = path.with_name("solution_partial.json")
    elif path.name == "solution_partial.json":
        raw_path = path.with_name("raw_result.json")
        solution_path = path
    else:
        payload = _read_json(path)
        return _load_component_result(payload)
    return _load_component_result(
        {
            "raw_result": _read_json(raw_path),
            "solution_partial": _read_json(solution_path),
        }
    )


def _build_validation_payload(
    *,
    expected_component_ids: tuple[str, ...],
    actual_component_ids: list[str],
    expected_team_ids: set[str],
    known_assignment_keys: set[tuple[str, str, int]],
    assignments: list[dict[str, Any]],
    merged_status: str,
) -> dict[str, Any]:
    assigned_team_ids = [str(item.get("team_id")) for item in assignments if isinstance(item, dict)]
    assigned_counts = Counter(assigned_team_ids)

    duplicate_teams = sorted(team_id for team_id, count in assigned_counts.items() if count > 1)
    absent_teams = sorted(expected_team_ids - set(assigned_team_ids))
    unknown_team_ids = sorted(set(assigned_team_ids) - expected_team_ids)
    missing_components = sorted(set(expected_component_ids) - set(actual_component_ids))
    unexpected_components = sorted(set(actual_component_ids) - set(expected_component_ids)) if expected_component_ids else []
    duplicate_components = sorted(
        component_id for component_id, count in Counter(actual_component_ids).items() if count > 1
    )
    unknown_assignments = _unknown_assignments(assignments, known_assignment_keys)

    errors: list[dict[str, Any]] = []
    _append_error(errors, "missing_component", missing_components)
    _append_error(errors, "unexpected_component", unexpected_components)
    _append_error(errors, "duplicate_component", duplicate_components)
    if str(merged_status).upper() != "INFEASIBLE":
        _append_error(errors, "duplicate_team_assignment", duplicate_teams)
        _append_error(errors, "absent_team_assignment", absent_teams)
        _append_error(errors, "unknown_team_assignment", unknown_team_ids)
        _append_error(errors, "unknown_assignment", unknown_assignments)

    return {
        "artifact_type": "resource_solver_component_merge_validation",
        "status": "valid" if not errors else "invalid",
        "component_count": len(actual_component_ids),
        "expected_component_ids": list(expected_component_ids),
        "actual_component_ids": actual_component_ids,
        "assignment_count": len(assignments),
        "expected_team_count": len(expected_team_ids),
        "errors": errors,
    }


def _merged_status(statuses: Iterable[str]) -> str:
    normalized = [str(status or "UNKNOWN").upper() for status in statuses]
    if not normalized:
        return "UNKNOWN"
    if "INFEASIBLE" in normalized:
        return "INFEASIBLE"
    if "UNKNOWN" in normalized or "TIME_LIMIT" in normalized:
        return "UNKNOWN"
    if all(status == "OPTIMAL" for status in normalized):
        return "OPTIMAL"
    if all(status in {"OPTIMAL", "FEASIBLE"} for status in normalized) and "FEASIBLE" in normalized:
        return "FEASIBLE"
    return "UNKNOWN"


def _sum_objectives(raw_payloads: list[dict[str, Any]]) -> float | None:
    values = [_numeric_or_none(payload.get("objective_value")) for payload in raw_payloads]
    if not values or any(value is None for value in values):
        return None
    return float(sum(value for value in values if value is not None))


def _merged_list(payloads: list[dict[str, Any]], key: str) -> list[Any]:
    values: list[Any] = []
    for payload in payloads:
        items = payload.get(key) or []
        if not isinstance(items, list):
            raise ValueError(f"{key} must be a list in partial solution payloads")
        values.extend(items)
    return values


def _merge_entity_excess(payloads: list[dict[str, Any]]) -> dict[str, int]:
    merged: Counter[str] = Counter()
    for payload in payloads:
        value = payload.get("entity_excess") or {}
        if not isinstance(value, dict):
            continue
        for key, count in value.items():
            numeric = _numeric_or_none(count)
            if numeric is not None:
                merged[str(key)] += int(numeric)
    return dict(sorted(merged.items()))


def _merged_logs(raw_payloads: list[dict[str, Any]], solution_payloads: list[dict[str, Any]]) -> list[str]:
    logs: list[str] = []
    for payload in [*raw_payloads, *solution_payloads]:
        value = payload.get("logs") or []
        if isinstance(value, list):
            logs.extend(str(item) for item in value)
    return logs


def _unknown_assignments(
    assignments: list[dict[str, Any]],
    known_assignment_keys: set[tuple[str, str, int]],
) -> list[dict[str, Any]]:
    if not known_assignment_keys:
        return []
    unknown: list[dict[str, Any]] = []
    for assignment in assignments:
        key = _assignment_key(assignment)
        if key is not None and key not in known_assignment_keys:
            unknown.append(
                {
                    "team_id": key[0],
                    "group_id": key[1],
                    "number": key[2],
                }
            )
    return unknown


def _context_team_ids(context: Any) -> set[str]:
    teams = _context_items(context, "teams")
    return {str(_item_value(team, "team_id")) for team in teams}


def _context_assignment_keys(context: Any) -> set[tuple[str, str, int]]:
    candidates = _context_items(context, "candidates")
    keys: set[tuple[str, str, int]] = set()
    for candidate in candidates:
        try:
            keys.add(
                (
                    str(_item_value(candidate, "team_id")),
                    str(_item_value(candidate, "group_id")),
                    int(_item_value(candidate, "number")),
                )
            )
        except (TypeError, ValueError):
            continue
    return keys


def _context_items(context: Any, key: str) -> Iterable[Any]:
    if isinstance(context, dict):
        return context.get(key) or []
    return getattr(context, key, ()) or ()


def _assignment_key(assignment: Any) -> tuple[str, str, int] | None:
    try:
        return (
            str(_item_value(assignment, "team_id")),
            str(_item_value(assignment, "group_id")),
            int(_item_value(assignment, "number")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _item_value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item[key]
    return getattr(item, key)


def _status(raw_result: dict[str, Any], solution: dict[str, Any]) -> str:
    return str(raw_result.get("status") or solution.get("status") or "UNKNOWN").upper()


def _component_id(*payloads: dict[str, Any]) -> str:
    for payload in payloads:
        value = payload.get("component_id")
        if value:
            return str(value)
    raise ValueError("component_id is required for each component result")


def _is_raw_artifact(payload: dict[str, Any]) -> bool:
    return payload.get("artifact_type") == "resource_solver_component_raw_result"


def _is_solution_artifact(payload: dict[str, Any]) -> bool:
    return payload.get("artifact_type") == "resource_solver_component_solution_partial"


def _numeric_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _append_error(errors: list[dict[str, Any]], code: str, rows: list[Any]) -> None:
    if rows:
        errors.append({"code": code, "items": rows})


def _read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload must be an object: {path}")
    return payload


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = ""
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_name = tmp_file.name
            json.dump(_json_ready(payload), tmp_file, ensure_ascii=False, indent=2, sort_keys=True)
            tmp_file.write("\n")
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_name, path)
    except Exception:
        if tmp_name:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


__all__ = [
    "ComponentMergeValidationError",
    "merge_component_results",
]
