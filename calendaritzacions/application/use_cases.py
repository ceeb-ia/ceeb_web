"""Application use cases for calendarization."""

from __future__ import annotations

from typing import Optional

from calendaritzacions.application.compatibility import LegacyProcessResult, process_excel


def process_calendarization(
    input_path: str,
    return_logs: bool = False,
    task_id: Optional[str] = None,
    segona_fase_bool: bool = False,
) -> LegacyProcessResult:
    """Process a calendarization request through the current compatible engine."""
    return process_excel(
        input_path=input_path,
        return_logs=return_logs,
        task_id=task_id,
        segona_fase_bool=segona_fase_bool,
    )
