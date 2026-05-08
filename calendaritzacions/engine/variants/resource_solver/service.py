"""Service entry point for the resource solver engine."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from calendaritzacions.domain.phases import PRIMERA_FASE, SEGONA_FASE
from calendaritzacions.engine.base import EngineResult
from calendaritzacions.engine.variants.resource_solver.audit import (
    build_audit_payloads,
    write_audit_payloads,
)
from calendaritzacions.engine.variants.resource_solver.config import (
    ResourceSolverConfig,
    coerce_resource_solver_config,
)
from calendaritzacions.engine.variants.resource_solver.local_explanations import (
    build_local_explanations,
)
from calendaritzacions.engine.variants.resource_solver.solution import (
    build_solution,
    result_to_json_ready,
)
from calendaritzacions.engine.variants.resource_solver.types import SolverContext


class ResourceSolverEngine:
    """Resource solver service boundary.

    The CP-SAT model is developed by another layer. Until that layer is present,
    this service returns an auditable empty result instead of falling back to
    legacy behavior.
    """

    def run(self, input_path: str, config: Any, progress: Any | None = None) -> EngineResult:
        solver_config = coerce_resource_solver_config(config)
        logs = ["resource_solver: starting"]
        _report(progress, "Preparant motor resource_solver...", 5)

        raw_result, context, built_model = self._run_solver_or_scaffold(
            input_path=input_path,
            config=solver_config,
            progress=progress,
            logs=logs,
        )
        result = build_solution(raw_result, context)
        local_explanations = build_local_explanations(result, context)
        audit_payloads = build_audit_payloads(
            result=result,
            context=context,
            raw_result=raw_result,
            built_model=built_model,
            local_explanations=local_explanations,
        )

        output_dir = _output_dir_for(input_path)
        audit_paths = write_audit_payloads(audit_payloads, output_dir)
        result_json_path = output_dir / "resource_solver_result.json"
        result_json_path.write_text(
            json.dumps(result_to_json_ready(result), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        audit_paths["resource_solver_result"] = str(result_json_path)

        output_path = output_dir / f"assignacions_{Path(input_path).stem}.xlsx"
        from calendaritzacions.reporting.resource_solver_excel_adapter import (
            write_resource_solver_workbook,
        )

        write_resource_solver_workbook(
            str(output_path),
            result=result,
            context=context,
        )

        logs.extend(str(item) for item in result.logs)
        logs.append(f"resource_solver: status={result.status}")
        logs.append(f"resource_solver: excel={output_path.name}")
        _report(progress, "Excel i auditoria resource_solver generats.", 90)
        return EngineResult(
            output_path=str(output_path),
            audit_paths=audit_paths,
            logs=logs,
        )

    def _run_solver_or_scaffold(
        self,
        input_path: str,
        config: ResourceSolverConfig,
        progress: Any | None,
        logs: list[str],
    ) -> tuple[Any, SolverContext, Any | None]:
        """Run the real model when available, otherwise return a safe scaffold."""

        try:
            return self._run_optional_model_pipeline(input_path, config, progress, logs)
        except (ImportError, NotImplementedError) as exc:
            logs.append(f"resource_solver: model pipeline unavailable ({exc})")
            context = _empty_context(config)
            raw_result = SimpleNamespace(
                status="UNKNOWN",
                objective_value=None,
                best_bound=None,
                wall_time=0.0,
                assignments=(),
                entity_excess={},
                logs=("resource_solver scaffold result; CP-SAT model not executed",),
            )
            return raw_result, context, None

    def _run_optional_model_pipeline(
        self,
        input_path: str,
        config: ResourceSolverConfig,
        progress: Any | None,
        logs: list[str],
    ) -> tuple[Any, SolverContext, Any | None]:
        """Hook for the future RS-01..RS-05 pipeline.

        The function intentionally imports lazily. Other agents can provide
        ``build_context_from_input``, ``build_solver_model`` and ``solve_model``
        without changing this service contract.
        """

        from calendaritzacions.engine.variants.resource_solver.input_adapter import (  # type: ignore
            build_context_from_input,
        )
        from calendaritzacions.engine.variants.resource_solver.model import (  # type: ignore
            build_solver_model,
            solve_model,
        )

        _report(progress, "Construint context resource_solver...", 20)
        context = build_context_from_input(input_path=input_path, config=config)
        _report(progress, "Executant CP-SAT resource_solver...", 50)
        built_model = build_solver_model(context)
        raw_result = solve_model(built_model, config)
        logs.append("resource_solver: CP-SAT model executed")
        return raw_result, context, built_model


def _empty_context(config: ResourceSolverConfig) -> SolverContext:
    phase = SEGONA_FASE if config.phase_name == "segona_fase" else PRIMERA_FASE
    phase_name = "segona_fase" if config.phase_name == "segona_fase" else "primera_fase"
    return SolverContext(
        teams=(),
        phase=phase,
        phase_name=phase_name,
        base_resources={},
        capacities={},
        pressure=(),
        groups=(),
        candidates=(),
        config=config,
    )


def _output_dir_for(input_path: str) -> Path:
    path = Path(input_path)
    parent = path.parent if str(path.parent) not in ("", ".") else Path.cwd()
    stem = path.stem or "resource_solver"
    return parent / f"{stem}_resource_solver_audit"


def _report(progress: Any | None, message: str, percent: int) -> None:
    if progress is None:
        return
    report = getattr(progress, "report", None)
    if callable(report):
        report(message, percent)
