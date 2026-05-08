"""Engine configuration primitives."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineConfig:
    """Minimal engine selection configuration."""

    name: str = "legacy"
    phase_name: str = "primera_fase"
