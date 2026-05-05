"""Registry for calendarization engines."""

from __future__ import annotations

from collections.abc import Callable

from calendaritzacions.application.compatibility import LegacyProcessResult, process_excel

EngineCallable = Callable[[str, bool, str | None, bool], LegacyProcessResult]

_ENGINES: dict[str, EngineCallable] = {
    "legacy": process_excel,
}


def register_engine(name: str, engine: EngineCallable) -> None:
    """Register an engine callable by name."""
    _ENGINES[name] = engine


def get_engine(name: str = "legacy") -> EngineCallable:
    """Return a registered engine callable."""
    return _ENGINES[name]
