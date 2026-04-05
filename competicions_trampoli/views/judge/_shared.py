import io
import json
import logging
import math
import mimetypes
import os
import subprocess
import tempfile

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.urls import reverse

from ...models.scoring import ScoreEntryVideo
from ...services.scoring_subjects import serialize_subject_payload, subject_video_models
from ...services.update_payloads import (
    filter_inputs_for_allowed_codes as shared_filter_inputs_for_allowed_codes,
)

logger = logging.getLogger(__name__)

try:
    import qrcode
except ImportError:  # pragma: no cover - optional at import time, required at runtime for QR endpoints.
    qrcode = None


class VideoValidationError(Exception):
    def __init__(self, message: str, reason: str = "video_validation_failed", payload=None):
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.payload = payload or {}


def _require_qrcode():
    if qrcode is None:
        raise RuntimeError("La dependencia 'qrcode' no esta disponible.")
    return qrcode


def _qr_png_response(url: str) -> HttpResponse:
    img = _require_qrcode().make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")


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


def _filter_inputs_for_allowed_codes(inputs: dict, allowed_codes: set) -> dict:
    return shared_filter_inputs_for_allowed_codes(inputs, allowed_codes)


def _subject_dom_id(subject) -> str:
    if not isinstance(subject, dict):
        return ""
    raw_id = subject.get("id")
    if raw_id not in (None, ""):
        return str(raw_id)
    subject_id = subject.get("subject_id")
    return "" if subject_id in (None, "") else str(subject_id)


def _clamp_exercici_for_aparell(comp_aparell, exercici_raw):
    try:
        exercici = int(exercici_raw or 1)
    except Exception:
        exercici = 1
    max_ex = max(1, int(getattr(comp_aparell, "nombre_exercicis", 1) or 1))
    return max(1, min(max_ex, exercici))


def _judge_video_capture_enabled_for_token(tok) -> bool:
    return bool(getattr(tok, "can_record_video", False))


def _protected_video_response(video_file, *, original_filename: str = "", mime_type: str = ""):
    if not video_file or not getattr(video_file, "name", ""):
        raise Http404("Video no disponible")
    try:
        file_handle = video_file.open("rb")
    except Exception as exc:
        raise Http404("Video no disponible") from exc
    response = FileResponse(file_handle, as_attachment=False, filename=(original_filename or "").strip() or None)
    if mime_type:
        response["Content-Type"] = mime_type
    return response


def _serialize_video_record(video_record, request, *, token_obj=None, subject=None, exercici=None):
    url = None
    if video_record.video_file and token_obj is not None and subject is not None and exercici is not None:
        try:
            media_url = reverse(
                "judge_video_file",
                kwargs={
                    "token": str(token_obj.id),
                    "subject_kind": str(subject.get("subject_kind") or "inscripcio"),
                    "subject_id": int(subject.get("subject_id") or 0),
                    "exercici": int(exercici),
                },
            )
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


def _redact_token_value(value) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"


def _sanitize_video_log_payload(payload: dict) -> dict:
    clean = {}
    for key, value in (payload or {}).items():
        if key in {"token", "judge_token"}:
            clean[key] = _redact_token_value(value)
        else:
            clean[key] = value
    return clean


def _log_video_event(level: str, event: str, **payload):
    raw = {"event": event}
    raw.update(_sanitize_video_log_payload(payload))
    msg = json.dumps(raw, ensure_ascii=True, sort_keys=True)
    if level == "error":
        logger.error(msg)
    elif level == "warning":
        logger.warning(msg)
    else:
        logger.info(msg)


def _video_belongs_to_same_token(video_obj, tok) -> bool:
    return bool(video_obj and getattr(video_obj, "judge_token_id", None) == getattr(tok, "id", None))


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
        event_model.objects.create(**create_kwargs)
    except Exception:
        logger.exception("Unable to persist ScoreEntryVideoEvent")
