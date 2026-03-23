import json
from collections import OrderedDict
from typing import Optional

from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .live_cache import mark_live_dirty
from .models import Competicio, Equip, EquipContext, Inscripcio, InscripcioEquipAssignacio
from .services.equip_contexts import (
    NATIVE_EQUIP_CONTEXT_CODE,
    build_unique_equip_context_code,
    get_contextual_assignment_map,
    get_custom_equip_context,
    get_equip_context_payload,
    get_equips_for_context,
    is_native_equip_context,
    normalize_equip_context_code,
)
from .views import (
    capture_inscripcions_history_snapshot,
    get_allowed_group_fields,
    record_inscripcions_history_entry,
    with_inscripcions_history_payload,
)


def _norm_val(v):
    return "__NULL__" if v in (None, "") else str(v).strip()


def _pretty_val(v):
    if v in (None, "", "__NULL__"):
        return "(Sense valor)"
    return str(v)


def _ins_value(ins: Inscripcio, code: str):
    extra = ins.extra or {}
    if isinstance(extra, dict) and isinstance(code, str) and code.startswith("excel__"):
        if code in extra:
            return extra.get(code)
        legacy_code = code[len("excel__"):]
        if legacy_code in extra:
            return extra.get(legacy_code)
    if hasattr(ins, code):
        return getattr(ins, code)
    if isinstance(extra, dict) and code in extra:
        return extra.get(code)
    return extra.get(code)


def _parse_payload(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return None


def _payload_context_code(payload) -> str:
    if not isinstance(payload, dict):
        return NATIVE_EQUIP_CONTEXT_CODE
    return normalize_equip_context_code(payload.get("context_code"))


def _mark_live_dirty_on_commit(competicio_id):
    if not competicio_id:
        return
    transaction.on_commit(lambda cid=int(competicio_id): mark_live_dirty(cid))


def _serialize_equips(competicio: Competicio, context_code=NATIVE_EQUIP_CONTEXT_CODE):
    equips = get_equips_for_context(competicio, context_code)
    return [
        {
            "id": e.id,
            "nom": e.nom,
            "origen": e.origen,
            "membres": int(getattr(e, "membres_count", 0) or 0),
        }
        for e in equips
    ]


def _serialize_contexts(competicio: Competicio):
    return get_equip_context_payload(competicio)


def _get_context_or_400(competicio: Competicio, context_code: str):
    code = normalize_equip_context_code(context_code)
    if is_native_equip_context(code):
        return code, None, None
    ctx = get_custom_equip_context(competicio, code)
    if ctx is None:
        return code, None, HttpResponseBadRequest("context_code invalid")
    return code, ctx, None


def _filter_inscripcions(competicio: Competicio, filters: Optional[dict]):
    qs = Inscripcio.objects.filter(competicio=competicio)
    if not isinstance(filters, dict):
        return qs

    q = (filters.get("q") or "").strip()
    categoria = (filters.get("categoria") or "").strip()
    subcategoria = (filters.get("subcategoria") or "").strip()
    entitat = (filters.get("entitat") or "").strip()

    if subcategoria:
        qs = qs.filter(subcategoria__iexact=subcategoria)
    if entitat:
        qs = qs.filter(entitat__icontains=entitat)
    if categoria:
        qs = qs.filter(categoria__iexact=categoria)
    if q:
        qs = qs.filter(
            Q(nom_i_cognoms__icontains=q)
            | Q(document__icontains=q)
            | Q(entitat__icontains=q)
        )
    return qs


def _validated_partition_fields(competicio: Competicio, requested):
    requested = requested or []
    if not isinstance(requested, list):
        return []
    allowed = {f["code"] for f in get_allowed_group_fields(competicio)}
    out = []
    for code in requested:
        if isinstance(code, str) and code in allowed and code not in out:
            out.append(code)
    return out


def _partition_records(records, fields):
    grouped = OrderedDict()
    for ins in records:
        vals_norm = [_norm_val(_ins_value(ins, f)) for f in fields]
        vals_pretty = [_pretty_val(v) for v in vals_norm]
        key = json.dumps(vals_norm, ensure_ascii=False)
        if key not in grouped:
            grouped[key] = {"vals_norm": vals_norm, "vals_pretty": vals_pretty, "ids": []}
        grouped[key]["ids"].append(ins.id)
    return grouped


def _build_team_name(fields, vals_pretty):
    del fields  # kept in signature for compatibility with existing calls
    parts = [str(v).strip() for v in (vals_pretty or []) if str(v).strip()]
    return " | ".join(parts) if parts else "Equip automatic"


@require_POST
@csrf_protect
def equips_preview(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    if payload is None:
        return HttpResponseBadRequest("JSON invalid")

    fields = _validated_partition_fields(competicio, payload.get("fields"))
    if not fields:
        return HttpResponseBadRequest("No hi ha camps de particio valids")
    context_code = _payload_context_code(payload)
    _code, _ctx, err = _get_context_or_400(competicio, context_code)
    if err is not None:
        return err

    filters = payload.get("filters") or {}
    selected_ids = payload.get("selected_ids") or []
    if not isinstance(selected_ids, list):
        selected_ids = []

    qs = _filter_inscripcions(competicio, filters)
    if selected_ids:
        ids_clean = [int(x) for x in selected_ids if str(x).isdigit()]
        qs = qs.filter(id__in=ids_clean)

    builtin_fields = [f for f in fields if hasattr(Inscripcio, f)]
    records = list(qs.only("id", "extra", *builtin_fields).order_by("ordre_sortida", "id"))
    grouped = _partition_records(records, fields)

    preview = []
    for item in grouped.values():
        preview.append(
            {
                "nom_suggerit": _build_team_name(fields, item["vals_pretty"]),
                "count": len(item["ids"]),
                "values": item["vals_pretty"],
            }
        )

    return JsonResponse(
        {
            "ok": True,
            "context_code": context_code,
            "fields": fields,
            "total_inscripcions": len(records),
            "total_equips": len(preview),
            "preview": preview,
        }
    )


@require_POST
@csrf_protect
@transaction.atomic
def equips_auto_create(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    if payload is None:
        return HttpResponseBadRequest("JSON invalid")

    fields = _validated_partition_fields(competicio, payload.get("fields"))
    if not fields:
        return HttpResponseBadRequest("No hi ha camps de particio valids")
    context_code = _payload_context_code(payload)
    context_code, context_obj, err = _get_context_or_400(competicio, context_code)
    if err is not None:
        return err

    replace_existing = bool(payload.get("replace_existing", True))
    filters = payload.get("filters") or {}
    selected_ids = payload.get("selected_ids") or []
    if not isinstance(selected_ids, list):
        selected_ids = []

    qs = _filter_inscripcions(competicio, filters)
    if selected_ids:
        ids_clean = [int(x) for x in selected_ids if str(x).isdigit()]
        qs = qs.filter(id__in=ids_clean)

    builtin_fields = [f for f in fields if hasattr(Inscripcio, f)]
    only_fields = ["id", "extra", *builtin_fields]
    if is_native_equip_context(context_code):
        only_fields.append("equip_id")
    records = list(qs.only(*only_fields).order_by("ordre_sortida", "id"))
    if not records:
        return JsonResponse(
            with_inscripcions_history_payload(
                {"ok": True, "created": 0, "updated": 0, "equips": [], "contexts": _serialize_contexts(competicio)},
                request,
                competicio.id,
            )
        )

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    grouped = _partition_records(records, fields)
    team_by_key = {}
    created = 0
    existing_assignments = get_contextual_assignment_map(competicio, records, context_code)

    for g in grouped.values():
        name = _build_team_name(fields, g["vals_pretty"])
        equip, was_created = Equip.objects.get_or_create(
            competicio=competicio,
            nom=name,
            defaults={
                "origen": Equip.Origen.AUTO,
                "criteri": {
                    "mode": "partition",
                    "fields": fields,
                    "values": g["vals_norm"],
                },
            },
        )

        if was_created:
            created += 1
        team_by_key[json.dumps(g["vals_norm"], ensure_ascii=False)] = equip.id

    updated = 0
    if is_native_equip_context(context_code):
        updates = []
        for ins in records:
            vals_norm = [_norm_val(_ins_value(ins, f)) for f in fields]
            key = json.dumps(vals_norm, ensure_ascii=False)
            new_team_id = team_by_key.get(key)
            if not new_team_id:
                continue
            if replace_existing or getattr(ins, "equip_id", None) in (None, new_team_id):
                if getattr(ins, "equip_id", None) != new_team_id:
                    ins.equip_id = new_team_id
                    updates.append(ins)

        if updates:
            Inscripcio.objects.bulk_update(updates, ["equip"], batch_size=500)
        updated = len(updates)
    else:
        creates = []
        updates = []
        for ins in records:
            vals_norm = [_norm_val(_ins_value(ins, f)) for f in fields]
            key = json.dumps(vals_norm, ensure_ascii=False)
            new_team_id = team_by_key.get(key)
            if not new_team_id:
                continue

            current_row = existing_assignments.get(ins.id)
            current_team_id = getattr(current_row, "equip_id", None)
            if not replace_existing and current_team_id not in (None, new_team_id):
                continue
            if current_team_id == new_team_id:
                continue

            criteri = {
                "mode": "partition",
                "fields": fields,
                "values": vals_norm,
            }
            if current_row is None:
                creates.append(
                    InscripcioEquipAssignacio(
                        competicio=competicio,
                        context=context_obj,
                        inscripcio=ins,
                        equip_id=new_team_id,
                        origen=InscripcioEquipAssignacio.Origen.AUTO,
                        criteri=criteri,
                    )
                )
            else:
                current_row.equip_id = new_team_id
                current_row.origen = InscripcioEquipAssignacio.Origen.AUTO
                current_row.criteri = criteri
                updates.append(current_row)
        if creates:
            InscripcioEquipAssignacio.objects.bulk_create(creates, batch_size=500)
        if updates:
            InscripcioEquipAssignacio.objects.bulk_update(updates, ["equip", "origen", "criteri", "updated_at"], batch_size=500)
        updated = len(creates) + len(updates)

    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="equips_auto_create",
        action_label="Crear equips automaticament",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    _mark_live_dirty_on_commit(competicio.id)
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "context_code": context_code,
                "created": created,
                "updated": updated,
                "equips": _serialize_equips(competicio, context_code),
                "contexts": _serialize_contexts(competicio),
            },
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
@transaction.atomic
def equips_create_manual(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    if payload is None:
        return HttpResponseBadRequest("JSON invalid")

    nom = (payload.get("name") or "").strip()
    if not nom:
        return HttpResponseBadRequest("name buit")
    context_code = _payload_context_code(payload)
    context_code, context_obj, err = _get_context_or_400(competicio, context_code)
    if err is not None:
        return err

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    equip, created = Equip.objects.get_or_create(
        competicio=competicio,
        nom=nom,
        defaults={"origen": Equip.Origen.MANUAL, "criteri": {}},
    )

    selected_ids = payload.get("selected_ids") or []
    if not isinstance(selected_ids, list):
        selected_ids = []
    ids_clean = [int(x) for x in selected_ids if str(x).isdigit()]
    updated = 0
    if ids_clean:
        if is_native_equip_context(context_code):
            updated = Inscripcio.objects.filter(
                competicio=competicio,
                id__in=ids_clean,
            ).update(equip=equip)
        else:
            ins_qs = list(Inscripcio.objects.filter(competicio=competicio, id__in=ids_clean).only("id"))
            existing_assignments = get_contextual_assignment_map(competicio, ids_clean, context_code)
            creates = []
            updates = []
            for ins in ins_qs:
                current_row = existing_assignments.get(ins.id)
                if current_row is None:
                    creates.append(
                        InscripcioEquipAssignacio(
                            competicio=competicio,
                            context=context_obj,
                            inscripcio=ins,
                            equip=equip,
                            origen=InscripcioEquipAssignacio.Origen.MANUAL,
                            criteri={},
                        )
                    )
                elif current_row.equip_id != equip.id or current_row.origen != InscripcioEquipAssignacio.Origen.MANUAL:
                    current_row.equip = equip
                    current_row.origen = InscripcioEquipAssignacio.Origen.MANUAL
                    current_row.criteri = {}
                    updates.append(current_row)
            if creates:
                InscripcioEquipAssignacio.objects.bulk_create(creates, batch_size=500)
            if updates:
                InscripcioEquipAssignacio.objects.bulk_update(updates, ["equip", "origen", "criteri", "updated_at"], batch_size=500)
            updated = len(creates) + len(updates)

    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="equips_create_manual",
        action_label="Crear equip manual",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    _mark_live_dirty_on_commit(competicio.id)
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "context_code": context_code,
                "created": created,
                "equip_id": equip.id,
                "updated": updated,
                "equips": _serialize_equips(competicio, context_code),
                "contexts": _serialize_contexts(competicio),
            },
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
@transaction.atomic
def equips_assign(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    if payload is None:
        return HttpResponseBadRequest("JSON invalid")

    equip_id = payload.get("equip_id")
    if not str(equip_id).isdigit():
        return HttpResponseBadRequest("equip_id invalid")
    context_code = _payload_context_code(payload)
    context_code, context_obj, err = _get_context_or_400(competicio, context_code)
    if err is not None:
        return err

    equip = get_object_or_404(Equip, pk=int(equip_id), competicio=competicio)
    ids = payload.get("inscripcio_ids") or []
    if not isinstance(ids, list):
        ids = []
    ids_clean = [int(x) for x in ids if str(x).isdigit()]
    if not ids_clean:
        return HttpResponseBadRequest("No hi ha inscripcions seleccionades")

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    if is_native_equip_context(context_code):
        updated = Inscripcio.objects.filter(competicio=competicio, id__in=ids_clean).update(equip=equip)
    else:
        ins_qs = list(Inscripcio.objects.filter(competicio=competicio, id__in=ids_clean).only("id"))
        existing_assignments = get_contextual_assignment_map(competicio, ids_clean, context_code)
        creates = []
        updates = []
        for ins in ins_qs:
            current_row = existing_assignments.get(ins.id)
            if current_row is None:
                creates.append(
                    InscripcioEquipAssignacio(
                        competicio=competicio,
                        context=context_obj,
                        inscripcio=ins,
                        equip=equip,
                        origen=InscripcioEquipAssignacio.Origen.MANUAL,
                        criteri={},
                    )
                )
            elif current_row.equip_id != equip.id or current_row.origen != InscripcioEquipAssignacio.Origen.MANUAL:
                current_row.equip = equip
                current_row.origen = InscripcioEquipAssignacio.Origen.MANUAL
                current_row.criteri = {}
                updates.append(current_row)
        if creates:
            InscripcioEquipAssignacio.objects.bulk_create(creates, batch_size=500)
        if updates:
            InscripcioEquipAssignacio.objects.bulk_update(updates, ["equip", "origen", "criteri", "updated_at"], batch_size=500)
        updated = len(creates) + len(updates)
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="equips_assign",
        action_label="Assignar equip",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    _mark_live_dirty_on_commit(competicio.id)
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "updated": updated, "context_code": context_code},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
@transaction.atomic
def equips_unassign(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    if payload is None:
        return HttpResponseBadRequest("JSON invalid")

    ids = payload.get("inscripcio_ids") or []
    if not isinstance(ids, list):
        ids = []
    ids_clean = [int(x) for x in ids if str(x).isdigit()]
    if not ids_clean:
        return HttpResponseBadRequest("No hi ha inscripcions seleccionades")
    context_code = _payload_context_code(payload)
    context_code, context_obj, err = _get_context_or_400(competicio, context_code)
    if err is not None:
        return err

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    if is_native_equip_context(context_code):
        updated = Inscripcio.objects.filter(competicio=competicio, id__in=ids_clean).update(equip=None)
    else:
        updated, _deleted = InscripcioEquipAssignacio.objects.filter(
            competicio=competicio,
            context=context_obj,
            inscripcio_id__in=ids_clean,
        ).delete()
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="equips_unassign",
        action_label="Treure equip",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    _mark_live_dirty_on_commit(competicio.id)
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "updated": updated, "context_code": context_code},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
@transaction.atomic
def equips_rename(request, pk, equip_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    equip = get_object_or_404(Equip, pk=equip_id, competicio=competicio)
    payload = _parse_payload(request)
    if payload is None:
        return HttpResponseBadRequest("JSON invalid")

    new_name = (payload.get("name") or "").strip()
    if not new_name:
        return HttpResponseBadRequest("name buit")
    context_code = _payload_context_code(payload)
    _code, _ctx, err = _get_context_or_400(competicio, context_code)
    if err is not None:
        return err

    exists = Equip.objects.filter(competicio=competicio, nom=new_name).exclude(pk=equip.id).exists()
    if exists:
        return HttpResponseBadRequest("Ja existeix un equip amb aquest nom")

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    equip.nom = new_name
    equip.save(update_fields=["nom", "updated_at"])
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="equips_rename",
        action_label="Renombrar equip",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    _mark_live_dirty_on_commit(competicio.id)
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "equip_id": equip.id, "name": equip.nom, "context_code": context_code},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
@transaction.atomic
def equips_delete(request, pk, equip_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    equip = get_object_or_404(Equip, pk=equip_id, competicio=competicio)
    payload = _parse_payload(request) or {}
    context_code = _payload_context_code(payload)
    context_code, context_obj, err = _get_context_or_400(competicio, context_code)
    if err is not None:
        return err
    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    if is_native_equip_context(context_code):
        equip.delete()
    else:
        InscripcioEquipAssignacio.objects.filter(
            competicio=competicio,
            context=context_obj,
            equip=equip,
        ).delete()
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="equips_delete",
        action_label="Eliminar equip",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    _mark_live_dirty_on_commit(competicio.id)
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "context_code": context_code},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
@transaction.atomic
def equips_delete_all(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request) or {}
    context_code = _payload_context_code(payload)
    context_code, context_obj, err = _get_context_or_400(competicio, context_code)
    if err is not None:
        return err
    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    if is_native_equip_context(context_code):
        deleted_count, _ = Equip.objects.filter(competicio=competicio).delete()
    else:
        deleted_count, _ = InscripcioEquipAssignacio.objects.filter(
            competicio=competicio,
            context=context_obj,
        ).delete()
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="equips_delete_all",
        action_label="Eliminar tots els equips",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    _mark_live_dirty_on_commit(competicio.id)
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "deleted": deleted_count, "context_code": context_code},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
@transaction.atomic
def equip_context_create(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    if payload is None:
        return HttpResponseBadRequest("JSON invalid")

    nom = str(payload.get("name") or "").strip()
    if not nom:
        return HttpResponseBadRequest("name buit")

    code = str(payload.get("code") or "").strip()
    if code:
        code = slugify(code)
        if not code or code == NATIVE_EQUIP_CONTEXT_CODE:
            return HttpResponseBadRequest("code invalid")
        if EquipContext.objects.filter(competicio=competicio, code=code).exists():
            return HttpResponseBadRequest("Ja existeix un context amb aquest codi")
    else:
        code = build_unique_equip_context_code(competicio, nom)

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    ctx = EquipContext.objects.create(
        competicio=competicio,
        code=code,
        nom=nom,
        description=str(payload.get("description") or "").strip(),
    )
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="equip_context_create",
        action_label="Crear context d'equips",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    _mark_live_dirty_on_commit(competicio.id)
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "context": {"code": ctx.code, "nom": ctx.nom}, "contexts": _serialize_contexts(competicio)},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
@transaction.atomic
def equip_context_rename(request, pk, context_code):
    competicio = get_object_or_404(Competicio, pk=pk)
    ctx = get_custom_equip_context(competicio, context_code)
    if ctx is None:
        return HttpResponseBadRequest("context_code invalid")
    payload = _parse_payload(request)
    if payload is None:
        return HttpResponseBadRequest("JSON invalid")

    nom = str(payload.get("name") or "").strip()
    if not nom:
        return HttpResponseBadRequest("name buit")

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    ctx.nom = nom
    ctx.description = str(payload.get("description") or ctx.description or "").strip()
    ctx.save(update_fields=["nom", "description", "updated_at"])
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="equip_context_rename",
        action_label="Renombrar context d'equips",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    _mark_live_dirty_on_commit(competicio.id)
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "context": {"code": ctx.code, "nom": ctx.nom}, "contexts": _serialize_contexts(competicio)},
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
@transaction.atomic
def equip_context_delete(request, pk, context_code):
    competicio = get_object_or_404(Competicio, pk=pk)
    ctx = get_custom_equip_context(competicio, context_code)
    if ctx is None:
        return HttpResponseBadRequest("context_code invalid")

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    ctx.delete()
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="equip_context_delete",
        action_label="Eliminar context d'equips",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    _mark_live_dirty_on_commit(competicio.id)
    return JsonResponse(
        with_inscripcions_history_payload(
            {"ok": True, "contexts": _serialize_contexts(competicio)},
            request,
            competicio.id,
        )
    )
