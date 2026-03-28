import io
import json
import logging
import math
import mimetypes
import os
import qrcode
import subprocess
import tempfile
import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_http_methods, require_POST
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models_judging import JudgeDeviceToken, PublicLiveToken
from .models import Competicio, Equip, Inscripcio
from .models_trampoli import CompeticioAparell, InscripcioAparellExclusio
from .models_rotacions import RotacioAssignacio, RotacioFranja
from .models_scoring import (
    ScoreEntry,
    ScoreEntryVideo,
    ScoreEntryVideoEvent,
    ScoringSchema,
    TeamCompetitiveSubject,
    TeamScoreEntry,
    TeamScoreEntryVideo,
    TeamScoreEntryVideoEvent,
)
from .scoring_engine import ScoringEngine, ScoringError
from .services.scoring_subjects import (
    get_or_create_subject_entry_locked,
    resolve_scoring_subject,
    serialize_subject_payload,
    subject_entry_model,
    subject_video_models,
)
from .services.team_scoring import (
    build_permission_label,
    build_team_subjects_for_comp_aparell,
    is_team_context_app,
    logical_team_inputs_to_runtime_inputs,
    normalize_permission_target,
    resolve_permission_runtime_entries,
    runtime_schema_for_comp_aparell,
    runtime_inputs_to_logical_team_inputs,
)
from .services.team_subject_contract import (
    build_team_subject_registry,
    filter_team_subject_ids_for_serie,
    runtime_schema_for_team_subjects,
    team_subject_meta,
)
from .services.competition_groups import (
    get_group_maps,
    get_inscripcio_competition_order,
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
from .services.team_series import team_subject_bucket_key, team_subject_bucket_label

logger = logging.getLogger(__name__)


class VideoValidationError(Exception):
    def __init__(self, message: str, reason: str = "video_validation_failed", payload=None):
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.payload = payload or {}


def _mime_from_probe(format_name: str, original_filename: str = "") -> str:
    fmt = (format_name or "").strip().lower()
    tokens = {x.strip() for x in fmt.split(",") if x.strip()}
    ext = os.path.splitext((original_filename or "").lower())[1]

    if "webm" in tokens or ext == ".webm":
        return "video/webm"

    has_mp4_family = bool(tokens.intersection({"mp4", "m4a", "3gp", "3g2", "mj2"}))
    has_mov = "mov" in tokens
    if ext == ".mov":
        return "video/quicktime"
    if has_mp4_family:
        return "video/mp4"
    if has_mov:
        return "video/quicktime"

    guessed, _ = mimetypes.guess_type(original_filename or "")
    return (guessed or "").strip().lower()


def _probe_uploaded_video_metadata(uploaded_file):
    suffix = os.path.splitext(getattr(uploaded_file, "name", "") or "")[1]
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_path = tmp.name
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)

        ffprobe_bin = getattr(settings, "JUDGE_VIDEO_FFPROBE_BIN", os.getenv("JUDGE_VIDEO_FFPROBE_BIN", "ffprobe"))
        ffprobe_timeout = int(
            getattr(
                settings,
                "JUDGE_VIDEO_FFPROBE_TIMEOUT_SECONDS",
                os.getenv("JUDGE_VIDEO_FFPROBE_TIMEOUT_SECONDS", "15"),
            )
        )

        cmd = [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name:stream=codec_type,codec_name",
            "-of",
            "json",
            temp_path,
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max(1, ffprobe_timeout),
                check=False,
            )
        except FileNotFoundError as exc:
            raise VideoValidationError(
                "La validacio de video no esta disponible al servidor (ffprobe).",
                reason="ffprobe_missing",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise VideoValidationError(
                "No s'ha pogut validar el video dins del temps limit.",
                reason="ffprobe_timeout",
            ) from exc

        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            raise VideoValidationError(
                "El fitxer no sembla un video valid.",
                reason="ffprobe_failed",
                payload={"stderr": stderr[:300]},
            )

        try:
            parsed = json.loads(proc.stdout or "{}")
        except Exception as exc:
            raise VideoValidationError(
                "No s'han pogut llegir metadades del video.",
                reason="ffprobe_json_parse_failed",
            ) from exc

        streams = parsed.get("streams") or []
        video_stream = next(
            (s for s in streams if str((s or {}).get("codec_type", "")).lower() == "video"),
            None,
        )
        if not video_stream:
            raise VideoValidationError(
                "El fitxer no conte cap pista de video valida.",
                reason="no_video_stream",
            )

        fmt = parsed.get("format") or {}
        duration_raw = fmt.get("duration")
        try:
            duration_float = float(duration_raw)
        except Exception as exc:
            raise VideoValidationError(
                "No s'ha pogut calcular la durada real del video.",
                reason="duration_missing",
            ) from exc

        if not math.isfinite(duration_float) or duration_float <= 0:
            raise VideoValidationError(
                "Durada de video invalida.",
                reason="invalid_duration",
                payload={"duration": duration_raw},
            )

        duration_seconds = int(math.ceil(duration_float))
        if duration_seconds > ScoreEntryVideo.VIDEO_MAX_DURATION_SECONDS:
            raise VideoValidationError(
                (
                    "La durada supera el limit "
                    f"de {ScoreEntryVideo.VIDEO_MAX_DURATION_SECONDS} segons."
                ),
                reason="duration_too_long",
                payload={"duration_seconds": duration_seconds},
            )

        format_name = str(fmt.get("format_name") or "").strip().lower()
        mime_type = _mime_from_probe(format_name, getattr(uploaded_file, "name", "") or "")
        if not mime_type:
            raise VideoValidationError(
                "No s'ha pogut identificar el tipus MIME real del video.",
                reason="missing_mime_from_probe",
                payload={"format_name": format_name},
            )
        if mime_type not in ScoreEntryVideo.ALLOWED_MIME_TYPES:
            raise VideoValidationError(
                f"Tipus MIME no permes: {mime_type}",
                reason="mime_not_allowed",
                payload={"mime_type": mime_type, "format_name": format_name},
            )

        return {
            "duration_seconds": duration_seconds,
            "mime_type": mime_type,
            "format_name": format_name,
            "video_codec": str((video_stream or {}).get("codec_name") or "").strip().lower(),
        }
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except Exception:
                pass
        try:
            uploaded_file.seek(0)
        except Exception:
            pass

def _sanitize_patch_by_permissions(schema: dict, permissions: list, patch: dict) -> dict:
    """
    Retorna un patch limitat a:
    - camps autoritzats
    - per matrix: només la fila judge_index i rang d'ítems si s'ha definit
    - per list: només index judge_index
    """
    # index de fields per code
    by_code = {}
    for f in (schema.get("fields") or []):
        if isinstance(f, dict) and f.get("code"):
            by_code[f["code"]] = f

    perms_by_code = {}
    for p in permissions:
        runtime_code = str(p.get("runtime_field_code") or p.get("field_code") or "").strip()
        if not runtime_code:
            continue
        perms_by_code.setdefault(runtime_code, []).append(p)

    clean = {}

    for code, incoming_val in (patch or {}).items():
        is_crash_key = isinstance(code, str) and code.startswith("__crash__")
        base_code = code[len("__crash__"):] if is_crash_key else code

        if base_code not in perms_by_code:
            continue
        f = by_code.get(base_code)
        if not f:
            continue

        ftype = f.get("type") or "number"

        # per simplicitat: si hi ha més d'un permís pel mateix code,
        # aquí apliquem TOTS (unió). Normalment en tindràs 1.
        perms = perms_by_code[base_code]

        if is_crash_key:
            crash_cfg = f.get("crash") if isinstance(f.get("crash"), dict) else {}
            if ftype != "matrix" or not crash_cfg.get("enabled"):
                continue

            sets = []
            for p in perms:
                j = max(1, int(p.get("judge_index") or 1))
                if isinstance(incoming_val, list):
                    v = incoming_val[j - 1] if len(incoming_val) >= j else None
                else:
                    v = incoming_val
                sets.append((j - 1, v))
            clean[code] = {"__set_list__": sets}
            continue

        if ftype == "number":
            clean[base_code] = incoming_val
            continue

        if ftype == "list":
            # incoming_val ha de ser una llista; però nosaltres només acceptem el nostre índex
            # i ho reconstruïm sobre el valor existent més tard amb MERGE
            # aquí deixem un patch del tipus {"CODE": {"__set_list__": [(idx, val), ...]}}
            sets = []
            for p in perms:
                j = max(1, int(p.get("judge_index") or 1))
                # incoming pot ser llista completa o valor “nu”
                if isinstance(incoming_val, list):
                    v = incoming_val[j-1] if len(incoming_val) >= j else None
                else:
                    v = incoming_val
                sets.append((j-1, v))
            clean[base_code] = {"__set_list__": sets}
            continue

        if ftype == "matrix":
            n_items = int(((f.get("items") or {}).get("count")) or 0) or 1

            sets = []
            for p in perms:
                j = max(1, int(p.get("judge_index") or 1))
                start = max(1, int(p.get("item_start") or 1))
                count = p.get("item_count")
                if count is None:
                    count = n_items - start + 1
                count = max(1, int(count))

                # incoming_val pot ser matriu completa o només la fila
                row = None
                if isinstance(incoming_val, list) and len(incoming_val) > 0:
                    if isinstance(incoming_val[0], list):
                        row = incoming_val[j-1] if len(incoming_val) >= j else None
                    else:
                        # fila sola
                        row = incoming_val
                if row is None:
                    continue

                for k in range(count):
                    idx1 = start + k
                    idx0 = idx1 - 1
                    v = row[idx0] if len(row) > idx0 else None
                    sets.append((j-1, idx0, v))
            clean[base_code] = {"__set_matrix__": sets}
            continue

        # altres tipus: ignora
    return clean

def _normalize_permissions(perms):
    """
    Normalitza permisos per evitar errors.
    Espera list[dict].
    """
    if not isinstance(perms, list):
        return []
    out = []
    for p in perms:
        if not isinstance(p, dict):
            continue
        raw_perm = normalize_permission_target(p)
        code = raw_perm.get("field_code")
        if not code:
            continue
        scope = str(raw_perm.get("scope") or "shared").strip().lower() or "shared"
        item_count = raw_perm.get("item_count")
        row = {
            "field_code": str(code),
            "runtime_field_code": str(raw_perm.get("runtime_field_code") or code),
            "scope": scope,
            "judge_index": int(raw_perm.get("judge_index") or 1),
            "item_start": int(raw_perm.get("item_start") or 1),
            "item_count": (None if item_count in (None, "", "null") else int(item_count)),
        }
        if scope == "member":
            row["member_mode"] = str(raw_perm.get("member_mode") or "all")
            if raw_perm.get("member_slots") not in (None, ""):
                row["member_slots"] = list(raw_perm.get("member_slots") or [])
            if raw_perm.get("member_slot"):
                row["member_slot"] = int(raw_perm.get("member_slot"))
        row["label"] = build_permission_label(row)
        out.append(row)
    return out


def _allowed_input_codes_from_permissions(permissions: list) -> set:
    allowed_codes = set()
    for p in permissions or []:
        code = p.get("runtime_field_code") or p.get("field_code")
        if not code:
            continue
        allowed_codes.add(str(code))
        allowed_codes.add(f"__crash__{code}")
    return allowed_codes


def _subject_member_count(subject) -> int:
    if not isinstance(subject, dict):
        return 0
    team_subject = subject.get("team_subject")
    if team_subject is not None:
        return len(getattr(team_subject, "member_ids", []) or [])
    return len(subject.get("members") or [])


def _resolve_permissions_for_subject(permissions: list, comp_aparell, subject=None) -> list:
    member_count = _subject_member_count(subject)
    resolved = []
    for perm in permissions or []:
        resolved.extend(
            resolve_permission_runtime_entries(
                perm,
                comp_aparell,
                member_count=member_count,
            )
        )
    return resolved


def _subject_dom_id(subject) -> str:
    if not isinstance(subject, dict):
        return ""
    raw_id = subject.get("id")
    if raw_id not in (None, ""):
        return str(raw_id)
    subject_id = subject.get("subject_id")
    return "" if subject_id in (None, "") else str(subject_id)


def _filter_inputs_for_allowed_codes(inputs: dict, allowed_codes: set) -> dict:
    if not isinstance(inputs, dict):
        return {}
    return {k: v for k, v in inputs.items() if k in allowed_codes}


def _clamp_exercici_for_aparell(comp_aparell, exercici_raw):
    try:
        exercici = int(exercici_raw or 1)
    except Exception:
        exercici = 1
    max_ex = max(1, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1))
    return max(1, min(max_ex, exercici))


def _judge_video_capture_enabled_for_token(tok) -> bool:
    return bool(getattr(tok, "can_record_video", False))


def _serialize_video_record(video_record, request):
    url = None
    if video_record.video_file:
        try:
            media_url = video_record.video_file.url
            url = request.build_absolute_uri(media_url)
        except Exception:
            url = None

    return {
        "id": video_record.id,
        "status": video_record.status,
        "duration_seconds": video_record.duration_seconds,
        "file_size_bytes": int(video_record.file_size_bytes or 0),
        "mime_type": video_record.mime_type or "",
        "original_filename": video_record.original_filename or "",
        "updated_at": video_record.updated_at.isoformat() if video_record.updated_at else None,
        "url": url,
    }


def _request_meta(request):
    return {
        "ip": (request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR") or "").split(",")[0].strip(),
        "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:250],
    }


def _log_video_event(level: str, event: str, **payload):
    raw = {"event": event}
    raw.update(payload)
    msg = json.dumps(raw, ensure_ascii=True, sort_keys=True)
    if level == "error":
        logger.error(msg)
    elif level == "warning":
        logger.warning(msg)
    else:
        logger.info(msg)


def _create_video_audit_event(
    *,
    action: str,
    ok: bool,
    http_status: int,
    detail: str,
    competicio,
    comp_aparell,
    subject,
    judge_token=None,
    score_entry=None,
    video=None,
    payload=None,
):
    try:
        _video_model, event_model = subject_video_models(comp_aparell)
        create_kwargs = {
            "action": action,
            "ok": bool(ok),
            "http_status": int(http_status or 0),
            "detail": (detail or "")[:255],
            "payload": payload or {},
            "competicio": competicio,
            "comp_aparell": comp_aparell,
            "judge_token": judge_token,
            "video": video,
        }
        if str(subject.get("subject_kind")) == "team_unit":
            create_kwargs["team_subject"] = subject["team_subject"]
            create_kwargs["equip"] = subject["equip"]
            create_kwargs["team_score_entry"] = score_entry
        else:
            create_kwargs["inscripcio"] = subject["inscripcio"]
            create_kwargs["score_entry"] = score_entry
        event_model.objects.create(
            **create_kwargs
        )
    except Exception:
        logger.exception("Unable to persist ScoreEntryVideoEvent")


def judge_qr_png(request, token):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    portal_url = reverse("judge_portal", kwargs={"token": str(tok.id)})
    req_ex = request.GET.get("ex")
    if req_ex not in (None, ""):
        ex = _clamp_exercici_for_aparell(tok.comp_aparell, req_ex)
        portal_url = f"{portal_url}?ex={ex}"
    req_franja = request.GET.get("franja")
    if req_franja not in (None, ""):
        try:
            franja_id = int(req_franja)
        except Exception:
            franja_id = None
        if franja_id and RotacioFranja.objects.filter(competicio=tok.competicio, pk=franja_id).exists():
            sep = "&" if "?" in portal_url else "?"
            portal_url = f"{portal_url}{sep}franja={franja_id}"
    url = request.build_absolute_uri(portal_url)
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")


def public_live_qr_png(request, token):
    tok = get_object_or_404(PublicLiveToken, pk=token)
    url = request.build_absolute_uri(reverse("public_live_portal", kwargs={"token": str(tok.id)}))
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")


@require_http_methods(["GET"])
def public_live_portal(request, token):
    tok = get_object_or_404(PublicLiveToken, pk=token)
    if not tok.is_valid():
        return render(request, "judge/invalid_token.html", {"token": tok}, status=403)

    tok.touch()

    base_url = reverse("classificacions_live", kwargs={"pk": tok.competicio_id})
    return redirect(f"{base_url}?public=1")


@require_http_methods(["GET"])
def judge_portal(request, token):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        return render(request, "judge/invalid_token.html", {"token": tok}, status=403)

    tok.touch()

    comp_aparell = tok.comp_aparell
    competicio = tok.competicio
    video_capture_enabled = _judge_video_capture_enabled_for_token(tok)

    ss, _ = ScoringSchema.objects.get_or_create(
        aparell=comp_aparell.aparell,
        defaults={"schema": {}},
    )

    permissions = _normalize_permissions(tok.permissions)

    franja_modes = get_rotacions_order_modes(competicio)

    team_subject_mode = is_team_context_app(comp_aparell)

    # Franges programades per aquest aparell. El portal mostra tots els grups
    # visibles i resol l'ordre de cada grup segons la seva franja associada.
    group_maps = get_group_maps(competicio)
    groups_by_id = group_maps["by_id"]
    franges = list(
        RotacioFranja.objects
        .filter(competicio=competicio)
        .order_by("ordre", "id")
    )
    franges_by_id = {fr.id: fr for fr in franges}
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
    rotation_step_map = (
        build_series_rotation_step_map(all_assigns, franja_modes)
        if team_subject_mode
        else build_group_rotation_step_map(all_assigns, franja_modes)
    )
    assigns = [
        a for a in all_assigns
        if getattr(a, "estacio", None) is not None and getattr(a.estacio, "comp_aparell_id", None) == comp_aparell.id
    ]
    app_franja_ids = unique_ordered(
        int(a.franja_id)
        for a in assigns
        if getattr(a, "franja_id", None)
    )
    app_programmed_group_ids = []
    app_groups_by_franja = {}
    group_first_app_franja_id = {}
    for a in assigns:
        fid = getattr(a, "franja_id", None)
        if not fid:
            continue
        if team_subject_mode:
            groups_for_assignacio = [
                team_subject_bucket_key({"serie_id": serie_id}, comp_aparell.id)
                for serie_id in assignacio_series(a)
            ]
        else:
            groups_for_assignacio = assignacio_grups(a)
        if not groups_for_assignacio:
            continue
        app_groups_by_franja[fid] = unique_ordered(
            list(app_groups_by_franja.get(fid, [])) + list(groups_for_assignacio)
        )
        app_programmed_group_ids = unique_ordered(list(app_programmed_group_ids) + list(groups_for_assignacio))
        for group_id in groups_for_assignacio:
            group_first_app_franja_id.setdefault(group_id, fid)

    raw_franja_override = request.GET.get("franja")
    try:
        franja_override_id = int(raw_franja_override) if raw_franja_override not in (None, "") else None
    except Exception:
        franja_override_id = None
    if franja_override_id not in app_franja_ids:
        franja_override_id = None
    franja_override = franges_by_id.get(franja_override_id) if franja_override_id else None

    if team_subject_mode:
        registry = build_team_subject_registry(competicio, comp_aparell)
        raw_subjects = list(registry["subjects"])
        schema = runtime_schema_for_team_subjects(ss.schema or {}, comp_aparell, raw_subjects)
        base_subjects = [
            dict(item)
            for item in raw_subjects
            if int(comp_aparell.id) in (item.get("allowed_app_ids") or []) or item.get("invalid_reasons")
        ]
        app_name = str(getattr(comp_aparell.aparell, "nom", "") or "").strip()
        for item in base_subjects:
            item.setdefault("nom_i_cognoms", item.get("name") or "")
            item.setdefault("ordre_sortida", item.get("order") or "")
            item["group"] = team_subject_bucket_key(item, comp_aparell.id)
            item["group_label"] = team_subject_bucket_label(item, app_name)
    else:
        schema = runtime_schema_for_comp_aparell(ss.schema or {}, comp_aparell)
        excluded_ins_ids = set(
            InscripcioAparellExclusio.objects
            .filter(comp_aparell=comp_aparell)
            .values_list("inscripcio_id", flat=True)
        )
        ins_base_qs = (
            Inscripcio.objects
            .filter(competicio=competicio)
            .exclude(id__in=excluded_ins_ids)
            .select_related("grup_competicio")
            .order_by("grup_competicio__display_num", "ordre_competicio", "ordre_sortida", "id")
        )
        base_subjects = []
        for ins in ins_base_qs:
            base_subjects.append({
                "id": int(ins.id),
                "subject_id": int(ins.id),
                "subject_kind": "inscripcio",
                "name": getattr(ins, "nom_i_cognoms", "") or "",
                "nom_i_cognoms": getattr(ins, "nom_i_cognoms", "") or "",
                "order": get_inscripcio_competition_order(ins) or "",
                "ordre_sortida": getattr(ins, "ordre_sortida", None),
                "group": 0 if ins.grup_competicio_id in (None, 0) else int(ins.grup_competicio_id),
                "meta": "",
            })

    # El portal mostra tots els grups programats de l'aparell i calcula la
    # posicio efectiva segons la primera franja assignada a cada grup, amb
    # suport d'override per query string quan arriba ?franja=...
    subject_list = []
    grouped = {}
    for subject in base_subjects:
        if team_subject_mode:
            key = str(subject.get("group") or team_subject_bucket_key(subject, comp_aparell.id))
        else:
            key = 0 if subject.get("group") in (None, 0) else int(subject.get("group") or 0)
        grouped.setdefault(key, []).append(subject)

    ordered_groups = [g for g in app_programmed_group_ids if g in grouped]
    if team_subject_mode:
        unassigned_key = team_subject_bucket_key({}, comp_aparell.id)
        remaining_groups = sorted(
            (g for g in grouped.keys() if g not in app_programmed_group_ids and g != unassigned_key),
            key=lambda value: str(value),
        )
    else:
        remaining_groups = sorted(g for g in grouped.keys() if g not in app_programmed_group_ids and g != 0)
    always_visible_group_ids = list(ordered_groups)
    if team_subject_mode:
        if unassigned_key in grouped and unassigned_key not in always_visible_group_ids:
            always_visible_group_ids.append(unassigned_key)
    else:
        if 0 in grouped and 0 not in always_visible_group_ids:
            always_visible_group_ids.append(0)
    show_out_of_program_groups = show_out_of_program_in_competition_views(competicio)

    override_group_ids = set(app_groups_by_franja.get(franja_override_id, [])) if franja_override_id else set()

    def resolve_group_franja_id(group_id):
        default_fid = group_first_app_franja_id.get(group_id)
        if not franja_override_id:
            return default_fid
        if group_id in override_group_ids:
            return franja_override_id
        return default_fid

    def group_label_for(group_id) -> str:
        if team_subject_mode:
            items = grouped.get(group_id, [])
            if items:
                return str(items[0].get("group_label") or "Sense serie")
            return "Sense serie"
        if group_id in (None, 0):
            return "Sense grup"
        return group_label(groups_by_id.get(group_id))

    def build_group_block(group_id):
        group_items = grouped.get(group_id, [])
        base_pairs = [(item["subject_id"], item) for item in group_items]
        fid = resolve_group_franja_id(group_id)
        mode_for_group = franja_modes.get(str(fid), ORDER_MODE_MAINTAIN) if fid else ORDER_MODE_MAINTAIN
        rotate_steps = effective_rotate_steps(
            mode_for_group,
            (
                rotation_step_map.get((int(str(group_id).rsplit("-", 1)[-1]), fid), 0)
                if team_subject_mode and str(group_id).startswith(f"app-{comp_aparell.id}-serie-") and fid
                else rotation_step_map.get((group_id, fid), 0) if fid else 0
            ),
        )
        seed_franja = fid if fid is not None else 0

        ordered_pairs = order_pairs_for_mode(
            base_pairs,
            mode_for_group,
            rotate_steps=rotate_steps,
            seed_prefix=f"judge|{competicio.id}|{seed_franja}|{comp_aparell.id}|{group_id}",
        )
        ordered_subjects = []
        for rank, (_subject_id, subject) in enumerate(ordered_pairs, start=1):
            item = dict(subject)
            item["rotation_order_display"] = rank
            item["rotation_base_order_display"] = subject.get("order") or ""
            ordered_subjects.append(item)
        return {
            "key": group_id,
            "label": group_label_for(group_id),
            "franja_id": fid,
            "franja_label": (
                f"{getattr(franges_by_id.get(fid), 'titol', None) or 'Franja'} · "
                f"{franges_by_id[fid].hora_inici.strftime('%H:%M')}-{franges_by_id[fid].hora_fi.strftime('%H:%M')}"
                if fid and fid in franges_by_id
                else ""
            ),
            "list": ordered_subjects,
        }

    programmed_group_blocks = []
    out_of_program_group_blocks = []
    for g in always_visible_group_ids:
        block = build_group_block(g)
        programmed_group_blocks.append(block)
        subject_list.extend(block["list"])
    if show_out_of_program_groups:
        for g in remaining_groups:
            block = build_group_block(g)
            out_of_program_group_blocks.append(block)
            subject_list.extend(block["list"])
    if not programmed_group_blocks and not out_of_program_group_blocks and grouped:
        fallback_group_ids = sorted(
            grouped.keys(),
            key=lambda group_id: ((group_id == 0) if not team_subject_mode else (str(group_id) == unassigned_key), str(group_id)),
        )
        for g in fallback_group_ids:
            block = build_group_block(g)
            programmed_group_blocks.append(block)
            subject_list.extend(block["list"])

    visible_group_keys = [block["key"] for block in programmed_group_blocks]
    visible_group_keys.extend(block["key"] for block in out_of_program_group_blocks)
    raw_group = request.GET.get("group")
    if team_subject_mode:
        requested_group_key = str(raw_group).strip() if raw_group not in (None, "") else None
    else:
        try:
            requested_group_key = int(raw_group) if raw_group not in (None, "") else None
        except Exception:
            requested_group_key = None
    if requested_group_key in visible_group_keys:
        active_group_key = requested_group_key
    elif visible_group_keys:
        active_group_key = visible_group_keys[0]
    else:
        active_group_key = None

    # Prefetch entries existents (per mostrar valors actuals)
    subject_ids = [int(item["subject_id"]) for item in subject_list]
    entry_model = subject_entry_model(comp_aparell)
    entry_filters = {
        "competicio": competicio,
        "comp_aparell": comp_aparell,
    }
    if team_subject_mode:
        entry_filters["team_subject_id__in"] = subject_ids
    else:
        entry_filters["inscripcio_id__in"] = subject_ids
    entries = entry_model.objects.filter(**entry_filters)
    if team_subject_mode:
        entries = entries.select_related("team_subject")
    entry_map = {}
    for e in entries:
        owner_id = int(e.team_subject_id if team_subject_mode else e.inscripcio_id)
        entry_map[(owner_id, e.exercici)] = e

    # Construïm un “snapshot” dels inputs rellevants per inscripció/exercici
    # Per simplicitat: assumim exercici=1 si al teu flux n’hi ha més, ho pots estendre.
    max_ex = max(1, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1))
    exercicis = list(range(1, max_ex + 1))
    exercici_default = _clamp_exercici_for_aparell(comp_aparell, request.GET.get("ex"))
    scores_payload = {}
    for item in subject_list:
        subject_dom_id = _subject_dom_id(item) or str(item.get("subject_id") or "")
        resolved_permissions = _resolve_permissions_for_subject(permissions, comp_aparell, item)
        allowed_input_codes = _allowed_input_codes_from_permissions(resolved_permissions)
        exercise_map = {}
        for ex in exercicis:
            e = entry_map.get((int(item["subject_id"]), ex))
            if team_subject_mode and e and isinstance(e.inputs, dict):
                runtime_inputs = logical_team_inputs_to_runtime_inputs(e.inputs, e.team_subject, ss.schema or {})
            else:
                runtime_inputs = e.inputs if e and isinstance(e.inputs, dict) else {}
            exercise_map[str(ex)] = {
                "inputs": (
                    _filter_inputs_for_allowed_codes(runtime_inputs, allowed_input_codes)
                    if runtime_inputs
                    else {}
                ),
                "outputs": (e.outputs if e and isinstance(e.outputs, dict) else {}),
                "total": (float(e.total) if e else 0.0),
                "updated_at": (e.updated_at.isoformat() if e else None),
            }
        scores_payload[subject_dom_id] = {
            "exercises": exercise_map,
        }

    save_url = reverse("judge_save_partial", kwargs={"token": str(tok.id)})
    try:
        updates_url = reverse("judge_updates", kwargs={"token": str(tok.id)})
    except NoReverseMatch:
        try:
            updates_url = reverse("competicions_trampoli:judge_updates", kwargs={"token": str(tok.id)})
        except NoReverseMatch:
            updates_url = save_url.replace("/api/save/", "/api/updates/")

    ctx = {
        "token_obj": tok,
        "token": str(tok.id),
        "competicio": competicio,
        "comp_aparell": comp_aparell,
        "hide_base_chrome": True,
        "judge_kiosk": True,
        "schema": schema,
        "permissions": permissions,
        "inscripcions": subject_list,
        "subjects_payload_json": subject_list,
        "group_blocks": programmed_group_blocks,
        "out_of_program_group_blocks": out_of_program_group_blocks,
        "active_group_key": active_group_key,
        "show_out_of_program_in_competition_views": show_out_of_program_groups,
        "franja_override_id": franja_override_id,
        "franja_override": franja_override,
        "scores_payload_json": scores_payload,
        "save_url": save_url,
        "updates_url": updates_url,
        "updates_cursor_init": timezone.now().isoformat(),
        "video_capture_enabled": video_capture_enabled,
        "video_status_url": (
            reverse("judge_video_status", kwargs={"token": str(tok.id)})
            if video_capture_enabled
            else ""
        ),
        "video_upload_url": (
            reverse("judge_video_upload", kwargs={"token": str(tok.id)})
            if video_capture_enabled
            else ""
        ),
        "video_delete_url": (
            reverse("judge_video_delete", kwargs={"token": str(tok.id)})
            if video_capture_enabled
            else ""
        ),
        "video_max_duration_seconds": ScoreEntryVideo.VIDEO_MAX_DURATION_SECONDS,
        "video_max_size_bytes": ScoreEntryVideo.VIDEO_MAX_SIZE_BYTES,
        "exercicis": exercicis,
        "exercici": exercici_default,
        "team_subject_mode": team_subject_mode,
    }
    return render(request, "judge/portal.html", ctx)


@require_http_methods(["GET"])
def judge_updates(request, token):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        return JsonResponse({"ok": False, "error": "Token invàlid o revocat"}, status=403)

    since = request.GET.get("since")
    dt = parse_datetime(since) if since else None
    if dt is None:
        return JsonResponse({"ok": True, "now": timezone.now().isoformat(), "updates": []})

    competicio = tok.competicio
    comp_aparell = tok.comp_aparell
    raw_exercicis = request.GET.getlist("exercici")
    serie_id = request.GET.get("serie_id")
    if not raw_exercicis:
        single_exercici = request.GET.get("exercici") or request.GET.get("ex")
        raw_exercicis = [single_exercici] if single_exercici not in (None, "") else []
    if raw_exercicis:
        exercicis = unique_ordered(
            _clamp_exercici_for_aparell(comp_aparell, raw_exercici)
            for raw_exercici in raw_exercicis
        )
    else:
        exercicis = [_clamp_exercici_for_aparell(comp_aparell, request.GET.get("exercici") or request.GET.get("ex"))]
    permissions = _normalize_permissions(tok.permissions)
    ss, _ = ScoringSchema.objects.get_or_create(aparell=comp_aparell.aparell, defaults={"schema": {}})

    if is_team_context_app(comp_aparell):
        registry = build_team_subject_registry(competicio, comp_aparell)
        subject_map = registry["all_by_id"]
        allowed_team_ids = filter_team_subject_ids_for_serie(subject_map, serie_id)
        qs = (
            TeamScoreEntry.objects
            .filter(
                competicio=competicio,
                comp_aparell=comp_aparell,
                exercici__in=exercicis,
                updated_at__gt=dt,
                team_subject_id__in=allowed_team_ids,
            )
            .select_related("team_subject")
            .order_by("updated_at", "id")
        )
    else:
        excluded_ins_ids = (
            InscripcioAparellExclusio.objects
            .filter(comp_aparell=comp_aparell)
            .values_list("inscripcio_id", flat=True)
        )

        qs = (
            ScoreEntry.objects
            .filter(
                competicio=competicio,
                comp_aparell=comp_aparell,
                exercici__in=exercicis,
                updated_at__gt=dt,
            )
            .exclude(inscripcio_id__in=excluded_ins_ids)
            .order_by("updated_at", "id")
        )

    updates = []
    for s in qs[:500]:
        subject_kind = "team_unit" if is_team_context_app(comp_aparell) else "inscripcio"
        subject_id = s.team_subject_id if subject_kind == "team_unit" else s.inscripcio_id
        if subject_kind == "team_unit":
            subject_meta = dict(subject_map.get(int(subject_id), {}))
            subject_meta["team_subject"] = getattr(s, "team_subject", None)
            resolved_permissions = _resolve_permissions_for_subject(permissions, comp_aparell, subject_meta)
            runtime_inputs = (
                logical_team_inputs_to_runtime_inputs(s.inputs, s.team_subject, ss.schema or {})
                if isinstance(s.inputs, dict)
                else {}
            )
        else:
            subject_meta = {}
            resolved_permissions = _resolve_permissions_for_subject(permissions, comp_aparell, None)
            runtime_inputs = s.inputs if isinstance(s.inputs, dict) else {}
        allowed_input_codes = _allowed_input_codes_from_permissions(resolved_permissions)
        payload = {
            **serialize_subject_payload(subject_kind, subject_id),
            "exercici": s.exercici,
            "comp_aparell_id": s.comp_aparell_id,
            "inputs": _filter_inputs_for_allowed_codes(runtime_inputs, allowed_input_codes),
            "outputs": s.outputs or {},
            "total": float(s.total),
            "updated_at": s.updated_at.isoformat(),
        }
        if subject_kind == "team_unit":
            payload.update(team_subject_meta(subject_meta))
        updates.append(payload)

    return JsonResponse({"ok": True, "now": timezone.now().isoformat(), "updates": updates})


@require_http_methods(["GET"])
def judge_video_status(request, token):
    started = time.monotonic()
    req_meta = _request_meta(request)
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        _log_video_event(
            "warning",
            "video_status_denied_token",
            token=str(token),
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse({"ok": False, "error": "Token invàlid o revocat"}, status=403)
    if not _judge_video_capture_enabled_for_token(tok):
        _log_video_event(
            "warning",
            "video_status_disabled_by_config",
            token=str(token),
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse(
            {
                "ok": False,
                "error": "La gravacio de video esta desactivada per aquest QR.",
                "reason": "video_disabled",
            },
            status=403,
        )
    tok.touch()

    subject_payload = {
        "subject_kind": request.GET.get("subject_kind"),
        "subject_id": request.GET.get("subject_id"),
        "inscripcio_id": request.GET.get("inscripcio_id"),
    }
    if not subject_payload.get("subject_id") and not subject_payload.get("inscripcio_id"):
        _log_video_event(
            "warning",
            "video_status_bad_request",
            token=str(token),
            reason="missing_subject_id",
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse({"ok": False, "error": "Falta subject_id/inscripcio_id"}, status=400)

    exercici = _clamp_exercici_for_aparell(tok.comp_aparell, request.GET.get("exercici") or request.GET.get("ex"))
    competicio = tok.competicio
    comp_aparell = tok.comp_aparell

    team_ids = None
    if is_team_context_app(comp_aparell):
        team_ids = list(build_team_subject_registry(competicio, comp_aparell)["eligible_by_id"].keys())
    subject, error_response = resolve_scoring_subject(
        competicio,
        comp_aparell,
        subject_payload,
        eligible_team_ids=team_ids,
    )
    if error_response is not None:
        _log_video_event(
            "warning",
            "video_status_denied_subject",
            token=str(token),
            subject_kind=subject_payload.get("subject_kind") or ("team_unit" if is_team_context_app(comp_aparell) else "inscripcio"),
            subject_id=subject_payload.get("subject_id") or subject_payload.get("inscripcio_id"),
            exercici=exercici,
            comp_aparell_id=comp_aparell.id,
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return error_response

    entry_filters = {
        "competicio": competicio,
        "exercici": exercici,
        "comp_aparell": comp_aparell,
    }
    if subject["subject_kind"] == "team_unit":
        entry_filters["team_subject"] = subject["team_subject"]
    else:
        entry_filters["inscripcio"] = subject["inscripcio"]

    entry = (
        subject_entry_model(comp_aparell).objects
        .filter(**entry_filters)
        .first()
    )
    if not entry:
        _log_video_event(
            "info",
            "video_status_empty",
            token=str(token),
            **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
            exercici=exercici,
            comp_aparell_id=comp_aparell.id,
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse({
            "ok": True,
            "has_video": False,
            **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
            "exercici": exercici,
        })

    video_model, _event_model = subject_video_models(comp_aparell)
    video_lookup = {"team_score_entry": entry} if subject["subject_kind"] == "team_unit" else {"score_entry": entry}
    video = video_model.objects.filter(**video_lookup).first()
    if not video or not video.video_file:
        _log_video_event(
            "info",
            "video_status_no_file",
            token=str(token),
            **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
            exercici=exercici,
            comp_aparell_id=comp_aparell.id,
            score_entry_id=entry.id,
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse(
            {
                "ok": True,
                "has_video": False,
                **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
                "exercici": exercici,
                "score_entry_id": entry.id,
            }
        )

    out = JsonResponse(
        {
            "ok": True,
            "has_video": True,
            **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
            "exercici": exercici,
            "score_entry_id": entry.id,
            "video": _serialize_video_record(video, request),
        }
    )
    _log_video_event(
        "info",
        "video_status_ok",
        token=str(token),
        **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
        exercici=exercici,
        comp_aparell_id=comp_aparell.id,
        score_entry_id=entry.id,
        video_id=video.id,
        latency_ms=int((time.monotonic() - started) * 1000),
        **req_meta,
    )
    return out


@require_POST
@transaction.atomic
def judge_video_upload(request, token):
    started = time.monotonic()
    req_meta = _request_meta(request)
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        _log_video_event(
            "warning",
            "video_upload_denied_token",
            token=str(token),
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse({"ok": False, "error": "Token invàlid o revocat"}, status=403)
    if not _judge_video_capture_enabled_for_token(tok):
        _log_video_event(
            "warning",
            "video_upload_disabled_by_config",
            token=str(token),
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse(
            {
                "ok": False,
                "error": "La gravacio de video esta desactivada per aquest QR.",
                "reason": "video_disabled",
            },
            status=403,
        )
    tok.touch()

    subject_payload = {
        "subject_kind": request.POST.get("subject_kind"),
        "subject_id": request.POST.get("subject_id"),
        "inscripcio_id": request.POST.get("inscripcio_id"),
    }
    if not subject_payload.get("subject_id") and not subject_payload.get("inscripcio_id"):
        _log_video_event(
            "warning",
            "video_upload_bad_request",
            token=str(token),
            reason="missing_subject_id",
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse({"ok": False, "error": "Falta subject_id/inscripcio_id"}, status=400)

    exercici = _clamp_exercici_for_aparell(tok.comp_aparell, request.POST.get("exercici") or request.POST.get("ex"))
    competicio = tok.competicio
    comp_aparell = tok.comp_aparell

    team_ids = None
    if is_team_context_app(comp_aparell):
        team_ids = list(build_team_subject_registry(competicio, comp_aparell)["eligible_by_id"].keys())
    subject, error_response = resolve_scoring_subject(
        competicio,
        comp_aparell,
        subject_payload,
        eligible_team_ids=team_ids,
    )
    if error_response is not None:
        rejected_subject = None
        if is_team_context_app(comp_aparell):
            team_subject_id = subject_payload.get("subject_id")
            team_subject = TeamCompetitiveSubject.objects.filter(
                pk=team_subject_id,
                competicio=competicio,
                comp_aparell=comp_aparell,
            ).select_related("equip", "context").first() if team_subject_id else None
            if team_subject is not None:
                rejected_subject = {
                    "subject_kind": "team_unit",
                    "subject_id": int(team_subject.id),
                    "team_subject": team_subject,
                    "equip": team_subject.equip,
                    "context": team_subject.context,
                }
        else:
            ins_id = subject_payload.get("subject_id") or subject_payload.get("inscripcio_id")
            ins = Inscripcio.objects.filter(pk=ins_id, competicio=competicio).first() if ins_id else None
            if ins is not None:
                rejected_subject = {
                    "subject_kind": "inscripcio",
                    "subject_id": int(ins.id),
                    "inscripcio": ins,
                }
        if rejected_subject is not None:
            _log_video_event(
                "warning",
                "video_upload_rejected",
                token=str(token),
                **serialize_subject_payload(rejected_subject["subject_kind"], rejected_subject["subject_id"]),
                exercici=exercici,
                comp_aparell_id=comp_aparell.id,
                reason="subject_not_allowed",
                http_status=getattr(error_response, "status_code", 403),
                latency_ms=int((time.monotonic() - started) * 1000),
                **req_meta,
            )
            _create_video_audit_event(
                action=ScoreEntryVideoEvent.Action.UPLOAD_REJECTED,
                ok=False,
                http_status=getattr(error_response, "status_code", 403),
                detail="subject not allowed",
                competicio=competicio,
                comp_aparell=comp_aparell,
                subject=rejected_subject,
                judge_token=tok,
                payload={"reason": "subject_not_allowed"},
            )
        return error_response

    def _reject(message, status_code, reason, score_entry=None, payload=None):
        _log_video_event(
            "warning",
            "video_upload_rejected",
            token=str(token),
            **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
            exercici=exercici,
            comp_aparell_id=comp_aparell.id,
            score_entry_id=(score_entry.id if score_entry else None),
            reason=reason,
            http_status=status_code,
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        _create_video_audit_event(
            action=ScoreEntryVideoEvent.Action.UPLOAD_REJECTED,
            ok=False,
            http_status=status_code,
            detail=message,
            competicio=competicio,
            comp_aparell=comp_aparell,
            subject=subject,
            judge_token=tok,
            score_entry=score_entry,
            payload=payload or {"reason": reason},
        )
        return JsonResponse({"ok": False, "error": message}, status=status_code)

    uploaded = request.FILES.get("video_file") or request.FILES.get("video")
    if not uploaded:
        return _reject("Falta el fitxer de video (video_file).", 400, "missing_file")

    file_size = int(getattr(uploaded, "size", 0) or 0)
    if file_size <= 0:
        return _reject("Fitxer de video buit.", 400, "empty_file")
    if file_size > ScoreEntryVideo.VIDEO_MAX_SIZE_BYTES:
        return _reject(
            f"El fitxer supera el limit de {ScoreEntryVideo.VIDEO_MAX_SIZE_BYTES} bytes.",
            400,
            "file_too_large",
            payload={"size": file_size},
        )

    try:
        server_meta = _probe_uploaded_video_metadata(uploaded)
    except VideoValidationError as exc:
        return _reject(
            exc.message,
            400,
            exc.reason,
            payload={"size": file_size, **(exc.payload or {})},
        )

    mime_type = server_meta["mime_type"]
    duration_seconds = server_meta["duration_seconds"]

    entry, _created = get_or_create_subject_entry_locked(
        competicio=competicio,
        comp_aparell=comp_aparell,
        exercici=exercici,
        subject=subject,
        defaults={"inputs": {}, "outputs": {}, "total": 0},
    )

    video_model, event_model = subject_video_models(comp_aparell)
    video_lookup = {"team_score_entry": entry} if subject["subject_kind"] == "team_unit" else {"score_entry": entry}
    video, created_video = video_model.objects.get_or_create(
        **video_lookup,
        defaults={
            "status": video_model.Status.PENDING,
            "file_size_bytes": 0,
        },
    )

    previous_file_name = video.video_file.name if video.video_file else ""

    video.video_file = uploaded
    video.judge_token = tok
    video.status = video_model.Status.READY
    video.duration_seconds = duration_seconds
    video.file_size_bytes = file_size
    video.mime_type = mime_type
    video.original_filename = request.POST.get("original_filename") or (uploaded.name or "")
    video.error_message = ""
    try:
        video.full_clean()
        video.save()
    except ValidationError as exc:
        msg = str(exc)
        return _reject(
            msg,
            400,
            "validation_error",
            score_entry=entry,
            payload={"mime_type": mime_type, "size": file_size},
        )
    except Exception:
        logger.exception("Unexpected error saving uploaded judge video")
        return _reject(
            "Error inesperat guardant el video.",
            500,
            "save_exception",
            score_entry=entry,
            payload={"mime_type": mime_type, "size": file_size},
        )

    if previous_file_name and previous_file_name != video.video_file.name:
        try:
            video.video_file.storage.delete(previous_file_name)
        except Exception:
            pass

    action = ScoreEntryVideoEvent.Action.REPLACE if previous_file_name else ScoreEntryVideoEvent.Action.UPLOAD
    _create_video_audit_event(
        action=action,
        ok=True,
        http_status=200,
        detail="video stored",
        competicio=competicio,
        comp_aparell=comp_aparell,
        subject=subject,
        judge_token=tok,
        score_entry=entry,
        video=video,
        payload={
            "video_id": video.id,
            "mime_type": mime_type,
            "file_size_bytes": file_size,
            "duration_seconds": duration_seconds,
            "format_name": server_meta.get("format_name", ""),
            "video_codec": server_meta.get("video_codec", ""),
            "server_validated": True,
            "replaced_previous": bool(previous_file_name),
        },
    )
    _log_video_event(
        "info",
        "video_upload_ok",
        token=str(token),
        **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
        exercici=exercici,
        comp_aparell_id=comp_aparell.id,
        score_entry_id=entry.id,
        video_id=video.id,
        action=action,
        mime_type=mime_type,
        file_size_bytes=file_size,
        duration_seconds=duration_seconds,
        latency_ms=int((time.monotonic() - started) * 1000),
        **req_meta,
    )

    return JsonResponse(
        {
            "ok": True,
            "created": created_video,
            **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
            "exercici": exercici,
            "score_entry_id": entry.id,
            "video": _serialize_video_record(video, request),
        }
    )


@require_POST
@transaction.atomic
def judge_video_delete(request, token):
    started = time.monotonic()
    req_meta = _request_meta(request)
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        _log_video_event(
            "warning",
            "video_delete_denied_token",
            token=str(token),
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse({"ok": False, "error": "Token invàlid o revocat"}, status=403)
    if not _judge_video_capture_enabled_for_token(tok):
        _log_video_event(
            "warning",
            "video_delete_disabled_by_config",
            token=str(token),
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse(
            {
                "ok": False,
                "error": "La gravacio de video esta desactivada per aquest QR.",
                "reason": "video_disabled",
            },
            status=403,
        )
    tok.touch()

    subject_payload = {
        "subject_kind": request.POST.get("subject_kind"),
        "subject_id": request.POST.get("subject_id"),
        "inscripcio_id": request.POST.get("inscripcio_id"),
    }
    if not subject_payload.get("subject_id") and not subject_payload.get("inscripcio_id"):
        _log_video_event(
            "warning",
            "video_delete_bad_request",
            token=str(token),
            reason="missing_subject_id",
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse({"ok": False, "error": "Falta subject_id/inscripcio_id"}, status=400)

    exercici = _clamp_exercici_for_aparell(tok.comp_aparell, request.POST.get("exercici") or request.POST.get("ex"))
    competicio = tok.competicio
    comp_aparell = tok.comp_aparell

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
        _log_video_event(
            "warning",
            "video_delete_denied_subject",
            token=str(token),
            **serialize_subject_payload(
                str(subject_payload.get("subject_kind") or ("team_unit" if is_team_context_app(comp_aparell) else "inscripcio")),
                int(subject_payload.get("subject_id") or subject_payload.get("inscripcio_id") or 0),
            ),
            exercici=exercici,
            comp_aparell_id=comp_aparell.id,
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return error_response

    entry = (
        subject_entry_model(comp_aparell).objects
        .filter(
            competicio=competicio,
            exercici=exercici,
            comp_aparell=comp_aparell,
            **({"team_subject": subject["team_subject"]} if subject["subject_kind"] == "team_unit" else {"inscripcio": subject["inscripcio"]}),
        )
        .first()
    )
    if not entry:
        _log_video_event(
            "info",
            "video_delete_no_score",
            token=str(token),
            **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
            exercici=exercici,
            comp_aparell_id=comp_aparell.id,
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse(
            {
                "ok": True,
                "deleted": False,
                **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
                "exercici": exercici,
            },
        )

    video_model, _event_model = subject_video_models(comp_aparell)
    video = video_model.objects.filter(
        **({"team_score_entry": entry} if subject["subject_kind"] == "team_unit" else {"score_entry": entry})
    ).first()
    if not video:
        _log_video_event(
            "info",
            "video_delete_no_video",
            token=str(token),
            **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
            exercici=exercici,
            comp_aparell_id=comp_aparell.id,
            score_entry_id=entry.id,
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse(
            {
                "ok": True,
                "deleted": False,
                **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
                "exercici": exercici,
                "score_entry_id": entry.id,
            }
        )

    deleted_path = video.video_file.name if video.video_file else ""
    _create_video_audit_event(
        action=ScoreEntryVideoEvent.Action.DELETE,
        ok=True,
        http_status=200,
        detail="video deleted",
        competicio=competicio,
        comp_aparell=comp_aparell,
        subject=subject,
        judge_token=tok,
        score_entry=entry,
        video=video,
        payload={"deleted_path": deleted_path},
    )

    if video.video_file:
        video.video_file.delete(save=False)
    video.delete()

    _log_video_event(
        "info",
        "video_delete_ok",
        token=str(token),
        **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
        exercici=exercici,
        comp_aparell_id=comp_aparell.id,
        score_entry_id=entry.id,
        deleted_path=deleted_path,
        latency_ms=int((time.monotonic() - started) * 1000),
        **req_meta,
    )

    return JsonResponse(
        {
            "ok": True,
            "deleted": True,
            **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
            "exercici": exercici,
            "score_entry_id": entry.id,
        }
    )

def _apply_sanitized_patch(current_inputs: dict, sanitized_patch: dict, schema: dict) -> dict:
    out = dict(current_inputs or {})

    by_code = {f.get("code"): f for f in (schema.get("fields") or []) if isinstance(f, dict) and f.get("code")}

    for code, payload in sanitized_patch.items():
        if isinstance(code, str) and code.startswith("__crash__"):
            base_code = code[len("__crash__"):]
            f = by_code.get(base_code, {})
            crash_cfg = f.get("crash") if isinstance(f.get("crash"), dict) else {}
            if (f.get("type") or "number") != "matrix" or not crash_cfg.get("enabled"):
                continue
            if isinstance(payload, dict) and "__set_list__" in payload:
                cur = out.get(code)
                cur = cur if isinstance(cur, list) else []
                max_idx = max((i for i, _ in payload["__set_list__"]), default=-1)
                while len(cur) <= max_idx:
                    cur.append(0)
                for i, v in payload["__set_list__"]:
                    cur[i] = v
                out[code] = cur
            continue

        f = by_code.get(code, {})
        ftype = f.get("type") or "number"

        if ftype == "number":
            out[code] = payload
            continue

        if ftype == "list" and isinstance(payload, dict) and "__set_list__" in payload:
            cur = out.get(code)
            cur = cur if isinstance(cur, list) else []
            # assegura llargada
            max_idx = max((i for i,_ in payload["__set_list__"]), default=-1)
            while len(cur) <= max_idx:
                cur.append(None)
            for i, v in payload["__set_list__"]:
                cur[i] = v
            out[code] = cur
            continue

        if ftype == "matrix" and isinstance(payload, dict) and "__set_matrix__" in payload:
            cur = out.get(code)
            cur = cur if isinstance(cur, list) else []
            # assegura files
            max_row = max((r for r,_,__ in payload["__set_matrix__"]), default=-1)
            while len(cur) <= max_row:
                cur.append([])
            # assegura cols per cada fila que toquem
            n_items = int(((f.get("items") or {}).get("count")) or 0) or 1
            for r, c, v in payload["__set_matrix__"]:
                row = cur[r] if isinstance(cur[r], list) else []
                while len(row) < n_items:
                    row.append(None)
                row[c] = v
                cur[r] = row
            out[code] = cur
            continue

    return out



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

    subject_payload = {
        "subject_kind": payload.get("subject_kind"),
        "subject_id": payload.get("subject_id"),
        "inscripcio_id": payload.get("inscripcio_id"),
    }
    exercici_raw = payload.get("exercici")
    inputs_patch = payload.get("inputs_patch", {})
    competicio: Competicio = tok.competicio
    comp_aparell: CompeticioAparell = tok.comp_aparell
    exercici = _clamp_exercici_for_aparell(comp_aparell, exercici_raw)

    if not subject_payload.get("subject_id") and not subject_payload.get("inscripcio_id"):
        return JsonResponse({"ok": False, "error": "Falta subject_id/inscripcio_id"}, status=400)
    if not isinstance(inputs_patch, dict):
        return JsonResponse({"ok": False, "error": "inputs_patch ha de ser objecte JSON"}, status=400)

    permissions = _normalize_permissions(tok.permissions)

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

    ss, _ = ScoringSchema.objects.get_or_create(aparell=comp_aparell.aparell, defaults={"schema": {}})
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
    schema = runtime_schema_for_comp_aparell(ss.schema or {}, comp_aparell, member_count=team_member_count)

    entry, _ = get_or_create_subject_entry_locked(
        competicio=competicio,
        comp_aparell=comp_aparell,
        exercici=exercici,
        subject=subject,
        defaults={"inputs": {}, "outputs": {}, "total": 0},
    )

    sanitized = _sanitize_patch_by_permissions(schema, resolved_permissions, inputs_patch)
    current_inputs = entry.inputs if isinstance(entry.inputs, dict) else {}
    if team_subject is not None:
        current_inputs = logical_team_inputs_to_runtime_inputs(current_inputs, team_subject, ss.schema or {})

    # MERGE per no trepitjar altres camps/jutges
    merged_inputs = _apply_sanitized_patch(current_inputs, sanitized, schema)

    # Filtrat d'inputs segons schema.fields (mateixa idea que tens a scoring_save)
    allowed = set()
    for f in (schema.get("fields") or []):
        if isinstance(f, dict) and f.get("code"):
            allowed.add(f["code"])
            allowed.add(f"__crash__{f['code']}")

    clean_inputs = {k: v for k, v in merged_inputs.items() if k in allowed}

    try:
        engine = ScoringEngine(schema)
        result = engine.compute(clean_inputs)
    except ScoringError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Error inesperat calculant puntuació"}, status=500)

    entry.inputs = (
        runtime_inputs_to_logical_team_inputs(result.inputs, team_subject, ss.schema or {})
        if team_subject is not None
        else result.inputs
    )
    entry.outputs = result.outputs
    entry.total = result.total
    entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])

    return JsonResponse({
        "ok": True,
        **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
        "inputs": _filter_inputs_for_allowed_codes(result.inputs if team_subject is not None else entry.inputs, allowed_input_codes),
        "outputs": entry.outputs or {},
        "total": float(entry.total),
        "updated_at": entry.updated_at.isoformat(),
    })

