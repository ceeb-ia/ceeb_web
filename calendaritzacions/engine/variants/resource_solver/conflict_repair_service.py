"""Experimental conflict-repair resource solver engine."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from calendaritzacions.engine.base import EngineResult
from calendaritzacions.engine.variants.resource_solver.audit import (
    build_audit_payloads,
    write_audit_payloads,
)
from calendaritzacions.engine.variants.resource_solver.component_context import (
    filter_context_by_team_ids,
)
from calendaritzacions.engine.variants.resource_solver.config import (
    coerce_resource_solver_config,
)
from calendaritzacions.engine.variants.resource_solver.conflict_repair import (
    build_initial_components,
    build_repair_blocks,
    component_solve_payload,
    conflict_hubs_payload,
    context_with_residual_capacities,
    detect_conflict_hubs,
    frozen_usage_by_resource,
    initial_components_payload,
    iteration_summary_payload,
    merge_assignments,
    repair_blocks_payload,
    team_to_initial_component,
    validate_assignments,
)
from calendaritzacions.engine.variants.resource_solver.local_explanations import (
    build_local_explanations,
)
from calendaritzacions.engine.variants.resource_solver.model import (
    build_solver_model,
    solve_model,
)
from calendaritzacions.engine.variants.resource_solver.service import (
    _build_input_pre_analysis,
    _competition_context_log_lines,
    _competition_result_log_lines,
    _context_log_lines,
    _output_dir_for,
    _report,
    _result_log_lines,
)
from calendaritzacions.engine.variants.resource_solver.solution import (
    build_solution,
    result_to_json_ready,
)
from calendaritzacions.engine.variants.resource_solver.types import (
    Assignment,
    ResourceSolverResult,
    SolverContext,
)


class ResourceSolverConflictRepairEngine:
    """Two-level solver that repairs only resource conflict hubs."""

    def run(self, input_path: str, config: Any, progress: Any | None = None) -> EngineResult:
        solver_config = coerce_resource_solver_config(config)
        logs = [
            "resource_solver_conflict_repair: starting",
            f"resource_solver_conflict_repair: input={Path(input_path).name}",
            f"resource_solver_conflict_repair: phase={solver_config.phase_name}",
        ]
        output_dir = _output_dir_for(input_path)
        _report(progress, "Preparant motor conflict-repair...", 5)
        pre_analysis = _build_input_pre_analysis(
            input_path=input_path,
            output_dir=output_dir,
            logs=logs,
            progress=progress,
        )

        from calendaritzacions.engine.variants.resource_solver.input_adapter import (
            build_context_from_dataframe,
        )

        _report(progress, "Construint context conflict-repair...", 20)
        context = build_context_from_dataframe(pre_analysis["input_df"], config=solver_config)
        logs.extend(_context_log_lines(context))
        logs.extend(_competition_context_log_lines(context))

        _report(progress, "Resolent components inicials per competicio i links...", 35)
        initial_components = build_initial_components(context)
        initial_assignments, initial_records = _solve_initial_components(context, initial_components)
        initial_result = _result_from_assignments(
            context=context,
            assignments=initial_assignments,
            status=_aggregate_status(record["status"] for record in initial_records),
            logs=("resource_solver_conflict_repair: initial component merge",),
        )
        logs.append(
            "conflict-repair: initial "
            f"components={len(initial_components)} "
            f"assignments={len(initial_result.assignments)}/{len(context.teams)} "
            f"resource_excess={_total_resource_excess(initial_result)}"
        )

        _report(progress, "Detectant hubs de conflicte de recursos...", 55)
        team_to_component = team_to_initial_component(initial_components)
        conflict_hubs = detect_conflict_hubs(context, initial_result, team_to_component)
        repair_blocks = build_repair_blocks(context, initial_components, conflict_hubs)
        logs.append(
            "conflict-repair: hubs "
            f"conflicts={len(conflict_hubs)} blocks={len(repair_blocks)}"
        )

        _report(progress, "Reoptimitzant blocs amb capacitats residuals...", 65)
        repaired_by_block, repair_records = _repair_blocks(
            context=context,
            initial_result=initial_result,
            repair_blocks=repair_blocks,
        )

        try:
            final_assignments = merge_assignments(
                context=context,
                initial_assignments=initial_result.assignments,
                repaired_assignments_by_block=repaired_by_block,
                repair_blocks=repair_blocks,
            )
            validation = validate_assignments(context, final_assignments)
            final_status = _aggregate_status(
                [
                    initial_result.status,
                    *(record["status"] for record in repair_records if record.get("accepted")),
                ]
            )
        except ValueError as exc:
            logs.append(f"conflict-repair: merge invalid ({exc})")
            final_assignments = initial_result.assignments
            validation = validate_assignments(context, final_assignments)
            final_status = "INVALID_MERGE"

        final_result = _result_from_assignments(
            context=context,
            assignments=final_assignments,
            status=final_status,
            logs=("resource_solver_conflict_repair: final global solution rebuilt",),
        )
        logs.append(
            "conflict-repair: final "
            f"assignments={len(final_result.assignments)}/{len(context.teams)} "
            f"resource_excess={_total_resource_excess(final_result)} "
            f"accepted_repairs={sum(1 for record in repair_records if record.get('accepted'))}"
        )

        _report(progress, "Generant auditoria i Excel conflict-repair...", 80)
        audit_payloads = build_audit_payloads(
            result=final_result,
            context=context,
            raw_result=_raw_result(final_status, final_assignments),
            built_model=None,
            local_explanations=build_local_explanations(final_result, context),
        )
        audit_payloads.update(pre_analysis["audit_payloads"])
        audit_payloads.update(
            {
                "conflict_repair_initial_components": initial_components_payload(initial_components),
                "conflict_repair_component_solves": component_solve_payload(initial_records),
                "conflict_repair_hubs": conflict_hubs_payload(conflict_hubs),
                "conflict_repair_blocks": repair_blocks_payload(repair_blocks),
                "conflict_repair_iteration_summary": iteration_summary_payload(
                    initial_result=initial_result,
                    final_result=final_result,
                    repair_records=repair_records,
                    validation=validation,
                ),
            }
        )

        audit_paths = write_audit_payloads(audit_payloads, output_dir)
        result_json_path = output_dir / "resource_solver_conflict_repair_result.json"
        result_json_path.write_text(
            json.dumps(result_to_json_ready(final_result), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        audit_paths["resource_solver_conflict_repair_result"] = str(result_json_path)

        output_path = output_dir / f"assignacions_conflict_repair_{Path(input_path).stem}.xlsx"
        from calendaritzacions.reporting.resource_solver_excel_adapter import (
            write_resource_solver_workbook,
        )

        write_resource_solver_workbook(str(output_path), result=final_result, context=context)

        try:
            from calendaritzacions.reporting.resource_solver_plots import (
                write_resource_solver_final_plots,
            )

            final_plots = write_resource_solver_final_plots(
                output_dir / "plots_final_conflict_repair",
                result=final_result,
                context=context,
                stem=f"resource_solver_conflict_repair_{Path(input_path).stem}",
            )
            manifest_path = final_plots.get("manifest")
            if manifest_path:
                audit_paths["resource_solver_final_plots"] = manifest_path
            logs.append(f"conflict-repair: plots finals generats={max(0, len(final_plots) - 1)}")
        except Exception as exc:
            logs.append(f"conflict-repair: plots finals no generats ({exc})")

        try:
            from calendaritzacions.reporting.resource_solver_decomposition_plots import (
                write_resource_solver_decomposition_plots,
            )

            conflict_repair_plots = write_resource_solver_decomposition_plots(
                output_dir / "plots_conflict_repair",
                summary={"components": initial_components_payload(initial_components)["components"]},
                context=context,
                stem=f"resource_solver_conflict_repair_components_{Path(input_path).stem}",
            )
            manifest_path = conflict_repair_plots.get("manifest")
            if manifest_path:
                _rewrite_conflict_repair_plot_manifest(manifest_path)
                audit_paths["resource_solver_conflict_repair_plots"] = manifest_path
            logs.append(f"conflict-repair: plots components generats={max(0, len(conflict_repair_plots) - 1)}")
        except Exception as exc:
            logs.append(f"conflict-repair: plots components no generats ({exc})")

        logs.extend(str(item) for item in final_result.logs)
        logs.append(f"resource_solver_conflict_repair: status={final_result.status}")
        logs.extend(_result_log_lines(final_result))
        logs.extend(_competition_result_log_lines(final_result, context))
        logs.append(f"resource_solver_conflict_repair: excel={output_path.name}")
        _report(progress, "Excel i auditoria conflict-repair generats.", 90)
        return EngineResult(output_path=str(output_path), audit_paths=audit_paths, logs=logs)


def _solve_initial_components(
    context: SolverContext,
    initial_components: tuple[Any, ...],
) -> tuple[tuple[Assignment, ...], tuple[dict[str, Any], ...]]:
    assignments: list[Assignment] = []
    records: list[dict[str, Any]] = []
    for component in initial_components:
        subcontext = filter_context_by_team_ids(context, component.team_ids)
        built_model = build_solver_model(subcontext)
        raw_result = solve_model(built_model, subcontext.config)
        solution = build_solution(raw_result, subcontext)
        assignments.extend(solution.assignments)
        records.append(
            {
                "stage": "initial",
                "component_id": component.component_id,
                "team_count": len(component.team_ids),
                "candidate_count": len(subcontext.candidates),
                "status": solution.status,
                "assignment_count": len(solution.assignments),
                "resource_excess": _total_resource_excess(solution),
                "backend": getattr(built_model, "backend", "unknown"),
                "model_summary": getattr(built_model, "summary", {}) or {},
            }
        )
    return tuple(assignments), tuple(records)


def _repair_blocks(
    *,
    context: SolverContext,
    initial_result: ResourceSolverResult,
    repair_blocks: tuple[Any, ...],
) -> tuple[dict[str, tuple[Assignment, ...]], tuple[dict[str, Any], ...]]:
    repaired: dict[str, tuple[Assignment, ...]] = {}
    records: list[dict[str, Any]] = []
    for block in repair_blocks:
        subcontext = filter_context_by_team_ids(context, block.team_ids)
        frozen_usage = frozen_usage_by_resource(initial_result, block.team_ids)
        repair_context = context_with_residual_capacities(subcontext, frozen_usage)
        built_model = build_solver_model(repair_context)
        raw_result = solve_model(built_model, repair_context.config)
        solution = build_solution(raw_result, repair_context)
        accepted = solution.status in {"OPTIMAL", "FEASIBLE"} and len(solution.assignments) == len(block.team_ids)
        if accepted:
            repaired[block.block_id] = solution.assignments
        records.append(
            {
                "stage": "repair",
                "block_id": block.block_id,
                "initial_component_ids": block.initial_component_ids,
                "team_count": len(block.team_ids),
                "conflict_resource_ids": block.conflict_resource_ids,
                "frozen_usage": frozen_usage,
                "status": solution.status,
                "assignment_count": len(solution.assignments),
                "resource_excess": _total_resource_excess(solution),
                "accepted": accepted,
                "backend": getattr(built_model, "backend", "unknown"),
                "model_summary": getattr(built_model, "summary", {}) or {},
            }
        )
    return repaired, tuple(records)


def _result_from_assignments(
    *,
    context: SolverContext,
    assignments: tuple[Assignment, ...] | list[Assignment],
    status: str,
    logs: tuple[str, ...] = (),
) -> ResourceSolverResult:
    return build_solution(_raw_result(status, tuple(assignments), logs=logs), context)


def _raw_result(
    status: str,
    assignments: tuple[Assignment, ...] | list[Assignment],
    logs: tuple[str, ...] = (),
) -> Any:
    return SimpleNamespace(
        status=status,
        objective_value=None,
        best_bound=None,
        wall_time=0.0,
        assignments=tuple(assignments),
        resource_excess={},
        logs=logs,
    )


def _aggregate_status(statuses: Any) -> str:
    values = tuple(str(status or "UNKNOWN") for status in statuses)
    if not values:
        return "UNKNOWN"
    if any(status in {"INFEASIBLE", "MODEL_INVALID", "INVALID", "INVALID_MERGE"} for status in values):
        return "INVALID_MERGE" if "INVALID_MERGE" in values else "INFEASIBLE"
    if any(status == "FEASIBLE" for status in values):
        return "FEASIBLE"
    if all(status == "OPTIMAL" for status in values):
        return "OPTIMAL"
    return values[-1]


def _rewrite_conflict_repair_plot_manifest(manifest_path: str) -> None:
    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return
    payload["artifact_type"] = "resource_solver_conflict_repair_plots"
    notes = list(payload.get("notes") or [])
    notes.insert(
        0,
        "Aquests plots descriuen la particio inicial del motor conflict-repair: competicions i vinculacions abans de conciliar recursos.",
    )
    payload["notes"] = notes
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _total_resource_excess(result: ResourceSolverResult) -> int:
    return sum(int(usage.excess) for usage in result.resource_usage)


__all__ = ["ResourceSolverConflictRepairEngine"]
