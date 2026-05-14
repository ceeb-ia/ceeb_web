"""Pure component-level solve adapter for the resource solver."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable

from calendaritzacions.domain.phases import PRIMERA_FASE, SEGONA_FASE
from calendaritzacions.engine.variants.resource_solver.audit import json_ready
from calendaritzacions.engine.variants.resource_solver.config import ResourceSolverConfig
from calendaritzacions.engine.variants.resource_solver.model import (
    build_solver_model,
    solve_model,
)
from calendaritzacions.engine.variants.resource_solver.solution import (
    build_solution,
    result_to_json_ready,
)
from calendaritzacions.engine.variants.resource_solver.types import (
    BaseResource,
    Candidate,
    CapacityEstimate,
    GroupSpec,
    PressureRow,
    SolverContext,
    TeamRecord,
)


BuildSolverModel = Callable[[SolverContext], Any]
SolveModel = Callable[[Any, ResourceSolverConfig | None], Any]


def load_component_context_payload(source: str | Path | dict[str, Any] | SolverContext) -> SolverContext:
    """Load a component ``SolverContext`` from a JSON file or JSON-ready payload."""

    if isinstance(source, SolverContext):
        return source
    if isinstance(source, (str, Path)):
        payload = json.loads(Path(source).read_text(encoding="utf-8"))
    else:
        payload = source

    context_payload = payload.get("context", payload)
    if not isinstance(context_payload, dict):
        raise TypeError("component context payload must be a JSON object")
    return _context_from_payload(context_payload)


def solve_component_context(
    context_or_payload: str | Path | dict[str, Any] | SolverContext,
    output_dir: str | Path,
    *,
    component_id: str | None = None,
    build_solver_model_func: BuildSolverModel | None = None,
    solve_model_func: SolveModel | None = None,
) -> dict[str, Any]:
    """Build, solve and persist JSON artifacts for one component.

    This function is intentionally free of Django, DB and Celery concerns. Tests
    can inject lightweight ``build_solver_model`` and ``solve_model`` callables.
    """

    context = load_component_context_payload(context_or_payload)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    build = build_solver_model_func or build_solver_model
    solve = solve_model_func or solve_model

    built_model = build(context)
    model_summary = _model_summary_payload(built_model, context, component_id)
    model_summary_path = output_path / "model_summary.json"
    _atomic_write_json(model_summary_path, model_summary)

    raw_result = solve(built_model, context.config)
    raw_result_payload = _artifact_payload(
        "resource_solver_component_raw_result",
        raw_result,
        component_id,
    )
    raw_result_path = output_path / "raw_result.json"
    _atomic_write_json(raw_result_path, raw_result_payload)

    solution = build_solution(raw_result, context)
    solution_payload = _artifact_payload(
        "resource_solver_component_solution_partial",
        result_to_json_ready(solution),
        component_id,
    )
    solution_path = output_path / "solution_partial.json"
    _atomic_write_json(solution_path, solution_payload)

    return {
        "artifact_type": "resource_solver_component_solve",
        "component_id": component_id,
        "status": raw_result_payload.get("status"),
        "model_summary": model_summary,
        "raw_result": raw_result_payload,
        "solution_partial": solution_payload,
        "paths": {
            "model_summary": str(model_summary_path),
            "raw_result": str(raw_result_path),
            "solution_partial": str(solution_path),
        },
    }


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp_file:
        tmp_name = tmp_file.name
        json.dump(json_ready(payload), tmp_file, ensure_ascii=False, indent=2, sort_keys=True)
        tmp_file.write("\n")
        tmp_file.flush()
        os.fsync(tmp_file.fileno())
    os.replace(tmp_name, path)


def _model_summary_payload(
    built_model: Any,
    context: SolverContext,
    component_id: str | None,
) -> dict[str, Any]:
    summary = json_ready(getattr(built_model, "summary", {}) or {})
    if not isinstance(summary, dict):
        summary = {"summary": summary}
    return {
        "artifact_type": "resource_solver_component_model_summary",
        "component_id": component_id,
        "num_teams": len(context.teams),
        "num_groups": len(context.groups),
        "num_candidates": len(context.candidates),
        **summary,
    }


def _artifact_payload(artifact_type: str, value: Any, component_id: str | None) -> dict[str, Any]:
    payload = _object_payload(value)
    if not isinstance(payload, dict):
        payload = {"value": payload}
    return {
        "artifact_type": artifact_type,
        "component_id": component_id,
        **payload,
    }


def _object_payload(value: Any) -> Any:
    if is_dataclass(value):
        return json_ready(asdict(value))
    if isinstance(value, dict):
        return json_ready(value)
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        return json_ready(attributes)
    return json_ready(value)


def _context_from_payload(payload: dict[str, Any]) -> SolverContext:
    phase_name = str(payload.get("phase_name") or getattr(payload.get("config"), "phase_name", ""))
    phase_payload = payload.get("phase")
    phase = _phase_from_payload(phase_payload, phase_name)
    config = _config_from_payload(payload.get("config"))

    return SolverContext(
        teams=tuple(_dataclass_from_payload(TeamRecord, item) for item in payload.get("teams", ())),
        phase=phase,
        phase_name=phase_name or config.phase_name,
        base_resources={
            str(key): _dataclass_from_payload(BaseResource, value)
            for key, value in (payload.get("base_resources") or {}).items()
        },
        capacities={
            str(key): _dataclass_from_payload(CapacityEstimate, value)
            for key, value in (payload.get("capacities") or {}).items()
        },
        pressure=tuple(
            _dataclass_from_payload(PressureRow, item)
            for item in payload.get("pressure", ())
        ),
        groups=tuple(_dataclass_from_payload(GroupSpec, item) for item in payload.get("groups", ())),
        candidates=tuple(
            _candidate_from_payload(item)
            for item in payload.get("candidates", ())
        ),
        config=config,
    )


def _phase_from_payload(value: Any, phase_name: str):
    if value:
        return tuple(
            tuple((int(home), int(away)) for home, away in round_matches)
            for round_matches in value
        )
    if phase_name == "segona_fase":
        return SEGONA_FASE
    return PRIMERA_FASE


def _config_from_payload(value: Any) -> ResourceSolverConfig:
    if isinstance(value, ResourceSolverConfig):
        return value
    if not isinstance(value, dict):
        return ResourceSolverConfig()
    valid_names = {field.name for field in fields(ResourceSolverConfig)}
    kwargs = {key: item for key, item in value.items() if key in valid_names}
    return ResourceSolverConfig(**kwargs)


def _dataclass_from_payload(cls: type, value: Any) -> Any:
    if isinstance(value, cls):
        return value
    if is_dataclass(value):
        value = asdict(value)
    if not isinstance(value, dict):
        raise TypeError(f"{cls.__name__} payload must be a JSON object")
    valid_names = {field.name for field in fields(cls)}
    kwargs = {key: value[key] for key in valid_names if key in value}
    if cls is GroupSpec and "numbers" in kwargs:
        kwargs["numbers"] = tuple(int(item) for item in kwargs["numbers"])
    if cls is PressureRow and "team_ids" in kwargs:
        kwargs["team_ids"] = tuple(str(item) for item in kwargs["team_ids"])
    return cls(**kwargs)


def _candidate_from_payload(value: Any) -> Candidate:
    if isinstance(value, Candidate):
        return value
    if is_dataclass(value):
        value = asdict(value)
    if not isinstance(value, dict):
        raise TypeError("Candidate payload must be a JSON object")
    return Candidate(
        candidate_id=str(value["candidate_id"]),
        team_id=str(value["team_id"]),
        group_id=str(value["group_id"]),
        number=int(value["number"]),
        seed_request_original=value.get("seed_request_original", ""),
        potential_home_rounds=tuple(int(item) for item in value.get("potential_home_rounds", ())),
        opponent_number_by_round={
            int(round_index): int(opponent)
            for round_index, opponent in (value.get("opponent_number_by_round") or {}).items()
        },
        potential_resources=tuple(str(item) for item in value.get("potential_resources", ())),
    )


__all__ = [
    "load_component_context_payload",
    "solve_component_context",
]
