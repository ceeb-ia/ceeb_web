"""Application use cases for calendarization."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from calendaritzacions.application.compatibility import LegacyProcessResult
from calendaritzacions.application.progress import ProgressReporter, progress_for_task
from calendaritzacions.application.storage import finalize_result_path
from calendaritzacions.ingestion import read_excel


def process_calendarization(
    input_path: str,
    return_logs: bool = False,
    return_artifacts: bool = False,
    task_id: Optional[str] = None,
    segona_fase_bool: bool = False,
    engine_name: str = "legacy",
    progress_reporter: ProgressReporter | None = None,
) -> LegacyProcessResult:
    """Process a calendarization request through the application orchestration boundary."""
    progress = progress_reporter or progress_for_task(task_id)
    if engine_name != "legacy":
        from calendaritzacions.engine.config import EngineConfig
        from calendaritzacions.engine.registry import get_engine

        config = EngineConfig(
            name=engine_name,
            phase_name="segona_fase" if segona_fase_bool else "primera_fase",
        )
        engine = get_engine(engine_name)
        if hasattr(engine, "run"):
            result = engine.run(input_path=input_path, config=config, progress=progress)
            if return_artifacts:
                return result.output_path, result.logs, result.audit_paths, result.kpis_path or ""
            if return_logs:
                return result.output_path, result.logs
            return result.output_path
        result = engine(input_path, return_logs, task_id, segona_fase_bool)
        return result

    from calendaritzacions.application.legacy_pipeline import processar_dades_2

    logs: list[str] = []
    input_name = Path(input_path).name

    progress.report(f"Llegint fitxer Excel... {input_name}", 10)
    df = read_excel(input_path)
    progress.report(f"S'han carregat {len(df)} inscripcions.", 15)

    excel_path = processar_dades_2(
        df,
        nom_fitxer=input_name,
        task_id=task_id,
        segona_fase_bool=segona_fase_bool,
    )
    progress.report(f"Resultat generat: {Path(excel_path).name}", 90)

    final_path = finalize_result_path(excel_path, logs)
    if return_artifacts:
        return str(final_path), logs, {}, ""
    if return_logs:
        return str(final_path), logs
    return str(final_path)
