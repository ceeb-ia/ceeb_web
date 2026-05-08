"""Backward-compatible facade for the legacy calendarization pipeline.

The implementation has moved to ``calendaritzacions.application.legacy_pipeline``.
This module preserves historical imports such as ``from main import process_excel``
and keeps ``python main.py ...`` working.
"""

from __future__ import annotations

import runpy

from calendaritzacions.application import legacy_pipeline as _legacy_pipeline

for _name, _value in vars(_legacy_pipeline).items():
    if _name not in {"__builtins__", "__cached__", "__doc__", "__file__", "__loader__", "__name__", "__package__", "__spec__"}:
        globals()[_name] = _value

__all__ = [
    _name
    for _name in globals()
    if _name not in {"_legacy_pipeline", "runpy"}
]


if __name__ == "__main__":
    runpy.run_module("calendaritzacions.application.legacy_pipeline", run_name="__main__")
