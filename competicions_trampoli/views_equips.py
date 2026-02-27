import json
from collections import OrderedDict
from typing import Optional

from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .models import Competicio, Equip, Inscripcio
from .views import get_allowed_group_fields


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


def _serialize_equips(competicio: Competicio):
    qs = (
        Equip.objects.filter(competicio=competicio)
        .annotate(membres_count=Count("membres"))
        .order_by("nom", "id")
    )
    return [
        {
            "id": e.id,
            "nom": e.nom,
            "origen": e.origen,
            "membres": e.membres_count,
        }
        for e in qs
    ]


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
    records = list(qs.only("id", "extra", "equip_id", *builtin_fields).order_by("ordre_sortida", "id"))
    if not records:
        return JsonResponse({"ok": True, "created": 0, "updated": 0, "equips": []})

    grouped = _partition_records(records, fields)
    team_by_key = {}
    created = 0

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

    updates = []
    for ins in records:
        vals_norm = [_norm_val(_ins_value(ins, f)) for f in fields]
        key = json.dumps(vals_norm, ensure_ascii=False)
        new_team_id = team_by_key.get(key)
        if not new_team_id:
            continue
        if replace_existing or ins.equip_id in (None, new_team_id):
            if ins.equip_id != new_team_id:
                ins.equip_id = new_team_id
                updates.append(ins)

    if updates:
        Inscripcio.objects.bulk_update(updates, ["equip"], batch_size=500)

    return JsonResponse(
        {
            "ok": True,
            "created": created,
            "updated": len(updates),
            "equips": _serialize_equips(competicio),
        }
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
        updated = Inscripcio.objects.filter(
            competicio=competicio,
            id__in=ids_clean,
        ).update(equip=equip)

    return JsonResponse(
        {
            "ok": True,
            "created": created,
            "equip_id": equip.id,
            "updated": updated,
            "equips": _serialize_equips(competicio),
        }
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

    equip = get_object_or_404(Equip, pk=int(equip_id), competicio=competicio)
    ids = payload.get("inscripcio_ids") or []
    if not isinstance(ids, list):
        ids = []
    ids_clean = [int(x) for x in ids if str(x).isdigit()]
    if not ids_clean:
        return HttpResponseBadRequest("No hi ha inscripcions seleccionades")

    updated = Inscripcio.objects.filter(competicio=competicio, id__in=ids_clean).update(equip=equip)
    return JsonResponse({"ok": True, "updated": updated})


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

    updated = Inscripcio.objects.filter(competicio=competicio, id__in=ids_clean).update(equip=None)
    return JsonResponse({"ok": True, "updated": updated})


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

    exists = Equip.objects.filter(competicio=competicio, nom=new_name).exclude(pk=equip.id).exists()
    if exists:
        return HttpResponseBadRequest("Ja existeix un equip amb aquest nom")

    equip.nom = new_name
    equip.save(update_fields=["nom", "updated_at"])
    return JsonResponse({"ok": True, "equip_id": equip.id, "name": equip.nom})


@require_POST
@csrf_protect
@transaction.atomic
def equips_delete(request, pk, equip_id):
    competicio = get_object_or_404(Competicio, pk=pk)
    equip = get_object_or_404(Equip, pk=equip_id, competicio=competicio)
    equip.delete()
    return JsonResponse({"ok": True})


@require_POST
@csrf_protect
@transaction.atomic
def equips_delete_all(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    deleted_count, _ = Equip.objects.filter(competicio=competicio).delete()
    return JsonResponse({"ok": True, "deleted": deleted_count})
