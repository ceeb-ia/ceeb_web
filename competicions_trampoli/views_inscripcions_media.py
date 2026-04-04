import json
import mimetypes
import os
from decimal import Decimal

from django.db import transaction
from django.http import FileResponse, Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .models import Competicio, Inscripcio, InscripcioMedia
from .services.inscripcions.history import with_inscripcions_history_payload
from .services.media_matching import (
    build_inscripcio_media_match_candidates,
    match_media_files_to_inscripcions,
    normalize_media_matching_config,
)


MEDIA_MAX_SIZE_BYTES = 250 * 1024 * 1024
MEDIA_ALLOWED_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".ogg",
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".jpg",
    ".jpeg",
    ".png",
}


def _get_media_matching_config(competicio):
    view_cfg = competicio.inscripcions_view or {}
    return normalize_media_matching_config(view_cfg.get("media_matching"))


def _load_json_body(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        raise ValueError("JSON invalid")


def _guess_media_tipus(*, mime_type: str, filename: str) -> str:
    mime_l = str(mime_type or "").strip().lower()
    if mime_l.startswith("audio/"):
        return InscripcioMedia.Tipus.AUDIO
    if mime_l.startswith("video/"):
        return InscripcioMedia.Tipus.VIDEO
    if mime_l.startswith("image/"):
        return InscripcioMedia.Tipus.IMAGE

    ext = os.path.splitext(str(filename or ""))[1].lower()
    if ext in {".mp3", ".wav", ".m4a", ".aac", ".ogg"}:
        return InscripcioMedia.Tipus.AUDIO
    if ext in {".mp4", ".mov", ".m4v", ".webm"}:
        return InscripcioMedia.Tipus.VIDEO
    if ext in {".jpg", ".jpeg", ".png"}:
        return InscripcioMedia.Tipus.IMAGE
    return InscripcioMedia.Tipus.OTHER


def _validate_uploaded_media_file(uploaded):
    if uploaded is None:
        raise ValueError("Falta fitxer multimèdia.")
    size = int(getattr(uploaded, "size", 0) or 0)
    if size <= 0:
        raise ValueError("Fitxer buit.")
    if size > MEDIA_MAX_SIZE_BYTES:
        raise ValueError(f"El fitxer supera el limit de {MEDIA_MAX_SIZE_BYTES} bytes.")

    filename = str(getattr(uploaded, "name", "") or "").strip()
    ext = os.path.splitext(filename)[1].lower()
    if ext not in MEDIA_ALLOWED_EXTENSIONS:
        raise ValueError("Extensio de fitxer no permesa.")

    mime_type = str(getattr(uploaded, "content_type", "") or "").strip().lower()
    if not mime_type:
        mime_type = str(mimetypes.guess_type(filename)[0] or "").strip().lower()
    return {
        "filename": filename,
        "size": size,
        "mime_type": mime_type,
        "tipus": _guess_media_tipus(mime_type=mime_type, filename=filename),
    }


def _serialize_media_item(item):
    return {
        "id": item.id,
        "inscripcio_id": item.inscripcio_id,
        "tipus": item.tipus,
        "mime_type": item.mime_type or "",
        "original_filename": item.original_filename or "",
        "file_size_bytes": int(item.file_size_bytes or 0),
        "is_primary": bool(item.is_primary),
        "source": item.source or "",
        "match_score": float(item.match_score) if item.match_score is not None else None,
        "url": reverse(
            "inscripcions_media_file",
            kwargs={"pk": item.competicio_id, "media_id": item.id},
        ),
    }


def _create_inscripcio_media_record(*, competicio, inscripcio, uploaded, source: str, match_score=None, force_primary: bool = False):
    meta = _validate_uploaded_media_file(uploaded)
    match_decimal = None
    if match_score not in (None, ""):
        try:
            match_decimal = Decimal(str(match_score))
        except Exception:
            match_decimal = None

    tipus = meta["tipus"]
    with transaction.atomic():
        existing_qs = InscripcioMedia.objects.filter(competicio=competicio, inscripcio=inscripcio, tipus=tipus)
        will_be_primary = bool(force_primary) or (not existing_qs.filter(is_primary=True).exists())
        if will_be_primary:
            existing_qs.update(is_primary=False)

        item = InscripcioMedia.objects.create(
            competicio=competicio,
            inscripcio=inscripcio,
            fitxer=uploaded,
            tipus=tipus,
            mime_type=meta["mime_type"],
            original_filename=meta["filename"],
            file_size_bytes=meta["size"],
            is_primary=will_be_primary,
            source=source,
            match_score=match_decimal,
        )
    return item


def inscripcions_media_file(request, pk, media_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    item = get_object_or_404(
        InscripcioMedia.objects.select_related("inscripcio"),
        pk=media_id,
        competicio=competicio,
    )
    if not item.fitxer or not getattr(item.fitxer, "name", ""):
        raise Http404("Fitxer no disponible")
    try:
        file_handle = item.fitxer.open("rb")
    except Exception as exc:
        raise Http404("Fitxer no disponible") from exc
    response = FileResponse(
        file_handle,
        as_attachment=False,
        filename=(item.original_filename or "").strip() or None,
    )
    if item.mime_type:
        response["Content-Type"] = item.mime_type
    return response


@require_POST
@csrf_protect
def inscripcions_media_upload(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        inscripcio_id = int(request.POST.get("inscripcio_id"))
    except Exception:
        return HttpResponseBadRequest("inscripcio_id invalid")

    inscripcio = get_object_or_404(Inscripcio, pk=inscripcio_id, competicio=competicio)
    uploaded = request.FILES.get("media_file") or request.FILES.get("file")
    set_primary = str(request.POST.get("set_primary") or "").strip().lower() in {"1", "true", "yes", "on"}
    try:
        item = _create_inscripcio_media_record(
            competicio=competicio,
            inscripcio=inscripcio,
            uploaded=uploaded,
            source=InscripcioMedia.Source.MANUAL,
            force_primary=set_primary,
        )
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    payload = {"ok": True, "item": _serialize_media_item(item), "inscripcio_id": inscripcio.id}
    return JsonResponse(with_inscripcions_history_payload(payload, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_media_delete(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = _load_json_body(request)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    try:
        media_id = int(payload.get("media_id"))
    except Exception:
        return HttpResponseBadRequest("media_id invalid")

    item = get_object_or_404(InscripcioMedia, pk=media_id, competicio=competicio)
    was_primary = bool(item.is_primary)
    inscripcio_id = item.inscripcio_id
    tipus = item.tipus
    if item.fitxer:
        item.fitxer.delete(save=False)
    item.delete()

    if was_primary:
        next_item = (
            InscripcioMedia.objects.filter(competicio=competicio, inscripcio_id=inscripcio_id, tipus=tipus)
            .order_by("-created_at", "id")
            .first()
        )
        if next_item:
            next_item.is_primary = True
            next_item.save(update_fields=["is_primary"])

    response = {"ok": True, "deleted_media_id": media_id, "inscripcio_id": inscripcio_id}
    return JsonResponse(with_inscripcions_history_payload(response, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_media_set_primary(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = _load_json_body(request)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    try:
        media_id = int(payload.get("media_id"))
    except Exception:
        return HttpResponseBadRequest("media_id invalid")

    item = get_object_or_404(InscripcioMedia, pk=media_id, competicio=competicio)
    with transaction.atomic():
        InscripcioMedia.objects.filter(
            competicio=competicio,
            inscripcio_id=item.inscripcio_id,
            tipus=item.tipus,
        ).update(is_primary=False)
        item.is_primary = True
        item.save(update_fields=["is_primary"])

    return JsonResponse(with_inscripcions_history_payload({"ok": True, "item": _serialize_media_item(item)}, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_media_match_preview(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = _load_json_body(request)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    files = payload.get("files") or []
    if not isinstance(files, list):
        return HttpResponseBadRequest("files ha de ser una llista")
    if len(files) > 3000:
        return HttpResponseBadRequest("Massa fitxers al preview")

    inscripcions = Inscripcio.objects.filter(competicio=competicio).only("id", "nom_i_cognoms", "entitat", "subcategoria", "sexe")
    candidates = build_inscripcio_media_match_candidates(inscripcions)
    cfg = _get_media_matching_config(competicio)
    rows = match_media_files_to_inscripcions(files, candidates, config=cfg, top_k=3)

    auto_count = len([row for row in rows if row.get("status") == "auto"])
    review_count = len([row for row in rows if row.get("status") == "review"])
    unmatched_count = len([row for row in rows if row.get("status") == "unmatched"])
    return JsonResponse(
        {
            "ok": True,
            "rows": rows,
            "counts": {
                "total": len(rows),
                "auto": auto_count,
                "review": review_count,
                "unmatched": unmatched_count,
            },
            "config": cfg,
        }
    )


@require_POST
@csrf_protect
def inscripcions_media_match_apply(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    raw = request.POST.get("mapping_json") or "[]"
    try:
        mapping = json.loads(raw)
    except Exception:
        return HttpResponseBadRequest("mapping_json invalid")
    if not isinstance(mapping, list):
        return HttpResponseBadRequest("mapping_json ha de ser una llista")

    key_to_row = {}
    target_ids = set()
    for row in mapping:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        try:
            ins_id = int(row.get("inscripcio_id"))
        except Exception:
            continue
        key_to_row[key] = {"inscripcio_id": ins_id, "score": row.get("score")}
        target_ids.add(ins_id)

    if not key_to_row:
        return HttpResponseBadRequest("No hi ha assignacions valides")

    inscripcions = {ins.id: ins for ins in Inscripcio.objects.filter(competicio=competicio, id__in=target_ids)}
    created = []
    errors = []
    for key, row in key_to_row.items():
        uploaded = request.FILES.get(f"file_{key}")
        if uploaded is None:
            errors.append({"key": key, "error": "Fitxer no trobat al POST"})
            continue
        inscripcio = inscripcions.get(row["inscripcio_id"])
        if inscripcio is None:
            errors.append({"key": key, "error": "Inscripcio no valida"})
            continue
        try:
            item = _create_inscripcio_media_record(
                competicio=competicio,
                inscripcio=inscripcio,
                uploaded=uploaded,
                source=InscripcioMedia.Source.ASSISTED,
                match_score=row.get("score"),
            )
            created.append(_serialize_media_item(item))
        except ValueError as exc:
            errors.append({"key": key, "error": str(exc)})

    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "created_count": len(created),
                "error_count": len(errors),
                "created": created[:25],
                "errors": errors[:25],
            },
            request,
            competicio.id,
        )
    )


__all__ = [
    "_get_media_matching_config",
    "_serialize_media_item",
    "inscripcions_media_delete",
    "inscripcions_media_file",
    "inscripcions_media_match_apply",
    "inscripcions_media_match_preview",
    "inscripcions_media_set_primary",
    "inscripcions_media_upload",
]
