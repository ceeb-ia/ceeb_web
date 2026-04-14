import json
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Max
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_time
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from ...models import Competicio
from ...models.rotacions import RotacioAssignacio, RotacioEstacio, RotacioFranja, normalize_hex_color
from ...models.scoring import SerieEquip
from ...services.rotacions.rotacions_ordering import set_rotacio_order_mode
from ...services.shared.competition_groups import get_group_maps
from ._shared import (
    _assignacio_program_keys,
    _split_program_keys,
    _sync_assignacio_groups,
    _sync_assignacio_series,
)
from ._timing import (
    FRANJA_DAY,
    FRANJA_FALLBACK_DURATION_MINUTES,
    build_competitive_reorder_plan,
    build_competitive_shift_plan,
    build_delete_shift_plan,
    format_time,
    is_competitive_franja,
    build_competitive_visual_sync_sequence,
    build_visual_reorder_sequence,
    resequence_franja_orders,
    resequence_franja_visual_orders,
    serialize_time_change,
    sort_franges_temporally,
    sort_franges_visually,
    time_to_dt,
)


def _clean_franja_tipus(raw_value):
    value = str(raw_value or "").strip().lower()
    allowed = {
        RotacioFranja.TIPUS_COMPETITION,
        RotacioFranja.TIPUS_BREAK,
        RotacioFranja.TIPUS_AWARDS,
        RotacioFranja.TIPUS_SEPARATOR,
    }
    return value if value in allowed else RotacioFranja.TIPUS_COMPETITION


def _load_franges(competicio):
    return list(RotacioFranja.objects.filter(competicio=competicio).order_by("ordre", "id"))


def _load_visual_franges(competicio):
    return list(RotacioFranja.objects.filter(competicio=competicio).order_by("ordre_visual", "id"))


def _rotation_station_mode(estacio):
    if getattr(estacio, "tipus", "") != "aparell" or not getattr(estacio, "comp_aparell_id", None):
        return "other"
    aparell = getattr(getattr(estacio, "comp_aparell", None), "aparell", None)
    if aparell is not None and getattr(aparell, "competition_unit", "") == "team":
        return "team"
    return "individual"


def _build_shifted_station_payloads(estacions, base_payloads_by_station, *, key, steps):
    ordered_stations = list(estacions or [])
    if not ordered_stations:
        return {}
    values = [list((base_payloads_by_station.get(estacio.id) or {}).get(key, [])) for estacio in ordered_stations]
    total = len(ordered_stations)
    return {
        estacio.id: list(values[(index - steps) % total])
        for index, estacio in enumerate(ordered_stations)
    }


def _resequence_all_franges(competicio):
    franges = _load_franges(competicio)
    ordered = resequence_franja_orders(franges)
    if ordered:
        franja_ids = [int(fr.id) for fr in ordered]
        RotacioFranja.objects.filter(competicio=competicio, id__in=franja_ids).update(ordre=F("ordre") + 1000)
        RotacioFranja.objects.bulk_update(ordered, ["ordre"], batch_size=200)
    return ordered


def _persist_visual_sequence(franges):
    ordered = list(franges or [])
    for idx, franja in enumerate(ordered, start=1):
        franja.ordre_visual = idx
    if ordered:
        RotacioFranja.objects.bulk_update(ordered, ["ordre_visual"], batch_size=200)
    return ordered


def _resequence_all_visual_franges(competicio):
    return _persist_visual_sequence(resequence_franja_visual_orders(_load_visual_franges(competicio)))


def _sync_competitive_visual_order(competicio):
    visual_franges = _load_visual_franges(competicio)
    return _persist_visual_sequence(build_competitive_visual_sync_sequence(visual_franges))


def _position_franja_in_visual_order(competicio, *, franja_id, target_id, position):
    visual_franges = _load_visual_franges(competicio)
    return _persist_visual_sequence(
        build_visual_reorder_sequence(
            visual_franges,
            dragged_id=franja_id,
            target_id=target_id,
            position=position,
        )
    )


def _next_visual_order(competicio):
    return (RotacioFranja.objects.filter(competicio=competicio).aggregate(Max("ordre_visual"))["ordre_visual__max"] or 0) + 1


def _clean_color_fons(raw_value):
    try:
        return normalize_hex_color(raw_value)
    except ValidationError as exc:
        raise ValueError(str(exc))


def _apply_time_changes(competicio, changes):
    changed_franges = []
    seen_ids = set()
    for change in changes or []:
        franja = change.franja
        franja.hora_inici = change.new_start
        franja.hora_fi = change.new_end
        franja.full_clean()
        franja_id = int(franja.id)
        if franja_id in seen_ids:
            continue
        seen_ids.add(franja_id)
        changed_franges.append(franja)
    if changed_franges:
        RotacioFranja.objects.bulk_update(changed_franges, ["hora_inici", "hora_fi"], batch_size=200)
    return _resequence_all_franges(competicio)


def _serialize_origin_preview(*, franja_id, title, old_start, old_end, new_start, new_end, tipus):
    return {
        "franja_id": int(franja_id) if franja_id else None,
        "title": str(title or "Franja"),
        "type": str(tipus or RotacioFranja.TIPUS_COMPETITION),
        "old_start": format_time(old_start),
        "old_end": format_time(old_end),
        "new_start": format_time(new_start),
        "new_end": format_time(new_end),
    }


def _preview_payload(*, origin, affected, action, action_label):
    return {
        "ok": True,
        "preview_only": True,
        "requires_confirmation": bool(affected),
        "action": action,
        "action_label": action_label,
        "origin": origin,
        "affected": [serialize_time_change(change) for change in affected],
    }


def _parse_preview_flags(payload):
    return bool(payload.get("preview_only")), bool(payload.get("confirm_reorder"))


def _competitive_preview_response(*, preview_only, confirm_reorder, origin, affected, action, action_label):
    preview = _preview_payload(origin=origin, affected=affected, action=action, action_label=action_label)
    if preview_only:
        return preview, None
    if affected and not confirm_reorder:
        return preview, JsonResponse(preview, status=409)
    return preview, None


@require_POST
@csrf_protect
def franges_auto_create(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    hi = parse_time(payload.get("hora_inici") or "")
    hf = parse_time(payload.get("hora_fi") or "")
    interval = payload.get("interval_min", None)
    clear_existing = bool(payload.get("clear_existing", False))
    titol_base = (payload.get("titol_base") or "Franja").strip()

    try:
        interval = int(interval)
    except Exception:
        return HttpResponseBadRequest("interval_min ha de ser un enter (minuts)")

    if not hi or not hf:
        return HttpResponseBadRequest("Hora inici/fi obligatories")
    if interval <= 0:
        return HttpResponseBadRequest("interval_min ha de ser > 0")

    start = time_to_dt(hi)
    end = time_to_dt(hf)
    if end <= start:
        return HttpResponseBadRequest("hora_fi ha de ser posterior a hora_inici")

    existing_competitive = [
        fr
        for fr in _load_franges(competicio)
        if is_competitive_franja(fr)
    ]
    if existing_competitive and not clear_existing:
        latest_end = max(time_to_dt(fr.hora_fi) for fr in existing_competitive)
        if start < latest_end:
            return HttpResponseBadRequest(
                "La generacio automatica sense esborrar no pot solapar franges competitives existents."
            )

    with transaction.atomic():
        if clear_existing:
            franges = RotacioFranja.objects.filter(competicio=competicio)
            RotacioAssignacio.objects.filter(competicio=competicio, franja__in=franges).delete()
            franges.delete()

        base_ord = (RotacioFranja.objects.filter(competicio=competicio).aggregate(Max("ordre"))["ordre__max"] or 0)
        base_visual = (RotacioFranja.objects.filter(competicio=competicio).aggregate(Max("ordre_visual"))["ordre_visual__max"] or 0)
        to_create = []
        cur = start
        idx = 1
        while cur < end:
            nxt = cur + timedelta(minutes=interval)
            if nxt > end:
                break
            base_ord += 1
            base_visual += 1
            to_create.append(
                RotacioFranja(
                    competicio=competicio,
                    hora_inici=cur.time(),
                    hora_fi=nxt.time(),
                    ordre=base_ord,
                    ordre_visual=base_visual,
                    titol=f"{titol_base} {idx}",
                    tipus=RotacioFranja.TIPUS_COMPETITION,
                )
            )
            cur = nxt
            idx += 1

        RotacioFranja.objects.bulk_create(to_create)
        _resequence_all_franges(competicio)

    return JsonResponse({"ok": True, "created": len(to_create)})


@require_POST
@csrf_protect
def franja_create(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    hi = parse_time(payload.get("hora_inici") or "")
    hf = parse_time(payload.get("hora_fi") or "")
    titol = (payload.get("titol") or "").strip()
    tipus = _clean_franja_tipus(payload.get("tipus"))
    try:
        color_fons = _clean_color_fons(payload.get("color_fons"))
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    preview_only, confirm_reorder = _parse_preview_flags(payload)

    if not hi or not hf:
        return HttpResponseBadRequest("Hora inici/fi obligatories")
    if time_to_dt(hf) <= time_to_dt(hi):
        return HttpResponseBadRequest("hora_fi ha de ser posterior a hora_inici")

    if tipus != RotacioFranja.TIPUS_COMPETITION:
        if preview_only:
            return JsonResponse(
                _preview_payload(
                    origin=_serialize_origin_preview(
                        franja_id=None,
                        title=titol or RotacioFranja.TIPUS_LABELS.get(tipus, "Franja"),
                        old_start=None,
                        old_end=None,
                        new_start=hi,
                        new_end=hf,
                        tipus=tipus,
                    ),
                    affected=[],
                    action="create",
                    action_label="Crear franja",
                )
            )
        max_ord = (RotacioFranja.objects.filter(competicio=competicio).aggregate(Max("ordre"))["ordre__max"] or 0) + 1
        f = RotacioFranja(
            competicio=competicio,
            hora_inici=hi,
            hora_fi=hf,
            ordre=max_ord,
            ordre_visual=_next_visual_order(competicio),
            titol=titol,
            tipus=tipus,
            color_fons=color_fons,
        )
        f.full_clean()
        f.save()
        _resequence_all_franges(competicio)
        _resequence_all_visual_franges(competicio)
        return JsonResponse({"ok": True, "id": f.id})

    franges = _load_franges(competicio)
    try:
        affected, _previous = build_competitive_shift_plan(
            franges,
            candidate_id=None,
            candidate_start=hi,
            candidate_end=hf,
            fallback_minutes=FRANJA_FALLBACK_DURATION_MINUTES,
        )
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    origin = _serialize_origin_preview(
        franja_id=None,
        title=titol or "Franja",
        old_start=None,
        old_end=None,
        new_start=hi,
        new_end=hf,
        tipus=tipus,
    )
    preview, response = _competitive_preview_response(
        preview_only=preview_only,
        confirm_reorder=confirm_reorder,
        origin=origin,
        affected=affected,
        action="create",
        action_label="Crear franja competitiva",
    )
    if response is not None:
        return response
    if preview_only:
        return JsonResponse(preview)

    with transaction.atomic():
        max_ord = (RotacioFranja.objects.filter(competicio=competicio).aggregate(Max("ordre"))["ordre__max"] or 0) + 1
        f = RotacioFranja.objects.create(
            competicio=competicio,
            hora_inici=hi,
            hora_fi=hf,
            ordre=max_ord,
            ordre_visual=_next_visual_order(competicio),
            titol=titol,
            tipus=tipus,
            color_fons=color_fons,
        )
        if affected:
            refreshed = {
                int(fr.id): fr
                for fr in RotacioFranja.objects.filter(competicio=competicio, id__in=[change.franja.id for change in affected])
            }
            for change in affected:
                if int(change.franja.id) in refreshed:
                    change.franja = refreshed[int(change.franja.id)]
            _apply_time_changes(competicio, affected)
        else:
            _resequence_all_franges(competicio)
        _resequence_all_visual_franges(competicio)

    return JsonResponse({"ok": True, "id": f.id})


@require_POST
@csrf_protect
def franja_delete(request, pk, franja_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    target = get_object_or_404(RotacioFranja, pk=franja_id, competicio=competicio)

    with transaction.atomic():
        franges = _load_franges(competicio)
        affected = build_delete_shift_plan(franges, delete_id=target.id)
        RotacioAssignacio.objects.filter(competicio=competicio, franja=target).delete()
        target.delete()
        if affected:
            refreshed = {
                int(fr.id): fr
                for fr in RotacioFranja.objects.filter(competicio=competicio, id__in=[change.franja.id for change in affected])
            }
            for change in affected:
                if int(change.franja.id) in refreshed:
                    change.franja = refreshed[int(change.franja.id)]
            _apply_time_changes(competicio, affected)
        else:
            _resequence_all_franges(competicio)
        _resequence_all_visual_franges(competicio)

    return JsonResponse({"ok": True})


@require_POST
@csrf_protect
def franja_insert_after(request, pk, franja_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    fr_prev = get_object_or_404(RotacioFranja, pk=franja_id, competicio=competicio)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    preview_only, confirm_reorder = _parse_preview_flags(payload)
    titol = (payload.get("titol") or "").strip()
    try:
        color_fons = _clean_color_fons(payload.get("color_fons"))
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    prev_start = time_to_dt(fr_prev.hora_inici)
    prev_end = time_to_dt(fr_prev.hora_fi)
    if prev_end <= prev_start:
        return HttpResponseBadRequest("La franja base te hores invalides.")

    delta = prev_end - prev_start
    if delta.total_seconds() <= 0:
        delta = timedelta(minutes=FRANJA_FALLBACK_DURATION_MINUTES)
    new_start = prev_end
    new_end = new_start + delta

    franges = _load_franges(competicio)
    try:
        affected, _previous = build_competitive_shift_plan(
            franges,
            candidate_id=None,
            candidate_start=new_start.time(),
            candidate_end=new_end.time(),
            fallback_minutes=FRANJA_FALLBACK_DURATION_MINUTES,
        )
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    origin = _serialize_origin_preview(
        franja_id=None,
        title=titol or "Franja",
        old_start=None,
        old_end=None,
        new_start=new_start.time(),
        new_end=new_end.time(),
        tipus=RotacioFranja.TIPUS_COMPETITION,
    )
    preview, response = _competitive_preview_response(
        preview_only=preview_only,
        confirm_reorder=confirm_reorder,
        origin=origin,
        affected=affected,
        action="insert_after",
        action_label="Inserir franja competitiva",
    )
    if response is not None:
        return response
    if preview_only:
        return JsonResponse(preview)

    with transaction.atomic():
        max_ord = (RotacioFranja.objects.filter(competicio=competicio).aggregate(Max("ordre"))["ordre__max"] or 0) + 1
        f_new = RotacioFranja.objects.create(
            competicio=competicio,
            hora_inici=new_start.time(),
            hora_fi=new_end.time(),
            ordre=max_ord,
            ordre_visual=_next_visual_order(competicio),
            titol=titol or "",
            tipus=RotacioFranja.TIPUS_COMPETITION,
            color_fons=color_fons,
        )
        if affected:
            refreshed = {
                int(fr.id): fr
                for fr in RotacioFranja.objects.filter(competicio=competicio, id__in=[change.franja.id for change in affected])
            }
            for change in affected:
                if int(change.franja.id) in refreshed:
                    change.franja = refreshed[int(change.franja.id)]
            _apply_time_changes(competicio, affected)
        else:
            _resequence_all_franges(competicio)
        _position_franja_in_visual_order(
            competicio,
            franja_id=f_new.id,
            target_id=fr_prev.id,
            position="after",
        )

    return JsonResponse({"ok": True, "id": f_new.id})


@require_POST
@csrf_protect
def franja_update_inline(request, pk, franja_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    fr = get_object_or_404(RotacioFranja, pk=franja_id, competicio=competicio)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    preview_only, confirm_reorder = _parse_preview_flags(payload)
    titol = (payload.get("titol") or "").strip()
    tipus = _clean_franja_tipus(payload.get("tipus", fr.tipus))
    try:
        color_fons = _clean_color_fons(payload.get("color_fons"))
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    hora_inici = payload.get("hora_inici")
    hora_fi = payload.get("hora_fi")

    if not hora_inici or not hora_fi:
        return HttpResponseBadRequest("Falten hores")

    try:
        hi = datetime.strptime(hora_inici, "%H:%M").time()
        hf = datetime.strptime(hora_fi, "%H:%M").time()
    except ValueError:
        return HttpResponseBadRequest("Format d'hora incorrecte (HH:MM)")

    if time_to_dt(hf) <= time_to_dt(hi):
        return HttpResponseBadRequest("L'hora de fi ha de ser posterior a l'hora d'inici")
    if tipus != RotacioFranja.TIPUS_COMPETITION:
        has_assignacions = RotacioAssignacio.objects.filter(competicio=competicio, franja=fr).exists()
        if has_assignacions:
            return HttpResponseBadRequest("No pots convertir una franja amb assignacions en una franja no competitiva.")

    if tipus != RotacioFranja.TIPUS_COMPETITION:
        if preview_only:
            return JsonResponse(
                _preview_payload(
                    origin=_serialize_origin_preview(
                        franja_id=fr.id,
                        title=titol or fr.display_label,
                        old_start=fr.hora_inici,
                        old_end=fr.hora_fi,
                        new_start=hi,
                        new_end=hf,
                        tipus=tipus,
                    ),
                    affected=[],
                    action="update",
                    action_label="Editar franja",
                )
            )
        fr.titol = titol
        fr.hora_inici = hi
        fr.hora_fi = hf
        fr.tipus = tipus
        fr.color_fons = color_fons
        fr.full_clean()
        fr.save(update_fields=["titol", "hora_inici", "hora_fi", "tipus", "color_fons"])
        _resequence_all_franges(competicio)
        _resequence_all_visual_franges(competicio)
        return JsonResponse({"ok": True})

    franges = _load_franges(competicio)
    try:
        affected, _previous = build_competitive_shift_plan(
            franges,
            candidate_id=fr.id,
            candidate_start=hi,
            candidate_end=hf,
            fallback_minutes=FRANJA_FALLBACK_DURATION_MINUTES,
        )
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    origin = _serialize_origin_preview(
        franja_id=fr.id,
        title=titol or fr.display_label,
        old_start=fr.hora_inici,
        old_end=fr.hora_fi,
        new_start=hi,
        new_end=hf,
        tipus=tipus,
    )
    preview, response = _competitive_preview_response(
        preview_only=preview_only,
        confirm_reorder=confirm_reorder,
        origin=origin,
        affected=affected,
        action="update",
        action_label="Reordenacio horaria",
    )
    if response is not None:
        return response
    if preview_only:
        return JsonResponse(preview)

    with transaction.atomic():
        fr.titol = titol
        fr.hora_inici = hi
        fr.hora_fi = hf
        fr.tipus = tipus
        fr.color_fons = color_fons
        fr.full_clean()
        fr.save(update_fields=["titol", "hora_inici", "hora_fi", "tipus", "color_fons"])
        if affected:
            refreshed = {
                int(obj.id): obj
                for obj in RotacioFranja.objects.filter(competicio=competicio, id__in=[change.franja.id for change in affected])
            }
            for change in affected:
                if int(change.franja.id) in refreshed:
                    change.franja = refreshed[int(change.franja.id)]
            _apply_time_changes(competicio, affected)
        else:
            _resequence_all_franges(competicio)
        _sync_competitive_visual_order(competicio)

    return JsonResponse({"ok": True})


@require_POST
@csrf_protect
def franges_reorder(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    preview_only, confirm_reorder = _parse_preview_flags(payload)
    dragged_id = int(payload.get("dragged_id") or 0)
    target_id = int(payload.get("target_id") or 0)
    position = str(payload.get("position") or "before").lower()
    if dragged_id <= 0 or target_id <= 0:
        return HttpResponseBadRequest("Franges invalides per reorder.")

    franges = _load_franges(competicio)
    affected = build_competitive_reorder_plan(
        franges,
        dragged_id=dragged_id,
        target_id=target_id,
        position=position,
        fallback_minutes=FRANJA_FALLBACK_DURATION_MINUTES,
    )
    dragged = next((fr for fr in franges if int(fr.id) == dragged_id), None)
    target = next((fr for fr in franges if int(fr.id) == target_id), None)
    if dragged is None or target is None or not is_competitive_franja(dragged) or not is_competitive_franja(target):
        return HttpResponseBadRequest("El drag and drop nomes s'admet entre franges competitives.")

    if affected:
        new_self = next((change for change in affected if int(change.franja.id) == dragged_id), None)
        origin = _serialize_origin_preview(
            franja_id=dragged.id,
            title=dragged.display_label,
            old_start=dragged.hora_inici,
            old_end=dragged.hora_fi,
            new_start=new_self.new_start if new_self else dragged.hora_inici,
            new_end=new_self.new_end if new_self else dragged.hora_fi,
            tipus=dragged.tipus,
        )
    else:
        origin = _serialize_origin_preview(
            franja_id=dragged.id,
            title=dragged.display_label,
            old_start=dragged.hora_inici,
            old_end=dragged.hora_fi,
            new_start=dragged.hora_inici,
            new_end=dragged.hora_fi,
            tipus=dragged.tipus,
        )

    preview, response = _competitive_preview_response(
        preview_only=preview_only,
        confirm_reorder=confirm_reorder,
        origin=origin,
        affected=affected,
        action="reorder",
        action_label="Reordenar franges competitives",
    )
    if response is not None:
        return response
    if preview_only:
        return JsonResponse(preview)

    with transaction.atomic():
        refreshed = {
            int(obj.id): obj
            for obj in RotacioFranja.objects.filter(competicio=competicio, id__in=[change.franja.id for change in affected])
        }
        for change in affected:
            if int(change.franja.id) in refreshed:
                change.franja = refreshed[int(change.franja.id)]
        _apply_time_changes(competicio, affected)
        _sync_competitive_visual_order(competicio)

    return JsonResponse({"ok": True})


@require_POST
@csrf_protect
def franges_reorder_visual(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    dragged_id = int(payload.get("dragged_id") or 0)
    target_id = int(payload.get("target_id") or 0)
    position = str(payload.get("position") or "before").lower()
    if dragged_id <= 0 or target_id <= 0:
        return HttpResponseBadRequest("Franges invalides per reorder visual.")

    visual_franges = _load_visual_franges(competicio)
    dragged = next((fr for fr in visual_franges if int(fr.id) == dragged_id), None)
    target = next((fr for fr in visual_franges if int(fr.id) == target_id), None)
    if dragged is None or target is None:
        return HttpResponseBadRequest("Franges invalides per reorder visual.")
    if is_competitive_franja(dragged):
        return HttpResponseBadRequest("El drag visual nomes s'admet per franges globals.")
    if dragged_id == target_id:
        return JsonResponse({"ok": True, "ordered_ids": [int(fr.id) for fr in sort_franges_visually(visual_franges)]})

    with transaction.atomic():
        ordered = _persist_visual_sequence(
            build_visual_reorder_sequence(
                visual_franges,
                dragged_id=dragged_id,
                target_id=target_id,
                position=position,
            )
        )

    return JsonResponse({"ok": True, "ordered_ids": [int(fr.id) for fr in ordered]})


@require_POST
@csrf_protect
def franja_order_mode_set(request, pk, franja_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    fr = get_object_or_404(RotacioFranja, pk=franja_id, competicio=competicio)
    if not is_competitive_franja(fr):
        return HttpResponseBadRequest("Nomes les franges competitives tenen mode d'ordre.")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    mode = payload.get("mode")
    clean_mode = set_rotacio_order_mode(competicio, franja_id=franja_id, mode=mode)
    return JsonResponse({"ok": True, "franja_id": int(franja_id), "mode": clean_mode})


@require_POST
@csrf_protect
def rotacions_extrapolar(request, pk, franja_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    fr_base = get_object_or_404(RotacioFranja, pk=franja_id, competicio=competicio)
    if not is_competitive_franja(fr_base):
        return HttpResponseBadRequest("Nomes es pot extrapolar des d'una franja competitiva.")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    count = payload.get("count", None)
    estacions = list(
        RotacioEstacio.objects.filter(competicio=competicio, actiu=True)
        .select_related("comp_aparell__aparell")
        .order_by("ordre", "id")
    )
    if not estacions:
        return HttpResponseBadRequest("No hi ha estacions actives.")

    if count is None:
        count = max(0, len(estacions) - 1)

    try:
        count = int(count)
    except Exception:
        return HttpResponseBadRequest("count ha de ser un enter.")
    if count <= 0:
        return JsonResponse({"ok": True, "created_franges": 0, "filled": 0})

    base_map = {}
    for a in (
        RotacioAssignacio.objects
        .filter(competicio=competicio, franja=fr_base)
        .select_related("estacio__comp_aparell__aparell")
        .prefetch_related("grup_links__grup", "serie_links__serie")
    ):
        base_map[a.estacio_id] = _assignacio_program_keys(a)

    groups_by_id = get_group_maps(competicio)["by_id"]
    series_by_id = {
        int(serie.id): serie
        for serie in SerieEquip.objects.filter(competicio=competicio, actiu=True).select_related("comp_aparell")
    }
    station_modes = {estacio.id: _rotation_station_mode(estacio) for estacio in estacions}
    individual_stations = [estacio for estacio in estacions if station_modes.get(estacio.id) == "individual"]
    team_stations = [estacio for estacio in estacions if station_modes.get(estacio.id) == "team"]
    team_stations_by_app = {}
    for estacio in team_stations:
        team_stations_by_app.setdefault(int(getattr(estacio, "comp_aparell_id", 0) or 0), []).append(estacio)
    base_payloads_by_station = {}
    has_program = False
    for estacio in estacions:
        mode = station_modes.get(estacio.id, "other")
        group_ids, serie_ids = _split_program_keys(base_map.get(estacio.id, []))
        if mode == "individual":
            payload_entry = {"groups": group_ids, "series": []}
        elif mode == "team":
            payload_entry = {"groups": [], "series": serie_ids}
        else:
            payload_entry = {"groups": [], "series": []}
        if payload_entry["groups"] or payload_entry["series"]:
            has_program = True
        base_payloads_by_station[estacio.id] = payload_entry
    if not has_program:
        return HttpResponseBadRequest("La franja base no te cap grup assignat.")

    franges = _load_franges(competicio)
    competition_franges = [fr for fr in franges if is_competitive_franja(fr)]
    idx_base = next((i for i, f in enumerate(competition_franges) if f.id == fr_base.id), None)
    if idx_base is None:
        return HttpResponseBadRequest("Franja base no trobada al llistat competitiu.")

    def _delta_minutes(f):
        try:
            s = time_to_dt(f.hora_inici)
            t = time_to_dt(f.hora_fi)
            if t <= s:
                return None
            return int((t - s).total_seconds() // 60)
        except Exception:
            return None

    interval_min = _delta_minutes(fr_base)
    if not interval_min and idx_base > 0:
        interval_min = _delta_minutes(competition_franges[idx_base - 1])
    if not interval_min:
        interval_min = FRANJA_FALLBACK_DURATION_MINUTES

    created = 0
    with transaction.atomic():
        franges = _load_franges(competicio)
        competition_franges = [fr for fr in franges if is_competitive_franja(fr)]
        idx_base = next((i for i, f in enumerate(competition_franges) if f.id == fr_base.id), None)
        if idx_base is None:
            return HttpResponseBadRequest("Franja base no trobada al llistat competitiu.")

        max_ord = (RotacioFranja.objects.filter(competicio=competicio).aggregate(Max("ordre"))["ordre__max"] or 0)
        max_visual = (RotacioFranja.objects.filter(competicio=competicio).aggregate(Max("ordre_visual"))["ordre_visual__max"] or 0)
        target_franges = []
        for k in range(1, count + 1):
            idx = idx_base + k
            if idx < len(competition_franges):
                target_franges.append(competition_franges[idx])
            else:
                last = competition_franges[-1] if competition_franges else fr_base
                last_end = time_to_dt(last.hora_fi)
                new_start = last_end
                new_end = new_start + timedelta(minutes=interval_min)
                max_ord += 1
                max_visual += 1
                nf = RotacioFranja.objects.create(
                    competicio=competicio,
                    hora_inici=new_start.time(),
                    hora_fi=new_end.time(),
                    ordre=max_ord,
                    ordre_visual=max_visual,
                    titol=f"{fr_base.titol or 'Franja'} +{k}",
                    tipus=RotacioFranja.TIPUS_COMPETITION,
                )
                created += 1
                competition_franges.append(nf)
                target_franges.append(nf)

        filled_cells = 0
        for k, fr_t in enumerate(target_franges, start=1):
            shifted_groups_by_station = _build_shifted_station_payloads(
                individual_stations,
                base_payloads_by_station,
                key="groups",
                steps=k,
            )
            shifted_series_by_station = {}
            for team_station_group in team_stations_by_app.values():
                shifted_series_by_station.update(
                    _build_shifted_station_payloads(
                        team_station_group,
                        base_payloads_by_station,
                        key="series",
                        steps=k,
                    )
                )
            for e in estacions:
                station_mode = station_modes.get(e.id, "other")
                if station_mode == "individual":
                    group_ids = list(shifted_groups_by_station.get(e.id, []))
                    serie_ids = []
                elif station_mode == "team":
                    group_ids = []
                    serie_ids = [
                        serie_id
                        for serie_id in shifted_series_by_station.get(e.id, [])
                        if serie_id in series_by_id and int(series_by_id[serie_id].comp_aparell_id or 0) == int(getattr(e, "comp_aparell_id", 0) or 0)
                    ]
                else:
                    group_ids = []
                    serie_ids = []
                assignacio, _created = RotacioAssignacio.objects.update_or_create(
                    competicio=competicio,
                    franja=fr_t,
                    estacio=e,
                    defaults={"grups": [], "grup": None},
                )
                _sync_assignacio_groups(assignacio, group_ids, groups_by_id)
                _sync_assignacio_series(assignacio, serie_ids, series_by_id)
                filled_cells += 1
        _resequence_all_franges(competicio)

    return JsonResponse({"ok": True, "created_franges": created, "filled": filled_cells})


@require_POST
@csrf_protect
def rotacions_clear_all(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    with transaction.atomic():
        RotacioAssignacio.objects.filter(competicio=competicio).delete()
        RotacioFranja.objects.filter(competicio=competicio).delete()
    return JsonResponse({"ok": True})


__all__ = [
    "franges_auto_create",
    "franja_create",
    "franja_delete",
    "franja_insert_after",
    "franges_reorder",
    "franges_reorder_visual",
    "franja_order_mode_set",
    "franja_update_inline",
    "rotacions_clear_all",
    "rotacions_extrapolar",
]
