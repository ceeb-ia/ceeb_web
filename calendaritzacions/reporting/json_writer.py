"""JSON writers for reporting payloads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from calendaritzacions.analysis.kpi_payload import json_default


def write_kpis_json(path: str | Path, payload: dict[str, Any]) -> str:
    """Write a KPI payload as formatted UTF-8 JSON and return its path."""
    return write_json_payload(path, payload)


def write_json_payload(path: str | Path, payload: dict[str, Any]) -> str:
    """Write a JSON payload as formatted UTF-8 JSON and return its path."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, default=json_default)
    return str(output_path)


__all__ = ["write_json_payload", "write_kpis_json"]
