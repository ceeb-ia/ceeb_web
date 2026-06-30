"""Service entry point for the resource solver engine."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from calendaritzacions.analysis.input_demand import (
    build_input_demand_analysis,
    write_input_demand_plots,
)
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
from calendaritzacions.ingestion import (
    InputValidationError,
    normalize_legacy_input_columns,
    prepare_legacy_input,
    read_excel,
)
from calendaritzacions.ingestion.ids import ensure_team_ids


class ResourceSolverEngine:
    """Resource solver service boundary.

    The CP-SAT model is developed by another layer. Until that layer is present,
    this service returns an auditable empty result instead of falling back to
    legacy behavior.
    """

    def run(self, input_path: str, config: Any, progress: Any | None = None) -> EngineResult:
        solver_config = coerce_resource_solver_config(config)
        logs = [
            "resource_solver: starting",
            f"resource_solver: input={Path(input_path).name}",
            f"resource_solver: phase={solver_config.phase_name}",
        ]
        output_dir = _output_dir_for(input_path)
        _report(progress, "Preparant motor resource_solver...", 5)
        pre_analysis = _build_input_pre_analysis(
            input_path=input_path,
            output_dir=output_dir,
            logs=logs,
            progress=progress,
        )

        raw_result, context, built_model, early_audit_paths = self._run_solver_or_scaffold(
            input_path=input_path,
            input_df=pre_analysis["input_df"],
            config=solver_config,
            progress=progress,
            logs=logs,
            output_dir=output_dir,
        )
        logs.extend(_context_log_lines(context))
        if getattr(raw_result, "componentized_without_global_solve", False):
            audit_paths = dict(pre_analysis["audit_payloads"])
            audit_paths = write_audit_payloads(audit_paths, output_dir)
            audit_paths.update(early_audit_paths)
            manifest_path = getattr(raw_result, "manifest_path", "")
            if manifest_path:
                audit_paths["component_manifest"] = str(manifest_path)
            split_validation_path = getattr(raw_result, "split_validation_path", "")
            if split_validation_path:
                audit_paths["component_split_validation"] = str(split_validation_path)
            logs.extend(str(item) for item in getattr(raw_result, "logs", ()) or ())
            logs.append(f"resource_solver: status={getattr(raw_result, 'status', 'UNKNOWN')}")
            _report(progress, "Components resource_solver persistits.", 90)
            final_output_path = getattr(raw_result, "final_output_path", "") or ""
            run_status = getattr(raw_result, "status", "")
            return EngineResult(
                output_path=str(final_output_path or manifest_path or ""),
                status="running" if run_status == "RUNNING" else None,
                audit_paths=audit_paths,
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
        audit_payloads.update(pre_analysis["audit_payloads"])

        audit_paths = write_audit_payloads(audit_payloads, output_dir)
        audit_paths.update(early_audit_paths)
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

        try:
            from calendaritzacions.reporting.resource_solver_plots import (
                write_resource_solver_final_plots,
            )

            final_plots = write_resource_solver_final_plots(
                output_dir / "plots_final",
                result=result,
                context=context,
                stem=f"resource_solver_{Path(input_path).stem}",
            )
            manifest_path = final_plots.get("manifest")
            if manifest_path:
                audit_paths["resource_solver_final_plots"] = manifest_path
            logs.append(f"resource_solver: plots finals generats={max(0, len(final_plots) - 1)}")
        except Exception as exc:
            logs.append(f"resource_solver: plots finals no generats ({exc})")

        logs.extend(str(item) for item in result.logs)
        logs.append(f"resource_solver: status={result.status}")
        logs.extend(_result_log_lines(result))
        logs.extend(_competition_result_log_lines(result, context))
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
        input_df: pd.DataFrame,
        config: ResourceSolverConfig,
        progress: Any | None,
        logs: list[str],
        output_dir: Path,
    ) -> tuple[Any, SolverContext, Any | None, dict[str, str]]:
        """Run the real model when available, otherwise return a safe scaffold."""

        try:
            return self._run_optional_model_pipeline(input_path, input_df, config, progress, logs, output_dir)
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
            return raw_result, context, None, {}

    def _run_optional_model_pipeline(
        self,
        input_path: str,
        input_df: pd.DataFrame,
        config: ResourceSolverConfig,
        progress: Any | None,
        logs: list[str],
        output_dir: Path,
    ) -> tuple[Any, SolverContext, Any | None, dict[str, str]]:
        """Hook for the future RS-01..RS-05 pipeline.

        The function intentionally imports lazily. Other agents can provide
        ``build_context_from_input``, ``build_solver_model`` and ``solve_model``
        without changing this service contract.
        """

        from calendaritzacions.engine.variants.resource_solver.input_adapter import build_context_from_dataframe  # type: ignore

        _report(progress, "Construint context resource_solver...", 20)
        context = build_context_from_dataframe(input_df, config=config)
        logs.append(
            "resource_solver: context "
            f"teams={len(context.teams)} groups={len(context.groups)} "
            f"resources={len(context.base_resources)} candidates={len(context.candidates)}"
        )
        logs.extend(_competition_context_log_lines(context))
        early_audit_paths = {}
        if str(config.decomposition_mode) != "off":
            early_audit_paths = _write_decomposition_audit_only(
                context=context,
                output_dir=output_dir,
                input_path=input_path,
                progress=progress,
                logs=logs,
            )
        if str(config.decomposition_mode) in {"persist_components", "solve_components"}:
            from calendaritzacions.engine.variants.resource_solver.component_persistence import (
                persist_component_subcontexts,
            )
            from calendaritzacions.engine.variants.resource_solver.decomposition import (
                build_decomposition_summary,
            )

            _report(progress, "Persistint components resource_solver...", 45)
            summary = build_decomposition_summary(context)
            run = _calendarization_run_from_progress(progress)
            persistence = persist_component_subcontexts(
                run=run,
                output_dir=output_dir,
                context=context,
                summary=summary,
                mode=str(config.decomposition_mode),
            )
            early_audit_paths["component_manifest"] = str(persistence["manifest_path"])
            early_audit_paths["component_split_validation"] = str(persistence["split_validation_path"])
            _report_artifact(progress, "component_manifest", early_audit_paths["component_manifest"])
            _report_artifact(progress, "component_split_validation", early_audit_paths["component_split_validation"])
            logs.append(
                "components: "
                f"split={persistence['status']} "
                f"components={persistence['component_count']} "
                f"manifest={Path(persistence['manifest_path']).name}"
            )
            if run is None:
                logs.append("components: CalendarizationRun no disponible; DB component_runs no actualitzat")
            if str(config.decomposition_mode) == "solve_components":
                if persistence["status"] == "valid" and run is not None:
                    from calendaritzacions.django.models import CalendarizationComponentRun, CalendarizationRun
                    from calendaritzacions.django.services.component_tasks import enqueue_component

                    components = list(
                        CalendarizationComponentRun.objects.filter(
                            run=run,
                            attempt=1,
                            active_attempt=1,
                        ).order_by("component_id")
                    )
                    for component_run in components:
                        enqueue_component(component_run)
                    run.refresh_from_db()
                    logs.append(f"components: enqueued={len(components)} queue=heavy_queue")
                    if run.status == CalendarizationRun.STATUS_SUCCESS and run.output_path:
                        logs.append("components: merge completat en backend sync")
                        return (
                            SimpleNamespace(
                                status=getattr(run, "status", "success"),
                                objective_value=None,
                                best_bound=None,
                                wall_time=0.0,
                                assignments=(),
                                entity_excess={},
                                logs=tuple(logs),
                                componentized_without_global_solve=True,
                                manifest_path=str(persistence["manifest_path"]),
                                split_validation_path=str(persistence["split_validation_path"]),
                                final_output_path=run.output_path,
                            ),
                            context,
                            None,
                            early_audit_paths,
                        )
                elif persistence["status"] == "valid":
                    logs.append("components: solve_components requereix CalendarizationRun per encolar")
            status = "COMPONENTS_PERSISTED" if persistence["status"] == "valid" else "COMPONENT_SPLIT_INVALID"
            if str(config.decomposition_mode) == "solve_components" and persistence["status"] == "valid" and run is not None:
                status = "RUNNING"
            return (
                SimpleNamespace(
                    status=status,
                    objective_value=None,
                    best_bound=None,
                    wall_time=0.0,
                    assignments=(),
                    entity_excess={},
                    logs=("resource_solver componentitzat; CP-SAT global no executat",),
                    componentized_without_global_solve=True,
                    manifest_path=str(persistence["manifest_path"]),
                    split_validation_path=str(persistence["split_validation_path"]),
                    final_output_path="",
                ),
                context,
                None,
                early_audit_paths,
            )
        from calendaritzacions.engine.variants.resource_solver.model import (  # type: ignore
            build_solver_model,
            solve_model,
        )

        _report(progress, "Executant CP-SAT resource_solver...", 50)
        built_model = build_solver_model(context)
        summary = getattr(built_model, "summary", {}) or {}
        logs.append(
            "resource_solver: model "
            f"backend={getattr(built_model, 'backend', 'unknown')} "
            f"variables={summary.get('num_variables', 0)} "
            f"constraints={sum((summary.get('constraints') or {}).values()) if isinstance(summary.get('constraints'), dict) else summary.get('num_constraints', 0)}"
        )
        raw_result = solve_model(built_model, config)
        logs.append("resource_solver: CP-SAT model executed")
        return raw_result, context, built_model, early_audit_paths


def _write_decomposition_audit_only(
    *,
    context: SolverContext,
    output_dir: Path,
    input_path: str,
    progress: Any | None,
    logs: list[str],
) -> dict[str, str]:
    """Write dependency-decomposition audits before solving, without changing the model."""

    try:
        from calendaritzacions.engine.variants.resource_solver.decomposition import (
            build_decomposition_summary,
            dependency_components_payload,
            dependency_edges_payload,
            dependency_summary_payload,
        )
    except Exception as exc:
        logs.append(f"decomposition: no disponible ({exc})")
        return {}

    try:
        _report(progress, "Grafitzant dependencies del problema...", 35)
        summary = build_decomposition_summary(context)
        summary_payload = dependency_summary_payload(summary)
        payloads = {
            "dependency_component_summary": summary_payload,
            "dependency_components": dependency_components_payload(summary),
            "dependency_component_edges": dependency_edges_payload(summary),
        }
        audit_paths = write_audit_payloads(payloads, output_dir)
        _report_artifact(progress, "dependency_component_summary", audit_paths.get("dependency_component_summary"))
        _report_artifact(progress, "dependency_components", audit_paths.get("dependency_components"))
        _report_artifact(progress, "dependency_component_edges", audit_paths.get("dependency_component_edges"))

        largest = summary_payload.get("largest_component", {}) if isinstance(summary_payload, dict) else {}
        logs.append(
            "decomposition: "
            f"components={summary_payload.get('component_count', 0)} "
            f"teams={summary_payload.get('total_teams', len(context.teams))} "
            f"competitions={summary_payload.get('total_competitions', 0)} "
            f"resources={summary_payload.get('total_resources', 0)}"
        )
        logs.append(
            "decomposition: largest="
            f"{largest.get('component_id', '-')} "
            f"teams={largest.get('teams', 0)} "
            f"competitions={largest.get('competitions', 0)} "
            f"resources={largest.get('resources', 0)} "
            f"candidates={largest.get('candidates', 0)}"
        )

        try:
            from calendaritzacions.reporting.resource_solver_decomposition_plots import (
                write_resource_solver_decomposition_plots,
            )

            plots = write_resource_solver_decomposition_plots(
                output_dir / "plots_decomposition",
                summary=summary_payload,
                context=context,
                stem=f"resource_solver_decomposition_{Path(input_path).stem}",
            )
            manifest_path = plots.get("manifest")
            if manifest_path:
                audit_paths["resource_solver_decomposition_plots"] = manifest_path
                _report_artifact(progress, "resource_solver_decomposition_plots", manifest_path)
            logs.append(f"decomposition: plots generated={max(0, len(plots) - 1)}")
        except Exception as exc:
            logs.append(f"decomposition: plots no generats ({exc})")

        _report(progress, "Graf de dependencies generat.", 40)
        return audit_paths
    except Exception as exc:
        logs.append(f"decomposition: auditoria no generada ({exc})")
        return {}


def _report_artifact(progress: Any | None, name: str, path: str | None) -> None:
    if progress is None or not path:
        return
    report_artifact = getattr(progress, "report_artifact", None)
    if callable(report_artifact):
        report_artifact(name, path)


def _calendarization_run_from_progress(progress: Any | None) -> Any | None:
    if progress is None:
        return None
    run = getattr(progress, "run", None)
    if run is not None:
        return run
    task_id = getattr(progress, "_task_id", None)
    if not task_id:
        return None
    try:
        from calendaritzacions.django.models import CalendarizationRun

        return CalendarizationRun.objects.get(pk=int(task_id))
    except Exception:
        return None


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


def _build_input_pre_analysis(
    *,
    input_path: str,
    output_dir: Path,
    logs: list[str],
    progress: Any | None,
) -> dict[str, Any]:
    _report(progress, "Analitzant input i demanda...", 10)
    raw_df = read_excel(input_path)
    logs.append(f"input: rows={len(raw_df)} columns={len(raw_df.columns)}")

    validation_notes: list[str] = []
    try:
        input_df, _modalitat_map = prepare_legacy_input(raw_df)
        validation_status = "legacy_prepared"
        logs.append("input: preparacio legacy aplicada (validacio columnes + Ids)")
    except InputValidationError as exc:
        validation_status = "fallback_prepared"
        validation_notes.append(str(exc))
        input_df = ensure_team_ids(normalize_legacy_input_columns(raw_df))
        logs.append(f"input: preparacio legacy no aplicable; fallback amb Ids ({exc})")

    demand_analysis = build_input_demand_analysis(input_df)
    demand_summary = demand_analysis.get("summary", {})
    logs.extend(_input_log_lines(input_df, demand_summary))

    plots = {}
    try:
        plots = write_input_demand_plots(
            demand_analysis,
            output_dir / "plots_input_demand",
            stem=f"input_demand_{Path(input_path).stem}",
        )
        if plots:
            logs.append(f"input: plots demanda generats={len(plots)}")
    except Exception as exc:
        validation_notes.append(f"No s'han pogut generar plots de demanda: {exc}")
        logs.append(f"input: plots demanda no generats ({exc})")

    demand_payload = dict(demand_analysis)
    demand_payload["plots"] = plots

    validation_payload = {
        "status": validation_status,
        "input_file": Path(input_path).name,
        "input_rows": int(len(raw_df)),
        "prepared_rows": int(len(input_df)),
        "columns": list(input_df.columns),
        "notes": validation_notes,
        "detected": _input_detected_summary(input_df),
        "requests": _request_summary(input_df),
    }
    return {
        "input_df": input_df,
        "audit_payloads": {
            "input_validation": validation_payload,
            "input_demand": demand_payload,
        },
    }


def _input_log_lines(input_df: pd.DataFrame, demand_summary: dict[str, Any]) -> list[str]:
    detected = _input_detected_summary(input_df)
    requests = _request_summary(input_df)
    lines = [
        "input: "
        f"teams={demand_summary.get('total_equips', len(input_df))} "
        f"modalitats={detected['modalitats']} categories={detected['categories']} "
        f"pistes={demand_summary.get('total_pistes', 0)} slots={demand_summary.get('total_slots_pista_dia_hora', 0)}",
        "input: "
        f"sense_pista={demand_summary.get('files_sense_pista', 0)} "
        f"sense_dia={demand_summary.get('files_sense_dia', 0)} "
        f"sense_hora={demand_summary.get('files_sense_hora', 0)} "
        f"max_demanda_slot={demand_summary.get('max_demanda_slot', 0)}",
        "input: "
        f"peticions_numero={requests['numeric']} "
        f"peticions_casa={requests['casa']} "
        f"peticions_fora={requests['fora']} "
        f"sense_peticio={requests['empty']}",
    ]
    top_slots = demand_summary.get("max_demanda_slot", 0)
    if int(top_slots or 0) >= 4:
        lines.append(f"input: alerta pressio inicial alta en algun slot ({top_slots} equips)")
    return lines


def _context_log_lines(context: SolverContext) -> list[str]:
    critical_resources = sum(1 for row in context.pressure if row.is_critical)
    max_pressure = max((row.pressure for row in context.pressure), default=0.0)
    return [
        "pre-solver: "
        f"groups={len(context.groups)} candidates={len(context.candidates)} "
        f"critical_resources={critical_resources} max_pressure={max_pressure:.2f}",
        "pre-solver: "
        f"weights resource_excess={getattr(context.config, 'resource_excess_weight', '-')} "
        f"entity_excess={getattr(context.config, 'entity_excess_weight', '-')} "
        f"empty_balance={getattr(context.config, 'empty_number_imbalance_weight', '-')} "
        f"time_limit={getattr(context.config, 'time_limit_seconds', '-')}s "
        f"search_workers={getattr(context.config, 'num_search_workers', '-')}",
    ]


def _competition_context_log_lines(context: SolverContext) -> list[str]:
    summaries = _competition_summaries(context)
    if not summaries:
        return []

    lines = [f"pre-solver: competicions={len(summaries)}"]
    for summary in summaries:
        repartiment = ",".join(str(value) for value in summary["repartiment"])
        bucket_targets = summary.get("bucket_targets") or {}
        bucket_suffix = ""
        if bucket_targets:
            buckets = ",".join(f"{key}:{value}" for key, value in sorted(bucket_targets.items()))
            bucket_suffix = f"buckets=[{buckets}] logical_total={summary['logical_target_total']} "
        lines.append(
            "pre-solver competicio: "
            f"{summary['label']} | teams={summary['teams']} "
            f"groups={summary['groups']} repartiment=[{repartiment}] "
            f"{bucket_suffix}"
            f"candidates={summary['candidates']} "
            f"critical_resources={summary['critical_resources']} "
            f"max_pressure={summary['max_pressure']:.2f}"
        )
    return lines


def _result_log_lines(result: Any) -> list[str]:
    resource_excess = sum(int(getattr(usage, "excess", 0) or 0) for usage in getattr(result, "resource_usage", ()) or ())
    entity_conflicts = len(getattr(result, "entity_excess", {}) or {})
    status = getattr(result, "status", "UNKNOWN")
    lines = [
        "post-solver: "
        f"assignments={len(getattr(result, 'assignments', ()) or ())} "
        f"matches={len(getattr(result, 'real_matches', ()) or ())} "
        f"resource_excess={resource_excess} entity_conflicts={entity_conflicts}",
    ]
    if status == "FEASIBLE":
        lines.append("post-solver: solucio factible trobada, pero no s'ha provat optimalitat dins el temps")
    if status == "INFEASIBLE":
        lines.append("post-solver: cap solucio compleix les restriccions actives")
    return lines


def _competition_result_log_lines(result: Any, context: SolverContext) -> list[str]:
    summaries = _competition_summaries(context)
    if not summaries:
        return []

    label_by_team = {team.team_id: _team_competition_label(team, context.config) for team in context.teams}
    label_by_group = _group_label_map(context)
    assigned_by_label = Counter()
    matches_by_label = Counter()
    entity_excess_by_label = Counter()

    for assignment in getattr(result, "assignments", ()) or ():
        assigned_by_label[label_by_team.get(assignment.team_id, "(desconegut)")] += 1
    for match in getattr(result, "real_matches", ()) or ():
        matches_by_label[label_by_team.get(match.home_team_id, "(desconegut)")] += 1
    for (_entity, group_id), excess in (getattr(result, "entity_excess", {}) or {}).items():
        entity_excess_by_label[label_by_group.get(group_id, "(desconegut)")] += int(excess)

    lines = []
    for summary in summaries:
        label = str(summary["label"])
        lines.append(
            "post-solver competicio: "
            f"{label} | assigned={assigned_by_label[label]}/{summary['teams']} "
            f"matches={matches_by_label[label]} "
            f"entity_excess={entity_excess_by_label[label]}"
        )
    return lines


def _competition_summaries(context: SolverContext) -> list[dict[str, Any]]:
    teams_by_label: dict[str, list[Any]] = defaultdict(list)
    for team in context.teams:
        teams_by_label[_team_competition_label(team, context.config)].append(team)

    group_ids_by_team: dict[str, set[str]] = defaultdict(set)
    candidate_count_by_label = Counter()
    team_by_id = {team.team_id: team for team in context.teams}
    for candidate in context.candidates:
        group_ids_by_team[candidate.team_id].add(candidate.group_id)
        team = team_by_id.get(candidate.team_id)
        if team is not None:
            candidate_count_by_label[_team_competition_label(team, context.config)] += 1

    group_by_id = {group.group_id: group for group in context.groups}
    summaries: list[dict[str, Any]] = []
    for label, teams in sorted(teams_by_label.items(), key=lambda item: item[0].casefold()):
        team_ids = {team.team_id for team in teams}
        group_ids = {
            group_id
            for team_id in team_ids
            for group_id in group_ids_by_team.get(team_id, set())
        }
        bucket_targets: dict[str, int] = {}
        normal_target_total = 0
        repartiment = []
        for group_id in sorted(group_ids, key=_natural_group_key):
            group = group_by_id.get(group_id)
            if group is None:
                continue
            repartiment.append(group.target_size)
            bucket_id = str(getattr(group, "size_bucket_id", "") or "")
            if bucket_id:
                bucket_targets[bucket_id] = int(getattr(group, "size_bucket_target", 0) or 0)
            else:
                normal_target_total += int(group.target_size)
        pressure_rows = [
            row
            for row in context.pressure
            if any(team_id in team_ids for team_id in getattr(row, "team_ids", ()) or ())
        ]
        summaries.append(
            {
                "label": label,
                "teams": len(teams),
                "groups": len(group_ids),
                "repartiment": repartiment,
                "bucket_targets": bucket_targets,
                "logical_target_total": normal_target_total + sum(bucket_targets.values()),
                "candidates": int(candidate_count_by_label[label]),
                "critical_resources": sum(1 for row in pressure_rows if getattr(row, "is_critical", False)),
                "max_pressure": max((float(getattr(row, "pressure", 0.0) or 0.0) for row in pressure_rows), default=0.0),
            }
        )
    return summaries


def _group_label_map(context: SolverContext) -> dict[str, str]:
    label_by_group: dict[str, str] = {}
    team_by_id = {team.team_id: team for team in context.teams}
    for candidate in context.candidates:
        team = team_by_id.get(candidate.team_id)
        if team is not None:
            label_by_group[candidate.group_id] = _team_competition_label(team, context.config)
    return label_by_group


def _team_competition_label(team: Any, config: Any | None = None) -> str:
    mode = str(getattr(config, "competition_grouping", "auto") if config is not None else "auto").strip().casefold()
    league = str(getattr(team, "league_name", "") or "").strip()
    if mode == "league":
        return f"Nom Lliga: {league or 'Sense lliga'}"
    parts = [
        str(getattr(team, "modality", "") or "").strip(),
        str(getattr(team, "category", "") or "").strip(),
        str(getattr(team, "subcategory", "") or "").strip(),
    ]
    if mode == "fields" or all(parts):
        return " / ".join(part or "Sense valor" for part in parts)
    return f"Nom Lliga: {league or 'Sense lliga'}"


def _natural_group_key(group_id: str) -> tuple[str, int]:
    text = str(group_id)
    digits = ""
    for char in reversed(text):
        if not char.isdigit():
            break
        digits = char + digits
    if not digits:
        return (text, 0)
    return (text[: -len(digits)], int(digits))


def _input_detected_summary(input_df: pd.DataFrame) -> dict[str, int]:
    return {
        "modalitats": _nunique_text(input_df, "Modalitat"),
        "categories": _nunique_text(input_df, "Nom Lliga"),
        "entitats": _nunique_text(input_df, "Entitat"),
        "pistes": _nunique_text(input_df, "Pista joc"),
    }


def _request_summary(input_df: pd.DataFrame) -> dict[str, int]:
    seed_col = _seed_column(input_df)
    if seed_col is None:
        return {"numeric": 0, "casa": 0, "fora": 0, "empty": int(len(input_df)), "invalid": 0}
    values = input_df[seed_col]
    text = values.fillna("").astype(str).str.strip().str.lower()
    numeric = text.map(_is_seed_number)
    casa = text.eq("casa")
    fora = text.eq("fora")
    empty = text.eq("") | text.isin({"nan", "none"})
    return {
        "numeric": int(numeric.sum()),
        "casa": int(casa.sum()),
        "fora": int(fora.sum()),
        "empty": int(empty.sum()),
        "invalid": int((~numeric & ~casa & ~fora & ~empty).sum()),
    }


def _seed_column(input_df: pd.DataFrame) -> str | None:
    for column in ("Núm. sorteig", "Num. sorteig", "NÃºm. sorteig"):
        if column in input_df.columns:
            return column
    return None


def _is_seed_number(value: str) -> bool:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return False
    return 1 <= number <= 10


def _nunique_text(input_df: pd.DataFrame, column: str) -> int:
    if column not in input_df.columns:
        return 0
    return int(input_df[column].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique())


def _report(progress: Any | None, message: str, percent: int) -> None:
    if progress is None:
        return
    report = getattr(progress, "report", None)
    if callable(report):
        report(message, percent)
