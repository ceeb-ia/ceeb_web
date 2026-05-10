"""Legacy-compatible engine modules."""

from calendaritzacions.engine.legacy.home_away import (
    HomeAwayResolution,
    HomeAwayResolutionError,
    resolve_home_away_requests,
)
from calendaritzacions.engine.legacy.service import assignar_grups_hungares

__all__ = [
    "HomeAwayResolution",
    "HomeAwayResolutionError",
    "assignar_grups_hungares",
    "resolve_home_away_requests",
]
