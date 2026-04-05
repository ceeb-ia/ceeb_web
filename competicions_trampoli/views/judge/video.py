import logging
import time

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods

from ...models import Inscripcio
from ...models.judging import JudgeDeviceToken
from ...models.scoring import ScoreEntryVideo, ScoreEntryVideoEvent, TeamCompetitiveSubject
from ...services.scoring.scoring_subjects import (
    get_or_create_subject_entry_locked,
    resolve_scoring_subject,
    serialize_subject_payload,
    subject_entry_model,
    subject_video_models,
)
from ...services.scoring.team_scoring import build_team_subjects_for_comp_aparell, is_team_context_app
from ...services.scoring.team_subject_contract import build_team_subject_registry
from ._shared import (
    VideoValidationError,
    _clamp_exercici_for_aparell,
    _create_video_audit_event,
    _judge_video_capture_enabled_for_token,
    _log_video_event,
    _probe_uploaded_video_metadata,
    _protected_video_response,
    _request_meta,
    _serialize_video_record,
    _video_belongs_to_same_token,
)

logger = logging.getLogger(__name__)


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
            "video": _serialize_video_record(
                video,
                request,
                token_obj=tok,
                subject=subject,
                exercici=exercici,
            ),
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
    if not created_video and getattr(video, "judge_token_id", None) and not _video_belongs_to_same_token(video, tok):
        return _reject(
            "Aquest video ja esta vinculat a un altre QR i no es pot substituir des d'aquest dispositiu.",
            403,
            "video_owned_by_other_token",
            score_entry=entry,
            payload={"existing_video_id": video.id},
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
            "video": _serialize_video_record(
                video,
                request,
                token_obj=tok,
                subject=subject,
                exercici=exercici,
            ),
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

    if getattr(video, "judge_token_id", None) and not _video_belongs_to_same_token(video, tok):
        _log_video_event(
            "warning",
            "video_delete_denied_owner",
            token=str(token),
            **serialize_subject_payload(subject["subject_kind"], subject["subject_id"]),
            exercici=exercici,
            comp_aparell_id=comp_aparell.id,
            score_entry_id=entry.id,
            video_id=video.id,
            latency_ms=int((time.monotonic() - started) * 1000),
            **req_meta,
        )
        return JsonResponse(
            {
                "ok": False,
                "error": "Aquest video esta vinculat a un altre QR i no es pot esborrar des d'aquest dispositiu.",
                "reason": "video_owned_by_other_token",
            },
            status=403,
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


@require_http_methods(["GET"])
def judge_video_file(request, token, subject_kind, subject_id, exercici):
    tok = get_object_or_404(JudgeDeviceToken, pk=token)
    if not tok.is_valid():
        raise Http404("Token invalid")
    if not _judge_video_capture_enabled_for_token(tok):
        raise Http404("Video disabled")

    comp_aparell = tok.comp_aparell
    competicio = tok.competicio
    eligible_team_ids = None
    if is_team_context_app(comp_aparell):
        eligible_team_ids = list(build_team_subject_registry(competicio, comp_aparell)["eligible_by_id"].keys())

    subject, error_response = resolve_scoring_subject(
        competicio,
        comp_aparell,
        {"subject_kind": subject_kind, "subject_id": subject_id},
        eligible_team_ids=eligible_team_ids,
    )
    if error_response is not None:
        raise Http404("Subject invalid")

    entry_filters = {
        "competicio": competicio,
        "exercici": _clamp_exercici_for_aparell(comp_aparell, exercici),
        "comp_aparell": comp_aparell,
    }
    if subject["subject_kind"] == "team_unit":
        entry_filters["team_subject"] = subject["team_subject"]
    else:
        entry_filters["inscripcio"] = subject["inscripcio"]
    entry = subject_entry_model(comp_aparell).objects.filter(**entry_filters).first()
    if not entry:
        raise Http404("Score absent")

    video_model, _event_model = subject_video_models(comp_aparell)
    video_lookup = {"team_score_entry": entry} if subject["subject_kind"] == "team_unit" else {"score_entry": entry}
    video_obj = video_model.objects.filter(**video_lookup).first()
    if not video_obj:
        raise Http404("Video absent")

    return _protected_video_response(
        video_obj.video_file,
        original_filename=video_obj.original_filename,
        mime_type=video_obj.mime_type,
    )
