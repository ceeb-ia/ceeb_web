import json

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from ...models.judging import JudgeDeviceToken
from ...scoring_engine import ScoringEngine, ScoringError
from ...services.scoring.schema_resolution import resolve_scoring_schema_for_comp_aparell
from ...services.scoring.judge_presence import (
    build_runtime_inputs_from_canonical,
    is_strict_presence_field,
    persist_inputs_after_compute,
    presence_key,
)
from ...services.scoring.scoring_subjects import (
    get_or_create_subject_entry_locked,
    resolve_scoring_subject,
    serialize_subject_payload,
)
from ...services.scoring.team_scoring import (
    build_team_subjects_for_comp_aparell,
    is_team_context_app,
    logical_team_inputs_to_runtime_inputs,
    runtime_inputs_to_logical_team_inputs,
    runtime_schema_for_comp_aparell,
)
from ._assignment_scope import (
    assignment_id_from_request,
    clamp_exercici_for_scope,
    ensure_subject_scoreable_for_scope,
    resolve_assignment_scope_for_request,
)
from ._shared import _filter_inputs_for_allowed_codes
from .permissions import (
    _allowed_input_codes_from_permissions,
    _apply_sanitized_patch,
    _normalize_permissions,
    _resolve_permissions_for_subject,
    _sanitize_patch_by_permissions,
)

@require_POST
@transaction.atomic
def judge_save_partial(request, token):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        return JsonResponse({"ok": False, "error": "Token invàlid o revocat"}, status=403)

    tok.touch()

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON invàlid"}, status=400)

    scope, scope_error = resolve_assignment_scope_for_request(tok, assignment_id_from_request(request, payload))
    if scope_error is not None:
        return scope_error

    subject_payload = {
        "subject_kind": payload.get("subject_kind"),
        "subject_id": payload.get("subject_id"),
        "inscripcio_id": payload.get("inscripcio_id"),
    }
    exercici_raw = payload.get("exercici")
    inputs_patch = payload.get("inputs_patch", {})
    competicio = scope.competicio
    comp_aparell = scope.comp_aparell
    exercici = clamp_exercici_for_scope(scope, exercici_raw)

    if not subject_payload.get("subject_id") and not subject_payload.get("inscripcio_id"):
        return JsonResponse({"ok": False, "error": "Falta subject_id/inscripcio_id"}, status=400)
    if not isinstance(inputs_patch, dict):
        return JsonResponse({"ok": False, "error": "inputs_patch ha de ser objecte JSON"}, status=400)

    permissions = _normalize_permissions(scope.permissions)

    team_ids = None
    if is_team_context_app(comp_aparell):
        team_ids = [
            int(item["subject_id"])
            for item in build_team_subjects_for_comp_aparell(competicio, comp_aparell)[0]
            if int(comp_aparell.id) in (item.get("allowed_app_ids") or [])
        ]
    subject, error_response = resolve_scoring_subject(
        competicio,
        comp_aparell,
        subject_payload,
        eligible_team_ids=team_ids,
    )
    if error_response is not None:
        return error_response
    scope_subject_error = ensure_subject_scoreable_for_scope(scope, subject)
    if scope_subject_error is not None:
        return scope_subject_error

    _schema_obj, base_schema = resolve_scoring_schema_for_comp_aparell(comp_aparell)
    team_subject = subject.get("team_subject") if str(subject.get("subject_kind")) == "team_unit" else None
    team_member_count = len(getattr(team_subject, "member_ids", []) or []) if team_subject is not None else 0
    resolved_permissions = _resolve_permissions_for_subject(permissions, comp_aparell, subject)
    allowed_codes = {str(p.get("runtime_field_code") or p.get("field_code") or "") for p in resolved_permissions}
    allowed_codes.discard("")
    allowed_input_codes = _allowed_input_codes_from_permissions(resolved_permissions)
    allowed_patch_codes = set(allowed_codes)
    allowed_patch_codes.update({f"__crash__{code}" for code in allowed_codes})
    patch_codes = set(inputs_patch.keys())
    if not patch_codes.issubset(allowed_patch_codes):
        return JsonResponse({"ok": False, "error": "Intentes editar un camp no autoritzat per aquest QR"}, status=403)
    schema = runtime_schema_for_comp_aparell(base_schema, comp_aparell, member_count=team_member_count)

    entry, _ = get_or_create_subject_entry_locked(
        competicio=competicio,
        comp_aparell=comp_aparell,
        exercici=exercici,
        subject=subject,
        fase=scope.phase,
        defaults={"inputs": {}, "outputs": {}, "total": 0},
    )

    sanitized = _sanitize_patch_by_permissions(schema, resolved_permissions, inputs_patch)
    current_inputs = entry.inputs if isinstance(entry.inputs, dict) else {}
    if team_subject is not None:
        current_inputs = logical_team_inputs_to_runtime_inputs(current_inputs, team_subject, base_schema)

    # MERGE per no trepitjar altres camps/jutges
    merged_inputs = _apply_sanitized_patch(current_inputs, sanitized, schema)

    # Filtrat d'inputs segons schema.fields (mateixa idea que tens a scoring_save)
    allowed = set()
    for f in (schema.get("fields") or []):
        if isinstance(f, dict) and f.get("code"):
            allowed.add(f["code"])
            allowed.add(f"__crash__{f['code']}")
            if is_strict_presence_field(f):
                allowed.add(presence_key(str(f["code"])))

    clean_inputs = {k: v for k, v in merged_inputs.items() if k in allowed}
    runtime_inputs = build_runtime_inputs_from_canonical(clean_inputs, schema)

    try:
        engine = ScoringEngine(schema)
        result = engine.compute(runtime_inputs)
    except ScoringError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Error inesperat calculant puntuació"}, status=500)

    entry.inputs = (
        runtime_inputs_to_logical_team_inputs(
            persist_inputs_after_compute(clean_inputs, result.inputs, schema),
            team_subject,
            base_schema,
        )
        if team_subject is not None
        else persist_inputs_after_compute(clean_inputs, result.inputs, schema)
    )
    entry.outputs = result.outputs
    entry.total = result.total
    entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])

    return JsonResponse({
        "ok": True,
        **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
        "inputs": _filter_inputs_for_allowed_codes(
            (
                persist_inputs_after_compute(clean_inputs, result.inputs, schema)
                if team_subject is not None
                else entry.inputs
            ),
            allowed_input_codes,
        ),
        "outputs": entry.outputs or {},
        "total": float(entry.total),
        "assignment_id": scope.assignment_id,
        "fase_id": entry.fase_id,
        "updated_at": entry.updated_at.isoformat(),
    })

