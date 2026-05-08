"""Service entry point for the resource solver engine."""

from __future__ import annotations

import json
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
from calendaritzacions.ingestion import InputValidationError, prepare_legacy_input, read_excel
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

        raw_result, context, built_model = self._run_solver_or_scaffold(
            input_path=input_path,
            input_df=pre_analysis["input_df"],
            config=solver_config,
            progress=progress,
            logs=logs,
        )
        logs.extend(_context_log_lines(context))
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
        logs.extend(_result_log_lines(result))
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
    ) -> tuple[Any, SolverContext, Any | None]:
        """Run the real model when available, otherwise return a safe scaffold."""

        try:
            return self._run_optional_model_pipeline(input_path, input_df, config, progress, logs)
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
        input_df: pd.DataFrame,
        config: ResourceSolverConfig,
        progress: Any | None,
        logs: list[str],
    ) -> tuple[Any, SolverContext, Any | None]:
        """Hook for the future RS-01..RS-05 pipeline.

        The function intentionally imports lazily. Other agents can provide
        ``build_context_from_input``, ``build_solver_model`` and ``solve_model``
        without changing this service contract.
        """

        from calendaritzacions.engine.variants.resource_solver.input_adapter import build_context_from_dataframe  # type: ignore
        from calendaritzacions.engine.variants.resource_solver.model import (  # type: ignore
            build_solver_model,
            solve_model,
        )

        _report(progress, "Construint context resource_solver...", 20)
        context = build_context_from_dataframe(input_df, config=config)
        logs.append(
            "resource_solver: context "
            f"teams={len(context.teams)} groups={len(context.groups)} "
            f"resources={len(context.base_resources)} candidates={len(context.candidates)}"
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
        input_df = ensure_team_ids(raw_df.copy())
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
        f"empty_balance={getattr(context.config, 'empty_number_imbalance_weight', '-')}",
    ]


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
    return 1 <= number <= 8


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
