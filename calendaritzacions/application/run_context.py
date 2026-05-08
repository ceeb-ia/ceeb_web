"""Run context structures for application-level orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LegacyRunContext:
    """Mutable context accumulated while the legacy pipeline is orchestrated."""

    input_file: str
    phase_name: str
    phase_rounds: int
    engine_name: str = "legacy"
    started_at: str = field(default_factory=_utc_now_iso)
    finished_at: str | None = None
    warnings: list[str] = field(default_factory=list)
    categories: list[dict[str, Any]] = field(default_factory=list)
    home_away_traces: list[str] = field(default_factory=list)
    missing_classifications: list[dict[str, Any]] = field(default_factory=list)
    unused_classification_teams: list[dict[str, Any]] = field(default_factory=list)
    input_rows: int = 0
    assigned_rows: int = 0
    excel_path: str | None = None
    kpis_path: str | None = None
    audit_paths: dict[str, str] = field(default_factory=dict)

    def finish(self) -> None:
        self.finished_at = _utc_now_iso()

    def add_category_result(self, category: str, info: dict[str, Any]) -> None:
        row = {"categoria": category}
        row.update(info)
        self.categories.append(row)
