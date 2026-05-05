"""Progress reporting interfaces for calendarization workflows."""

from __future__ import annotations

from typing import Protocol


class ProgressReporter(Protocol):
    """Small interface for reporting progress without coupling to a transport."""

    def report(self, message: str, percent: int | None = None) -> None:
        """Report a progress message."""


class NoopProgressReporter:
    """Progress reporter that intentionally ignores all updates."""

    def report(self, message: str, percent: int | None = None) -> None:
        return None
