import copy

from django.http import FileResponse, Http404
from django.urls import reverse

from ...models import InscripcioMedia
from ...models.scoring import TeamScoreEntryVideo
from ...services.scoring.team_scoring import is_team_context_app, runtime_schema_for_comp_aparell
from ...services.scoring.team_subject_contract import build_team_subject_registry
from ...services.scoring.update_payloads import build_score_update_payload, filter_inputs_for_allowed_codes


def _protected_file_response(file_field, *, original_filename: str = "", mime_type: str = ""):
    if not file_field or not getattr(file_field, "name", ""):
        raise Http404("Fitxer no disponible")
    try:
        file_handle = file_field.open("rb")
    except Exception as exc:
        raise Http404("Fitxer no disponible") from exc
    response = FileResponse(
        file_handle,
        as_attachment=False,
        filename=(original_filename or "").strip() or None,
    )
    if mime_type:
        response["Content-Type"] = mime_type
    return response


def _allowed_input_codes_for_schema(schema: dict, comp_aparell=None) -> set:
    if is_team_context_app(comp_aparell):
        allowed = set()
        for field in (schema.get("fields") or []):
            if isinstance(field, dict) and field.get("code"):
                allowed.add(field["code"])
                allowed.add(f"__crash__{field['code']}")
        return allowed
    runtime_schema = runtime_schema_for_comp_aparell(schema or {}, comp_aparell)
    allowed = set()
    for field in (runtime_schema.get("fields") or []):
        if isinstance(field, dict) and field.get("code"):
            allowed.add(field["code"])
            allowed.add(f"__crash__{field['code']}")
    return allowed


def _logical_team_input_codes(schema: dict) -> set:
    allowed = set()
    for field in (schema.get("fields") or []):
        if isinstance(field, dict) and field.get("code"):
            code = str(field["code"])
            allowed.add(code)
            allowed.add(f"__crash__{code}")
    return allowed


def _split_inputs_by_allowed_codes(inputs: dict, allowed_codes: set) -> tuple[dict, dict]:
    known = {}
    orphans = {}
    if not isinstance(inputs, dict):
        return known, orphans
    for key, value in inputs.items():
        target = known if key in allowed_codes else orphans
        target[key] = copy.deepcopy(value)
    return known, orphans


def _merge_inputs_preserving_orphans(known_inputs: dict, orphan_inputs: dict) -> dict:
    merged = {}
    if isinstance(orphan_inputs, dict):
        for key, value in orphan_inputs.items():
            merged[key] = copy.deepcopy(value)
    if isinstance(known_inputs, dict):
        for key, value in known_inputs.items():
            merged[key] = copy.deepcopy(value)
    return merged


def _team_field_scope_map(schema: dict) -> dict:
    scope_map = {}
    for field in (schema.get("fields") or []):
        if not isinstance(field, dict) or not field.get("code"):
            continue
        code = str(field["code"])
        scope = str(field.get("scope") or "member").strip().lower() or "member"
        scope_map[code] = scope
        scope_map[f"__crash__{code}"] = scope
    return scope_map


def _merge_team_logical_patch(current_inputs: dict, patch: dict, schema: dict) -> dict:
    merged = copy.deepcopy(current_inputs if isinstance(current_inputs, dict) else {})
    scope_map = _team_field_scope_map(schema)
    for key, value in (patch.items() if isinstance(patch, dict) else []):
        if key not in scope_map:
            continue
        if scope_map.get(key) == "member":
            existing = merged.get(key) if isinstance(merged.get(key), dict) else {}
            if isinstance(value, dict):
                next_map = copy.deepcopy(existing)
                for member_id, member_value in value.items():
                    next_map[str(member_id)] = copy.deepcopy(member_value)
                merged[key] = next_map
            else:
                merged[key] = copy.deepcopy(value)
            continue
        merged[key] = copy.deepcopy(value)
    return merged


def _sanitize_inputs_for_client(inputs: dict, allowed_codes: set) -> dict:
    return filter_inputs_for_allowed_codes(inputs, allowed_codes)


def _serialize_individual_scoring_update(entry, allowed_inputs: set) -> dict:
    return build_score_update_payload(
        subject_kind="inscripcio",
        subject_id=entry.inscripcio_id,
        exercici=entry.exercici,
        comp_aparell_id=entry.comp_aparell_id,
        inputs=_sanitize_inputs_for_client(entry.inputs or {}, allowed_inputs),
        outputs=entry.outputs or {},
        total=entry.total,
        updated_at=entry.updated_at,
    )


def _serialize_team_scoring_update(entry, allowed_inputs: set, subject_meta: dict | None) -> dict:
    return build_score_update_payload(
        subject_kind="team_unit",
        subject_id=entry.team_subject_id,
        exercici=entry.exercici,
        comp_aparell_id=entry.comp_aparell_id,
        inputs=_sanitize_inputs_for_client(entry.inputs or {}, allowed_inputs),
        outputs=entry.outputs or {},
        total=entry.total,
        updated_at=entry.updated_at,
        subject_meta=subject_meta,
    )


def _serialize_inscripcio_media_for_playback(item: InscripcioMedia) -> dict:
    return {
        "id": item.id,
        "tipus": item.tipus,
        "is_primary": bool(item.is_primary),
        "original_filename": item.original_filename or "",
        "mime_type": item.mime_type or "",
        "url": reverse("scoring_media_file", kwargs={"pk": item.competicio_id, "media_id": item.id}),
    }


def _split_media_for_playback(items: list) -> dict:
    grouped = {
        InscripcioMedia.Tipus.AUDIO: [],
        InscripcioMedia.Tipus.VIDEO: [],
        InscripcioMedia.Tipus.IMAGE: [],
        InscripcioMedia.Tipus.OTHER: [],
    }
    for item in items:
        tipus = str(item.get("tipus") or "")
        if tipus not in grouped:
            tipus = InscripcioMedia.Tipus.OTHER
        grouped[tipus].append(item)

    def _pick_primary_and_others(arr):
        primary = next((x for x in arr if x.get("is_primary")), None)
        if primary is None:
            return None, arr
        others = [x for x in arr if x.get("id") != primary.get("id")]
        return primary, others

    audio_primary, audio_others = _pick_primary_and_others(grouped[InscripcioMedia.Tipus.AUDIO])
    video_primary, video_others = _pick_primary_and_others(grouped[InscripcioMedia.Tipus.VIDEO])
    image_primary, image_others = _pick_primary_and_others(grouped[InscripcioMedia.Tipus.IMAGE])

    return {
        "audio_primary": audio_primary,
        "audio_others": audio_others,
        "video_primary": video_primary,
        "video_others": video_others,
        "image_primary": image_primary,
        "image_others": image_others,
        "other_files": grouped[InscripcioMedia.Tipus.OTHER],
    }


def _serialize_judge_video_for_playback(video_obj, competicio_id=None):
    if not video_obj or not video_obj.video_file or not competicio_id:
        return None
    video_kind = "team" if isinstance(video_obj, TeamScoreEntryVideo) else "individual"
    return {
        "id": video_obj.id,
        "original_filename": video_obj.original_filename or "",
        "mime_type": video_obj.mime_type or "",
        "url": reverse(
            "scoring_judge_video_file",
            kwargs={"pk": competicio_id, "video_kind": video_kind, "video_id": video_obj.id},
        ),
        "status": video_obj.status,
    }


def _parse_positive_int(raw_value):
    try:
        value = int(raw_value)
    except Exception:
        return None
    return value if value > 0 else None


def _eligible_team_subject_map(competicio, comp_aparell):
    if not is_team_context_app(comp_aparell):
        return {}
    return build_team_subject_registry(competicio, comp_aparell)["eligible_by_id"]


def _logical_schema_for_notes_ui(schema: dict, comp_aparell) -> dict:
    base = copy.deepcopy(schema or {})
    meta = base.get("meta") if isinstance(base.get("meta"), dict) else {}
    meta["subject_mode"] = "team" if is_team_context_app(comp_aparell) else "individual"
    base["meta"] = meta

    fields = base.get("fields") if isinstance(base.get("fields"), list) else []
    for field in fields:
        if isinstance(field, dict):
            field["render_scope"] = str(field.get("scope") or "member").strip().lower() or "member"

    computed = base.get("computed") if isinstance(base.get("computed"), list) else []
    if not is_team_context_app(comp_aparell):
        for comp in computed:
            if isinstance(comp, dict):
                comp["render_scope"] = "shared"
        return base

    runtime_probe = runtime_schema_for_comp_aparell(schema or {}, comp_aparell, member_count=1)
    member_computed_codes = {
        str(item.get("base_code") or "")
        for item in (runtime_probe.get("computed") or [])
        if isinstance(item, dict) and item.get("base_code")
    }
    for comp in computed:
        if not isinstance(comp, dict) or not comp.get("code"):
            continue
        comp["render_scope"] = "member" if str(comp.get("code")) in member_computed_codes else "shared"
    return base


def _bucket_app_id(bucket_key):
    key = str(bucket_key or "").strip()
    if not key.startswith("app-"):
        return None
    parts = key.split("-")
    if len(parts) < 2:
        return None
    try:
        value = int(parts[1])
    except Exception:
        return None
    return value if value > 0 else None
