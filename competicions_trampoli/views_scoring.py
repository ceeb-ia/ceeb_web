# views_scoring.py
import copy
import json
import logging
from collections import defaultdict
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView, UpdateView
from django.utils import timezone
from .models import Competicio, Inscripcio, InscripcioMedia
from .models_trampoli import Aparell, CompeticioAparell, InscripcioAparellExclusio
from .models_rotacions import RotacioAssignacio, RotacioAssignacioSerieEquip, RotacioFranja
from .models_scoring import ScoringSchema, ScoreEntry, ScoreEntryVideo, TeamScoreEntry, TeamScoreEntryVideo
from .forms import ScoringSchemaForm
from .scoring_engine import ScoringEngine, ScoringError
from .services.scoring_subjects import (
    get_or_create_subject_entry_locked,
    resolve_scoring_subject,
    score_store_key,
    serialize_subject_payload,
    subject_entry_model,
)
from .services.team_scoring import (
    MEMBER_CODE_SUFFIX_RE,
    build_team_subjects_for_comp_aparell,
    eligible_team_ids_for_comp_aparell,
    is_team_context_app,
    logical_team_inputs_to_runtime_inputs,
    runtime_schema_for_comp_aparell,
    runtime_inputs_to_logical_team_inputs,
)
from .services.competition_groups import (
    get_group_maps,
    get_inscripcio_competition_order,
    get_inscripcio_group_display_num,
    group_label,
    show_out_of_program_in_competition_views,
)
from .services.rotacions_ordering import (
    ORDER_MODE_MAINTAIN,
    assignacio_series,
    assignacio_grups,
    build_group_rotation_step_map,
    build_series_rotation_step_map,
    effective_rotate_steps,
    get_rotacions_order_modes,
    order_pairs_for_mode,
    unique_ordered,
)
from .services.team_subject_contract import (
    build_team_subject_registry,
    filter_team_subject_ids_for_serie,
    runtime_schema_for_team_subjects,
)
from .services.team_series import (
    get_series_maps,
    team_subject_bucket_key,
    team_subject_bucket_label,
)
from .services.incremental_feeds import FeedCursor, parse_feed_cursor
from .services.update_payloads import (
    build_score_update_payload,
    filter_inputs_for_allowed_codes,
)


logger = logging.getLogger(__name__)
SCORING_UPDATES_LIMIT = 500
SCORING_FEED_SOURCE_SCORE = "score"
SCORING_FEED_SOURCE_TEAM = "team"


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


def _combined_source_rank(source: str) -> int:
    return 0 if source == SCORING_FEED_SOURCE_SCORE else 1


def _parse_combined_after_id(raw_after_id: str) -> tuple[str, int | None]:
    text = str(raw_after_id or "").strip()
    if ":" not in text:
        return "", None
    source, raw_id = text.split(":", 1)
    try:
        parsed_id = int(raw_id)
    except Exception:
        return "", None
    return str(source or "").strip(), parsed_id


def _apply_combined_cursor(qs, cursor: FeedCursor, *, source: str):
    if cursor.dt is None:
        return qs

    after_source, after_id = _parse_combined_after_id(cursor.after_id)
    if after_source == source and after_id is not None:
        return qs.filter(
            Q(updated_at__gt=cursor.dt)
            | Q(updated_at=cursor.dt, id__gt=after_id)
        )
    if after_source == SCORING_FEED_SOURCE_SCORE and source == SCORING_FEED_SOURCE_TEAM:
        return qs.filter(
            Q(updated_at__gt=cursor.dt)
            | Q(updated_at=cursor.dt)
        )
    return qs.filter(updated_at__gt=cursor.dt)


def _combined_feed_meta(rows: list[dict], *, limit: int, cursor: FeedCursor) -> dict:
    page = rows[:limit]
    has_more = len(rows) > limit
    if page:
        last_row = page[-1]
        next_since = last_row["sort_updated_at"].isoformat() if last_row.get("sort_updated_at") else None
        next_after_id = f"{last_row.get('sort_source')}:{last_row.get('sort_id')}"
    else:
        next_since = cursor.dt.isoformat() if cursor.dt else None
        next_after_id = cursor.after_id
    return {
        "page": page,
        "has_more": has_more,
        "next_since": next_since,
        "next_after_id": str(next_after_id or ""),
    }


def _allowed_input_codes_for_schema(schema: dict, comp_aparell=None) -> set:
    if is_team_context_app(comp_aparell):
        allowed = set()
        for f in (schema.get("fields") or []):
            if isinstance(f, dict) and f.get("code"):
                allowed.add(f["code"])
                allowed.add(f"__crash__{f['code']}")
        return allowed
    runtime_schema = runtime_schema_for_comp_aparell(schema or {}, comp_aparell)
    allowed = set()
    for f in (runtime_schema.get("fields") or []):
        if isinstance(f, dict) and f.get("code"):
            allowed.add(f["code"])
            allowed.add(f"__crash__{f['code']}")
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


def _collect_team_scoring_updates(competicio, cursor: FeedCursor, *, comp_aparell_id=None, exercici=None, serie_id=None) -> list[dict]:
    team_apps_qs = (
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("aparell")
    )
    if comp_aparell_id:
        team_apps_qs = team_apps_qs.filter(pk=comp_aparell_id)
    team_apps = [app for app in team_apps_qs if is_team_context_app(app)]
    if not team_apps:
        return []

    team_app_ids = [int(app.id) for app in team_apps]
    allowed_inputs_by_app = {}
    subject_meta_by_app = {}
    allowed_team_ids_by_app = {}
    for app in team_apps:
        registry = build_team_subject_registry(competicio, app)
        subject_meta_by_app[int(app.id)] = registry["all_by_id"]
        if comp_aparell_id and str(app.id) == str(comp_aparell_id):
            allowed_team_ids_by_app[int(app.id)] = set(
                filter_team_subject_ids_for_serie(registry["all_by_id"], serie_id)
            )
        else:
            allowed_team_ids_by_app[int(app.id)] = set(registry["all_by_id"].keys())
        ss, _ = ScoringSchema.objects.get_or_create(aparell=app.aparell, defaults={"schema": {}})
        allowed_inputs_by_app[int(app.id)] = _logical_team_input_codes(ss.schema or {})

    qs = (
        TeamScoreEntry.objects
        .filter(
            competicio=competicio,
            comp_aparell_id__in=team_app_ids,
        )
        .select_related("team_subject")
        .order_by("updated_at", "id")
    )
    qs = _apply_combined_cursor(qs, cursor, source=SCORING_FEED_SOURCE_TEAM)
    if exercici:
        try:
            qs = qs.filter(exercici=int(exercici))
        except Exception:
            pass

    updates = []
    for entry in qs[: SCORING_UPDATES_LIMIT + 1]:
        app_id = int(entry.comp_aparell_id)
        if int(entry.team_subject_id) not in allowed_team_ids_by_app.get(app_id, set()):
            continue
        updates.append(
            {
                "payload": _serialize_team_scoring_update(
                    entry,
                    allowed_inputs=allowed_inputs_by_app.get(app_id, set()),
                    subject_meta=(subject_meta_by_app.get(app_id, {}) or {}).get(int(entry.team_subject_id), {}),
                ),
                "sort_updated_at": entry.updated_at,
                "sort_id": int(entry.id),
                "sort_source": SCORING_FEED_SOURCE_TEAM,
            }
        )
    return updates


def _recalculate_scores_for_comp_aparell(
    competicio,
    comp_aparell,
    chunk_size: int = 200,
    *,
    schema_override: dict | None = None,
    apply_changes: bool = True,
) -> dict:
    """
    Recalculate all ScoreEntry rows for one competition + comp_aparell using the current
    global schema attached to the Aparell.
    """
    entry_model = subject_entry_model(comp_aparell)
    qs = (
        entry_model.objects
        .filter(competicio=competicio, comp_aparell=comp_aparell)
        .order_by("id")
    )
    if is_team_context_app(comp_aparell):
        qs = qs.select_related("team_subject")
    summary = {
        "total": qs.count(),
        "updated": 0,
        "failed": 0,
        "errors_preview": [],
    }

    ss, _ = ScoringSchema.objects.get_or_create(aparell=comp_aparell.aparell, defaults={"schema": {}})
    base_schema = copy.deepcopy(schema_override) if isinstance(schema_override, dict) else (ss.schema or {})
    is_team_app = is_team_context_app(comp_aparell)
    pending_updates = []
    if not is_team_app:
        try:
            engine = ScoringEngine(runtime_schema_for_comp_aparell(base_schema, comp_aparell))
        except Exception as exc:
            summary["engine_error"] = str(exc)
            logger.exception(
                "Schema recalc init failed for competicio=%s comp_aparell=%s: %s",
                getattr(competicio, "id", None),
                getattr(comp_aparell, "id", None),
                exc,
            )
            return summary
        allowed_inputs = _allowed_input_codes_for_schema(base_schema, comp_aparell)
    else:
        engine = None
        allowed_inputs = _logical_team_input_codes(base_schema)

    for entry in qs.iterator(chunk_size=chunk_size):
        try:
            raw_inputs = entry.inputs if isinstance(entry.inputs, dict) else {}
            known_inputs, orphan_inputs = _split_inputs_by_allowed_codes(raw_inputs, allowed_inputs)
            if is_team_app:
                team_subject = getattr(entry, "team_subject", None)
                member_count = len(getattr(team_subject, "member_ids", []) or []) if team_subject is not None else 0
                runtime_schema = runtime_schema_for_comp_aparell(base_schema, comp_aparell, member_count=member_count)
                runtime_inputs = logical_team_inputs_to_runtime_inputs(known_inputs, team_subject, base_schema)
                result = ScoringEngine(runtime_schema).compute(runtime_inputs)
                logical_inputs = runtime_inputs_to_logical_team_inputs(result.inputs, team_subject, base_schema)
                entry_inputs = _merge_inputs_preserving_orphans(logical_inputs, orphan_inputs)
            else:
                result = engine.compute(known_inputs)
                entry_inputs = _merge_inputs_preserving_orphans(result.inputs, orphan_inputs)
            pending_updates.append(
                {
                    "entry": entry,
                    "inputs": entry_inputs,
                    "outputs": result.outputs,
                    "total": result.total,
                }
            )
            summary["updated"] += 1
        except ScoringError as exc:
            summary["failed"] += 1
            if len(summary["errors_preview"]) < 5:
                summary["errors_preview"].append(f"{entry.id}: {exc}")
            logger.warning(
                "Schema recalc failed for ScoreEntry id=%s (domain): %s",
                entry.id,
                exc,
            )
        except Exception as exc:
            summary["failed"] += 1
            if len(summary["errors_preview"]) < 5:
                summary["errors_preview"].append(f"{entry.id}: error inesperat")
            logger.exception(
                "Schema recalc failed for ScoreEntry id=%s (unexpected): %s",
                entry.id,
                exc,
            )

    if apply_changes and summary["failed"] == 0:
        with transaction.atomic():
            for item in pending_updates:
                entry = item["entry"]
                entry.inputs = item["inputs"]
                entry.outputs = item["outputs"]
                entry.total = item["total"]
                entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])

    summary["planned_updates"] = pending_updates

    logger.info(
        "Schema recalc summary competicio=%s comp_aparell=%s total=%s updated=%s failed=%s",
        getattr(competicio, "id", None),
        getattr(comp_aparell, "id", None),
        summary["total"],
        summary["updated"],
        summary["failed"],
    )
    return summary


def _safe_file_url(file_field):
    if not file_field:
        return ""
    try:
        return file_field.url
    except Exception:
        return ""


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
        n = int(raw_value)
    except Exception:
        return None
    return n if n > 0 else None


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


class ScoringNotesHome(TemplateView):
    """
    Pantalla de notes dinàmica basada en schema.
    Convivència amb la pantalla trampolí actual: és una home nova.
    """
    template_name = "competicio/scoring_notes_home.html"

    def get(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        competicio = self.competicio
        franges = list(RotacioFranja.objects.filter(competicio=competicio).order_by("ordre", "id"))
        franja_modes = get_rotacions_order_modes(competicio)
        group_maps = get_group_maps(competicio)
        groups_by_id = group_maps["by_id"]
        group_labels_map = {"0": "Sense grup"}
        for group in group_maps["groups"]:
            group_labels_map[str(group.id)] = group_label(group)
        team_group_rows_by_key = {}
        team_programmed_group_keys = []
        team_out_of_program_group_keys = []

        franja_selected_id = None
        fr_raw = self.request.GET.get("franja")
        if fr_raw not in (None, ""):
            try:
                fr_int = int(fr_raw)
            except Exception:
                fr_int = None
            if fr_int and any(f.id == fr_int for f in franges):
                franja_selected_id = fr_int

        ins = (
            Inscripcio.objects
            .filter(competicio=competicio)
            .select_related("grup_competicio")
            .order_by("grup_competicio__display_num", "ordre_competicio", "ordre_sortida", "id")
        )

        # Agrupació (igual que ja fas servir)
        from collections import defaultdict
        grouped = defaultdict(list)
        for r in ins:
            grouped[r.grup_competicio_id if r.grup_competicio_id is not None else 0].append(r)

        group_first_slot = {}
        assigns_for_order = (
            RotacioAssignacio.objects
            .filter(competicio=competicio)
            .select_related("franja")
            .prefetch_related("grup_links__grup")
            .order_by("franja__ordre", "franja_id", "estacio__ordre", "id")
        )
        for a in assigns_for_order:
            franja = getattr(a, "franja", None)
            franja_order = getattr(franja, "ordre", 10**9)
            fid = getattr(a, "franja_id", None) or 0
            for g in assignacio_grups(a):
                if g not in group_first_slot:
                    group_first_slot[g] = (franja_order, fid)

        numeric_group_keys = sorted([k for k in grouped.keys() if k != 0])
        competing_group_keys = [g for g in numeric_group_keys if g in group_first_slot]
        remaining_group_keys = [g for g in numeric_group_keys if g not in group_first_slot]
        competing_group_keys.sort(key=lambda g: (group_first_slot[g][0], group_first_slot[g][1], g))

        program_group_keys = list(competing_group_keys)
        out_of_program_group_keys = [g for g in remaining_group_keys if g != 0]
        always_visible_group_keys = list(program_group_keys)
        if 0 in grouped:
            always_visible_group_keys.append(0)

        programmed_groups = [(g, grouped[g]) for g in always_visible_group_keys]
        out_of_program_groups = [(g, grouped[g]) for g in out_of_program_group_keys]
        show_out_of_program_groups = show_out_of_program_in_competition_views(competicio)
        visible_groups = programmed_groups + (out_of_program_groups if show_out_of_program_groups else [])
        visible_individual_groups = list(visible_groups)


        # Aparells de la competició
        aparells_cfg = (
            CompeticioAparell.objects
            .filter(competicio=competicio, actiu=True)
            .select_related("aparell")
            .order_by("ordre", "id")
        )
        aparells_cfg = list(aparells_cfg)
        apparells_cfg_by_id = {int(ca.id): ca for ca in aparells_cfg}
        active_app_ids = [ca.id for ca in aparells_cfg]
        team_app_ids = {ca.id for ca in aparells_cfg if is_team_context_app(ca)}
        excluded_by_ins = defaultdict(set)
        if active_app_ids:
            excl_pairs = (
                InscripcioAparellExclusio.objects
                .filter(
                    inscripcio__in=ins,
                    comp_aparell_id__in=active_app_ids,
                )
                .values_list("inscripcio_id", "comp_aparell_id")
            )
            for ins_id, app_id in excl_pairs:
                excluded_by_ins[ins_id].add(app_id)
        
        def clamp_ex(n):
            try:
                n = int(n or 1)
            except Exception:
                n = 1
            return max(1, min(4, n))


        # Exercicis
        exercicis_by_aparell = {}
        max_ex = 1
        for ca in aparells_cfg:
            n = clamp_ex(getattr(ca, "nombre_exercicis", 1))
            exercicis_by_aparell[str(ca.id)] = list(range(1, n + 1))
            max_ex = max(max_ex, n)

        exercicis = list(range(1, max_ex + 1))
        
        # ─────────────────────────────
        # SCHEMAS (dict simple)
        # ─────────────────────────────
        schemas = {}
        logical_schemas = {}
        team_registry_by_app_id = {}
        for ca in aparells_cfg:
            ss, _ = ScoringSchema.objects.get_or_create(
                aparell=ca.aparell,
                defaults={"schema": {}},
            )
            logical_schemas[str(ca.id)] = _logical_schema_for_notes_ui(ss.schema or {}, ca)
            if is_team_context_app(ca):
                registry = build_team_subject_registry(competicio, ca)
                team_registry_by_app_id[int(ca.id)] = registry
                schemas[str(ca.id)] = runtime_schema_for_team_subjects(ss.schema or {}, ca, registry["subjects"])
            else:
                schemas[str(ca.id)] = runtime_schema_for_comp_aparell(ss.schema or {}, ca)

        # ─────────────────────────────
        # SCORES (dict clau -> dades)
        # ─────────────────────────────
        scores_qs = ScoreEntry.objects.filter(
            competicio=competicio,
            inscripcio__in=ins,
            exercici__in=exercicis,
            comp_aparell__in=[ca for ca in aparells_cfg if not is_team_context_app(ca)],
        )
        scores_qs = scores_qs.annotate(
            _excluded=Exists(
                InscripcioAparellExclusio.objects.filter(
                    inscripcio_id=OuterRef("inscripcio_id"),
                    comp_aparell_id=OuterRef("comp_aparell_id"),
                )
            )
        ).filter(_excluded=False)

        scores = {}
        for s in scores_qs:
            ca = apparells_cfg_by_id.get(int(s.comp_aparell_id))
            allowed_inputs = _allowed_input_codes_for_schema(logical_schemas.get(str(s.comp_aparell_id), {}), ca)
            key = score_store_key("inscripcio", s.inscripcio_id, s.exercici, s.comp_aparell_id)
            scores[key] = {
                "inputs": _sanitize_inputs_for_client(s.inputs or {}, allowed_inputs),
                "outputs": s.outputs or {},
                "total": float(s.total),
            }

        team_subjects = []
        team_issues_by_app = {}
        eligible_team_ids_by_app = {}
        for ca in aparells_cfg:
            if not is_team_context_app(ca):
                continue
            registry = team_registry_by_app_id.get(int(ca.id)) or build_team_subject_registry(competicio, ca)
            app_subjects = list(registry["subjects"])
            issues = list(registry["issues"])
            rows_by_bucket = defaultdict(list)
            programmed_series_ids = set(
                RotacioAssignacioSerieEquip.objects
                .filter(assignacio__competicio=competicio, serie__comp_aparell=ca)
                .values_list("serie_id", flat=True)
                .distinct()
            )
            app_name = str(getattr(ca.aparell, "nom", "") or "").strip()
            for raw_subject in app_subjects:
                subject = dict(raw_subject)
                bucket_key = team_subject_bucket_key(subject, ca.id)
                subject["group"] = bucket_key
                subject["group_label"] = team_subject_bucket_label(subject, app_name)
                rows_by_bucket[bucket_key].append(subject)
                if subject.get("serie_id"):
                    if int(subject["serie_id"]) in programmed_series_ids:
                        if bucket_key not in team_programmed_group_keys:
                            team_programmed_group_keys.append(bucket_key)
                    elif bucket_key not in team_out_of_program_group_keys:
                        team_out_of_program_group_keys.append(bucket_key)
                elif bucket_key not in team_out_of_program_group_keys:
                    team_out_of_program_group_keys.append(bucket_key)
                group_labels_map[str(bucket_key)] = subject["group_label"]
                team_subjects.append(subject)
            for bucket_key, rows in rows_by_bucket.items():
                team_group_rows_by_key[str(bucket_key)] = rows
            team_issues_by_app[str(ca.id)] = issues
            eligible_team_ids_by_app[int(ca.id)] = [
                int(subject["subject_id"])
                for subject in app_subjects
                if int(ca.id) in (subject.get("allowed_app_ids") or [])
            ]
        team_programmed_groups = [
            (group_key, team_group_rows_by_key[group_key])
            for group_key in team_programmed_group_keys
            if group_key in team_group_rows_by_key
        ]
        team_out_of_program_groups = [
            (group_key, team_group_rows_by_key[group_key])
            for group_key in team_out_of_program_group_keys
            if group_key in team_group_rows_by_key and group_key not in team_programmed_group_keys
        ]
        programmed_groups.extend(team_programmed_groups)
        out_of_program_groups.extend(team_out_of_program_groups)
        visible_groups = programmed_groups + (out_of_program_groups if show_out_of_program_groups else [])

        team_score_app_ids = [app_id for app_id, ids in eligible_team_ids_by_app.items() if ids]
        team_subject_ids = [team_id for ids in eligible_team_ids_by_app.values() for team_id in ids]
        if team_score_app_ids and team_subject_ids:
            team_scores_qs = TeamScoreEntry.objects.filter(
                competicio=competicio,
                comp_aparell_id__in=team_score_app_ids,
                team_subject_id__in=team_subject_ids,
                exercici__in=exercicis,
            ).select_related("team_subject")
            for s in team_scores_qs:
                allowed_inputs = _logical_team_input_codes(logical_schemas.get(str(s.comp_aparell_id), {}))
                key = score_store_key("team_unit", s.team_subject_id, s.exercici, s.comp_aparell_id)
                scores[key] = {
                    "inputs": _sanitize_inputs_for_client(s.inputs or {}, allowed_inputs),
                    "outputs": s.outputs or {},
                    "total": float(s.total),
                }

        # ─────────────────────────────
        # INSCRIPCIONS (llista plana per JS)
        # ─────────────────────────────
        # inscripcions: llista plana per al JS
        inscripcions = []
        for g, rows in visible_individual_groups:
            for r in rows:
                meta_parts = []
                if getattr(r, "entitat", None):
                    meta_parts.append(str(r.entitat))
                if getattr(r, "categoria", None):
                    meta_parts.append(str(r.categoria))
                if getattr(r, "subcategoria", None):
                    meta_parts.append(str(r.subcategoria))
                allowed_app_ids = [
                    app_id for app_id in active_app_ids
                    if app_id not in excluded_by_ins.get(r.id, set()) and app_id not in team_app_ids
                ]

                inscripcions.append({
                    "id": r.id,
                    "subject_id": r.id,
                    "subject_kind": "inscripcio",
                    "order": get_inscripcio_competition_order(r) or "",
                    "name": getattr(r, "nom_i_cognoms", "") or "",
                    "group": getattr(r, "grup_competicio_id", 0) or 0,
                    "group_display_num": get_inscripcio_group_display_num(r) or "",
                    "allowed_app_ids": allowed_app_ids,
                    "meta": " · ".join(meta_parts) if meta_parts else "",
                })
        inscripcions.extend(team_subjects)


        # ─────────────────────────────
        # CONTEXT FINAL
        # ─────────────────────────────
        inscripcio_ids = [int(x["subject_id"]) for x in inscripcions if x.get("subject_kind") == "inscripcio"]
        media_counts_by_inscripcio = {
            str(ins_id): {"audio": 0, "video": 0}
            for ins_id in inscripcio_ids
        }
        if inscripcio_ids:
            media_counts_rows = (
                InscripcioMedia.objects
                .filter(
                    competicio=competicio,
                    inscripcio_id__in=inscripcio_ids,
                    tipus__in=[InscripcioMedia.Tipus.AUDIO, InscripcioMedia.Tipus.VIDEO],
                )
                .values("inscripcio_id", "tipus")
                .annotate(total=Count("id"))
            )
            for row in media_counts_rows:
                ins_id = str(row.get("inscripcio_id") or "")
                bucket = media_counts_by_inscripcio.setdefault(ins_id, {"audio": 0, "video": 0})
                tipus = str(row.get("tipus") or "")
                if tipus in ("audio", "video"):
                    bucket[tipus] = int(row.get("total") or 0)

        judge_video_presence_by_key = {}
        if inscripcio_ids and active_app_ids and exercicis:
            judge_video_rows = (
                ScoreEntryVideo.objects
                .filter(
                    score_entry__competicio=competicio,
                    score_entry__inscripcio_id__in=inscripcio_ids,
                    score_entry__comp_aparell_id__in=active_app_ids,
                    score_entry__exercici__in=exercicis,
                )
                .exclude(video_file="")
                .values_list(
                    "score_entry__inscripcio_id",
                    "score_entry__exercici",
                    "score_entry__comp_aparell_id",
                )
            )
            for ins_id, exercici_id, app_id in judge_video_rows:
                judge_video_presence_by_key[score_store_key("inscripcio", ins_id, exercici_id, app_id)] = 1
        if team_subject_ids and team_score_app_ids and exercicis:
            team_judge_video_rows = (
                TeamScoreEntryVideo.objects
                .filter(
                    team_score_entry__competicio=competicio,
                    team_score_entry__team_subject_id__in=team_subject_ids,
                    team_score_entry__comp_aparell_id__in=team_score_app_ids,
                    team_score_entry__exercici__in=exercicis,
                )
                .exclude(video_file="")
                .values_list(
                    "team_score_entry__team_subject_id",
                    "team_score_entry__exercici",
                    "team_score_entry__comp_aparell_id",
                )
            )
            for team_subject_id, exercici_id, app_id in team_judge_video_rows:
                judge_video_presence_by_key[score_store_key("team_unit", team_subject_id, exercici_id, app_id)] = 1

        rotation_rank_map = {}
        rotation_groups_by_app = {}
        if franja_selected_id:
            all_assigns = list(
                RotacioAssignacio.objects
                .filter(
                    competicio=competicio,
                    estacio__tipus="aparell",
                    estacio__comp_aparell__isnull=False,
                )
                .select_related("franja", "estacio")
                .prefetch_related("grup_links__grup", "serie_links__serie")
                .order_by("franja__ordre", "franja_id", "estacio__ordre", "id")
            )
            rotation_group_step_map = build_group_rotation_step_map(all_assigns, franja_modes)
            rotation_series_step_map = build_series_rotation_step_map(all_assigns, franja_modes)
            assigns = [a for a in all_assigns if a.franja_id == franja_selected_id]
            app_groups_map = {}
            for a in assigns:
                app_id = a.estacio.comp_aparell_id
                if app_id in team_app_ids:
                    groups_for_cell = [
                        f"app-{app_id}-serie-{serie_id}"
                        for serie_id in assignacio_series(a)
                    ]
                else:
                    groups_for_cell = assignacio_grups(a)
                prev = app_groups_map.get(app_id, [])
                app_groups_map[app_id] = unique_ordered(list(prev) + list(groups_for_cell))

            mode_for_franja = franja_modes.get(str(franja_selected_id), ORDER_MODE_MAINTAIN)

            for app_id in active_app_ids:
                app_key = str(app_id)
                app_groups = app_groups_map.get(app_id, [])
                rotation_groups_by_app[app_key] = app_groups
                rank = 1
                subject_rows_by_group = {}
                if app_id in team_app_ids:
                    for subject in team_subjects:
                        if int(app_id) not in (subject.get("allowed_app_ids") or []) and not subject.get("invalid_reasons"):
                            continue
                        key = str(subject.get("group") or "")
                        if key not in app_groups:
                            continue
                        subject_rows_by_group.setdefault(key, []).append(subject)
                else:
                    for g, rows in programmed_groups:
                        if isinstance(g, str):
                            continue
                        key = 0 if g in (None, 0) else int(g)
                        subject_rows_by_group[key] = list(rows)
                for g in app_groups:
                    base_pairs = []
                    for r in subject_rows_by_group.get(g, []):
                        if app_id in team_app_ids:
                            base_pairs.append((r["id"], r))
                            continue
                        if app_id in excluded_by_ins.get(r.id, set()):
                            continue
                        base_pairs.append((r.id, r))

                    ordered = order_pairs_for_mode(
                        base_pairs,
                        mode_for_franja,
                        rotate_steps=effective_rotate_steps(
                            mode_for_franja,
                            (
                                rotation_series_step_map.get((int(str(g).rsplit("-", 1)[-1]), franja_selected_id), 0)
                                if app_id in team_app_ids and str(g).startswith(f"app-{app_id}-serie-")
                                else rotation_group_step_map.get((g, franja_selected_id), 0)
                            ),
                        ),
                        seed_prefix=f"notes|{competicio.id}|{franja_selected_id}|{app_id}|{g}",
                    )
                    for subject_id, _r in ordered:
                        key = f"{app_id}|{subject_id}"
                        if key in rotation_rank_map:
                            continue
                        rotation_rank_map[key] = rank
                        rank += 1

        def _group_visible_for_app(group_key, app_id):
            visible_group_keys = rotation_groups_by_app.get(str(app_id)) or []
            if not visible_group_keys:
                return True
            return str(group_key) in {str(item) for item in visible_group_keys}

        def _apps_for_individual_group(group_key, rows):
            visible_apps = []
            for ca in aparells_cfg:
                if int(ca.id) in team_app_ids:
                    continue
                if not _group_visible_for_app(group_key, ca.id):
                    continue
                has_rows = any(int(ca.id) not in excluded_by_ins.get(row.id, set()) for row in rows)
                if has_rows:
                    visible_apps.append(ca)
            return visible_apps

        def _apps_for_team_bucket(group_key, rows):
            app_id = _bucket_app_id(group_key)
            if app_id is None or not _group_visible_for_app(group_key, app_id):
                return []
            ca = apparells_cfg_by_id.get(int(app_id))
            if ca is None:
                return []
            return [ca]

        def _render_groups_payload(group_rows):
            rendered = []
            for group_key, rows in group_rows:
                key_str = str(group_key)
                if isinstance(group_key, str):
                    visible_apps = _apps_for_team_bucket(group_key, rows)
                    kind = "team_bucket"
                else:
                    visible_apps = _apps_for_individual_group(group_key, rows)
                    kind = "individual_group"
                if not visible_apps:
                    continue
                rendered.append({
                    "key": key_str,
                    "label": group_labels_map.get(key_str, "Sense grup"),
                    "kind": kind,
                    "count": len(rows),
                    "apps": visible_apps,
                })
            return rendered

        groups_render = _render_groups_payload(programmed_groups)
        out_of_program_groups_render = (
            _render_groups_payload(out_of_program_groups)
            if show_out_of_program_groups
            else []
        )

        ctx.update({
            "competicio": competicio,
            "groups": programmed_groups,
            "out_of_program_groups": out_of_program_groups if show_out_of_program_groups else [],
            "groups_render": groups_render,
            "out_of_program_groups_render": out_of_program_groups_render,
            "show_out_of_program_in_competition_views": show_out_of_program_groups,
            "group_labels_map": group_labels_map,
            "aparells_cfg": aparells_cfg,
            "exercicis": exercicis,
            "exercicis_by_aparell": exercicis_by_aparell,
            "franges": franges,
            "franja_selected_id": franja_selected_id,
            "rotation_rank_map": rotation_rank_map,
            "rotation_groups_by_app": rotation_groups_by_app,

            # per json_script
            "schemas": schemas,
            "logical_schemas": logical_schemas,
            "scores": scores,
            "inscripcions": inscripcions,
            "media_counts_by_inscripcio": media_counts_by_inscripcio,
            "judge_video_presence_by_key": judge_video_presence_by_key,
            "team_issues_by_app": team_issues_by_app,
            "updates_cursor_init": timezone.now().isoformat(),
        })
        return ctx


class ScoringSchemaUpdate(UpdateView):
    model = ScoringSchema
    form_class = ScoringSchemaForm
    template_name = "competicio/scoring_schema_builder.html"

    def dispatch(self, request, *args, **kwargs):
        # per poder tornar on toca
        self.next_url = request.GET.get("next")

        self.competicio = None
        self.comp_aparell = None
        self.aparell = None

        # MODE VELL (ve de: competicio/<pk>/aparell/<ap_id>/schema/)
        if "ap_id" in kwargs:
            self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
            self.comp_aparell = get_object_or_404(
                CompeticioAparell,
                pk=kwargs["ap_id"],
                competicio=self.competicio,
            )
            self.aparell = self.comp_aparell.aparell

        # MODE NOU (ve de: trampoli/aparells/<pk>/puntuacio/)
        else:
            self.aparell = get_object_or_404(Aparell, pk=kwargs["pk"])

        if not self._can_manage_aparell(self.aparell):
            raise PermissionDenied("No tens permisos per editar aquest aparell.")

        return super().dispatch(request, *args, **kwargs)

    def _can_manage_aparell(self, aparell: Aparell) -> bool:
        if self.request.user.is_superuser or self.request.user.groups.filter(name="platform_admin").exists():
            return True
        return aparell.created_by_id == self.request.user.id

    def get_object(self):
        # si estem en mode competició (competicio/<pk>/aparell/<ap_id>/schema/)
        if self.comp_aparell:
            obj, _ = ScoringSchema.objects.get_or_create(
                aparell=self.comp_aparell.aparell,
                defaults={"schema": {}},
            )
            return obj

        # si estem en mode global (trampoli/aparells/<pk>/puntuacio/)
        obj, _ = ScoringSchema.objects.get_or_create(
            aparell=self.aparell,
            defaults={"schema": {}},
        )
        return obj

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["comp_aparell"] = self.comp_aparell
        return kwargs

    def _saved_schema_payload(self):
        return self.object.schema if isinstance(getattr(self.object, "schema", None), dict) else {}

    def _schema_draft_storage_key(self):
        mode = "competition" if self.comp_aparell else "global"
        parts = [
            "scoring-schema-builder",
            mode,
            f"aparell:{getattr(self.aparell, 'id', 'unknown')}",
        ]
        if self.comp_aparell:
            parts.append(f"comp-aparell:{self.comp_aparell.id}")
        parts.append(self.request.path)
        return "::".join(str(part) for part in parts if part is not None)

    def _schema_bootstrap_payload(self):
        base = getattr(self, "_schema_bootstrap_payload_override", None)
        if isinstance(base, dict):
            payload = dict(base)
        else:
            saved_schema = self._saved_schema_payload()
            payload = {
                "schema_initial": saved_schema,
                "schema_saved": saved_schema,
                "schema_initial_source": "saved",
                "schema_raw_invalid_json": "",
            }
        payload["schema_draft_storage_key"] = self._schema_draft_storage_key()
        return payload

    def _build_invalid_schema_bootstrap(self, form):
        saved_schema = self._saved_schema_payload()
        raw_schema = ""
        if form is not None and hasattr(form, "get_raw_schema_json"):
            raw_schema = str(form.get_raw_schema_json() or "")
        if not raw_schema and form is not None:
            raw_schema = str((form.data.get("schema_json") if hasattr(form, "data") else "") or "")
        raw_schema = raw_schema.strip()

        bootstrap = {
            "schema_initial": saved_schema,
            "schema_saved": saved_schema,
            "schema_initial_source": "saved",
            "schema_raw_invalid_json": "",
        }
        if not raw_schema:
            return bootstrap

        try:
            parsed = json.loads(raw_schema)
        except Exception:
            bootstrap["schema_initial_source"] = "raw_invalid_json"
            bootstrap["schema_raw_invalid_json"] = raw_schema
            return bootstrap

        if isinstance(parsed, dict):
            bootstrap["schema_initial"] = parsed
            bootstrap["schema_initial_source"] = "posted_invalid"
            return bootstrap

        bootstrap["schema_initial_source"] = "raw_invalid_json"
        bootstrap["schema_raw_invalid_json"] = raw_schema
        return bootstrap

    def form_invalid(self, form):
        self._schema_bootstrap_payload_override = self._build_invalid_schema_bootstrap(form)
        return self.render_to_response(self.get_context_data(form=form))

    def form_valid(self, form):
        schema_json = form.cleaned_data.get("schema_json")
        schema_changed = False

        if schema_json is not None:
            previous_schema = self.object.schema if isinstance(self.object.schema, dict) else {}
            schema_changed = previous_schema != schema_json

        # Auto recalc only in competition flow and only if schema really changed.
        if schema_changed and self.competicio and self.comp_aparell:
            summary = _recalculate_scores_for_comp_aparell(
                self.competicio,
                self.comp_aparell,
                schema_override=schema_json,
                apply_changes=False,
            )
            engine_error = summary.get("engine_error")

            if engine_error:
                messages.error(
                    self.request,
                    f"Schema no desat: validacio del recalc ha fallat ({engine_error}).",
                )
                return redirect(self.get_success_url())
            elif summary["failed"] > 0:
                preview = "; ".join(summary["errors_preview"])
                extra = f" Errors: {preview}" if preview else ""
                messages.error(
                    self.request,
                    f"Schema no desat. El recalc ha fallat per {summary['failed']}/{summary['total']} notes.{extra}",
                )
                return redirect(self.get_success_url())
            else:
                with transaction.atomic():
                    self.object.schema = schema_json
                    self.object.save()
                    for item in summary.get("planned_updates", []):
                        entry = item["entry"]
                        entry.inputs = item["inputs"]
                        entry.outputs = item["outputs"]
                        entry.total = item["total"]
                        entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])

        elif schema_changed:
            self.object.schema = schema_json
            self.object.save()

        if schema_changed:
            messages.success(
                self.request,
                (
                    f"Schema desat. Recalculades {summary['updated']}/{summary['total']} notes."
                    if self.competicio and self.comp_aparell
                    else "Schema desat."
                ),
            )

        return redirect(self.get_success_url())

    def get_success_url(self):
        # 1) si venies d'algun lloc, torna-hi
        if self.next_url:
            return self.next_url

        # 2) si estàs en una competició, torna a notes-v2
        if self.competicio:
            return reverse("scoring_notes_home", kwargs={"pk": self.competicio.id})

        # 3) si és global, torna a editar l'aparell (o a la llista)
        return reverse("aparell_update", kwargs={"pk": self.aparell.id})
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        schema_bootstrap = self._schema_bootstrap_payload()
        ctx["schema_bootstrap"] = schema_bootstrap
        ctx["schema_initial"] = schema_bootstrap.get("schema_initial") or {}
        ctx["schema_initial_source"] = schema_bootstrap.get("schema_initial_source") or "saved"
        ctx["schema_raw_invalid_json"] = schema_bootstrap.get("schema_raw_invalid_json") or ""
        ctx["schema_draft_storage_key"] = schema_bootstrap.get("schema_draft_storage_key") or ""
        ctx["aparell"] = self.aparell

        next_url = self.request.GET.get("next")
        if next_url:
            ctx["next"] = next_url

        # només si vens del flux antic
        if self.competicio:
            ctx["competicio"] = self.competicio
        if self.comp_aparell:
            ctx["comp_aparell"] = self.comp_aparell
            ctx["schema_builder_config"] = {
                "competition_unit": getattr(self.comp_aparell.aparell, "competition_unit", "individual"),
                "is_team_unit": bool(self.comp_aparell.is_team_competition_unit),
            }
        else:
            ctx["schema_builder_config"] = {
                "competition_unit": getattr(self.aparell, "competition_unit", "individual"),
                "is_team_unit": bool(getattr(self.aparell, "is_team_competition_unit", False)),
            }

        return ctx

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
        return JsonResponse({"ok": False, "error": "JSON invàlid"}, status=400)

    comp_aparell_id = payload.get("comp_aparell_id")
    exercici = int(payload.get("exercici") or 1)
    inputs = payload.get("inputs", {})

    if not comp_aparell_id:
        return JsonResponse({"ok": False, "error": "Falta comp_aparell_id"}, status=400)

    comp_aparell = get_object_or_404(CompeticioAparell, pk=comp_aparell_id, competicio=competicio, actiu=True)
    subject, error_response = resolve_scoring_subject(
        competicio,
        comp_aparell,
        payload,
        eligible_team_ids=eligible_team_ids_for_comp_aparell(competicio, comp_aparell) if is_team_context_app(comp_aparell) else None,
    )
    if error_response is not None:
        return error_response

    ss, _ = ScoringSchema.objects.get_or_create(aparell=comp_aparell.aparell, defaults={"schema": {}})
    team_subject = subject.get("team_subject") if str(subject.get("subject_kind")) == "team_unit" else None
    team_member_count = len(getattr(team_subject, "member_ids", []) or []) if team_subject is not None else 0
    base_schema = ss.schema or {}
    schema = runtime_schema_for_comp_aparell(base_schema, comp_aparell, member_count=team_member_count)
    if team_subject is not None:
        allowed = _logical_team_input_codes(base_schema)
        clean_inputs = {}
        if isinstance(inputs, dict):
            for k, v in inputs.items():
                if k in allowed:
                    clean_inputs[k] = copy.deepcopy(v)
        compute_inputs = logical_team_inputs_to_runtime_inputs(clean_inputs, team_subject, base_schema)
    else:
        allowed = _allowed_input_codes_for_schema(base_schema, comp_aparell)
        clean_inputs = {}
        if isinstance(inputs, dict):
            for k, v in inputs.items():
                if k in allowed:
                    clean_inputs[k] = v
        compute_inputs = clean_inputs

    try:
        engine = ScoringEngine(schema)
        result = engine.compute(compute_inputs)
    except ScoringError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Error inesperat calculant."}, status=500)

    max_ex = max(1, min(4, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1)))
    exercici = max(1, min(max_ex, exercici))

    entry, _ = get_or_create_subject_entry_locked(
        competicio=competicio,
        comp_aparell=comp_aparell,
        exercici=exercici,
        subject=subject,
    )
    entry.inputs = (
        runtime_inputs_to_logical_team_inputs(result.inputs, team_subject, base_schema)
        if team_subject is not None
        else result.inputs
    )
    entry.outputs = result.outputs
    entry.total = result.total
    entry.save()

    response = {
        "ok": True,
        "exercici": entry.exercici,
        "comp_aparell_id": comp_aparell.id,
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
    Igual que scoring_save, però:
    - rep inputs_patch (no inputs complet)
    - fa MERGE amb entry.inputs existent
    - recalcula amb ScoringEngine
    Payload:
    {
      "inscripcio_id": 10,
      "exercici": 1,
      "comp_aparell_id": 5,
      "inputs_patch": {...}
    }
    """
    competicio = get_object_or_404(Competicio, pk=pk)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON invàlid"}, status=400)

    comp_aparell_id = payload.get("comp_aparell_id")
    exercici = int(payload.get("exercici") or 1)
    patch = payload.get("inputs_patch", {})

    if not comp_aparell_id:
        return JsonResponse({"ok": False, "error": "Falta comp_aparell_id"}, status=400)
    if not isinstance(patch, dict):
        return JsonResponse({"ok": False, "error": "inputs_patch ha de ser objecte JSON"}, status=400)

    comp_aparell = get_object_or_404(CompeticioAparell, pk=comp_aparell_id, competicio=competicio, actiu=True)
    subject, error_response = resolve_scoring_subject(
        competicio,
        comp_aparell,
        payload,
        eligible_team_ids=eligible_team_ids_for_comp_aparell(competicio, comp_aparell) if is_team_context_app(comp_aparell) else None,
    )
    if error_response is not None:
        return error_response

    max_ex = max(1, min(4, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1)))
    exercici = max(1, min(max_ex, exercici))

    ss, _ = ScoringSchema.objects.get_or_create(aparell=comp_aparell.aparell, defaults={"schema": {}})
    team_subject = subject.get("team_subject") if str(subject.get("subject_kind")) == "team_unit" else None
    base_schema = ss.schema or {}
    team_member_count = len(getattr(team_subject, "member_ids", []) or []) if team_subject is not None else 0
    schema = runtime_schema_for_comp_aparell(base_schema, comp_aparell, member_count=team_member_count)
    allowed = set()
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
        defaults={"inputs": {}, "outputs": {}, "total": 0},
    )
    current_inputs = entry.inputs if isinstance(entry.inputs, dict) else {}
    if team_subject is not None:
        current_inputs, orphan_inputs = _split_inputs_by_allowed_codes(current_inputs, allowed)
        merged_logical = _merge_team_logical_patch(current_inputs, patch, base_schema)
        compute_inputs = logical_team_inputs_to_runtime_inputs(merged_logical, team_subject, base_schema)
    else:
        orphan_inputs = {}
        merged = dict(current_inputs)
        for k, v in patch.items():
            if k in allowed:
                merged[k] = v
        compute_inputs = merged

    try:
        engine = ScoringEngine(schema)
        result = engine.compute(compute_inputs)
    except ScoringError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Error inesperat calculant."}, status=500)

    entry.inputs = (
        _merge_inputs_preserving_orphans(
            runtime_inputs_to_logical_team_inputs(result.inputs, team_subject, base_schema),
            orphan_inputs,
        )
        if team_subject is not None
        else result.inputs
    )
    entry.outputs = result.outputs
    entry.total = result.total
    entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])

    response = {
        "ok": True,
        "exercici": entry.exercici,
        "comp_aparell_id": comp_aparell.id,
        "inputs": (
            runtime_inputs_to_logical_team_inputs(result.inputs, team_subject, base_schema)
            if team_subject is not None
            else entry.inputs
        ),
        "outputs": entry.outputs,
        "total": float(entry.total),
        "updated_at": entry.updated_at.isoformat(),
    }
    response.update(serialize_subject_payload(subject["subject_kind"], subject["subject_id"]))
    return JsonResponse(response)
    current_inputs = entry.inputs if isinstance(entry.inputs, dict) else {}

    # MERGE: només claus permeses
    merged = dict(current_inputs)
    for k, v in patch.items():
        if k in allowed:
            merged[k] = v

    try:
        engine = ScoringEngine(schema)
        result = engine.compute(merged)
    except ScoringError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Error inesperat calculant."}, status=500)

    entry.inputs = result.inputs
    entry.outputs = result.outputs
    entry.total = result.total
    entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])

    return JsonResponse({
        "ok": True,
        "inscripcio_id": ins.id,
        "exercici": entry.exercici,
        "comp_aparell_id": comp_aparell.id,
        "inputs": entry.inputs,     # útil per refrescar client
        "outputs": entry.outputs,
        "total": float(entry.total),
        "updated_at": entry.updated_at.isoformat(),
    })


@require_GET
def scoring_media_file(request, pk, media_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    item = get_object_or_404(
        InscripcioMedia.objects.select_related("inscripcio"),
        pk=media_id,
        competicio=competicio,
    )
    return _protected_file_response(
        item.fitxer,
        original_filename=item.original_filename,
        mime_type=item.mime_type,
    )


@require_GET
def scoring_judge_video_file(request, pk, video_kind, video_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    normalized_kind = str(video_kind or "").strip().lower()
    if normalized_kind == "team":
        video_obj = get_object_or_404(
            TeamScoreEntryVideo.objects.select_related("team_score_entry"),
            pk=video_id,
            team_score_entry__competicio=competicio,
        )
    elif normalized_kind == "individual":
        video_obj = get_object_or_404(
            ScoreEntryVideo.objects.select_related("score_entry"),
            pk=video_id,
            score_entry__competicio=competicio,
        )
    else:
        raise Http404("Tipus de video invalid")
    return _protected_file_response(
        video_obj.video_file,
        original_filename=video_obj.original_filename,
        mime_type=video_obj.mime_type,
    )


@require_GET
def scoring_media_context(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)

    subject_kind = str(request.GET.get("subject_kind") or "").strip().lower()
    subject_id = _parse_positive_int(request.GET.get("subject_id"))
    ins_id = _parse_positive_int(request.GET.get("inscripcio_id"))
    comp_aparell_id = _parse_positive_int(request.GET.get("comp_aparell_id"))
    exercici = _parse_positive_int(request.GET.get("exercici"))

    comp_aparell = None
    if comp_aparell_id:
        comp_aparell = (
            CompeticioAparell.objects
            .filter(pk=comp_aparell_id, competicio=competicio)
            .select_related("aparell")
            .first()
        )
    if comp_aparell_id and comp_aparell is None:
        return JsonResponse({"ok": False, "error": "comp_aparell_id invalid per aquesta competicio."}, status=400)

    if comp_aparell and is_team_context_app(comp_aparell):
        eligible_subjects = _eligible_team_subject_map(competicio, comp_aparell)
        subject, error_response = resolve_scoring_subject(
            competicio,
            comp_aparell,
            {
                "subject_kind": subject_kind,
                "subject_id": subject_id,
                "inscripcio_id": ins_id,
            },
            eligible_team_ids=eligible_subjects.keys(),
        )
        if error_response is not None:
            return error_response
        team_subject_obj = subject["team_subject"]
        equip = team_subject_obj.equip
        team_subject = eligible_subjects.get(int(team_subject_obj.id), {})
        judge_video_payload = None
        if exercici:
            score = (
                TeamScoreEntry.objects
                .filter(
                    competicio=competicio,
                    team_subject=team_subject_obj,
                    comp_aparell=comp_aparell,
                    exercici=exercici,
                )
                .first()
            )
            if score:
                video_obj = TeamScoreEntryVideo.objects.filter(team_score_entry=score).first()
                judge_video_payload = _serialize_judge_video_for_playback(video_obj, competicio.id)

        return JsonResponse({
            "ok": True,
            **serialize_subject_payload("team_unit", team_subject_obj.id),
            "subject": {
                "kind": "team_unit",
                "id": team_subject_obj.id,
                "name": f"{team_subject.get('context_name') or ''} · {team_subject.get('name') or team_subject_obj.label}".strip(" ·"),
                "meta": " · ".join(
                    part for part in [
                        team_subject.get("members_text", ""),
                        team_subject.get("serie_label", ""),
                    ] if part
                ),
            },
            "context": {
                "comp_aparell_id": comp_aparell_id,
                "exercici": exercici,
                "serie_id": team_subject.get("serie_id"),
                "serie_label": team_subject.get("serie_label"),
            },
            "media": _split_media_for_playback([]),
            "judge_video": judge_video_payload,
        })

    ins_id = subject_id or ins_id
    if subject_kind and subject_kind != "inscripcio":
        return JsonResponse({"ok": False, "error": "Aquest context nomes accepta subject_kind=inscripcio."}, status=400)
    if not ins_id:
        return JsonResponse({"ok": False, "error": "Falta subject_id/inscripcio_id valid."}, status=400)

    inscripcio = get_object_or_404(Inscripcio, pk=ins_id, competicio=competicio)

    media_qs = (
        InscripcioMedia.objects
        .filter(competicio=competicio, inscripcio=inscripcio)
        .order_by("tipus", "-is_primary", "-created_at", "id")
    )
    media_items = [_serialize_inscripcio_media_for_playback(m) for m in media_qs]
    media_payload = _split_media_for_playback(media_items)

    judge_video_payload = None
    if comp_aparell_id and exercici:
        score = (
            ScoreEntry.objects
            .filter(
                competicio=competicio,
                inscripcio=inscripcio,
                comp_aparell_id=comp_aparell_id,
                exercici=exercici,
            )
            .first()
        )
        if score:
            video_obj = ScoreEntryVideo.objects.filter(score_entry=score).first()
            judge_video_payload = _serialize_judge_video_for_playback(video_obj, competicio.id)

    meta_parts = []
    if getattr(inscripcio, "entitat", None):
        meta_parts.append(str(inscripcio.entitat))
    if getattr(inscripcio, "categoria", None):
        meta_parts.append(str(inscripcio.categoria))
    if getattr(inscripcio, "subcategoria", None):
        meta_parts.append(str(inscripcio.subcategoria))

    return JsonResponse({
        "ok": True,
        **serialize_subject_payload("inscripcio", inscripcio.id),
        "subject": {
            "kind": "inscripcio",
            "id": inscripcio.id,
            "name": inscripcio.nom_i_cognoms or "",
            "meta": " · ".join(meta_parts) if meta_parts else "",
        },
        "context": {
            "comp_aparell_id": comp_aparell_id,
            "exercici": exercici,
        },
        "media": media_payload,
        "judge_video": judge_video_payload,
    })


@require_GET
def scoring_updates(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)

    cursor = parse_feed_cursor(request)
    comp_aparell_id = request.GET.get("comp_aparell_id")
    exercici = request.GET.get("exercici")
    group = request.GET.get("group")  # opcional
    serie_id = request.GET.get("serie_id")  # opcional per aparells team

    if cursor.dt is None:
        # si no arriba since, no petem: retornem buit
        return JsonResponse(
            {
                "ok": True,
                "now": None,
                "updates": [],
                "next_since": None,
                "next_after_id": "",
                "has_more": False,
            }
        )

    rows = []
    allowed_inputs_by_app = {}
    qs = ScoreEntry.objects.filter(competicio=competicio)
    qs = qs.annotate(
        _excluded=Exists(
            InscripcioAparellExclusio.objects.filter(
                inscripcio_id=OuterRef("inscripcio_id"),
                comp_aparell_id=OuterRef("comp_aparell_id"),
            )
        )
    ).filter(_excluded=False)

    if comp_aparell_id:
        qs = qs.filter(comp_aparell_id=comp_aparell_id)
    if exercici:
        try:
            qs = qs.filter(exercici=int(exercici))
        except Exception:
            pass
    if group is not None:
        try:
            qs = qs.filter(inscripcio__grup_competicio_id=int(group))
        except Exception:
            pass

    qs = _apply_combined_cursor(qs.order_by("updated_at", "id"), cursor, source=SCORING_FEED_SOURCE_SCORE)

    for s in qs.select_related("inscripcio")[: SCORING_UPDATES_LIMIT + 1]:
        if int(s.comp_aparell_id) not in allowed_inputs_by_app:
            ca = CompeticioAparell.objects.filter(pk=s.comp_aparell_id, competicio=competicio).first()
            ss, _ = ScoringSchema.objects.get_or_create(aparell=ca.aparell, defaults={"schema": {}}) if ca else (None, False)
            allowed_inputs_by_app[int(s.comp_aparell_id)] = _allowed_input_codes_for_schema(
                ss.schema if ss is not None else {},
                ca,
            )
        rows.append(
            {
                "payload": _serialize_individual_scoring_update(
                    s,
                    allowed_inputs=allowed_inputs_by_app.get(int(s.comp_aparell_id), set()),
                ),
                "sort_updated_at": s.updated_at,
                "sort_id": int(s.id),
                "sort_source": SCORING_FEED_SOURCE_SCORE,
            }
        )

    rows.extend(
        _collect_team_scoring_updates(
            competicio,
            cursor,
            comp_aparell_id=comp_aparell_id,
            exercici=exercici,
            serie_id=serie_id if comp_aparell_id else None,
        )
    )

    # “now” del servidor per anar avançant el cursor
    rows.sort(key=lambda row: (row["sort_updated_at"], _combined_source_rank(row["sort_source"]), row["sort_id"]))
    feed_meta = _combined_feed_meta(rows, limit=SCORING_UPDATES_LIMIT, cursor=cursor)
    return JsonResponse(
        {
            "ok": True,
            "now": feed_meta["next_since"],
            "updates": [row["payload"] for row in feed_meta["page"]],
            "next_since": feed_meta["next_since"],
            "next_after_id": feed_meta["next_after_id"],
            "has_more": feed_meta["has_more"],
        }
    )
