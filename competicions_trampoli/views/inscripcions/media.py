import json
import mimetypes
import os
from contextlib import nullcontext
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from ...models import Competicio, Inscripcio, InscripcioMedia
from ...services.inscripcions.history import (
    capture_inscripcions_history_snapshot,
    record_inscripcions_history_entry,
    with_inscripcions_history_payload,
)
from ...services.inscripcions.media_matching import (
    build_inscripcio_media_match_candidates,
    build_inscripcio_media_match_candidate_index,
    match_media_files_to_inscripcions,
    normalize_media_matching_config,
)
from ...services.inscripcions.timing import get_inscripcions_timing_collector


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
MEDIA_WORKSPACE_DEFAULT_PAGE_SIZE = 40
MEDIA_WORKSPACE_MAX_PAGE_SIZE = 100


def _get_media_matching_config(competicio):
    view_cfg = competicio.inscripcions_view or {}
    return normalize_media_matching_config(view_cfg.get("media_matching"))


def _parse_json_body(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return None


def _timing_scope(timing, name):
    if timing is None:
        return nullcontext()
    return timing.section(name)


def _load_json_body(request):
    payload = _parse_json_body(request)
    if payload is None:
        raise ValueError("JSON invalid")
    return payload


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


def _serialize_media_workspace_item(item):
    data = _serialize_media_item(item)
    data["created_at"] = item.created_at.isoformat() if getattr(item, "created_at", None) else None
    data["updated_at"] = item.updated_at.isoformat() if getattr(item, "updated_at", None) else None
    return data


def _normalize_media_match_detail_level(raw_detail_level, raw_expanded=None) -> str:
    detail_level = str(raw_detail_level or "").strip().lower()
    if detail_level in {"expanded", "expandit", "expandida", "full", "detailed"}:
        return "expanded"
    if bool(raw_expanded):
        return "expanded"
    return "compact"


def _resolve_media_matching_config_payload(payload):
    if not isinstance(payload, dict):
        return {}
    for key in ("config_draft", "config", "media_matching", "draft_config"):
        raw_cfg = payload.get(key)
        if raw_cfg is not None:
            return raw_cfg
    return {}


def _normalize_media_workspace_media_state(raw_state):
    state = str(raw_state or "all").strip().lower()
    if state in {"", "all", "any", "tots", "total"}:
        return "all"
    if state in {"assigned", "with", "amb", "media", "has", "has_media", "primary", "principal", "principals"}:
        return "with"
    if state in {"unassigned", "without", "sense", "none", "no_media"}:
        return "without"
    return "all"


def _normalize_media_workspace_source(raw_source):
    source = str(raw_source or "all").strip().lower()
    if source in {"", "all", "any", "tots"}:
        return "all"
    if source in {InscripcioMedia.Source.MANUAL, "manual", "upload"}:
        return InscripcioMedia.Source.MANUAL
    if source in {InscripcioMedia.Source.ASSISTED, "assisted", "match"}:
        return InscripcioMedia.Source.ASSISTED
    return "all"


def _normalize_media_workspace_tipus(raw_tipus):
    tipus = str(raw_tipus or "all").strip().lower()
    if tipus in {"", "all", "any", "tots"}:
        return "all"
    if tipus in {InscripcioMedia.Tipus.AUDIO, InscripcioMedia.Tipus.VIDEO, InscripcioMedia.Tipus.IMAGE, InscripcioMedia.Tipus.OTHER}:
        return tipus
    return "all"


def _normalize_media_workspace_filters(raw_filters):
    filters = raw_filters if isinstance(raw_filters, dict) else {}
    q = str(filters.get("q") or "").strip()
    media_state = _normalize_media_workspace_media_state(filters.get("media_state"))
    source = _normalize_media_workspace_source(filters.get("source"))
    tipus = _normalize_media_workspace_tipus(filters.get("tipus"))

    try:
        inscripcio_id = int(filters.get("inscripcio_id"))
    except Exception:
        inscripcio_id = None
    if inscripcio_id is not None and inscripcio_id <= 0:
        inscripcio_id = None

    return {
        "q": q,
        "media_state": media_state,
        "source": source,
        "tipus": tipus,
        "inscripcio_id": inscripcio_id,
    }


def _build_media_workspace_queryset(competicio, filters):
    filters = _normalize_media_workspace_filters(filters)
    qs = Inscripcio.objects.filter(competicio=competicio)
    if filters["inscripcio_id"]:
        qs = qs.filter(id=filters["inscripcio_id"])

    q = filters["q"]
    if q:
        qs = qs.filter(
            Q(nom_i_cognoms__icontains=q)
            | Q(entitat__icontains=q)
            | Q(categoria__icontains=q)
            | Q(subcategoria__icontains=q)
            | Q(sexe__icontains=q)
            | Q(media_files__original_filename__icontains=q)
        )

    if filters["media_state"] == "with":
        qs = qs.filter(media_files__isnull=False)
    elif filters["media_state"] == "without":
        qs = qs.filter(media_files__isnull=True)

    if filters["source"] != "all":
        qs = qs.filter(media_files__source=filters["source"])
    if filters["tipus"] != "all":
        qs = qs.filter(media_files__tipus=filters["tipus"])

    return qs.distinct().order_by("ordre_sortida", "id"), filters


def _serialize_media_workspace_inscripcio(inscripcio, media_items):
    primary_count = sum(1 for item in media_items if bool(getattr(item, "is_primary", False)))
    inscripcio_label = str(getattr(inscripcio, "nom_i_cognoms", "") or "").strip() or f"Inscripcio {inscripcio.id}"
    return {
        "inscripcio_id": inscripcio.id,
        "inscripcio_label": inscripcio_label,
        "nom_i_cognoms": inscripcio_label,
        "entitat": inscripcio.entitat or "",
        "categoria": getattr(inscripcio, "categoria", "") or "",
        "subcategoria": inscripcio.subcategoria or "",
        "sexe": inscripcio.sexe or "",
        "ordre_sortida": int(getattr(inscripcio, "ordre_sortida", 0) or 0),
        "media_count": len(media_items),
        "primary_media_count": primary_count,
        "media_state": "with" if media_items else "without",
        "media_items": [_serialize_media_workspace_item(item) for item in media_items],
    }


def _build_media_workspace_payload(competicio, payload):
    page = max(1, int(payload.get("page") or 1))
    page_size = max(1, min(MEDIA_WORKSPACE_MAX_PAGE_SIZE, int(payload.get("page_size") or MEDIA_WORKSPACE_DEFAULT_PAGE_SIZE)))
    filters_qs, normalized_filters = _build_media_workspace_queryset(competicio, payload.get("filters"))
    filtered_total = int(filters_qs.count() or 0)
    total_inscripcions = int(Inscripcio.objects.filter(competicio=competicio).count() or 0)
    inscripcions_with_media = int(Inscripcio.objects.filter(competicio=competicio, media_files__isnull=False).distinct().count() or 0)
    inscripcions_without_media = max(0, total_inscripcions - inscripcions_with_media)
    filtered_with_media = filters_qs.filter(media_files__isnull=False).distinct().count()
    filtered_without_media = filters_qs.filter(media_files__isnull=True).distinct().count()

    filtered_ids_qs = filters_qs.values_list("id", flat=True)
    media_scope = InscripcioMedia.objects.filter(competicio=competicio, inscripcio_id__in=filtered_ids_qs)
    media_total = int(media_scope.count() or 0)
    primary_media_total = int(media_scope.filter(is_primary=True).count() or 0)

    source_counts = {
        item["source"]: int(item["total"] or 0)
        for item in media_scope.values("source").annotate(total=Count("id"))
    }
    tipus_counts = {
        item["tipus"]: int(item["total"] or 0)
        for item in media_scope.values("tipus").annotate(total=Count("id"))
    }

    start = (page - 1) * page_size
    end = start + page_size
    page_rows = list(filters_qs[start:end])
    page_ids = [row.id for row in page_rows]
    page_media = list(
        InscripcioMedia.objects.filter(competicio=competicio, inscripcio_id__in=page_ids)
        .order_by("inscripcio_id", "-is_primary", "-created_at", "id")
    )
    media_by_inscripcio_id = {}
    for item in page_media:
        media_by_inscripcio_id.setdefault(item.inscripcio_id, []).append(item)

    rows = [
        _serialize_media_workspace_inscripcio(row, media_by_inscripcio_id.get(row.id, []))
        for row in page_rows
    ]

    workspace = {
        "filters": normalized_filters,
        "summary": {
            "total_inscripcions": total_inscripcions,
            "filtered_inscripcions": filtered_total,
            "inscripcions_with_media": filtered_with_media,
            "inscripcions_without_media": filtered_without_media,
            "media_total": media_total,
            "primary_media_total": primary_media_total,
            "source_counts": source_counts,
            "tipus_counts": tipus_counts,
        },
        "filter_options": {
            "media_state": [
                {"code": "all", "label": "Tots", "count": filtered_total},
                {"code": "with", "label": "Amb media", "count": filtered_with_media},
                {"code": "without", "label": "Sense media", "count": filtered_without_media},
            ],
            "source": [
                {"code": "all", "label": "Tots", "count": media_total},
                {"code": InscripcioMedia.Source.MANUAL, "label": "Manual", "count": source_counts.get(InscripcioMedia.Source.MANUAL, 0)},
                {"code": InscripcioMedia.Source.ASSISTED, "label": "Assistit", "count": source_counts.get(InscripcioMedia.Source.ASSISTED, 0)},
            ],
            "tipus": [
                {"code": "all", "label": "Tots", "count": media_total},
                {"code": InscripcioMedia.Tipus.AUDIO, "label": "Audio", "count": tipus_counts.get(InscripcioMedia.Tipus.AUDIO, 0)},
                {"code": InscripcioMedia.Tipus.VIDEO, "label": "Video", "count": tipus_counts.get(InscripcioMedia.Tipus.VIDEO, 0)},
                {"code": InscripcioMedia.Tipus.IMAGE, "label": "Imatge", "count": tipus_counts.get(InscripcioMedia.Tipus.IMAGE, 0)},
                {"code": InscripcioMedia.Tipus.OTHER, "label": "Altre", "count": tipus_counts.get(InscripcioMedia.Tipus.OTHER, 0)},
            ],
        },
        "page": page,
        "page_size": page_size,
        "total": filtered_total,
        "pages": max(1, (filtered_total + page_size - 1) // page_size) if filtered_total else 1,
        "has_more": end < filtered_total,
        "rows": rows,
    }
    return workspace


def _promote_next_primary_media(competicio, inscripcio_id, tipus, exclude_media_id=None):
    qs = InscripcioMedia.objects.filter(
        competicio=competicio,
        inscripcio_id=inscripcio_id,
        tipus=tipus,
    )
    if exclude_media_id is not None:
        qs = qs.exclude(pk=exclude_media_id)
    next_item = qs.order_by("-is_primary", "-created_at", "id").first()
    if next_item and not next_item.is_primary:
        next_item.is_primary = True
        next_item.save(update_fields=["is_primary"])
    return next_item


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
def inscripcions_media_match_config_save(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = _load_json_body(request)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if not isinstance(payload, dict):
        return HttpResponseBadRequest("JSON invalid")
    raw_cfg = _resolve_media_matching_config_payload(payload)
    normalized_cfg = normalize_media_matching_config(raw_cfg)

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    view_cfg = dict(competicio.inscripcions_view or {})
    view_cfg["media_matching"] = normalized_cfg
    competicio.inscripcions_view = view_cfg
    competicio.save(update_fields=["inscripcions_view"])
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="save_media_matching_config",
        action_label="Desar configuracio de matching multimedia",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "config": normalized_cfg}, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_media_workspace(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = _load_json_body(request)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if not isinstance(payload, dict):
        return HttpResponseBadRequest("JSON invalid")
    workspace = _build_media_workspace_payload(competicio, payload if isinstance(payload, dict) else {})
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "workspace": workspace, **workspace}, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_media_reassign(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = _load_json_body(request)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if not isinstance(payload, dict):
        return HttpResponseBadRequest("JSON invalid")

    try:
        media_id = int(payload.get("media_id"))
    except Exception:
        return HttpResponseBadRequest("media_id invalid")
    try:
        inscripcio_id = int(payload.get("inscripcio_id"))
    except Exception:
        return HttpResponseBadRequest("inscripcio_id invalid")

    item = get_object_or_404(InscripcioMedia, pk=media_id, competicio=competicio)
    destination = get_object_or_404(Inscripcio, pk=inscripcio_id, competicio=competicio)

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    with transaction.atomic():
        source_inscripcio_id = item.inscripcio_id
        source_tipus = item.tipus
        source_was_primary = bool(item.is_primary)
        destination_has_primary = InscripcioMedia.objects.filter(
            competicio=competicio,
            inscripcio=destination,
            tipus=source_tipus,
            is_primary=True,
        ).exclude(pk=item.pk).exists()

        item.inscripcio = destination
        item.is_primary = not destination_has_primary
        item.save(update_fields=["inscripcio", "is_primary", "updated_at"])

        if source_was_primary and source_inscripcio_id != destination.id:
            _promote_next_primary_media(competicio, source_inscripcio_id, source_tipus, exclude_media_id=item.id)

    item.refresh_from_db()
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="reassign_media",
        action_label="Reassignar media",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "item": _serialize_media_item(item)}, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_media_match_preview(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    timing = get_inscripcions_timing_collector(request)
    try:
        payload = _load_json_body(request)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if not isinstance(payload, dict):
        return HttpResponseBadRequest("JSON invalid")

    with _timing_scope(timing, "media.preview_input"):
        files = payload.get("files") or []
        if not isinstance(files, list):
            return HttpResponseBadRequest("files ha de ser una llista")
        if len(files) > 3000:
            return HttpResponseBadRequest("Massa fitxers al preview")

    with _timing_scope(timing, "media.candidates"):
        with _timing_scope(timing, "media.candidates.query"):
            inscripcions = Inscripcio.objects.filter(competicio=competicio).only("id", "nom_i_cognoms", "entitat", "categoria", "subcategoria", "sexe")
        with _timing_scope(timing, "media.candidates.build"):
            candidates = build_inscripcio_media_match_candidates(inscripcions)
        with _timing_scope(timing, "media.candidates.index"):
            candidate_index = build_inscripcio_media_match_candidate_index(candidates)
        raw_cfg = None
        if isinstance(payload, dict):
            for key in ("config_draft", "config", "media_matching", "draft_config"):
                if key in payload:
                    raw_cfg = payload.get(key)
                    break
        cfg = normalize_media_matching_config(_get_media_matching_config(competicio) if raw_cfg is None else raw_cfg)
        detail_level = _normalize_media_match_detail_level(payload.get("detail_level"), payload.get("expanded"))

    with _timing_scope(timing, "media.matching"):
        rows = match_media_files_to_inscripcions(
            files,
            candidates,
            config=cfg,
            top_k=3,
            candidate_index=candidate_index,
            detail_level=detail_level,
        )

    with _timing_scope(timing, "media.serialization"):
        auto_count = len([row for row in rows if row.get("status") == "auto"])
        review_count = len([row for row in rows if row.get("status") == "review"])
        unmatched_count = len([row for row in rows if row.get("status") == "unmatched"])
        response = JsonResponse(
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
                "detail_level": detail_level,
                # El frontend pinta el selector amb `top_candidates` de cada fila;
                # no cal enviar un cataleg global complet d'inscripcions.
            }
        )
    timing.apply_to_response(response)
    return response


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
    "inscripcions_media_match_config_save",
    "inscripcions_media_delete",
    "inscripcions_media_file",
    "inscripcions_media_match_apply",
    "inscripcions_media_match_preview",
    "inscripcions_media_reassign",
    "inscripcions_media_workspace",
    "inscripcions_media_set_primary",
    "inscripcions_media_upload",
]
