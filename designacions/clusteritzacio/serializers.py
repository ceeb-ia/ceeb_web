from __future__ import annotations

from .contracts import PreviewResult


def serialize_preview_result(result: PreviewResult) -> dict:
    return result.to_dict()
