from __future__ import annotations

import copy

from .scoring_subjects import serialize_subject_payload
from .team_subject_contract import team_subject_meta


def filter_inputs_for_allowed_codes(inputs: dict, allowed_codes: set) -> dict:
    if not isinstance(inputs, dict):
        return {}
    return {
        key: copy.deepcopy(value)
        for key, value in inputs.items()
        if key in allowed_codes
    }


def build_score_update_payload(
    *,
    subject_kind: str,
    subject_id,
    exercici: int,
    comp_aparell_id: int,
    inputs: dict,
    outputs: dict,
    total,
    updated_at,
    subject_meta: dict | None = None,
) -> dict:
    payload = {
        **serialize_subject_payload(subject_kind, subject_id),
        "exercici": exercici,
        "comp_aparell_id": comp_aparell_id,
        "inputs": copy.deepcopy(inputs or {}),
        "outputs": copy.deepcopy(outputs or {}),
        "total": float(total or 0),
        "updated_at": updated_at.isoformat() if updated_at is not None else None,
    }
    if str(subject_kind) == "team_unit":
        payload.update(team_subject_meta(subject_meta))
    return payload
