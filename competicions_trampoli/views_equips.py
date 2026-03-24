import json
from collections import OrderedDict, defaultdict
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
    get_equip_context_summary,
    get_equip_context_payload,
    get_equips_for_context,
    get_team_members_payload_for_context,
    is_native_equip_context,
    normalize_equip_context_code,
    resolve_inscripcio_equip,
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


def _serialize_equips(
    competicio: Competicio,
    context_code=NATIVE_EQUIP_CONTEXT_CODE,
    members_by_team_id=None,
):
    equips = get_equips_for_context(competicio, context_code)
    members_map = members_by_team_id if isinstance(members_by_team_id, dict) else {}
    return [
        {
            "id": e.id,
            "nom": e.nom,
            "origen": e.origen,
            "membres": int(getattr(e, "membres_count", 0) or 0),
            "members": list(members_map.get(int(e.id), []) or []),
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


def _append_preview_sample(container, value, limit=4):
    if not value:
        return
    items = container.setdefault("items", [])
    if len(items) < limit:
        items.append(str(value))
    container["extra"] = int(container.get("extra") or 0) + 1


def _finalize_preview_sample(container):
    if not isinstance(container, dict):
        return [], 0
    items = [str(x).strip() for x in (container.get("items") or []) if str(x).strip()]
    total = int(container.get("extra") or 0)
    remaining = max(0, total - len(items))
    return items, remaining


def _filters_are_active(filters):
    if not isinstance(filters, dict):
        return False
    return any(str(filters.get(key) or "").strip() for key in ("q", "categoria", "subcategoria", "entitat"))


def _build_preview_selection_summary(records_count, filters, selected_ids, replace_existing):
    selected_count = len(selected_ids or [])
    filters_active = _filters_are_active(filters)
    if selected_count:
        mode = "selected"
        label = f"{records_count} seleccionades"
    elif filters_active:
        mode = "filtered"
        label = f"{records_count} filtrades"
    else:
        mode = "all"
        label = f"{records_count} totals"
    return {
        "mode": mode,
        "label": label,
        "selected_count": selected_count,
        "filters_active": filters_active,
        "replace_existing": bool(replace_existing),
    }


def _normalize_workspace_filters(filters):
    data = filters if isinstance(filters, dict) else {}
    return {
        "q": str(data.get("q") or "").strip(),
        "categoria": str(data.get("categoria") or "").strip(),
        "subcategoria": str(data.get("subcategoria") or "").strip(),
        "entitat": str(data.get("entitat") or "").strip(),
        "assignment_state": str(data.get("assignment_state") or "all").strip().lower() or "all",
        "equip_id": str(data.get("equip_id") or "").strip(),
    }


def _serialize_workspace_candidate(ins, context_code, current_team=None):
    native_team = getattr(ins, "equip", None)
    current_team_id = getattr(current_team, "id", None)
    native_team_id = getattr(native_team, "id", None)
    return {
        "id": int(ins.id),
        "nom": str(getattr(ins, "nom_i_cognoms", "") or "").strip(),
        "document": str(getattr(ins, "document", "") or "").strip(),
        "entitat": str(getattr(ins, "entitat", "") or "").strip(),
        "categoria": str(getattr(ins, "categoria", "") or "").strip(),
        "subcategoria": str(getattr(ins, "subcategoria", "") or "").strip(),
        "current_team_id": current_team_id,
        "current_team_name": str(getattr(current_team, "nom", "") or "").strip(),
        "native_team_id": native_team_id,
        "native_team_name": str(getattr(native_team, "nom", "") or "").strip(),
        "has_team_in_context": bool(current_team_id),
        "show_native_team_hint": not is_native_equip_context(context_code),
    }


def _build_workspace_filter_options(records, context_code, assignment_map, teams):
    categories = sorted({str(getattr(ins, "categoria", "") or "").strip() for ins in records if str(getattr(ins, "categoria", "") or "").strip()})
    subcategories = sorted({str(getattr(ins, "subcategoria", "") or "").strip() for ins in records if str(getattr(ins, "subcategoria", "") or "").strip()})
    entitats = sorted({str(getattr(ins, "entitat", "") or "").strip() for ins in records if str(getattr(ins, "entitat", "") or "").strip()})
    return {
        "categories": categories,
        "subcategories": subcategories,
        "entitats": entitats,
        "teams": [
            {
                "id": int(e.id),
                "name": str(e.nom or "").strip(),
                "members": int(getattr(e, "membres_count", 0) or 0),
            }
            for e in teams
        ],
        "assignment_states": [
            {"id": "all", "label": "Totes"},
            {"id": "unassigned", "label": "Sense equip en aquest context"},
            {"id": "assigned", "label": "Amb equip en aquest context"},
        ],
    }


def _build_workspace_payload(competicio, context_code, filters=None, page=1, page_size=40):
    filters = _normalize_workspace_filters(filters)
    page = max(1, int(page or 1))
    page_size = max(10, min(200, int(page_size or 40)))
    qs = (
        _filter_inscripcions(competicio, filters)
        .select_related("equip")
        .only("id", "nom_i_cognoms", "document", "entitat", "categoria", "subcategoria", "equip_id", "ordre_sortida")
        .order_by("ordre_sortida", "id")
    )
    records = list(qs)
    teams = list(get_equips_for_context(competicio, context_code))
    team_members = get_team_members_payload_for_context(competicio, context_code)
    assignment_map = get_contextual_assignment_map(competicio, records, context_code)

    equip_id_filter = None
    if str(filters.get("equip_id") or "").isdigit():
        equip_id_filter = int(filters["equip_id"])
    assignment_state = str(filters.get("assignment_state") or "all").strip().lower()

    filtered_candidates = []
    for ins in records:
        current_team = resolve_inscripcio_equip(
            ins,
            context_code=context_code,
            fallback=None,
            assignment_map=assignment_map,
        )
        current_team_id = getattr(current_team, "id", None)
        if assignment_state == "assigned" and current_team_id is None:
            continue
        if assignment_state == "unassigned" and current_team_id is not None:
            continue
        if equip_id_filter and current_team_id != equip_id_filter:
            continue
        filtered_candidates.append(_serialize_workspace_candidate(ins, context_code, current_team=current_team))

    total_filtered = len(filtered_candidates)
    start = (page - 1) * page_size
    end = start + page_size
    page_rows = filtered_candidates[start:end]
    summary = get_equip_context_summary(competicio, context_code)

    return {
        "ok": True,
        "context_code": context_code,
        "context": next((item for item in get_equip_context_payload(competicio) if item["code"] == context_code), {
            "code": context_code,
            "nom": "Context",
            "description": "",
            "is_native": is_native_equip_context(context_code),
        }),
        "summary": {
            **summary,
            "filtered_count": total_filtered,
            "page_count": len(page_rows),
        },
        "filters": filters,
        "filter_options": _build_workspace_filter_options(records, context_code, assignment_map, teams),
        "candidates": {
            "items": page_rows,
            "total": total_filtered,
            "page": page,
            "page_size": page_size,
            "has_more": end < total_filtered,
        },
        "teams": _serialize_equips(competicio, context_code, members_by_team_id=team_members),
        "contexts": _serialize_contexts(competicio),
    }


@require_POST
@csrf_protect
def equips_workspace(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    payload = _parse_payload(request)
    if payload is None:
        return HttpResponseBadRequest("JSON invalid")

    context_code = _payload_context_code(payload)
    context_code, _ctx, err = _get_context_or_400(competicio, context_code)
    if err is not None:
        return err

    filters = payload.get("filters") or {}
    page = payload.get("page") or 1
    page_size = payload.get("page_size") or 40
    return JsonResponse(_build_workspace_payload(competicio, context_code, filters=filters, page=page, page_size=page_size))


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
    replace_existing = bool(payload.get("replace_existing", True))

    qs = _filter_inscripcions(competicio, filters)
    ids_clean = []
    if selected_ids:
        ids_clean = [int(x) for x in selected_ids if str(x).isdigit()]
        qs = qs.filter(id__in=ids_clean)

    builtin_fields = [f for f in fields if hasattr(Inscripcio, f)]
    only_fields = ["id", "extra", "nom_i_cognoms", *builtin_fields]
    if is_native_equip_context(context_code):
        only_fields.append("equip_id")
    records = list(qs.only(*only_fields).order_by("ordre_sortida", "id"))
    grouped = _partition_records(records, fields)
    record_map = OrderedDict((ins.id, ins) for ins in records)
    existing_assignments = get_contextual_assignment_map(competicio, records, context_code)
    existing_teams = list(get_equips_for_context(competicio, context_code))
    existing_team_by_id = {e.id: e for e in existing_teams}
    existing_team_by_name = {str(e.nom or "").strip(): e for e in existing_teams}
    source_impact = defaultdict(
        lambda: {
            "team_id": None,
            "team_name": "",
            "current_members_context": 0,
            "outgoing_count": 0,
            "incoming_count": 0,
            "keep_count": 0,
            "sample": {"items": [], "extra": 0},
        }
    )
    target_impact = defaultdict(
        lambda: {
            "team_id": None,
            "team_name": "",
            "current_members_context": 0,
            "outgoing_count": 0,
            "incoming_count": 0,
            "keep_count": 0,
            "sample": {"items": [], "extra": 0},
        }
    )

    preview = []
    for item in grouped.values():
        target_name = _build_team_name(fields, item["vals_pretty"])
        target_team = existing_team_by_name.get(target_name)
        target_team_id = getattr(target_team, "id", None)
        member_sample = {"items": [], "extra": 0}
        current_same_count = 0
        current_other_count = 0
        current_none_count = 0
        skipped_reassign_count = 0

        for ins_id in item["ids"]:
            ins = record_map.get(ins_id)
            if ins is None:
                continue
            current_team = resolve_inscripcio_equip(
                ins,
                context_code=context_code,
                fallback=None,
                assignment_map=existing_assignments,
            )
            current_team_id = getattr(current_team, "id", None)
            if current_team_id is None:
                current_none_count += 1
            elif target_team_id and current_team_id == target_team_id:
                current_same_count += 1
            else:
                current_other_count += 1
                if not replace_existing and current_team_id is not None:
                    skipped_reassign_count += 1

            _append_preview_sample(member_sample, getattr(ins, "nom_i_cognoms", ""))

            if target_team_id:
                target_entry = target_impact[target_team_id]
                target_entry["team_id"] = target_team_id
                target_entry["team_name"] = str(target_team.nom or "").strip()
                target_entry["current_members_context"] = int(getattr(target_team, "membres_count", 0) or 0)
                if current_team_id == target_team_id:
                    target_entry["keep_count"] += 1
                    _append_preview_sample(target_entry["sample"], getattr(ins, "nom_i_cognoms", ""))
                elif current_team_id is None or replace_existing:
                    target_entry["incoming_count"] += 1
                    _append_preview_sample(target_entry["sample"], getattr(ins, "nom_i_cognoms", ""))

            if replace_existing and current_team_id and current_team_id != target_team_id:
                source_team = current_team or existing_team_by_id.get(current_team_id)
                if source_team is not None:
                    source_entry = source_impact[current_team_id]
                    source_entry["team_id"] = current_team_id
                    source_entry["team_name"] = str(getattr(source_team, "nom", "") or "").strip()
                    source_entry["current_members_context"] = int(getattr(source_team, "membres_count", 0) or 0)
                    source_entry["outgoing_count"] += 1
                    _append_preview_sample(source_entry["sample"], getattr(ins, "nom_i_cognoms", ""))

        member_samples, member_samples_remaining = _finalize_preview_sample(member_sample)
        preview.append(
            {
                "nom_suggerit": target_name,
                "count": len(item["ids"]),
                "values": item["vals_pretty"],
                "member_samples": member_samples,
                "member_samples_remaining": member_samples_remaining,
                "existing_team_id": target_team_id,
                "existing_team_name": str(target_team.nom or "").strip() if target_team else "",
                "will_create": target_team is None,
                "will_reassign": bool(replace_existing and current_other_count > 0),
                "will_keep": bool(current_same_count > 0),
                "current_same_count": current_same_count,
                "current_other_count": current_other_count,
                "current_none_count": current_none_count,
                "skipped_reassign_count": skipped_reassign_count,
            }
        )

    def _serialize_impact_rows(rows_dict):
        rows = []
        for row in rows_dict.values():
            sample_items, sample_remaining = _finalize_preview_sample(row.get("sample"))
            current_members_context = int(row.get("current_members_context") or 0)
            outgoing_count = int(row.get("outgoing_count") or 0)
            incoming_count = int(row.get("incoming_count") or 0)
            keep_count = int(row.get("keep_count") or 0)
            remaining_members = max(0, current_members_context - outgoing_count)
            impact_kind = "existing"
            if outgoing_count > 0 and remaining_members == 0:
                impact_kind = "removed"
            elif outgoing_count > 0:
                impact_kind = "reduced"
            elif incoming_count > 0:
                impact_kind = "incoming"
            rows.append(
                {
                    "team_id": row.get("team_id"),
                    "team_name": row.get("team_name") or "Equip",
                    "current_members_context": current_members_context,
                    "remaining_members_context": remaining_members,
                    "outgoing_count": outgoing_count,
                    "incoming_count": incoming_count,
                    "keep_count": keep_count,
                    "impact_kind": impact_kind,
                    "member_samples": sample_items,
                    "member_samples_remaining": sample_remaining,
                }
            )
        rows.sort(
            key=lambda item: (
                str(item.get("impact_kind") or ""),
                str(item.get("team_name") or "").lower(),
                int(item.get("team_id") or 0),
            )
        )
        return rows

    affected_teams = _serialize_impact_rows(source_impact)
    affected_by_target = _serialize_impact_rows(target_impact)
    seen_team_ids = {int(row.get("team_id") or 0) for row in affected_teams if row.get("team_id")}
    for row in affected_by_target:
        team_id = int(row.get("team_id") or 0)
        if team_id and team_id in seen_team_ids:
            for source_row in affected_teams:
                if int(source_row.get("team_id") or 0) != team_id:
                    continue
                source_row["incoming_count"] = int(source_row.get("incoming_count") or 0) + int(row.get("incoming_count") or 0)
                source_row["keep_count"] = int(source_row.get("keep_count") or 0) + int(row.get("keep_count") or 0)
                existing_samples = list(source_row.get("member_samples") or [])
                for sample_name in row.get("member_samples") or []:
                    if sample_name not in existing_samples and len(existing_samples) < 4:
                        existing_samples.append(sample_name)
                source_row["member_samples"] = existing_samples
                source_row["member_samples_remaining"] = max(
                    0,
                    int(source_row.get("member_samples_remaining") or 0) + int(row.get("member_samples_remaining") or 0),
                )
                if source_row.get("impact_kind") not in ("removed", "reduced"):
                    source_row["impact_kind"] = "incoming" if int(source_row.get("incoming_count") or 0) > 0 else "existing"
                break
        else:
            affected_teams.append(row)

    assigned_total = sum(int(getattr(e, "membres_count", 0) or 0) for e in existing_teams)
    teams_with_members = sum(1 for e in existing_teams if int(getattr(e, "membres_count", 0) or 0) > 0)

    return JsonResponse(
        {
            "ok": True,
            "context_code": context_code,
            "fields": fields,
            "total_inscripcions": len(records),
            "total_equips": len(preview),
            "selection_summary": _build_preview_selection_summary(
                len(records),
                filters,
                ids_clean,
                replace_existing,
            ),
            "existing_summary": {
                "teams_total": len(existing_teams),
                "teams_with_members": teams_with_members,
                "assigned_total": assigned_total,
                "affected_teams": affected_teams,
            },
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
