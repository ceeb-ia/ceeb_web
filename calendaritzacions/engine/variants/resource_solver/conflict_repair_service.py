"""Experimental conflict-repair resource solver engine."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from time import perf_counter
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
    build_linkage_repair_blocks,
    build_repair_blocks,
    component_solve_payload,
    conflict_hubs_payload,
    context_with_residual_capacities,
    detect_conflict_hubs,
    detect_linkage_conflicts,
    frozen_usage_by_resource,
    initial_components_payload,
    iteration_summary_payload,
    linkage_conflicts_payload,
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
    _report_artifact,
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
        started_at = perf_counter()
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
        early_audit_paths = _write_and_report_partial_audits(
            pre_analysis["audit_payloads"],
            output_dir,
            progress,
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
        initial_components_audit = _write_and_report_partial_audits(
            {"conflict_repair_initial_components": initial_components_payload(initial_components)},
            output_dir,
            progress,
        )
        early_audit_paths.update(initial_components_audit)
        early_plot_paths = _write_and_report_conflict_repair_plots(
            output_dir=output_dir,
            context=context,
            initial_components=initial_components,
            input_path=input_path,
            progress=progress,
            logs=logs,
        )
        early_audit_paths.update(early_plot_paths)
        initial_assignments, initial_records = _solve_initial_components(
            context,
            initial_components,
            progress=progress,
            output_dir=output_dir,
        )
        early_audit_paths.update(
            _write_and_report_partial_audits(
                {"conflict_repair_component_solves": component_solve_payload(initial_records)},
                output_dir,
                progress,
            )
        )
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

        _report(progress, "Detectant linkages tallats per reconciliar...", 55)
        linkage_conflicts = detect_linkage_conflicts(context, initial_result, initial_components)
        linkage_blocks = build_linkage_repair_blocks(context, initial_components, linkage_conflicts)
        early_audit_paths.update(
            _write_and_report_partial_audits(
                {
                    "conflict_repair_linkage_conflicts": linkage_conflicts_payload(linkage_conflicts),
                    "conflict_repair_linkage_blocks": repair_blocks_payload(linkage_blocks),
                },
                output_dir,
                progress,
            )
        )
        logs.append(
            "conflict-repair: linkage "
            f"conflicts={len(linkage_conflicts)} "
            f"mismatches={sum(conflict.mismatch_count for conflict in linkage_conflicts)} "
            f"blocks={len(linkage_blocks)}"
        )

        _report(progress, "Reoptimitzant blocs de linkage...", 58)
        linkage_repaired_by_block, linkage_repair_records = _repair_linkage_blocks(
            context=context,
            initial_components=initial_components,
            initial_result=initial_result,
            linkage_blocks=linkage_blocks,
            progress=progress,
            repair_deadline_at=_repair_deadline_at(started_at, solver_config),
        )
        try:
            linkage_assignments = merge_assignments(
                context=context,
                initial_assignments=initial_result.assignments,
                repaired_assignments_by_block=linkage_repaired_by_block,
                repair_blocks=linkage_blocks,
            )
            linkage_result = _result_from_assignments(
                context=context,
                assignments=linkage_assignments,
                status=_aggregate_status([initial_result.status, *(record["status"] for record in linkage_repair_records if record.get("accepted"))]),
                logs=("resource_solver_conflict_repair: linkage repair solution rebuilt",),
            )
        except ValueError as exc:
            logs.append(f"conflict-repair: linkage merge invalid ({exc})")
            linkage_result = initial_result
            linkage_repair_records = (
                *linkage_repair_records,
                {
                    "stage": "linkage_repair",
                    "status": "INVALID_MERGE",
                    "accepted": False,
                    "fallback_used": True,
                    "error": str(exc),
                },
            )

        _report(progress, "Detectant hubs de conflicte de recursos...", 62)
        team_to_component = team_to_initial_component(initial_components)
        conflict_hubs = detect_conflict_hubs(context, linkage_result, team_to_component)
        repair_blocks = build_repair_blocks(context, initial_components, conflict_hubs)
        early_audit_paths.update(
            _write_and_report_partial_audits(
                {
                    "conflict_repair_hubs": conflict_hubs_payload(conflict_hubs),
                    "conflict_repair_blocks": repair_blocks_payload(repair_blocks),
                    "conflict_repair_iteration_summary_partial": _partial_iteration_summary_payload(
                        initial_result=initial_result,
                        conflict_hubs=conflict_hubs,
                        repair_blocks=repair_blocks,
                    ),
                },
                output_dir,
                progress,
            )
        )
        logs.append(
            "conflict-repair: hubs "
            f"conflicts={len(conflict_hubs)} blocks={len(repair_blocks)}"
        )

        _report(progress, "Reoptimitzant blocs amb capacitats residuals...", 68)
        repaired_by_block, repair_records = _repair_blocks(
            context=context,
            initial_result=linkage_result,
            repair_blocks=repair_blocks,
            progress=progress,
            repair_deadline_at=_repair_deadline_at(started_at, solver_config),
        )
        all_repair_records = (*linkage_repair_records, *repair_records)

        try:
            final_assignments = merge_assignments(
                context=context,
                initial_assignments=linkage_result.assignments,
                repaired_assignments_by_block=repaired_by_block,
                repair_blocks=repair_blocks,
            )
            validation = validate_assignments(context, final_assignments)
            final_status = _aggregate_status(
                [
                    linkage_result.status,
                    *(record["status"] for record in all_repair_records if record.get("accepted")),
                ]
            )
            if any(record.get("fallback_used") for record in all_repair_records):
                final_status = "FEASIBLE"
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
            f"accepted_repairs={sum(1 for record in all_repair_records if record.get('accepted'))}"
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
                "conflict_repair_linkage_conflicts": linkage_conflicts_payload(linkage_conflicts),
                "conflict_repair_linkage_blocks": repair_blocks_payload(linkage_blocks),
                "conflict_repair_hubs": conflict_hubs_payload(conflict_hubs),
                "conflict_repair_blocks": repair_blocks_payload(repair_blocks),
                "conflict_repair_iteration_summary": iteration_summary_payload(
                    initial_result=initial_result,
                    final_result=final_result,
                    repair_records=all_repair_records,
                    validation=validation,
                ),
            }
        )

        audit_paths = write_audit_payloads(audit_payloads, output_dir)
        audit_paths = {**early_audit_paths, **audit_paths}
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
    progress: Any | None = None,
    output_dir: Path | None = None,
) -> tuple[tuple[Assignment, ...], tuple[dict[str, Any], ...]]:
    assignments: list[Assignment] = []
    records: list[dict[str, Any]] = []
    total = len(initial_components)
    for index, component in enumerate(initial_components, start=1):
        subcontext = _with_solve_time_limit(
            filter_context_by_team_ids(context, component.team_ids),
            _initial_solve_limit(context),
        )
        solve_limit = getattr(subcontext.config, "time_limit_seconds", None)
        _report(
            progress,
            "Resolent component inicial "
            f"{index}/{total}: {component.component_id} "
            f"({len(component.team_ids)} equips, {len(subcontext.candidates)} candidats, timeout={solve_limit}s)",
            _stage_percent(35, 55, index - 1, total),
        )
        built_model = build_solver_model(subcontext)
        raw_result = solve_model(built_model, subcontext.config)
        solution = build_solution(raw_result, subcontext)
        assignments.extend(solution.assignments)
        _report(
            progress,
            "Component inicial resolt "
            f"{index}/{total}: {component.component_id} "
            f"status={solution.status} assignacions={len(solution.assignments)}/{len(component.team_ids)}",
            _stage_percent(35, 55, index, total),
        )
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
        if output_dir is not None:
            _write_and_report_partial_audits(
                {"conflict_repair_component_solves": component_solve_payload(records)},
                output_dir,
                progress,
            )
    return tuple(assignments), tuple(records)


def _write_and_report_partial_audits(
    payloads: dict[str, Any],
    output_dir: Path,
    progress: Any | None,
) -> dict[str, str]:
    audit_paths = write_audit_payloads(payloads, output_dir)
    for name, path in audit_paths.items():
        _report_artifact(progress, name, path)
    return audit_paths


def _write_and_report_conflict_repair_plots(
    *,
    output_dir: Path,
    context: SolverContext,
    initial_components: tuple[Any, ...],
    input_path: str,
    progress: Any | None,
    logs: list[str],
) -> dict[str, str]:
    try:
        from calendaritzacions.reporting.resource_solver_decomposition_plots import (
            write_resource_solver_decomposition_plots,
        )

        plots = write_resource_solver_decomposition_plots(
            output_dir / "plots_conflict_repair",
            summary={"components": initial_components_payload(initial_components)["components"]},
            context=context,
            stem=f"resource_solver_conflict_repair_components_{Path(input_path).stem}",
        )
        manifest_path = plots.get("manifest")
        if not manifest_path:
            return {}
        _rewrite_conflict_repair_plot_manifest(manifest_path)
        _report_artifact(progress, "resource_solver_conflict_repair_plots", manifest_path)
        logs.append(f"conflict-repair: plots components inicials generats={max(0, len(plots) - 1)}")
        return {"resource_solver_conflict_repair_plots": manifest_path}
    except Exception as exc:
        logs.append(f"conflict-repair: plots components inicials no generats ({exc})")
        return {}


def _partial_iteration_summary_payload(
    *,
    initial_result: ResourceSolverResult,
    conflict_hubs: tuple[Any, ...],
    repair_blocks: tuple[Any, ...],
) -> dict[str, Any]:
    return {
        "artifact_type": "resource_solver_conflict_repair_iteration_summary_partial",
        "stage": "before_repair",
        "initial_resource_excess": _total_resource_excess(initial_result),
        "initial_assignments": len(initial_result.assignments),
        "conflict_hub_count": len(conflict_hubs),
        "repair_block_count": len(repair_blocks),
        "pending_repair_blocks": len(repair_blocks),
    }


def _repair_linkage_blocks(
    *,
    context: SolverContext,
    initial_components: tuple[Any, ...],
    initial_result: ResourceSolverResult,
    linkage_blocks: tuple[Any, ...],
    progress: Any | None = None,
    repair_deadline_at: float | None = None,
) -> tuple[dict[str, tuple[Assignment, ...]], tuple[dict[str, Any], ...]]:
    repaired: dict[str, tuple[Assignment, ...]] = {}
    records: list[dict[str, Any]] = []
    total = len(linkage_blocks)
    if total == 0:
        _report(progress, "No hi ha blocs de linkage per reoptimitzar.", 62)
    for index, block in enumerate(linkage_blocks, start=1):
        subcontext = filter_context_by_team_ids(context, block.team_ids)
        block_solve_limit = _repair_block_solve_limit(
            context=context,
            repair_deadline_at=repair_deadline_at,
            remaining_blocks=total - index + 1,
        )
        repair_context = _with_solve_time_limit(subcontext, block_solve_limit)
        fallback_assignments = _assignments_for_team_ids(initial_result.assignments, block.team_ids)
        fallback_solution = build_solution(_raw_result("FEASIBLE", fallback_assignments), context)
        fallback_mismatches = _linkage_mismatch_total(
            context,
            fallback_solution,
            initial_components,
            block.linkage_keys,
        )
        fallback_resource_excess = _total_resource_excess(
            build_solution(_raw_result("FEASIBLE", fallback_assignments), repair_context)
        )
        skipped_due_deadline = block_solve_limit <= 0
        solve_limit = 0.0 if skipped_due_deadline else getattr(repair_context.config, "time_limit_seconds", None)
        _report(
            progress,
            "Reoptimitzant linkage "
            f"{index}/{total}: {block.block_id} "
            f"({len(block.team_ids)} equips, {len(repair_context.candidates)} candidats, "
            f"linkages={len(block.linkage_keys)}, timeout={solve_limit}s)",
            _stage_percent(58, 62, index - 1, total),
        )
        if skipped_due_deadline:
            built_model = None
            hint_added = False
            solution = build_solution(
                _raw_result(
                    "SKIPPED_GLOBAL_DEADLINE",
                    (),
                    logs=("linkage repair skipped to preserve finalization margin",),
                ),
                repair_context,
            )
            solution_mismatches = fallback_mismatches
            solution_resource_excess = fallback_resource_excess
        else:
            built_model = build_solver_model(repair_context)
            hint_added = _add_assignment_hint(built_model, fallback_assignments)
            raw_result = solve_model(built_model, repair_context.config)
            solution = build_solution(raw_result, repair_context)
            global_solution = build_solution(_raw_result(solution.status, solution.assignments), context)
            solution_mismatches = _linkage_mismatch_total(
                context,
                global_solution,
                initial_components,
                block.linkage_keys,
            )
            solution_resource_excess = _total_resource_excess(solution)

        accepted = (
            solution.status in {"OPTIMAL", "FEASIBLE"}
            and len(solution.assignments) == len(block.team_ids)
            and solution_mismatches <= fallback_mismatches
        )
        if accepted:
            repaired[block.block_id] = solution.assignments
            selected_assignments = solution.assignments
            selected_mismatches = solution_mismatches
            fallback_used = False
        else:
            repaired[block.block_id] = fallback_assignments
            selected_assignments = fallback_assignments
            selected_mismatches = fallback_mismatches
            fallback_used = True
        _report(
            progress,
            "Linkage reoptimitzat "
            f"{index}/{total}: {block.block_id} "
            f"status={solution.status} accepted={accepted} "
            f"fallback={fallback_used} "
            f"mismatches={selected_mismatches}",
            _stage_percent(58, 62, index, total),
        )
        records.append(
            {
                "stage": "linkage_repair",
                "block_id": block.block_id,
                "initial_component_ids": block.initial_component_ids,
                "team_count": len(block.team_ids),
                "linkage_keys": block.linkage_keys,
                "status": solution.status,
                "assignment_count": len(solution.assignments),
                "linkage_mismatches": solution_mismatches,
                "fallback_linkage_mismatches": fallback_mismatches,
                "selected_linkage_mismatches": selected_mismatches,
                "resource_excess": solution_resource_excess,
                "fallback_resource_excess": fallback_resource_excess,
                "accepted": accepted,
                "fallback_used": fallback_used,
                "fallback_assignment_count": len(fallback_assignments),
                "selected_assignment_count": len(selected_assignments),
                "hint_added": hint_added,
                "skipped_due_deadline": skipped_due_deadline,
                "solve_time_limit_seconds": solve_limit,
                "backend": getattr(built_model, "backend", "skipped"),
                "model_summary": getattr(built_model, "summary", {}) or {},
            }
        )
    return repaired, tuple(records)


def _linkage_mismatch_total(
    context: SolverContext,
    result: ResourceSolverResult,
    initial_components: tuple[Any, ...],
    linkage_keys: tuple[str, ...] | list[str] | set[str] | None = None,
) -> int:
    allowed = {str(key) for key in linkage_keys or ()}
    conflicts = detect_linkage_conflicts(context, result, initial_components)
    return sum(
        int(conflict.mismatch_count)
        for conflict in conflicts
        if not allowed or conflict.linkage_key in allowed
    )


def _repair_blocks(
    *,
    context: SolverContext,
    initial_result: ResourceSolverResult,
    repair_blocks: tuple[Any, ...],
    progress: Any | None = None,
    repair_deadline_at: float | None = None,
) -> tuple[dict[str, tuple[Assignment, ...]], tuple[dict[str, Any], ...]]:
    repaired: dict[str, tuple[Assignment, ...]] = {}
    records: list[dict[str, Any]] = []
    total = len(repair_blocks)
    if total == 0:
        _report(progress, "No hi ha blocs de reparacio per reoptimitzar.", 75)
    for index, block in enumerate(repair_blocks, start=1):
        subcontext = filter_context_by_team_ids(context, block.team_ids)
        frozen_usage = frozen_usage_by_resource(initial_result, block.team_ids)
        block_solve_limit = _repair_block_solve_limit(
            context=context,
            repair_deadline_at=repair_deadline_at,
            remaining_blocks=total - index + 1,
        )
        repair_context = _with_solve_time_limit(
            context_with_residual_capacities(subcontext, frozen_usage),
            block_solve_limit,
        )
        fallback_assignments = _assignments_for_team_ids(initial_result.assignments, block.team_ids)
        fallback_solution = build_solution(_raw_result("FEASIBLE", fallback_assignments), repair_context)
        fallback_resource_excess = _total_resource_excess(fallback_solution)
        skipped_due_deadline = block_solve_limit <= 0
        solve_limit = 0.0 if skipped_due_deadline else getattr(repair_context.config, "time_limit_seconds", None)
        _report(
            progress,
            "Reoptimitzant bloc "
            f"{index}/{total}: {block.block_id} "
            f"({len(block.team_ids)} equips, {len(repair_context.candidates)} candidats, "
            f"recursos conflictius={len(block.conflict_resource_ids)}, timeout={solve_limit}s)",
            _stage_percent(65, 80, index - 1, total),
        )
        if skipped_due_deadline:
            built_model = None
            hint_added = False
            solution = build_solution(
                _raw_result(
                    "SKIPPED_GLOBAL_DEADLINE",
                    (),
                    logs=("repair skipped to preserve finalization margin",),
                ),
                repair_context,
            )
            solution_resource_excess = fallback_resource_excess
        else:
            built_model = build_solver_model(repair_context)
            hint_added = _add_assignment_hint(built_model, fallback_assignments)
            raw_result = solve_model(built_model, repair_context.config)
            solution = build_solution(raw_result, repair_context)
            solution_resource_excess = _total_resource_excess(solution)
        accepted = (
            solution.status in {"OPTIMAL", "FEASIBLE"}
            and len(solution.assignments) == len(block.team_ids)
            and solution_resource_excess <= fallback_resource_excess
        )
        if accepted:
            repaired[block.block_id] = solution.assignments
            selected_assignments = solution.assignments
            selected_resource_excess = solution_resource_excess
            fallback_used = False
        else:
            repaired[block.block_id] = fallback_assignments
            selected_assignments = fallback_assignments
            selected_resource_excess = fallback_resource_excess
            fallback_used = True
        _report(
            progress,
            "Bloc reoptimitzat "
            f"{index}/{total}: {block.block_id} "
            f"status={solution.status} accepted={accepted} "
            f"fallback={fallback_used} "
            f"assignacions={len(selected_assignments)}/{len(block.team_ids)} "
            f"resource_excess={selected_resource_excess}",
            _stage_percent(65, 80, index, total),
        )
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
                "resource_excess": solution_resource_excess,
                "accepted": accepted,
                "fallback_used": fallback_used,
                "fallback_assignment_count": len(fallback_assignments),
                "fallback_resource_excess": fallback_resource_excess,
                "selected_assignment_count": len(selected_assignments),
                "selected_resource_excess": selected_resource_excess,
                "hint_added": hint_added,
                "skipped_due_deadline": skipped_due_deadline,
                "solve_time_limit_seconds": solve_limit,
                "backend": getattr(built_model, "backend", "skipped"),
                "model_summary": getattr(built_model, "summary", {}) or {},
            }
        )
    return repaired, tuple(records)


def _assignments_for_team_ids(
    assignments: tuple[Assignment, ...],
    team_ids: tuple[str, ...],
) -> tuple[Assignment, ...]:
    team_set = {str(team_id) for team_id in team_ids}
    return tuple(
        sorted(
            (assignment for assignment in assignments if assignment.team_id in team_set),
            key=lambda item: item.team_id,
        )
    )


def _add_assignment_hint(built_model: Any, assignments: tuple[Assignment, ...]) -> bool:
    model = getattr(built_model, "model", None)
    variables = getattr(built_model, "variables", None)
    if model is None or variables is None or not hasattr(model, "AddHint"):
        return False
    selected = {
        (assignment.team_id, assignment.group_id, int(assignment.number))
        for assignment in assignments
    }
    added = 0
    for candidate_id, candidate in getattr(variables, "candidate_by_id", {}).items():
        variable = getattr(variables, "x", {}).get(candidate_id)
        if variable is None:
            continue
        value = 1 if (candidate.team_id, candidate.group_id, int(candidate.number)) in selected else 0
        try:
            model.AddHint(variable, value)
        except Exception:
            return added > 0
        added += 1
    return added > 0


def _with_internal_solve_limit(context: SolverContext) -> SolverContext:
    return _with_solve_time_limit(context, _repair_solve_limit(context))


def _with_solve_time_limit(context: SolverContext, solve_limit: float) -> SolverContext:
    config = context.config
    limit = float(solve_limit or 0.0)
    current_limit = float(getattr(config, "time_limit_seconds", limit or 0.0) or 0.0)
    if limit <= 0 or current_limit == limit:
        return context
    return replace(context, config=replace(config, time_limit_seconds=limit))


def _initial_solve_limit(context: SolverContext) -> float:
    config = context.config
    return float(
        getattr(
            config,
            "initial_solve_time_limit_seconds",
            getattr(config, "time_limit_seconds", 0.0),
        )
        or 0.0
    )


def _repair_solve_limit(context: SolverContext) -> float:
    config = context.config
    return float(
        getattr(
            config,
            "repair_solve_time_limit_seconds",
            getattr(config, "internal_solve_time_limit_seconds", 0.0),
        )
        or 0.0
    )


def _repair_deadline_at(started_at: float, config: Any) -> float | None:
    worker_limit = float(getattr(config, "worker_time_limit_seconds", 0.0) or 0.0)
    margin = float(getattr(config, "finalization_margin_seconds", 0.0) or 0.0)
    if worker_limit <= 0 or margin <= 0 or worker_limit <= margin:
        return None
    return started_at + worker_limit - margin


def _repair_block_solve_limit(
    *,
    context: SolverContext,
    repair_deadline_at: float | None,
    remaining_blocks: int,
) -> float:
    configured_limit = _repair_solve_limit(context)
    if repair_deadline_at is None:
        return configured_limit
    remaining_seconds = repair_deadline_at - perf_counter()
    if remaining_seconds <= 0 or remaining_blocks <= 0:
        return 0.0
    fair_share = remaining_seconds / remaining_blocks
    if configured_limit <= 0:
        return max(0.1, fair_share)
    return max(0.1, min(configured_limit, fair_share))


def _stage_percent(start: int, end: int, completed: int, total: int) -> int:
    if total <= 0:
        return end
    ratio = max(0.0, min(1.0, completed / total))
    return int(round(start + (end - start) * ratio))


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
