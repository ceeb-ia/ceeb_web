"""Core engine interfaces for calendarization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EngineResult:
    """Normalized result shape for future engines."""

    output_path: str


class CalendarizationEngine(Protocol):
    """Protocol implemented by calendarization engines."""

    def process(
        self,
        input_path: str,
        return_logs: bool = False,
        task_id: str | None = None,
        segona_fase_bool: bool = False,
    ) -> str | tuple[str, list[str]]:
        """Process an input file and return the generated output path."""
