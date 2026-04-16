"""Helpers for browser-driven inscripcions tests.

This module stays pure and lightweight so future browser tests can share
stable selectors and small status helpers without depending on Playwright
objects or page setup.
"""

from __future__ import annotations

from typing import Iterable

INSCRIPCIONS_PAGE_SHELL_ID = "inscripcions-page-shell"
INSCRIPCIONS_TOOLBAR_FRAGMENT_ID = "inscripcions-toolbar-fragment"
INSCRIPCIONS_HEADER_FRAGMENT_ID = "inscripcions-header-fragment"
INSCRIPCIONS_HISTORY_FRAGMENT_ID = "inscripcions-history-fragment"

INSCRIPCIONS_DRAWER_TOGGLE_ID = "inscripcions-drawer-toggle"
INSCRIPCIONS_BACK_TO_TOP_ID = "inscripcions-back-to-top"
INSCRIPCIONS_ACTIONS_SIDEBAR_ID = "inscripcions-actions-sidebar"
INSCRIPCIONS_PANELS_NAV_ID = "inscripcions-panels-nav"
INSCRIPCIONS_PANELS_ROOT_ID = "inscripcions-panels"

SEARCH_INPUT_ID = "search-input"
SEARCH_BUTTON_ID = "search-btn"
CLEAR_SEARCH_BUTTON_ID = "clear-search-btn"
COMPETITION_ORDER_TAIL_TOGGLE_ID = "competition-order-tail-toggle"

HISTORY_UNDO_BUTTON_ID = "btn-history-undo"
HISTORY_REDO_BUTTON_ID = "btn-history-redo"
HISTORY_SUMMARY_ID = "history-stack-summary"

GROUPING_PANEL_ID = "panel-agrupacio"
COLUMNS_PANEL_ID = "panel-columnes"
GROUPS_PANEL_ID = "panel-grups"
TEAMS_PANEL_ID = "panel-equips"
SERIES_PANEL_ID = "panel-series-equips"
MEDIA_PANEL_ID = "panel-media"
OTHER_PANEL_ID = "panel-altres"

PANEL_KEYS = (
    "agrupacio",
    "columnes",
    "grups",
    "equips",
    "series-equips",
    "media",
    "altres",
)

PANEL_IDS = {
    "agrupacio": GROUPING_PANEL_ID,
    "columnes": COLUMNS_PANEL_ID,
    "grups": GROUPS_PANEL_ID,
    "equips": TEAMS_PANEL_ID,
    "series-equips": SERIES_PANEL_ID,
    "media": MEDIA_PANEL_ID,
    "altres": OTHER_PANEL_ID,
}

PANEL_BUTTON_TARGETS = {
    key: f'[data-panel-target="{key}"]' for key in PANEL_KEYS
}

COMMON_LOADING_MARKERS = (
    "carregant",
    "loading",
    "wait",
)

COMMON_ERROR_MARKERS = (
    "error",
    "failed",
    "fallada",
    "fallat",
    "no s'han pogut",
)


def normalize_text(value: object) -> str:
    """Return a trimmed single-spaced string for stable comparisons."""

    if value is None:
        return ""
    text = str(value).replace("\xa0", " ")
    return " ".join(text.split()).strip()


def compact_status(value: object) -> str:
    """Return a normalized lowercase status string."""

    return normalize_text(value).lower()


def is_loading_status(value: object) -> bool:
    """Return True when a status looks like a loading placeholder."""

    status = compact_status(value)
    return any(marker in status for marker in COMMON_LOADING_MARKERS)


def is_error_status(value: object) -> bool:
    """Return True when a status looks like an error or failure message."""

    status = compact_status(value)
    return any(marker in status for marker in COMMON_ERROR_MARKERS)


def is_ready_status(value: object) -> bool:
    """Return True when a status is neither loading nor error-like."""

    status = compact_status(value)
    return bool(status) and not is_loading_status(status) and not is_error_status(status)


def panel_id(panel_key: str) -> str:
    """Return the stable DOM id for a known panel key."""

    return PANEL_IDS[panel_key]


def panel_selector(panel_key: str) -> str:
    """Return the CSS id selector for a known panel key."""

    return f"#{panel_id(panel_key)}"


def panel_button_selector(panel_key: str) -> str:
    """Return the nav button selector for a known panel key."""

    return PANEL_BUTTON_TARGETS[panel_key]


def panel_related_selectors(panel_key: str) -> tuple[str, str]:
    """Return the button and panel selectors for a panel key."""

    return panel_button_selector(panel_key), panel_selector(panel_key)


def stable_selectors(panel_keys: Iterable[str] = PANEL_KEYS) -> tuple[str, ...]:
    """Return the core selectors used by browser tests."""

    selectors = (
        f"#{INSCRIPCIONS_PAGE_SHELL_ID}",
        f"#{INSCRIPCIONS_TOOLBAR_FRAGMENT_ID}",
        f"#{INSCRIPCIONS_HEADER_FRAGMENT_ID}",
        f"#{INSCRIPCIONS_HISTORY_FRAGMENT_ID}",
        f"#{INSCRIPCIONS_ACTIONS_SIDEBAR_ID}",
        f"#{INSCRIPCIONS_PANELS_NAV_ID}",
        f"#{INSCRIPCIONS_PANELS_ROOT_ID}",
        f"#{INSCRIPCIONS_DRAWER_TOGGLE_ID}",
        f"#{INSCRIPCIONS_BACK_TO_TOP_ID}",
        f"#{SEARCH_INPUT_ID}",
        f"#{SEARCH_BUTTON_ID}",
        f"#{CLEAR_SEARCH_BUTTON_ID}",
        f"#{COMPETITION_ORDER_TAIL_TOGGLE_ID}",
        f"#{HISTORY_UNDO_BUTTON_ID}",
        f"#{HISTORY_REDO_BUTTON_ID}",
    )
    panel_selectors = tuple(panel_selector(panel_key) for panel_key in panel_keys)
    return selectors + panel_selectors
