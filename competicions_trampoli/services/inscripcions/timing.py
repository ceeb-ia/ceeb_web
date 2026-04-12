from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Iterator

from django.conf import settings


INSCRIPCIONS_TIMINGS_HEADER = "X-Inscripcions-Timings"


def _normalize_flag(value: Any) -> bool:
    token = str(value or "").strip().lower()
    return token in {"1", "true", "yes", "on"}


def is_inscripcions_timing_enabled(request) -> bool:
    if bool(getattr(settings, "INSCRIPCIONS_TIMING_ENABLED", False)):
        return True

    meta = getattr(request, "META", {}) or {}
    for key in ("HTTP_X_INSCRIPCIONS_TIMINGS", "HTTP_X_INSCRIPCIONS_TIMING"):
        if _normalize_flag(meta.get(key)):
            return True

    return _normalize_flag(getattr(request, "GET", {}).get("_inscripcions_timings"))


@dataclass
class InscripcionsTimingCollector:
    enabled: bool
    sections: list[dict[str, Any]] = field(default_factory=list)

    @contextmanager
    def section(self, name: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return

        started_at = perf_counter()
        try:
            yield
        finally:
            elapsed_ms = round((perf_counter() - started_at) * 1000.0, 3)
            self.sections.append({"name": str(name or "").strip(), "elapsed_ms": elapsed_ms})

    def as_payload(self) -> dict[str, Any]:
        elapsed_ms = [float(item.get("elapsed_ms") or 0.0) for item in self.sections]
        return {
            "enabled": bool(self.enabled),
            "sections": list(self.sections),
            "total_ms": round(sum(elapsed_ms), 3),
        }

    def as_header_value(self) -> str:
        if not self.enabled or not self.sections:
            return ""
        return json.dumps(self.as_payload(), ensure_ascii=False, separators=(",", ":"))

    def apply_to_response(self, response) -> None:
        header_value = self.as_header_value()
        if header_value:
            response[INSCRIPCIONS_TIMINGS_HEADER] = header_value


def get_inscripcions_timing_collector(request) -> InscripcionsTimingCollector:
    collector = getattr(request, "_inscripcions_timing_collector", None)
    if collector is None:
        collector = InscripcionsTimingCollector(enabled=is_inscripcions_timing_enabled(request))
        setattr(request, "_inscripcions_timing_collector", collector)
    return collector


@contextmanager
def inscripcions_timing_section(request, name: str) -> Iterator[None]:
    with get_inscripcions_timing_collector(request).section(name):
        yield
