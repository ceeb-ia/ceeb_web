"""Registry for calendarization engines."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from calendaritzacions.engine.base import CalendarizationEngine, EngineResult
from calendaritzacions.engine.config import EngineConfig

LegacyProcessResult = str | tuple[str, list[str]]
EngineCallable = Callable[[str, bool, str | None, bool], LegacyProcessResult]
RegisteredEngine = CalendarizationEngine | EngineCallable


class LegacyEngine:
    """Adapter exposing the legacy callable through the engine contract."""

    def __call__(
        self,
        input_path: str,
        return_logs: bool = False,
        task_id: str | None = None,
        segona_fase_bool: bool = False,
    ) -> LegacyProcessResult:
        from calendaritzacions.application.compatibility import process_excel

        return process_excel(
            input_path=input_path,
            return_logs=return_logs,
            task_id=task_id,
            segona_fase_bool=segona_fase_bool,
        )

    def run(
        self,
        input_path: str,
        config: EngineConfig,
        progress: Any | None = None,
    ) -> EngineResult:
        result = self(input_path, return_logs=True)
        if isinstance(result, tuple):
            output_path, logs = result
        else:
            output_path, logs = result, []
        return EngineResult(output_path=output_path, logs=logs)


_ENGINES: dict[str, RegisteredEngine] = {
    "legacy": LegacyEngine(),
}


def _resource_solver_engine() -> CalendarizationEngine:
    from calendaritzacions.engine.variants.resource_solver import ResourceSolverEngine

    return ResourceSolverEngine()


def _resource_solver_conflict_repair_engine() -> CalendarizationEngine:
    from calendaritzacions.engine.variants.resource_solver import ResourceSolverConflictRepairEngine

    return ResourceSolverConflictRepairEngine()


_ENGINES["resource_solver"] = _resource_solver_engine()
_ENGINES["resource_solver_linkage"] = _resource_solver_engine()
_ENGINES["resource_solver_vinculacio"] = _resource_solver_engine()
_ENGINES["resource_solver_conflict_repair"] = _resource_solver_conflict_repair_engine()


def register_engine(name: str, engine: RegisteredEngine) -> None:
    """Register an engine callable or engine object by name."""
    _ENGINES[name] = engine


def get_engine(name: str = "legacy") -> RegisteredEngine:
    """Return a registered engine callable or engine object."""
    return _ENGINES[name]
