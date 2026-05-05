"""Compatibility wrappers around the legacy V1 implementation."""

from __future__ import annotations

from typing import Optional

LegacyProcessResult = str | tuple[str, list[str]]


def process_excel(
    input_path: str,
    return_logs: bool = False,
    task_id: Optional[str] = None,
    segona_fase_bool: bool = False,
) -> LegacyProcessResult:
    """Delegate to the legacy pipeline without importing it at module load."""
    from calendaritzacions.application.legacy_pipeline import (
        process_excel as legacy_process_excel,
    )

    return legacy_process_excel(
        input_path=input_path,
        return_logs=return_logs,
        task_id=task_id,
        segona_fase_bool=segona_fase_bool,
    )
