"""Pattern-master resource solver engine.

This experimental variant keeps competitions out of the first decomposition:
microhubs are connected only by resources and linkages, then a master model
selects compatible hub patterns before materializing real groups.
"""

from __future__ import annotations

import gc
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from calendaritzacions.engine.base import EngineResult
from calendaritzacions.engine.variants.resource_solver.audit import (
    build_audit_payloads,
    write_audit_payloads,
)
from calendaritzacions.engine.variants.resource_solver.config import coerce_resource_solver_config
from calendaritzacions.engine.variants.resource_solver.local_explanations import build_local_explanations
from calendaritzacions.engine.variants.resource_solver.pattern_master.incompatibilities import (
    build_pattern_conflicts,
    compatibility_payload,
)
from calendaritzacions.engine.variants.resource_solver.pattern_master.master_model import (
    master_selection_payload,
    solve_master_selection,
)
from calendaritzacions.engine.variants.resource_solver.pattern_master.materialization import (
    materialize_master_selection,
    materialization_payload,
    selected_patterns_from_ids,
)
from calendaritzacions.engine.variants.resource_solver.pattern_master.microhubs import (
    build_microhubs,
    microhubs_payload,
)
from calendaritzacions.engine.variants.resource_solver.pattern_master.patterns import (
    generate_initial_patterns,
    generate_variants_for_hubs,
    hubs_touching_competitions,
    hubs_touching_slot_domains,
    overloaded_competitions_from_patterns,
    overloaded_slot_domains_from_patterns,
    patterns_payload,
)
from calendaritzacions.engine.variants.resource_solver.pattern_master.plots import (
    build_graph_plot_payload,
    build_postrun_plot_payload,
    build_prerun_plot_payload,
)
from calendaritzacions.engine.variants.resource_solver.service import (
    _build_input_pre_analysis,
    _competition_context_log_lines,
    _context_log_lines,
    _output_dir_for,
    _report,
    _report_artifact,
    _result_log_lines,
)
from calendaritzacions.engine.variants.resource_solver.solution import result_to_json_ready


class ResourceSolverPatternMasterEngine:
    """Experimental pattern-selection solver variant."""

    def run(self, input_path: str, config: Any, progress: Any | None = None) -> EngineResult:
        run_started = perf_counter()
        solver_config = coerce_resource_solver_config(config)
        logs = [
            "resource_solver_pattern_master: starting",
            f"resource_solver_pattern_master: input={Path(input_path).name}",
            f"resource_solver_pattern_master: phase={solver_config.phase_name}",
        ]
        output_dir = _output_dir_for(input_path)
        _report(progress, "Preparant motor pattern-master...", 5)
        pre_analysis = _build_input_pre_analysis(
            input_path=input_path,
            output_dir=output_dir,
            logs=logs,
            progress=progress,
        )
        early_audit_paths = _write_and_report(pre_analysis["audit_payloads"], output_dir, progress)

        from calendaritzacions.engine.variants.resource_solver.input_adapter import build_context_from_dataframe

        _report(progress, "Construint context pattern-master...", 20)
        context = build_context_from_dataframe(pre_analysis["input_df"], config=solver_config)
        logs.extend(_context_log_lines(context))
        logs.extend(_competition_context_log_lines(context))
        del pre_analysis
        gc.collect()

        _report(progress, "Construint microhubs per recursos i linkages...", 30)
        hubs = build_microhubs(context)
        patterns = generate_initial_patterns(context, hubs)
        overloaded_competitions = overloaded_competitions_from_patterns(context, patterns)
        overloaded_slot_domains = overloaded_slot_domains_from_patterns(context, patterns)
        trigger_hubs = tuple(
            {
                hub.hub_id: hub
                for hub in (
                    *hubs_touching_competitions(hubs, overloaded_competitions),
                    *hubs_touching_slot_domains(context, hubs, overloaded_slot_domains),
                )
            }.values()
        )
        variant_hubs = hubs
        if variant_hubs:
            variants = generate_variants_for_hubs(context, variant_hubs, existing_patterns=patterns)
            patterns = (*patterns, *variants)
        logs.append(
            "pattern-master: "
            f"hubs={len(hubs)} largest={max((len(hub.team_ids) for hub in hubs), default=0)} "
            f"patterns={len(patterns)} variant_hubs={len(variant_hubs)}"
        )
        if overloaded_competitions:
            logs.append(f"pattern-master: variants generades per competicions saturades={len(overloaded_competitions)}")
        if overloaded_slot_domains:
            logs.append(f"pattern-master: variants generades per dominis de grup saturats={len(overloaded_slot_domains)}")
        if len(trigger_hubs) != len(variant_hubs):
            logs.append(
                "pattern-master: variants ampliades a tots els hubs "
                f"(triggers locals={len(trigger_hubs)}, hubs amb variants={len(variant_hubs)})"
            )

        prerun_payload = build_prerun_plot_payload(output_dir, hubs, patterns, context=context)
        early_audit_paths.update(
            _write_and_report(
                {
                    "pattern_master_microhubs": microhubs_payload(hubs),
                    "pattern_master_patterns": patterns_payload(patterns),
                    "pattern_master_prerun_plots": prerun_payload,
                },
                output_dir,
                progress,
            )
        )
        del prerun_payload
        gc.collect()

        _report(progress, "Construint graf d'incompatibilitats de patterns...", 42)
        conflicts = build_pattern_conflicts(context, patterns)
        compat_payload = compatibility_payload(context, patterns, conflicts)
        graph_payload = build_graph_plot_payload(output_dir, compat_payload)
        early_audit_paths.update(
            _write_and_report(
                {
                    "pattern_master_compatibility_graph": compat_payload,
                    "pattern_master_graph_plots": graph_payload,
                },
                output_dir,
                progress,
            )
        )
        del compat_payload, graph_payload
        gc.collect()

        _report(progress, "Resolent CP-SAT mestre de patterns...", 55)
        master_time_limit = _pattern_master_solve_time_limit(solver_config, run_started)
        logs.append(f"pattern-master: master time_limit={master_time_limit:.1f}s")
        selection = solve_master_selection(
            context,
            patterns,
            conflicts,
            time_limit_seconds=master_time_limit,
        )
        logs.extend(selection.logs)
        selected_patterns = selected_patterns_from_ids(patterns, selection.selected_pattern_ids)
        logs.append(
            "pattern-master: master "
            f"status={selection.status} selected={len(selected_patterns)}/{len(hubs)}"
        )

        _report(progress, "Materialitzant grups finals des dels patterns...", 68)
        result, raw_result, built_model = materialize_master_selection(context, selected_patterns, selection)
        logs.append(
            "pattern-master: materialization "
            f"status={result.status} assignments={len(result.assignments)}/{len(context.teams)}"
        )

        _report(progress, "Generant auditoria i Excel pattern-master...", 82)
        local_explanations = build_local_explanations(result, context)
        audit_payloads = build_audit_payloads(
            result=result,
            context=context,
            raw_result=raw_result,
            built_model=built_model,
            local_explanations=local_explanations,
        )
        postrun_payload = build_postrun_plot_payload(output_dir, selection, selected_patterns, result)
        audit_payloads.update(
            {
                "pattern_master_selection": master_selection_payload(selection),
                "pattern_master_materialization": materialization_payload(context, selected_patterns, result),
                "pattern_master_postrun_plots": postrun_payload,
            }
        )
        audit_paths = write_audit_payloads(audit_payloads, output_dir)
        audit_paths = {**early_audit_paths, **audit_paths}
        result_json_path = output_dir / "resource_solver_pattern_master_result.json"
        result_json_path.write_text(
            json.dumps(result_to_json_ready(result), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        audit_paths["resource_solver_pattern_master_result"] = str(result_json_path)

        output_path = output_dir / f"assignacions_pattern_master_{Path(input_path).stem}.xlsx"
        from calendaritzacions.reporting.resource_solver_excel_adapter import write_resource_solver_workbook

        write_resource_solver_workbook(str(output_path), result=result, context=context)

        try:
            from calendaritzacions.reporting.resource_solver_plots import write_resource_solver_final_plots

            final_plots = write_resource_solver_final_plots(
                output_dir / "plots_final_pattern_master",
                result=result,
                context=context,
                stem=f"resource_solver_pattern_master_{Path(input_path).stem}",
            )
            manifest_path = final_plots.get("manifest")
            if manifest_path:
                audit_paths["resource_solver_final_plots"] = manifest_path
                _report_artifact(progress, "resource_solver_final_plots", manifest_path)
            logs.append(f"pattern-master: plots finals generats={max(0, len(final_plots) - 1)}")
        except Exception as exc:
            logs.append(f"pattern-master: plots finals no generats ({exc})")

        logs.extend(str(item) for item in result.logs)
        logs.append(f"resource_solver_pattern_master: status={result.status}")
        logs.extend(_result_log_lines(result))
        logs.append(f"resource_solver_pattern_master: excel={output_path.name}")
        _report(progress, "Excel i auditoria pattern-master generats.", 90)
        return EngineResult(output_path=str(output_path), audit_paths=audit_paths, logs=logs)


def _write_and_report(payloads: dict[str, Any], output_dir: Path, progress: Any | None) -> dict[str, str]:
    paths = write_audit_payloads(payloads, output_dir)
    for name, path in paths.items():
        _report_artifact(progress, name, path)
    return paths


def _pattern_master_solve_time_limit(config: Any, run_started: float) -> float:
    explicit = float(getattr(config, "pattern_master_solve_time_limit_seconds", 0.0) or 0.0)
    if explicit > 0:
        return explicit

    fallback = max(1.0, float(getattr(config, "internal_solve_time_limit_seconds", 60.0) or 60.0))
    worker_limit = float(getattr(config, "worker_time_limit_seconds", 0.0) or 0.0)
    if worker_limit <= 0:
        return fallback

    reserve = max(0.0, float(getattr(config, "pattern_master_materialization_reserve_seconds", 3600.0) or 0.0))
    elapsed = max(0.0, perf_counter() - run_started)
    remaining_for_master = worker_limit - elapsed - reserve
    if remaining_for_master <= 0:
        return 1.0
    return max(1.0, remaining_for_master)


__all__ = ["ResourceSolverPatternMasterEngine"]
