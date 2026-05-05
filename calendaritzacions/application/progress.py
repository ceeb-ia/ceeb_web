"""Progress reporting interfaces for calendarization workflows."""

from __future__ import annotations

from importlib import import_module
from typing import Protocol

from asgiref.sync import async_to_sync


class ProgressReporter(Protocol):
    """Small interface for reporting progress without coupling to a transport."""

    def report(self, message: str, percent: int | None = None) -> None:
        """Report a progress message."""


class NoopProgressReporter:
    """Progress reporter that intentionally ignores all updates."""

    def report(self, message: str, percent: int | None = None) -> None:
        return None


class TaskProgressReporter:
    """Progress reporter that preserves the legacy Redis task channel."""

    def __init__(self, task_id: str | None) -> None:
        self._task_id = task_id

    def report(self, message: str, percent: int | None = None) -> None:
        if not self._task_id:
            return
        push_log = import_module("logs").push_log
        async_to_sync(push_log)(self._task_id, message, percent)


def progress_for_task(task_id: str | None) -> ProgressReporter:
    if task_id:
        return TaskProgressReporter(task_id)
    return NoopProgressReporter()
