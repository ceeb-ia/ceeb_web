import copy
import json

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from ...models import Competicio
from ...models.competicio import CompeticioAparell
from ...scoring_engine import ScoringEngine, ScoringError
from ...services.scoring.scoring_subjects import (
    get_or_create_subject_entry_locked,
    resolve_scoring_phase,
    resolve_scoring_subject,
    serialize_subject_payload,
)
from ...services.scoring.phase_eligibility import phase_subject_is_scoreable
from ...services.scoring.schema_resolution import resolve_scoring_schema_for_comp_aparell
from ...services.scoring.judge_presence import (
    build_runtime_inputs_from_canonical,
    canonicalize_inputs_for_schema,
    persist_inputs_after_compute,
)
from ...services.scoring.team_scoring import (
    MEMBER_CODE_SUFFIX_RE,
    eligible_team_ids_for_comp_aparell,
    is_team_context_app,
    logical_team_inputs_to_runtime_inputs,
    runtime_inputs_to_logical_team_inputs,
    runtime_schema_for_comp_aparell,
)
from .helpers import (
    _allowed_input_codes_for_schema,
    _logical_team_input_codes,
    _merge_inputs_preserving_orphans,
    _merge_team_logical_patch,
    _split_inputs_by_allowed_codes,
)


@require_POST
@transaction.atomic
def scoring_save(request, pk):
    """
    Guarda inputs i calcula outputs per un ScoreEntry.
    Payload:
    {
      "inscripcio_id": 10,
      "exercici": 1,
      "comp_aparell_id": 5,
      "inputs": {...}
    }
    """
    competicio = get_object_or_404(Competicio, pk=pk)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON invalid"}, status=400)

    comp_aparell_id = payload.get("comp_aparell_id")
    exercici = int(payload.get("exercici") or 1)
    inputs = payload.get("inputs", {})

    if not comp_aparell_id:
        return JsonResponse({"ok": False, "error": "Falta comp_aparell_id"}, status=400)

    comp_aparell = get_object_or_404(CompeticioAparell, pk=comp_aparell_id, competicio=competicio, actiu=True)
    fase, phase_error_response = resolve_scoring_phase(competicio, comp_aparell, payload.get("fase_id"))
    if phase_error_response is not None:
        return phase_error_response
    subject, error_response = resolve_scoring_subject(
        competicio,
        comp_aparell,
        payload,
        eligible_team_ids=eligible_team_ids_for_comp_aparell(competicio, comp_aparell) if is_team_context_app(comp_aparell) else None,
    )
    if error_response is not None:
        return error_response
    if fase is not None and not phase_subject_is_scoreable(
        fase,
        comp_aparell=comp_aparell,
        subject_kind=subject["subject_kind"],
        subject_id=subject["subject_id"],
    ):
        return JsonResponse(
            {"ok": False, "error": "Aquest subjecte no esta publicat per puntuar en aquesta fase."},
            status=403,
        )

    _schema_obj, base_schema = resolve_scoring_schema_for_comp_aparell(comp_aparell)
    team_subject = subject.get("team_subject") if str(subject.get("subject_kind")) == "team_unit" else None
    team_member_count = len(getattr(team_subject, "member_ids", []) or []) if team_subject is not None else 0
    base_schema = base_schema or {}
    schema = runtime_schema_for_comp_aparell(base_schema, comp_aparell, member_count=team_member_count)
    if team_subject is not None:
        allowed = _logical_team_input_codes(base_schema)
        clean_inputs = {}
        if isinstance(inputs, dict):
            for key, value in inputs.items():
                if key in allowed:
                    clean_inputs[key] = copy.deepcopy(value)
        canonical_inputs = logical_team_inputs_to_runtime_inputs(clean_inputs, team_subject, base_schema)
        runtime_inputs = build_runtime_inputs_from_canonical(canonical_inputs, schema)
    else:
        allowed = _allowed_input_codes_for_schema(base_schema, comp_aparell)
        clean_inputs = {}
        if isinstance(inputs, dict):
            for key, value in inputs.items():
                if key in allowed:
                    clean_inputs[key] = value
        canonical_inputs = canonicalize_inputs_for_schema(clean_inputs, schema)
        runtime_inputs = build_runtime_inputs_from_canonical(canonical_inputs, schema)

    try:
        engine = ScoringEngine(schema)
        result = engine.compute(runtime_inputs)
    except ScoringError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Error inesperat calculant."}, status=500)

    max_ex = max(1, min(4, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1)))
    exercici = max(1, min(max_ex, exercici))

    entry, _ = get_or_create_subject_entry_locked(
        competicio=competicio,
        comp_aparell=comp_aparell,
        exercici=exercici,
        subject=subject,
        fase=fase,
    )
    entry.inputs = (
        runtime_inputs_to_logical_team_inputs(
            persist_inputs_after_compute(canonical_inputs, result.inputs, schema),
            team_subject,
            base_schema,
        )
        if team_subject is not None
        else persist_inputs_after_compute(canonical_inputs, result.inputs, schema)
    )
    entry.outputs = result.outputs
    entry.total = result.total
    entry.save()

    response = {
        "ok": True,
        "exercici": entry.exercici,
        "comp_aparell_id": comp_aparell.id,
        "fase_id": entry.fase_id,
        "outputs": entry.outputs,
        "total": float(entry.total),
        "inputs": entry.inputs,
    }
    response.update(serialize_subject_payload(subject["subject_kind"], subject["subject_id"]))
    return JsonResponse(response)


@require_POST
@transaction.atomic
def scoring_save_partial(request, pk):
    """
    Igual que scoring_save, pero:
    - rep inputs_patch (no inputs complet)
    - fa merge amb entry.inputs existent
    - recalcula amb ScoringEngine
    """
    competicio = get_object_or_404(Competicio, pk=pk)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON invalid"}, status=400)

    comp_aparell_id = payload.get("comp_aparell_id")
    exercici = int(payload.get("exercici") or 1)
    patch = payload.get("inputs_patch", {})

    if not comp_aparell_id:
        return JsonResponse({"ok": False, "error": "Falta comp_aparell_id"}, status=400)
    if not isinstance(patch, dict):
        return JsonResponse({"ok": False, "error": "inputs_patch ha de ser objecte JSON"}, status=400)

    comp_aparell = get_object_or_404(CompeticioAparell, pk=comp_aparell_id, competicio=competicio, actiu=True)
    fase, phase_error_response = resolve_scoring_phase(competicio, comp_aparell, payload.get("fase_id"))
    if phase_error_response is not None:
        return phase_error_response
    subject, error_response = resolve_scoring_subject(
        competicio,
        comp_aparell,
        payload,
        eligible_team_ids=eligible_team_ids_for_comp_aparell(competicio, comp_aparell) if is_team_context_app(comp_aparell) else None,
    )
    if error_response is not None:
        return error_response
    if fase is not None and not phase_subject_is_scoreable(
        fase,
        comp_aparell=comp_aparell,
        subject_kind=subject["subject_kind"],
        subject_id=subject["subject_id"],
    ):
        return JsonResponse(
            {"ok": False, "error": "Aquest subjecte no esta publicat per puntuar en aquesta fase."},
            status=403,
        )

    max_ex = max(1, min(4, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1)))
    exercici = max(1, min(max_ex, exercici))

    _schema_obj, base_schema = resolve_scoring_schema_for_comp_aparell(comp_aparell)
    team_subject = subject.get("team_subject") if str(subject.get("subject_kind")) == "team_unit" else None
    base_schema = base_schema or {}
    team_member_count = len(getattr(team_subject, "member_ids", []) or []) if team_subject is not None else 0
    schema = runtime_schema_for_comp_aparell(base_schema, comp_aparell, member_count=team_member_count)

    if team_subject is not None:
        allowed = _logical_team_input_codes(base_schema)
        runtime_keys = [str(key) for key in patch.keys() if MEMBER_CODE_SUFFIX_RE.search(str(key or ""))]
        if runtime_keys:
            return JsonResponse(
                {"ok": False, "error": "Els aparells d'equip nomes accepten inputs logics; no claus runtime __mN."},
                status=400,
            )
    else:
        allowed = _allowed_input_codes_for_schema(base_schema, comp_aparell)

    entry, _ = get_or_create_subject_entry_locked(
        competicio=competicio,
        comp_aparell=comp_aparell,
        exercici=exercici,
        subject=subject,
        fase=fase,
        defaults={"inputs": {}, "outputs": {}, "total": 0},
    )
    current_inputs = entry.inputs if isinstance(entry.inputs, dict) else {}
    if team_subject is not None:
        current_inputs, orphan_inputs = _split_inputs_by_allowed_codes(current_inputs, allowed)
        merged_logical = _merge_team_logical_patch(current_inputs, patch, base_schema)
        canonical_inputs = canonicalize_inputs_for_schema(
            logical_team_inputs_to_runtime_inputs(merged_logical, team_subject, base_schema),
            schema,
        )
    else:
        orphan_inputs = {}
        merged = dict(current_inputs)
        for key, value in patch.items():
            if key in allowed:
                merged[key] = value
        canonical_inputs = canonicalize_inputs_for_schema(merged, schema)
    runtime_inputs = build_runtime_inputs_from_canonical(canonical_inputs, schema)

    try:
        engine = ScoringEngine(schema)
        result = engine.compute(runtime_inputs)
    except ScoringError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Error inesperat calculant."}, status=500)

    entry.inputs = (
        _merge_inputs_preserving_orphans(
            runtime_inputs_to_logical_team_inputs(
                persist_inputs_after_compute(canonical_inputs, result.inputs, schema),
                team_subject,
                base_schema,
            ),
            orphan_inputs,
        )
        if team_subject is not None
        else persist_inputs_after_compute(canonical_inputs, result.inputs, schema)
    )
    entry.outputs = result.outputs
    entry.total = result.total
    entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])

    response = {
        "ok": True,
        "exercici": entry.exercici,
        "comp_aparell_id": comp_aparell.id,
        "fase_id": entry.fase_id,
        "inputs": (
            runtime_inputs_to_logical_team_inputs(
                persist_inputs_after_compute(canonical_inputs, result.inputs, schema),
                team_subject,
                base_schema,
            )
            if team_subject is not None
            else entry.inputs
        ),
        "outputs": entry.outputs,
        "total": float(entry.total),
        "updated_at": entry.updated_at.isoformat(),
    }
    response.update(serialize_subject_payload(subject["subject_kind"], subject["subject_id"]))
    return JsonResponse(response)
