"""Domain-level errors for calendarization workflows."""

from __future__ import annotations


class CalendarizationError(Exception):
    """Base class for calendarization domain failures."""


class InfeasibleCalendarizationError(CalendarizationError):
    """Raised when a valid calendarization cannot be found."""


class InvalidSeedMappingError(CalendarizationError):
    """Raised when a home/away seed request maps to an invalid draw number."""
