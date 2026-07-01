from __future__ import annotations

import copy

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from ...models.inscripcions import Inscripcio
from ...models.judging import JudgeScoreSubmission
from ...models.scoring import TeamCompetitiveSubject
from ...scoring_engine import ScoringEngine
from ...services.scoring.judge_presence import (
    build_runtime_inputs_from_canonical,
    is_strict_presence_field,
    merge_judge_patch_into_canonical,
    persist_inputs_after_compute,
    presence_key,
)
from ...services.scoring.schema_resolution import resolve_scoring_schema_for_comp_aparell
from ...services.scoring.scoring_subjects import get_or_create_subject_entry_locked
from ...services.scoring.team_scoring import (
    is_team_context_app,
    logical_team_inputs_to_runtime_inputs,
    runtime_inputs_to_logical_team_inputs,
    runtime_schema_for_comp_aparell,
)
from .supervision import mark_submission_approved, token_is_supervisor_for_field


def _apply_sanitized_patch(current_inputs: dict, sanitized_patch: dict, schema: dict) -> dict:
    out = merge_judge_patch_into_canonical(current_inputs or {}, sanitized_patch or {}, schema or {})
    by_code = {
        field.get("code"): field
        for field in (schema.get("fields") or [])
        if isinstance(field, dict) and field.get("code")
    }
    for code, payload in (sanitized_patch or {}).items():
        if isinstance(code, str) and code.startswith("__crash__"):
            base_code = code[len("__crash__"):]
            field = by_code.get(base_code, {})
            crash_cfg = field.get("crash") if isinstance(field.get("crash"), dict) else {}
            if (field.get("type") or "number") != "matrix" or not crash_cfg.get("enabled"):
                continue
            if isinstance(payload, dict) and "__set_list__" in payload:
                current = out.get(code)
                current = current if isinstance(current, list) else []
                max_idx = max((idx for idx, _ in payload["__set_list__"]), default=-1)
                while len(current) <= max_idx:
                    current.append(0)
                for idx, value in payload["__set_list__"]:
                    current[idx] = copy.deepcopy(value)
                out[code] = current
            continue

        field = by_code.get(code, {})
        ftype = field.get("type") or "number"
        if ftype == "number":
            out[code] = copy.deepcopy(payload)
            continue
        if ftype == "list" and isinstance(payload, dict) and "__set_list__" in payload:
            current = out.get(code)
            current = current if isinstance(current, list) else []
            max_idx = max((idx for idx, _ in payload["__set_list__"]), default=-1)
            while len(current) <= max_idx:
                current.append(None)
            for idx, value in payload["__set_list__"]:
                current[idx] = copy.deepcopy(value)
            out[code] = current
            continue
        if ftype == "matrix" and isinstance(payload, dict) and "__set_matrix__" in payload:
            current = out.get(code)
            current = current if isinstance(current, list) else []
            max_row = max((row for row, _, __ in payload["__set_matrix__"]), default=-1)
            while len(current) <= max_row:
                current.append([])
            n_items = int(((field.get("items") or {}).get("count")) or 0) or 1
            for row, col, value in payload["__set_matrix__"]:
                current_row = current[row] if isinstance(current[row], list) else []
                while len(current_row) < n_items:
                    current_row.append(None)
                current_row[col] = copy.deepcopy(value)
                current[row] = current_row
            out[code] = current
            continue
    return out


def _allowed_input_codes_for_schema(schema: dict) -> set[str]:
    allowed = set()
    for field in (schema.get("fields") or []):
        if not isinstance(field, dict) or not field.get("code"):
            continue
        code = str(field["code"])
        allowed.add(code)
        allowed.add(f"__crash__{code}")
        if is_strict_presence_field(field):
            allowed.add(presence_key(code))
    return allowed


def _patch_for_submission_context(patch: dict, schema: dict, submission=None) -> dict:
    if submission is None:
        return dict(patch or {})
    by_code = {
        str(field.get("code")): field
        for field in (schema.get("fields") or [])
        if isinstance(field, dict) and field.get("code")
    }
    out = {}
    judge_idx = max(0, int(getattr(submission, "judge_index", 1) or 1) - 1)
    item_start = max(1, int(getattr(submission, "item_start", 1) or 1))
    for code, payload in (patch or {}).items():
        code = str(code)
        is_crash = code.startswith("__crash__")
        base_code = code[len("__crash__"):] if is_crash else code
        field = by_code.get(base_code)
        if not field:
            out[code] = copy.deepcopy(payload)
            continue
        ftype = str(field.get("type") or "number").strip().lower()
        if is_crash:
            out[code] = {"__set_list__": [(judge_idx, copy.deepcopy(payload))]}
            continue
        if ftype == "list" and not (isinstance(payload, dict) and "__set_list__" in payload):
            value = payload[judge_idx] if isinstance(payload, list) and len(payload) > judge_idx else payload
            out[code] = {"__set_list__": [(judge_idx, copy.deepcopy(value))]}
            continue
        if ftype == "matrix" and not (isinstance(payload, dict) and "__set_matrix__" in payload):
            row = None
            if isinstance(payload, list) and payload and isinstance(payload[0], list):
                row = payload[judge_idx] if len(payload) > judge_idx else None
            elif isinstance(payload, list):
                row = payload
            if row is None:
                out[code] = copy.deepcopy(payload)
                continue
            sets = []
            for offset, value in enumerate(row):
                sets.append((judge_idx, item_start - 1 + offset, copy.deepcopy(value)))
            out[code] = {"__set_matrix__": sets}
            continue
        out[code] = copy.deepcopy(payload)
    return out


def _subject_from_submission(submission: JudgeScoreSubmission) -> dict:
    if submission.subject_kind == "team_unit":
        team_subject = TeamCompetitiveSubject.objects.select_related("equip", "context").get(
            pk=submission.subject_id,
            competicio=submission.competicio,
            comp_aparell=submission.comp_aparell,
        )
        return {
            "subject_kind": "team_unit",
            "subject_id": int(team_subject.id),
            "team_subject": team_subject,
            "equip": team_subject.equip,
            "context": team_subject.context,
        }
    inscripcio = Inscripcio.objects.get(pk=submission.subject_id, competicio=submission.competicio)
    return {
        "subject_kind": "inscripcio",
        "subject_id": int(inscripcio.id),
        "inscripcio": inscripcio,
    }


def persist_subject_score_patch(
    *,
    competicio,
    comp_aparell,
    exercici: int,
    subject: dict,
    phase,
    patch: dict,
    submission=None,
):
    _schema_obj, base_schema = resolve_scoring_schema_for_comp_aparell(comp_aparell)
    team_subject = subject.get("team_subject") if str(subject.get("subject_kind")) == "team_unit" else None
    team_member_count = len(getattr(team_subject, "member_ids", []) or []) if team_subject is not None else 0
    schema = runtime_schema_for_comp_aparell(base_schema, comp_aparell, member_count=team_member_count)
    entry, _ = get_or_create_subject_entry_locked(
        competicio=competicio,
        comp_aparell=comp_aparell,
        exercici=exercici,
        subject=subject,
        fase=phase,
        defaults={"inputs": {}, "outputs": {}, "total": 0},
    )
    current_inputs = entry.inputs if isinstance(entry.inputs, dict) else {}
    if team_subject is not None:
        current_inputs = logical_team_inputs_to_runtime_inputs(current_inputs, team_subject, base_schema)
    effective_patch = _patch_for_submission_context(patch, schema, submission=submission)
    merged_inputs = _apply_sanitized_patch(current_inputs, effective_patch, schema)
    allowed = _allowed_input_codes_for_schema(schema)
    clean_inputs = {key: value for key, value in merged_inputs.items() if key in allowed}
    runtime_inputs = build_runtime_inputs_from_canonical(clean_inputs, schema)

    engine = ScoringEngine(schema)
    result = engine.compute(runtime_inputs)
    persisted_inputs = persist_inputs_after_compute(clean_inputs, result.inputs, schema)
    entry.inputs = (
        runtime_inputs_to_logical_team_inputs(persisted_inputs, team_subject, base_schema)
        if team_subject is not None
        else persisted_inputs
    )
    entry.outputs = result.outputs
    entry.total = result.total
    entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])
    return entry


@transaction.atomic
def approve_judge_score_submission(*, submission, supervisor_token, supervisor_assignment, inputs_patch=None):
    submission = JudgeScoreSubmission.objects.select_for_update().get(pk=submission.pk)
    if submission.status != JudgeScoreSubmission.Status.PENDING:
        raise ValidationError("La proposta ja no esta pendent.")
    if inputs_patch is not None and not isinstance(inputs_patch, dict):
        raise ValidationError("El patch revisat ha de ser un objecte JSON.")
    if not token_is_supervisor_for_field(
        token=supervisor_token,
        assignment=supervisor_assignment,
        comp_aparell=submission.comp_aparell,
        runtime_field_code=submission.runtime_field_code or submission.field_code,
    ):
        raise PermissionDenied("Aquest token no supervisa aquest camp.")
    subject = _subject_from_submission(submission)
    final_patch = dict(inputs_patch or submission.normalized_inputs_patch or submission.inputs_patch or {})
    entry = persist_subject_score_patch(
        competicio=submission.competicio,
        comp_aparell=submission.comp_aparell,
        exercici=submission.exercici,
        subject=subject,
        phase=submission.fase,
        patch=final_patch,
        submission=submission,
    )
    mark_submission_approved(submission, token=supervisor_token, assignment=supervisor_assignment)
    return submission, entry
