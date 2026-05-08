"""Audit artifact payload construction helpers."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from calendaritzacions.analysis.indicators import _df_records, _json_default

SCHEMA_VERSION = 1


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.DataFrame):
        return [_json_value(record) for record in _df_records(value)]
    if isinstance(value, pd.Series):
        return _json_value(value.to_dict())
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, Mapping):
        return {str(_json_value(key)): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    if isinstance(value, (datetime, date, pd.Timestamp)):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Path):
        return str(value)

    try:
        converted = _json_default(value)
    except (TypeError, ValueError):
        converted = value
    if converted is not value:
        return _json_value(converted)

    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, np.generic):
        return _json_value(value.item())
    return str(value)


def _payload(artifact_type: str, fields: Mapping[str, Any] | None, extra: Mapping[str, Any]) -> dict[str, Any]:
    payload = {}
    if fields:
        payload.update(fields)
    payload.update(extra)
    payload["schema_version"] = SCHEMA_VERSION
    payload["artifact_type"] = artifact_type
    return _json_value(payload)


def build_run_manifest(fields: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """Build a JSON-ready run manifest payload."""
    return _payload("run_manifest", fields, extra)


def build_input_validation_payload(fields: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """Build a JSON-ready input validation audit payload."""
    return _payload("input_validation", fields, extra)


def build_input_demand_payload(fields: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """Build a JSON-ready input demand audit payload."""
    return _payload("input_demand", fields, extra)


def build_home_away_resolution_payload(fields: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """Build a JSON-ready home/away resolution audit payload."""
    return _payload("home_away_resolution", fields, extra)


def build_constraints_report(fields: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """Build a JSON-ready constraints report audit payload."""
    return _payload("constraints_report", fields, extra)


def build_performance_payload(fields: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """Build a JSON-ready performance audit payload."""
    return _payload("performance", fields, extra)


def build_solver_trace(fields: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """Build a JSON-ready solver trace audit payload."""
    return _payload("solver_trace", fields, extra)


__all__ = [
    "build_constraints_report",
    "build_home_away_resolution_payload",
    "build_input_demand_payload",
    "build_input_validation_payload",
    "build_performance_payload",
    "build_run_manifest",
    "build_solver_trace",
]
