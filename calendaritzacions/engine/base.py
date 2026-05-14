"""Core engine interfaces for calendarization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from calendaritzacions.engine.config import EngineConfig


@dataclass(frozen=True)
class EngineResult:
    """Normalized result shape for future engines."""

    output_path: str
    kpis_path: str | None = None
    status: str | None = None
    audit_paths: dict[str, str] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)


class CalendarizationEngine(Protocol):
    """Protocol implemented by calendarization engines."""

    def run(
        self,
        input_path: str,
        config: EngineConfig,
        progress: Any | None = None,
    ) -> EngineResult:
        """Process an input file and return normalized engine outputs."""
