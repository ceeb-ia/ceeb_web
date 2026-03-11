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
from .models import Inscripcio, Competicio
from .models_trampoli import CompeticioAparell, InscripcioAparellExclusio
from .models_rotacions import RotacioAssignacio, RotacioFranja
from .models_scoring import ScoreEntry, ScoreEntryVideo, ScoreEntryVideoEvent, ScoringSchema
from .scoring_engine import ScoringEngine, ScoringError
from .services.competition_groups import (
    get_group_maps,
    get_inscripcio_competition_order,
    group_label,
    show_out_of_program_in_competition_views,
)
from .services.rotacions_ordering import (
    ORDER_MODE_MAINTAIN,
    assignacio_grups,
    build_group_rotation_step_map,
    effective_rotate_steps,
    get_rotacions_order_modes,
    order_pairs_for_mode,
    unique_ordered,
)

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



def _inscripcio_exclosa_en_aparell(inscripcio_id: int, comp_aparell_id: int) -> bool:
    return InscripcioAparellExclusio.objects.filter(
        inscripcio_id=inscripcio_id,
        comp_aparell_id=comp_aparell_id,
    ).exists()


def _get_or_create_scoreentry_locked(*, competicio, inscripcio, exercici, comp_aparell, defaults=None):
    """
    Get-or-create with row lock to avoid concurrent lost updates on score inputs.
    Must be called inside transaction.atomic().
    """
    lookup = {
        "competicio": competicio,
        "inscripcio": inscripcio,
        "exercici": exercici,
        "comp_aparell": comp_aparell,
    }
    defaults = defaults or {}

    entry = (
        ScoreEntry.objects
        .select_for_update()
        .filter(**lookup)
        .first()
    )
    if entry is not None:
        return entry, False

    try:
        entry = ScoreEntry.objects.create(**lookup, **defaults)
        return entry, True
    except IntegrityError:
        entry = (
            ScoreEntry.objects
            .select_for_update()
            .get(**lookup)
        )
        return entry, False


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
        perms_by_code.setdefault(p["field_code"], []).append(p)

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
        code = p.get("field_code")
        if not code:
            continue
        out.append({
            "field_code": str(code),
            "judge_index": int(p.get("judge_index") or 1),
            "item_start": int(p.get("item_start") or 1),
            "item_count": (None if p.get("item_count") in (None, "", "null") else int(p["item_count"])),
        })
    return out


def _allowed_input_codes_from_permissions(permissions: list) -> set:
    allowed_codes = set()
    for p in permissions or []:
        code = p.get("field_code")
        if not code:
            continue
        allowed_codes.add(str(code))
        allowed_codes.add(f"__crash__{code}")
    return allowed_codes


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
    inscripcio,
    judge_token=None,
    score_entry=None,
    video=None,
    payload=None,
):
    try:
        ScoreEntryVideoEvent.objects.create(
            action=action,
            ok=bool(ok),
            http_status=int(http_status or 0),
            detail=(detail or "")[:255],
            payload=payload or {},
            competicio=competicio,
            comp_aparell=comp_aparell,
            inscripcio=inscripcio,
            judge_token=judge_token,
            score_entry=score_entry,
            video=video,
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
    schema = ss.schema or {}

    permissions = _normalize_permissions(tok.permissions)
    allowed_input_codes = _allowed_input_codes_from_permissions(permissions)

    franja_modes = get_rotacions_order_modes(competicio)

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
        .prefetch_related("grup_links__grup")
        .order_by("franja__ordre", "franja_id", "estacio__ordre", "id")
    )
    rotation_step_map = build_group_rotation_step_map(all_assigns, franja_modes)
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

    # Llista d'inscripcions base (mateix criteri que notes home)
    excluded_ins_ids = (
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

    # El portal mostra tots els grups programats de l'aparell i calcula la
    # posicio efectiva segons la primera franja assignada a cada grup, amb
    # suport d'override per query string quan arriba ?franja=...
    ins_list = []
    grouped = {}
    for ins in ins_base_qs:
        key = 0 if ins.grup_competicio_id in (None, 0) else int(ins.grup_competicio_id)
        grouped.setdefault(key, []).append(ins)

    ordered_groups = [g for g in app_programmed_group_ids if g in grouped]
    remaining_groups = sorted(g for g in grouped.keys() if g not in app_programmed_group_ids and g != 0)
    always_visible_group_ids = list(ordered_groups)
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

    def group_label_for(group_id: int) -> str:
        if group_id in (None, 0):
            return "Sense grup"
        return group_label(groups_by_id.get(group_id))

    def build_group_block(group_id):
        group_items = grouped.get(group_id, [])
        base_pairs = [(ins.id, ins) for ins in group_items]
        fid = resolve_group_franja_id(group_id)
        mode_for_group = franja_modes.get(str(fid), ORDER_MODE_MAINTAIN) if fid else ORDER_MODE_MAINTAIN
        rotate_steps = effective_rotate_steps(
            mode_for_group,
            rotation_step_map.get((group_id, fid), 0) if fid else 0,
        )
        seed_franja = fid if fid is not None else 0

        ordered_pairs = order_pairs_for_mode(
            base_pairs,
            mode_for_group,
            rotate_steps=rotate_steps,
            seed_prefix=f"judge|{competicio.id}|{seed_franja}|{comp_aparell.id}|{group_id}",
        )
        ordered_ins = []
        for rank, (_ins_id, ins) in enumerate(ordered_pairs, start=1):
            ins.rotation_order_display = rank
            ins.rotation_base_order_display = get_inscripcio_competition_order(ins)
            ordered_ins.append(ins)
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
            "list": ordered_ins,
        }

    programmed_group_blocks = []
    out_of_program_group_blocks = []
    for g in always_visible_group_ids:
        block = build_group_block(g)
        programmed_group_blocks.append(block)
        ins_list.extend(block["list"])
    if show_out_of_program_groups:
        for g in remaining_groups:
            block = build_group_block(g)
            out_of_program_group_blocks.append(block)
            ins_list.extend(block["list"])

    # Prefetch entries existents (per mostrar valors actuals)
    ins_ids = [ins.id for ins in ins_list]
    entries = ScoreEntry.objects.filter(
        competicio=competicio,
        comp_aparell=comp_aparell,
        inscripcio_id__in=ins_ids,
    )
    entry_map = {}
    for e in entries:
        entry_map[(e.inscripcio_id, e.exercici)] = e

    # Construïm un “snapshot” dels inputs rellevants per inscripció/exercici
    # Per simplicitat: assumim exercici=1 si al teu flux n’hi ha més, ho pots estendre.
    max_ex = max(1, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1))
    exercicis = list(range(1, max_ex + 1))
    exercici_default = _clamp_exercici_for_aparell(comp_aparell, request.GET.get("ex"))
    scores_payload = {}
    for ins in ins_list:
        e = entry_map.get((ins.id, exercici_default))
        scores_payload[str(ins.id)] = {
            "inputs": (
                _filter_inputs_for_allowed_codes(e.inputs, allowed_input_codes)
                if e and isinstance(e.inputs, dict)
                else {}
            ),
            "outputs": (e.outputs if e and isinstance(e.outputs, dict) else {}),
            "total": (float(e.total) if e else 0.0),
            "updated_at": (e.updated_at.isoformat() if e else None),
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
        "inscripcions": ins_list,
        "group_blocks": programmed_group_blocks,
        "out_of_program_group_blocks": out_of_program_group_blocks,
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
    exercici = _clamp_exercici_for_aparell(comp_aparell, request.GET.get("exercici") or request.GET.get("ex"))
    permissions = _normalize_permissions(tok.permissions)
    allowed_input_codes = _allowed_input_codes_from_permissions(permissions)

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
            exercici=exercici,
            updated_at__gt=dt,
        )
        .exclude(inscripcio_id__in=excluded_ins_ids)
        .order_by("updated_at", "id")
    )

    updates = []
    for s in qs[:500]:
        updates.append({
            "inscripcio_id": s.inscripcio_id,
            "exercici": s.exercici,
            "comp_aparell_id": s.comp_aparell_id,
            "inputs": _filter_inputs_for_allowed_codes(s.inputs, allowed_input_codes),
            "outputs": s.outputs or {},
            "total": float(s.total),
            "updated_at": s.updated_at.isoformat(),
        })

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

    ins_id = request.GET.get("inscripcio_id")
    if not ins_id:
        _log_video_event(
            "warning",
            "video_status_bad_request",
            token=str(token),
            reason="missing_inscripcio_id",
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse({"ok": False, "error": "Falta inscripcio_id"}, status=400)

    exercici = _clamp_exercici_for_aparell(tok.comp_aparell, request.GET.get("exercici") or request.GET.get("ex"))
    competicio = tok.competicio
    comp_aparell = tok.comp_aparell

    ins = get_object_or_404(Inscripcio, pk=ins_id, competicio=competicio)
    if _inscripcio_exclosa_en_aparell(ins.id, comp_aparell.id):
        _log_video_event(
            "warning",
            "video_status_denied_excluded",
            token=str(token),
            inscripcio_id=ins.id,
            exercici=exercici,
            comp_aparell_id=comp_aparell.id,
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse(
            {"ok": False, "error": "Aquesta inscripcio no competeix en aquest aparell."},
            status=403,
        )

    entry = (
        ScoreEntry.objects
        .filter(
            competicio=competicio,
            inscripcio=ins,
            exercici=exercici,
            comp_aparell=comp_aparell,
        )
        .first()
    )
    if not entry:
        _log_video_event(
            "info",
            "video_status_empty",
            token=str(token),
            inscripcio_id=ins.id,
            exercici=exercici,
            comp_aparell_id=comp_aparell.id,
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse(
            {"ok": True, "has_video": False, "inscripcio_id": ins.id, "exercici": exercici},
        )

    video = ScoreEntryVideo.objects.filter(score_entry=entry).first()
    if not video or not video.video_file:
        _log_video_event(
            "info",
            "video_status_no_file",
            token=str(token),
            inscripcio_id=ins.id,
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
                "inscripcio_id": ins.id,
                "exercici": exercici,
                "score_entry_id": entry.id,
            }
        )

    out = JsonResponse(
        {
            "ok": True,
            "has_video": True,
            "inscripcio_id": ins.id,
            "exercici": exercici,
            "score_entry_id": entry.id,
            "video": _serialize_video_record(video, request),
        }
    )
    _log_video_event(
        "info",
        "video_status_ok",
        token=str(token),
        inscripcio_id=ins.id,
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

    ins_id = request.POST.get("inscripcio_id")
    if not ins_id:
        _log_video_event(
            "warning",
            "video_upload_bad_request",
            token=str(token),
            reason="missing_inscripcio_id",
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse({"ok": False, "error": "Falta inscripcio_id"}, status=400)

    exercici = _clamp_exercici_for_aparell(tok.comp_aparell, request.POST.get("exercici") or request.POST.get("ex"))
    competicio = tok.competicio
    comp_aparell = tok.comp_aparell

    ins = get_object_or_404(Inscripcio, pk=ins_id, competicio=competicio)

    def _reject(message, status_code, reason, score_entry=None, payload=None):
        _log_video_event(
            "warning",
            "video_upload_rejected",
            token=str(token),
            inscripcio_id=ins.id,
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
            inscripcio=ins,
            judge_token=tok,
            score_entry=score_entry,
            payload=payload or {"reason": reason},
        )
        return JsonResponse({"ok": False, "error": message}, status=status_code)

    if _inscripcio_exclosa_en_aparell(ins.id, comp_aparell.id):
        return _reject(
            "Aquesta inscripcio no competeix en aquest aparell.",
            403,
            "inscripcio_excluded",
            payload={"inscripcio_id": ins.id},
        )

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

    entry, _created = _get_or_create_scoreentry_locked(
        competicio=competicio,
        inscripcio=ins,
        exercici=exercici,
        comp_aparell=comp_aparell,
        defaults={"inputs": {}, "outputs": {}, "total": 0},
    )

    video, created_video = ScoreEntryVideo.objects.get_or_create(
        score_entry=entry,
        defaults={
            "status": ScoreEntryVideo.Status.PENDING,
            "file_size_bytes": 0,
        },
    )

    previous_file_name = video.video_file.name if video.video_file else ""

    video.video_file = uploaded
    video.judge_token = tok
    video.status = ScoreEntryVideo.Status.READY
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
        inscripcio=ins,
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
        inscripcio_id=ins.id,
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
            "inscripcio_id": ins.id,
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

    ins_id = request.POST.get("inscripcio_id")
    if not ins_id:
        _log_video_event(
            "warning",
            "video_delete_bad_request",
            token=str(token),
            reason="missing_inscripcio_id",
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse({"ok": False, "error": "Falta inscripcio_id"}, status=400)

    exercici = _clamp_exercici_for_aparell(tok.comp_aparell, request.POST.get("exercici") or request.POST.get("ex"))
    competicio = tok.competicio
    comp_aparell = tok.comp_aparell

    ins = get_object_or_404(Inscripcio, pk=ins_id, competicio=competicio)
    if _inscripcio_exclosa_en_aparell(ins.id, comp_aparell.id):
        _log_video_event(
            "warning",
            "video_delete_denied_excluded",
            token=str(token),
            inscripcio_id=ins.id,
            exercici=exercici,
            comp_aparell_id=comp_aparell.id,
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse(
            {"ok": False, "error": "Aquesta inscripcio no competeix en aquest aparell."},
            status=403,
        )

    entry = (
        ScoreEntry.objects
        .filter(
            competicio=competicio,
            inscripcio=ins,
            exercici=exercici,
            comp_aparell=comp_aparell,
        )
        .first()
    )
    if not entry:
        _log_video_event(
            "info",
            "video_delete_no_score",
            token=str(token),
            inscripcio_id=ins.id,
            exercici=exercici,
            comp_aparell_id=comp_aparell.id,
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse(
            {"ok": True, "deleted": False, "inscripcio_id": ins.id, "exercici": exercici},
        )

    video = ScoreEntryVideo.objects.filter(score_entry=entry).first()
    if not video:
        _log_video_event(
            "info",
            "video_delete_no_video",
            token=str(token),
            inscripcio_id=ins.id,
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
                "inscripcio_id": ins.id,
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
        inscripcio=ins,
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
        inscripcio_id=ins.id,
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
            "inscripcio_id": ins.id,
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

    ins_id = payload.get("inscripcio_id")
    exercici_raw = payload.get("exercici")
    inputs_patch = payload.get("inputs_patch", {})

    if not ins_id:
        return JsonResponse({"ok": False, "error": "Falta inscripcio_id"}, status=400)
    if not isinstance(inputs_patch, dict):
        return JsonResponse({"ok": False, "error": "inputs_patch ha de ser objecte JSON"}, status=400)

    # Seguretat: només permetre editar camps que apareixen a permissions
    permissions = _normalize_permissions(tok.permissions)
    allowed_codes = {p["field_code"] for p in permissions}
    allowed_input_codes = _allowed_input_codes_from_permissions(permissions)
    allowed_patch_codes = set(allowed_codes)
    allowed_patch_codes.update({f"__crash__{code}" for code in allowed_codes})
    patch_codes = set(inputs_patch.keys())
    if not patch_codes.issubset(allowed_patch_codes):
        return JsonResponse({"ok": False, "error": "Intentes editar un camp no autoritzat per aquest QR"}, status=403)

    competicio: Competicio = tok.competicio
    comp_aparell: CompeticioAparell = tok.comp_aparell
    exercici = _clamp_exercici_for_aparell(comp_aparell, exercici_raw)

    ins = get_object_or_404(Inscripcio, pk=ins_id, competicio=competicio)
    if _inscripcio_exclosa_en_aparell(ins.id, comp_aparell.id):
        return JsonResponse(
            {"ok": False, "error": "Aquesta inscripcio no competeix en aquest aparell."},
            status=403,
        )

    ss, _ = ScoringSchema.objects.get_or_create(aparell=comp_aparell.aparell, defaults={"schema": {}})
    schema = ss.schema or {}

    entry, _ = _get_or_create_scoreentry_locked(
        competicio=competicio,
        inscripcio=ins,
        exercici=exercici,
        comp_aparell=comp_aparell,
        defaults={"inputs": {}, "outputs": {}, "total": 0},
    )

    sanitized = _sanitize_patch_by_permissions(schema, permissions, inputs_patch)
    current_inputs = entry.inputs if isinstance(entry.inputs, dict) else {}

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

    entry.inputs = result.inputs
    entry.outputs = result.outputs
    entry.total = result.total
    entry.save(update_fields=["inputs", "outputs", "total", "updated_at"])

    return JsonResponse({
        "ok": True,
        "inputs": _filter_inputs_for_allowed_codes(entry.inputs, allowed_input_codes),
        "outputs": entry.outputs or {},
        "total": float(entry.total),
        "updated_at": entry.updated_at.isoformat(),
    })

