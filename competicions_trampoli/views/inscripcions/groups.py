import json
import math

from django.db import transaction
from django.db.models import Max
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from ...access import user_has_competicio_capability
from ...models import Competicio, GrupCompeticio, Inscripcio
from ...services.shared.competition_groups import (
    clear_inscripcions_group,
    compact_competition_order_for_group,
    ensure_group_for_display_num,
    get_group_board_filter_facets,
    get_competicio_groups,
    get_group_card_payload,
    get_group_detail_payload,
    get_group_for_display_num,
    get_group_maps,
    get_group_member_preview,
    get_group_summary_counts,
    get_programmed_group_ids,
    get_programmed_groups_emptied_by_ids,
    group_label,
    move_inscripcio_to_group,
    move_inscripcions_to_group,
    next_group_display_num,
    normalize_inscripcio_ids,
    normalize_positive_int,
    safe_deactivate_empty_group,
    save_group_competition_order,
    sync_competicio_group_names_view,
)
from ...services.inscripcions.groups import (
    _persist_group_suggested_names,
    sync_stable_groups_from_legacy,
)
from ...services.inscripcions.history import (
    capture_inscripcions_history_snapshot,
    record_inscripcions_history_entry,
    with_inscripcions_history_payload,
)
from ...services.inscripcions.queries import (
    _apply_group_suggested_names,
    _build_existing_groups_preview,
    _build_group_name_filter_sources,
    _build_inscripcions_filtered_qs,
    _build_sort_records_queryset,
    _build_bucket_source_kinds,
    _build_bucket_source_label,
    _bucket_labels_by_kind,
    _bucket_source_signature,
    _extract_sort_partition_codes,
    _message_for_emptied_programmed_groups,
    _normalize_sort_criterion,
    _normalize_sort_filters,
    _normalize_sort_group_by,
    _normalize_bucket_source_entries,
    _resolve_group_creation_buckets,
    annotate_inscripcions_queryset_for_group_codes,
    build_inscripcions_sort_context_key,
    competicio_has_rotacions,
    get_allowed_group_fields,
    get_available_sort_fields,
    get_competicio_custom_sort_rank_map,
    get_inscripcions_sort_context_state,
    reconcile_inscripcions_sort_context_state,
)
from ...services.inscripcions.sorting import sort_records_by_field_stable


def _normalize_group_workspace_filters(raw_filters):
    filters = raw_filters if isinstance(raw_filters, dict) else {}

    def _normalize_positive_int_list(raw_values):
        out = []
        values = raw_values if isinstance(raw_values, list) else []
        for value in values:
            try:
                clean = int(value)
            except Exception:
                continue
            if clean > 0 and clean not in out:
                out.append(clean)
        return out

    out = {
        **_normalize_sort_filters(filters),
        "group_state": str(filters.get("group_state") or "all").strip().lower(),
        "group_ids": _normalize_positive_int_list(filters.get("group_ids")),
        "group_id": None,
        "group_num": None,
    }
    if out["group_state"] not in {"all", "assigned", "unassigned"}:
        out["group_state"] = "all"
    try:
        group_id = int(filters.get("group_id"))
    except Exception:
        group_id = None
    try:
        group_num = int(filters.get("group_num"))
    except Exception:
        group_num = None
    if out.get("categoria") and out["categoria"] not in out["categories"]:
        out["categories"].append(out["categoria"])
    if out.get("subcategoria") and out["subcategoria"] not in out["subcategories"]:
        out["subcategories"].append(out["subcategoria"])
    if out.get("entitat") and out["entitat"] not in out["entitats"]:
        out["entitats"].append(out["entitat"])
    out["group_id"] = group_id if group_id and group_id > 0 else None
    out["group_num"] = group_num if group_num and group_num > 0 else None
    if out["group_id"] and out["group_id"] not in out["group_ids"]:
        out["group_ids"].append(out["group_id"])
    return out


def _build_group_workspace_candidates_qs(competicio, filters):
    filters = _normalize_group_workspace_filters(filters)
    qs = _build_inscripcions_filtered_qs(competicio, filters)
    group_ids = list(filters.get("group_ids") or [])
    group_id = filters.get("group_id")
    group_num = filters.get("group_num")
    if group_ids:
        qs = qs.filter(grup_competicio_id__in=group_ids)
    elif group_id:
        qs = qs.filter(grup_competicio_id=group_id)
    elif group_num:
        qs = qs.filter(grup=group_num)
    if filters["group_state"] == "assigned":
        qs = qs.filter(grup_competicio__isnull=False)
    elif filters["group_state"] == "unassigned":
        qs = qs.filter(grup_competicio__isnull=True)
    return qs


def _resolve_group_workspace_filtered_target_ids(competicio, filters):
    normalized_filters = _normalize_group_workspace_filters(filters)
    target_ids = list(_build_group_workspace_candidates_qs(competicio, normalized_filters).order_by("ordre_sortida", "id").values_list("id", flat=True))
    return {"filters": normalized_filters, "target_ids": normalize_inscripcio_ids(target_ids)}


def _resolve_group_workspace_target_ids(competicio, payload):
    filters = _normalize_group_workspace_filters(payload.get("filters"))
    selected_ids = normalize_inscripcio_ids(payload.get("selected_ids") or payload.get("ids") or [])
    if selected_ids:
        target_ids = list(selected_ids)
    elif str(payload.get("scope") or "").strip().lower() == "filtered":
        target_ids = _resolve_group_workspace_filtered_target_ids(competicio, filters)["target_ids"]
    else:
        target_ids = []
    return {"filters": filters, "selected_ids": selected_ids, "target_ids": normalize_inscripcio_ids(target_ids)}


def _normalize_group_workspace_auto_context_source_scope(raw_scope):
    scope = str(raw_scope or "competition_all").strip().lower()
    if scope not in {"competition_all", "selected"}:
        scope = "competition_all"
    return scope


def _normalize_group_workspace_bucket_fields(raw_codes, allowed_codes, used_codes=None):
    if not isinstance(raw_codes, list):
        return []
    used = set(used_codes or [])
    out = []
    for raw_code in raw_codes:
        code = str(raw_code or "").strip()
        if code not in allowed_codes and code.startswith("excel__"):
            legacy_code = code[len("excel__"):]
            if legacy_code in allowed_codes:
                code = legacy_code
        if code not in allowed_codes and f"excel__{code}" in allowed_codes:
            code = f"excel__{code}"
        if not code or code not in allowed_codes or code in used or code in out:
            continue
        out.append(code)
    return out


def _resolve_group_workspace_auto_context_inputs(competicio, request, payload):
    sort_context_filters_raw = payload.get("sort_context_filters")
    if not isinstance(sort_context_filters_raw, dict):
        sort_context_filters_raw = payload.get("filters")
    workspace_filters_raw = payload.get("workspace_filters")
    if not isinstance(workspace_filters_raw, dict):
        workspace_filters_raw = payload.get("filters")

    sort_context_filters = _normalize_sort_filters(sort_context_filters_raw)
    workspace_filters = _normalize_group_workspace_filters(workspace_filters_raw)
    selected_ids = normalize_inscripcio_ids(payload.get("selected_ids") or payload.get("ids") or [])
    source_scope = _normalize_group_workspace_auto_context_source_scope(payload.get("source_scope"))

    allowed_group_fields = get_allowed_group_fields(competicio)
    allowed_group_codes = {field["code"] for field in allowed_group_fields if field.get("code")}
    selected_group_codes = _normalize_sort_group_by(payload.get("group_by"), allowed_group_codes, fallback_group_by=competicio.group_by_default or [])

    sort_fields = get_available_sort_fields(competicio)
    sort_codes = {field["code"] for field in sort_fields if field.get("code")}
    context_key = build_inscripcions_sort_context_key(competicio.id, filters=sort_context_filters, group_by=selected_group_codes)
    sort_state = get_inscripcions_sort_context_state(request, context_key)
    stack_raw = sort_state.get("stack") if isinstance(sort_state.get("stack"), list) else []
    stack = []
    for item in stack_raw:
        normalized = _normalize_sort_criterion(item, sort_codes=sort_codes, allowed_group_codes=allowed_group_codes, fallback_group_by=selected_group_codes)
        if normalized is not None:
            stack.append(normalized)
    partition_codes = _extract_sort_partition_codes(stack)
    workspace_bucket_codes = _normalize_group_workspace_bucket_fields(
        payload.get("workspace_bucket_fields"),
        allowed_group_codes,
        used_codes=set(selected_group_codes) | set(partition_codes),
    )

    group_field_label_by_code = {field["code"]: field.get("ui_label") or field.get("label") or field["code"] for field in allowed_group_fields if isinstance(field, dict) and field.get("code")}
    sort_field_label_by_code = {field["code"]: field.get("ui_label") or field.get("label") or field["code"] for field in sort_fields if isinstance(field, dict) and field.get("code")}

    return {
        "sort_context_filters": sort_context_filters,
        "workspace_filters": workspace_filters,
        "selected_ids": selected_ids,
        "source_scope": source_scope,
        "selected_group_codes": selected_group_codes,
        "partition_codes": partition_codes,
        "workspace_bucket_codes": workspace_bucket_codes,
        "group_field_label_by_code": group_field_label_by_code,
        "sort_field_label_by_code": sort_field_label_by_code,
    }


def _build_group_workspace_auto_context(competicio, request, payload, include_bucket_ids=False):
    inputs = _resolve_group_workspace_auto_context_inputs(competicio, request, payload)
    selected_ids = list(inputs["selected_ids"])
    selected_id_set = set(selected_ids)
    workspace_visible_ids = set(_resolve_group_workspace_filtered_target_ids(competicio, inputs["workspace_filters"])["target_ids"])

    resolution_codes = list(dict.fromkeys(list(inputs["selected_group_codes"]) + list(inputs["partition_codes"]) + list(inputs["workspace_bucket_codes"])))
    resolution_builtin_fields = [code for code in resolution_codes if hasattr(Inscripcio, code)]

    if inputs["source_scope"] == "selected":
        records_qs = Inscripcio.objects.filter(competicio=competicio, id__in=selected_ids)
    else:
        records_qs = Inscripcio.objects.filter(competicio=competicio)
    if resolution_codes:
        records_qs = annotate_inscripcions_queryset_for_group_codes(records_qs, competicio, resolution_codes)
    records = list(records_qs.order_by("ordre_sortida", "id").only("id", "extra", "data_naixement", *resolution_builtin_fields))

    resolution = _resolve_group_creation_buckets(competicio, records, group_codes=inputs["selected_group_codes"], partition_codes=inputs["partition_codes"], workspace_codes=inputs["workspace_bucket_codes"], fallback_mode="strict")
    buckets_raw = (resolution.get("buckets") if resolution.get("ok") else []) or []
    bucket_ids_by_key = {}
    buckets = []
    for bucket in buckets_raw:
        key = str(bucket.get("key") or "").strip()
        if not key:
            continue
        bucket_ids = normalize_inscripcio_ids(bucket.get("ids") or [])
        bucket_ids_by_key[key] = bucket_ids
        buckets.append(
            {
                "key": key,
                "label": bucket.get("label"),
                "count": len(bucket_ids),
                "global_count": len(bucket_ids),
                "visible_count": sum(1 for ins_id in bucket_ids if ins_id in workspace_visible_ids),
                "selected_count": sum(1 for ins_id in bucket_ids if ins_id in selected_id_set),
                "sources": bucket.get("sources") or [],
                "kinds": list(dict.fromkeys(str(source.get("kind") or "").strip().lower() for source in (bucket.get("sources") or []) if str(source.get("kind") or "").strip())),
            }
        )

    out = {
        "selection_count": len(selected_ids),
        "selected_ids": selected_ids,
        "source_scope": inputs["source_scope"],
        "source_total": len(records),
        "buckets": buckets,
        "buckets_total": len(buckets),
        "layers_used": list(resolution.get("layers_used") or []) if resolution.get("ok") else [],
        "used_fallback": False,
        "fallback_reason": "",
        "default_bucket_keys": [bucket["key"] for bucket in buckets],
        "detected_group_fields": [{"code": code, "label": inputs["group_field_label_by_code"].get(code, code)} for code in inputs["selected_group_codes"]],
        "detected_sort_fields": [{"priority": priority, "code": code, "label": inputs["sort_field_label_by_code"].get(code, code)} for priority, code in enumerate(inputs["partition_codes"], start=1)],
        "detected_workspace_fields": [{"code": code, "label": inputs["group_field_label_by_code"].get(code, code)} for code in inputs["workspace_bucket_codes"]],
        "workspace_bucket_fields": list(inputs["workspace_bucket_codes"]),
    }
    if include_bucket_ids:
        out["bucket_ids_by_key"] = bucket_ids_by_key
    return out


def _apply_group_workspace_auto_context_selection(competicio, request, payload):
    context = _build_group_workspace_auto_context(competicio, request, payload, include_bucket_ids=True)
    bucket_ids_by_key = context.pop("bucket_ids_by_key", {}) or {}
    bucket_keys_raw = payload.get("bucket_keys")
    if not isinstance(bucket_keys_raw, list):
        bucket_keys_raw = payload.get("selected_keys")
    bucket_keys = []
    if isinstance(bucket_keys_raw, list):
        for value in bucket_keys_raw:
            clean = str(value or "").strip()
            if clean and clean in bucket_ids_by_key and clean not in bucket_keys:
                bucket_keys.append(clean)

    selection_mode = str(payload.get("selection_mode") or "add").strip().lower()
    if selection_mode not in {"add", "remove", "set"}:
        selection_mode = "add"

    target_ids = []
    seen_target_ids = set()
    for key in bucket_keys:
        for ins_id in bucket_ids_by_key.get(key) or []:
            if ins_id in seen_target_ids:
                continue
            seen_target_ids.add(ins_id)
            target_ids.append(ins_id)

    current_selected_ids = list(context.get("selected_ids") or [])
    current_selected_set = set(current_selected_ids)
    if selection_mode == "set":
        updated_selected_ids = list(target_ids)
    elif selection_mode == "remove":
        target_id_set = set(target_ids)
        updated_selected_ids = [ins_id for ins_id in current_selected_ids if ins_id not in target_id_set]
    else:
        updated_selected_ids = list(current_selected_ids)
        for ins_id in target_ids:
            if ins_id in current_selected_set:
                continue
            current_selected_set.add(ins_id)
            updated_selected_ids.append(ins_id)

    return {
        "operation": "apply_auto_context_selection",
        "selection_mode": selection_mode,
        "bucket_keys": bucket_keys,
        "buckets_applied": len(bucket_keys),
        "target_ids_count": len(target_ids),
        "selected_ids": updated_selected_ids,
        "selection": _build_group_workspace_selection_summary(competicio, updated_selected_ids),
        "selection_count": len(updated_selected_ids),
        "source_scope": context.get("source_scope"),
    }


def _resolve_group_workspace_group(competicio, payload, include_inactive=True):
    group_id = None
    raw_group_id = payload.get("group_id")
    raw_group_num = payload.get("group_num")
    if str(raw_group_id or "").strip().isdigit():
        group_id = int(raw_group_id)

    group_maps = get_group_maps(competicio, include_inactive=include_inactive)
    group = None
    if group_id:
        group = group_maps["by_id"].get(group_id)
    if group is None and str(raw_group_num or "").strip().isdigit():
        group = get_group_for_display_num(competicio, int(raw_group_num))
    return group


def _serialize_group_workspace_candidate(ins, selected_ids=None):
    group = getattr(ins, "grup_competicio", None)
    selected_ids = set(selected_ids or [])
    group_label_value = group_label(group) if group is not None else "Sense grup"
    return {
        "id": ins.id,
        "label": str(getattr(ins, "nom_i_cognoms", "") or "").strip() or f"Inscripcio {ins.id}",
        "secondary_label": str(getattr(ins, "entitat", "") or "").strip(),
        "group_id": getattr(ins, "grup_competicio_id", None),
        "group_num": int(group.display_num) if group is not None and getattr(group, "display_num", None) else getattr(ins, "grup", None),
        "group_label": group_label_value,
        "group_state": "unassigned" if group is None else "assigned",
        "ordre_competicio": int(ins.ordre_competicio) if getattr(ins, "ordre_competicio", None) is not None else None,
        "ordre_sortida": int(ins.ordre_sortida) if getattr(ins, "ordre_sortida", None) is not None else None,
        "is_selected": ins.id in selected_ids,
    }


def _build_group_workspace_filter_options(records, groups):
    categories = sorted({str(getattr(ins, "categoria", "") or "").strip() for ins in records if str(getattr(ins, "categoria", "") or "").strip()})
    subcategories = sorted({str(getattr(ins, "subcategoria", "") or "").strip() for ins in records if str(getattr(ins, "subcategoria", "") or "").strip()})
    entitats = sorted({str(getattr(ins, "entitat", "") or "").strip() for ins in records if str(getattr(ins, "entitat", "") or "").strip()})
    return {
        "categories": categories,
        "subcategories": subcategories,
        "entitats": entitats,
        "group_states": [{"id": "all", "label": "Totes"}, {"id": "assigned", "label": "Amb grup"}, {"id": "unassigned", "label": "Sense grup"}],
        "groups": [{"id": int(group.id), "display_num": int(group.display_num), "label": group_label(group)} for group in groups],
    }


def _build_group_workspace_filter_option_source_qs(competicio, filters):
    option_filters = {**_normalize_sort_filters(filters), "categoria": "", "subcategoria": "", "entitat": "", "categories": [], "subcategories": [], "entitats": []}
    return _build_inscripcions_filtered_qs(competicio, option_filters)


def _build_group_workspace_selection_summary(competicio, selected_ids):
    selected_ids = normalize_inscripcio_ids(selected_ids)
    if not selected_ids:
        return {"count": 0, "assigned_count": 0, "unassigned_count": 0, "group_count": 0, "group_ids": [], "group_labels": [], "member_names_preview": []}

    rows = list(
        Inscripcio.objects.filter(competicio=competicio, id__in=selected_ids)
        .select_related("grup_competicio")
        .order_by("ordre_sortida", "id")
        .only("id", "nom_i_cognoms", "grup_competicio_id", "grup", "ordre_sortida")
    )
    group_ids = []
    group_labels = []
    seen_group_ids = set()
    member_names = []
    assigned_count = 0
    for ins in rows:
        group = getattr(ins, "grup_competicio", None)
        if group is not None:
            assigned_count += 1
            if group.id not in seen_group_ids:
                seen_group_ids.add(group.id)
                group_ids.append(group.id)
                group_labels.append(group_label(group))
        member_name = str(getattr(ins, "nom_i_cognoms", "") or "").strip()
        if member_name:
            member_names.append(member_name)

    return {
        "count": len(rows),
        "assigned_count": assigned_count,
        "unassigned_count": max(0, len(rows) - assigned_count),
        "group_count": len(group_ids),
        "group_ids": group_ids,
        "group_labels": group_labels,
        "member_names_preview": member_names[:5],
        "member_names_remaining": max(0, len(member_names) - min(len(member_names), 5)),
    }


def _build_group_workspace_payload(competicio, payload):
    filtered_target_bundle = _resolve_group_workspace_filtered_target_ids(competicio, payload.get("filters"))
    filters = filtered_target_bundle["filters"]
    selected_ids = normalize_inscripcio_ids(payload.get("selected_ids") or payload.get("ids") or [])
    try:
        page = int(payload.get("page") or 1)
    except Exception:
        page = 1
    try:
        page_size = int(payload.get("page_size") or 40)
    except Exception:
        page_size = 40
    page = max(1, page)
    page_size = max(1, min(200, page_size))

    filter_option_records = list(_build_group_workspace_filter_option_source_qs(competicio, filters).order_by("ordre_sortida", "id").only("id", "categoria", "subcategoria", "entitat"))
    candidates_qs = _build_group_workspace_candidates_qs(competicio, filters)
    candidate_records = list(candidates_qs.select_related("grup_competicio").order_by("ordre_sortida", "id").only("id", "nom_i_cognoms", "entitat", "categoria", "subcategoria", "grup", "grup_competicio_id", "ordre_competicio", "ordre_sortida"))
    total_candidates = len(candidate_records)
    start = (page - 1) * page_size
    stop = start + page_size
    page_rows = candidate_records[start:stop]

    summary = get_group_summary_counts(competicio, include_inactive=False)
    groups = list(get_competicio_groups(competicio, include_inactive=False))
    group_filter_facets = get_group_board_filter_facets(competicio, group_ids=[group.id for group in groups])
    group_cards = [
        get_group_card_payload(
            group,
            members_count=None,
            member_limit=5,
            filter_facets=group_filter_facets.get(int(group.id), {}),
        )
        for group in groups
    ]

    return {
        "summary": summary,
        "rotacions_active": bool(competicio_has_rotacions(competicio)),
        "selection": _build_group_workspace_selection_summary(competicio, selected_ids),
        "filters": filters,
        "filter_options": _build_group_workspace_filter_options(filter_option_records, groups),
        "selected_ids": selected_ids,
        "paging": {"page": page, "page_size": page_size, "total": total_candidates, "pages": max(1, (total_candidates + page_size - 1) // page_size) if total_candidates else 1},
        "candidates": [_serialize_group_workspace_candidate(ins, selected_ids=selected_ids) for ins in page_rows],
        "groups": group_cards,
    }


def _get_programmed_groups_warned_by_ids(competicio, inscripcio_ids, exclude_group_id=None):
    clean_ids = normalize_inscripcio_ids(inscripcio_ids)
    if not clean_ids:
        return []
    programmed_group_ids = set(get_programmed_group_ids(competicio) or [])
    if not programmed_group_ids:
        return []
    blocked_groups = get_programmed_groups_emptied_by_ids(competicio, clean_ids, exclude_group_id=exclude_group_id)
    blocked_ids = {int(group.id) for group in blocked_groups}
    touched_group_ids = {
        int(group_id)
        for group_id in Inscripcio.objects.filter(competicio=competicio, id__in=clean_ids).values_list("grup_competicio_id", flat=True)
        if group_id and int(group_id) in programmed_group_ids and int(group_id) not in blocked_ids
    }
    if exclude_group_id:
        touched_group_ids.discard(int(exclude_group_id))
    if not touched_group_ids:
        return []
    groups_by_id = get_group_maps(competicio, include_inactive=True)["by_id"]
    return [groups_by_id[group_id] for group_id in sorted(touched_group_ids) if group_id in groups_by_id]


def _group_workspace_action_preview(competicio, payload):
    action = str(payload.get("action") or "create").strip().lower()
    target_bundle = _resolve_group_workspace_target_ids(competicio, payload)
    selected_ids = target_bundle["selected_ids"]
    target_ids = target_bundle["target_ids"]
    records = list(
        Inscripcio.objects.filter(competicio=competicio, id__in=target_ids)
        .select_related("grup_competicio")
        .order_by("ordre_sortida", "id")
        .only("id", "nom_i_cognoms", "entitat", "grup", "grup_competicio_id", "ordre_sortida", "ordre_competicio")
    )
    selection_summary = _build_group_workspace_selection_summary(competicio, selected_ids or target_ids)
    summary = get_group_summary_counts(competicio, include_inactive=False)
    blocked_groups = []
    moving_records = list(records)
    if action in {"create", "assign", "unassign"}:
        if action == "assign":
            group = _resolve_group_workspace_group(competicio, payload, include_inactive=True)
            moving_records = [ins for ins in records if getattr(ins, "grup_competicio_id", None) != getattr(group, "id", None)] if group is not None else list(records)
            blocked_groups = get_programmed_groups_emptied_by_ids(competicio, [ins.id for ins in moving_records], exclude_group_id=getattr(group, "id", None))
        else:
            blocked_groups = get_programmed_groups_emptied_by_ids(competicio, target_ids)
    warning_groups = []
    if action in {"create", "assign", "unassign"}:
        warning_groups = _get_programmed_groups_warned_by_ids(competicio, [ins.id for ins in moving_records] if action == "assign" else target_ids, exclude_group_id=getattr(_resolve_group_workspace_group(competicio, payload, include_inactive=True), "id", None) if action == "assign" else None)

    existing_groups_preview = _build_existing_groups_preview(competicio, records, moving_ids=[ins.id for ins in moving_records] if action == "assign" else target_ids) if records else []
    preview = {
        "action": action,
        "selection": selection_summary,
        "summary": summary,
        "rotacions_active": bool(competicio_has_rotacions(competicio)),
        "blocked": bool(blocked_groups),
        "blocked_groups": [get_group_card_payload(group, member_limit=5) for group in blocked_groups],
        "warning_groups": [get_group_card_payload(group, member_limit=5) for group in warning_groups],
        "existing_groups": existing_groups_preview,
        "planned_groups": [],
        "target_ids_count": len(moving_records if action == "assign" else target_ids),
        "target_member_names_preview": [str(getattr(ins, "nom_i_cognoms", "") or "").strip() for ins in (moving_records if action == "assign" else records)[:5] if str(getattr(ins, "nom_i_cognoms", "") or "").strip()],
    }

    if action == "create":
        next_group_num = next_group_display_num(competicio)
        preview["planned_groups"] = [{"preview_kind": "created", "impact_kind": "created", "group_num": next_group_num, "label": f"Grup {next_group_num}", "members_count": len(target_ids), "member_names_preview": preview["target_member_names_preview"], "member_names_remaining": max(0, len(target_ids) - len(preview["target_member_names_preview"]))}]
    elif action == "assign":
        group = _resolve_group_workspace_group(competicio, payload, include_inactive=True)
        if group is not None:
            group_count = int(Inscripcio.objects.filter(grup_competicio=group).count())
            preview["planned_groups"] = [{"preview_kind": "existing", "impact_kind": "updated", "group_num": group.display_num, "group_id": group.id, "label": group_label(group), "members_count": group_count + len(moving_records), "member_names_preview": get_group_member_preview(group, limit=5), "member_names_remaining": max(0, group_count + len(moving_records) - 5)}]
            preview["target_group"] = get_group_detail_payload(group, member_limit=5)
    elif action == "delete":
        group = _resolve_group_workspace_group(competicio, payload, include_inactive=True)
        preview["target_group"] = get_group_detail_payload(group, member_limit=5) if group is not None else None
        preview["can_delete"] = bool(preview["target_group"] and preview["target_group"].get("can_delete"))

    return preview


def _balanced_sizes(n, k):
    if n <= 0 or k <= 0:
        return []
    k = min(k, n)
    base = n // k
    rem = n % k
    return [base + (1 if i < rem else 0) for i in range(k)]


def _fixed_sizes(n, size):
    if n <= 0 or size <= 0:
        return []
    out = []
    remaining = n
    while remaining > 0:
        take = size if remaining >= size else remaining
        out.append(take)
        remaining -= take
    return out


def _assign_group_sizes_in_order(objs, sizes, start_group_num):
    idx = 0
    group_num = start_group_num
    for size in sizes:
        if size <= 0:
            continue
        group_num += 1
        for _ in range(size):
            if idx >= len(objs):
                break
            objs[idx].grup = group_num
            idx += 1
    return group_num


def _build_bucket_sources_by_id(buckets):
    out = {}
    for bucket in buckets or []:
        sources = list(bucket.get("sources") or [])
        for ins_id in bucket.get("ids") or []:
            out[ins_id] = list(sources)
    return out


def _build_group_creation_preview(objs, sizes, start_group_num, bucket_sources_by_id=None, filter_name_sources=None):
    bucket_sources_by_id = bucket_sources_by_id or {}
    out = []
    idx = 0
    next_group_num = start_group_num
    for size in sizes:
        if size <= 0:
            continue
        members = list(objs[idx:idx + size])
        idx += size
        if not members:
            continue
        next_group_num += 1
        source_counts = {}
        for obj in members:
            sources = bucket_sources_by_id.get(obj.id) or []
            source_key = _bucket_source_signature(sources)
            row = source_counts.get(source_key)
            if row is None:
                row = {
                    "label": _build_bucket_source_label(sources),
                    "count": 0,
                    "kinds": _build_bucket_source_kinds(sources),
                    "labels_by_kind": dict(_bucket_labels_by_kind(sources)),
                    "components": list(_normalize_bucket_source_entries(sources)),
                }
                source_counts[source_key] = row
            row["count"] += 1
        member_names = [str(getattr(obj, "nom_i_cognoms", "") or "").strip() for obj in members]
        member_names = [name for name in member_names if name]
        out.append(
            {
                "preview_kind": "created",
                "impact_kind": "created",
                "group_num": next_group_num,
                "members_count": len(members),
                "sources": list(source_counts.values()),
                "member_names_preview": member_names[:4],
                "member_names_remaining": max(0, len(member_names) - 4),
            }
        )
    return _apply_group_suggested_names(out, filter_sources=filter_name_sources)


GROUP_TRANSFORM_OPERATIONS = {
    "merge_into_current",
    "split_count",
    "split_size",
    "split_bucket",
    "extract_selection",
    "rebalance",
}


def _normalize_group_id_list(raw_values):
    out = []
    seen = set()
    values = raw_values if isinstance(raw_values, list) else []
    for raw in values:
        try:
            clean = int(raw)
        except Exception:
            continue
        if clean <= 0 or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _group_transform_error(message, status=400):
    return HttpResponseBadRequest(str(message or "transform invalid"))


def _group_transform_member_names(members, limit=4):
    names = []
    for member in list(members or [])[:limit]:
        label = str(getattr(member, "nom_i_cognoms", "") or "").strip()
        if label:
            names.append(label)
    return names


def _group_transform_group_row(group, members_count=None, impact_kind="updated"):
    return {
        "id": int(group.id),
        "group_id": int(group.id),
        "group_num": int(group.display_num),
        "label": group_label(group),
        "name": str(getattr(group, "nom", "") or "").strip(),
        "members_count": int(members_count or 0),
        "impact_kind": impact_kind,
        "is_programmed": False,
    }


def _group_transform_assignment_row(group, members, *, impact_kind="updated", suggested_name="", sources=None, rename_existing=False):
    row = {
        "preview_kind": "existing" if group is not None and getattr(group, "id", None) else "created",
        "impact_kind": impact_kind,
        "group_id": int(group.id) if group is not None and getattr(group, "id", None) else None,
        "group_num": int(group.display_num) if group is not None and getattr(group, "display_num", None) else None,
        "label": group_label(group) if group is not None and getattr(group, "id", None) else "",
        "name": str(getattr(group, "nom", "") or "").strip() if group is not None else "",
        "suggested_name": str(suggested_name or "").strip(),
        "rename_existing": bool(rename_existing),
        "members_count": len(members or []),
        "member_names_preview": _group_transform_member_names(members),
        "member_names_remaining": max(0, len(members or []) - min(len(members or []), 4)),
        "sources": list(sources or []),
        "member_ids": [int(member.id) for member in members or []],
    }
    return row


def _group_transform_created_row(display_num, members, *, suggested_name="", sources=None):
    return {
        "preview_kind": "created",
        "impact_kind": "created",
        "group_id": None,
        "group_num": int(display_num),
        "label": str(suggested_name or "").strip() or f"Grup {int(display_num)}",
        "name": "",
        "suggested_name": str(suggested_name or "").strip(),
        "members_count": len(members or []),
        "member_names_preview": _group_transform_member_names(members),
        "member_names_remaining": max(0, len(members or []) - min(len(members or []), 4)),
        "sources": list(sources or []),
        "member_ids": [int(member.id) for member in members or []],
    }


def _group_transform_suffix_name(group, idx, total):
    base = str(getattr(group, "nom", "") or "").strip() or group_label(group)
    return f"{base} {idx}/{total}".strip()


def _group_transform_get_members(competicio, group):
    if group is None:
        return []
    return list(
        Inscripcio.objects
        .filter(competicio=competicio, grup_competicio=group)
        .select_related("grup_competicio")
        .order_by("ordre_competicio", "ordre_sortida", "id")
        .only(
            "id",
            "nom_i_cognoms",
            "entitat",
            "categoria",
            "subcategoria",
            "extra",
            "data_naixement",
            "grup",
            "grup_competicio",
            "ordre_competicio",
            "ordre_sortida",
        )
    )


def _group_transform_resolve_context(competicio, payload):
    operation = str(payload.get("operation") or "").strip().lower()
    if operation not in GROUP_TRANSFORM_OPERATIONS:
        raise ValueError("operation invalid")
    source_payload = {"group_id": payload.get("source_group_id") or payload.get("group_id")}
    source_group = _resolve_group_workspace_group(competicio, source_payload, include_inactive=False)
    if source_group is None or not getattr(source_group, "actiu", False):
        raise ValueError("source group invalid")

    target_ids = _normalize_group_id_list(payload.get("target_group_ids"))
    group_maps = get_group_maps(competicio, include_inactive=False)
    target_groups = []
    for group_id in target_ids:
        if group_id == source_group.id:
            continue
        group = group_maps["by_id"].get(group_id)
        if group is not None and getattr(group, "actiu", False) and group not in target_groups:
            target_groups.append(group)

    if operation in {"merge_into_current", "rebalance"} and not target_groups:
        raise ValueError("target group invalid")

    affected_groups = [source_group]
    for group in target_groups:
        if group.id not in {row.id for row in affected_groups}:
            affected_groups.append(group)

    programmed_ids = set(get_programmed_group_ids(competicio) or [])
    blocked = [group for group in affected_groups if int(group.id) in programmed_ids]
    if blocked:
        labels = [group_label(group) for group in blocked]
        raise ValueError(f"No es poden transformar grups programats a rotacions: {', '.join(labels)}.")

    source_members = _group_transform_get_members(competicio, source_group)
    if not source_members:
        raise ValueError("source group empty")
    target_members_by_group = {group.id: _group_transform_get_members(competicio, group) for group in target_groups}
    return {
        "operation": operation,
        "source_group": source_group,
        "target_groups": target_groups,
        "affected_groups": affected_groups,
        "source_members": source_members,
        "target_members_by_group": target_members_by_group,
    }


def _group_transform_assignments_from_parts(competicio, source_group, parts, *, source_names=True, source_rows=None):
    max_num = (GrupCompeticio.objects.filter(competicio=competicio).aggregate(m=Max("display_num"))["m"] or 0)
    assignments = []
    created_index = 0
    total = len(parts)
    for idx, part in enumerate(parts, start=1):
        members = list(part.get("members") or [])
        sources = list(part.get("sources") or [])
        suggested_name = str(part.get("suggested_name") or "").strip()
        if not suggested_name and source_names:
            suggested_name = _group_transform_suffix_name(source_group, idx, total)
        if idx == 1:
            assignments.append(
                _group_transform_assignment_row(
                    source_group,
                    members,
                    impact_kind="updated",
                    suggested_name=suggested_name,
                    sources=sources,
                    rename_existing=not str(getattr(source_group, "nom", "") or "").strip(),
                )
            )
        else:
            created_index += 1
            assignments.append(
                _group_transform_created_row(
                    max_num + created_index,
                    members,
                    suggested_name=suggested_name,
                    sources=sources,
                )
            )
    if source_rows:
        assignments = _apply_group_suggested_names(assignments)
        for idx, part in enumerate(parts, start=1):
            fallback = str(part.get("suggested_name") or "").strip()
            if fallback and not str(assignments[idx - 1].get("suggested_name") or "").strip():
                assignments[idx - 1]["suggested_name"] = fallback
    return assignments


def _build_group_transform_plan(competicio, payload):
    context = _group_transform_resolve_context(competicio, payload)
    operation = context["operation"]
    source_group = context["source_group"]
    target_groups = context["target_groups"]
    source_members = context["source_members"]
    target_members_by_group = context["target_members_by_group"]
    affected_groups = context["affected_groups"]
    assignments = []
    deactivate_group_ids = []

    if operation == "merge_into_current":
        members = list(source_members)
        for group in target_groups:
            members.extend(target_members_by_group.get(group.id) or [])
            deactivate_group_ids.append(int(group.id))
        assignments = [_group_transform_assignment_row(source_group, members, impact_kind="updated")]

    elif operation == "split_count":
        try:
            group_count = int(payload.get("group_count") or 0)
        except Exception:
            group_count = 0
        if group_count < 2 or group_count > len(source_members):
            raise ValueError("group_count invalid")
        sizes = _balanced_sizes(len(source_members), group_count)
        parts = []
        offset = 0
        for size in sizes:
            parts.append({"members": source_members[offset:offset + size]})
            offset += size
        assignments = _group_transform_assignments_from_parts(competicio, source_group, parts)

    elif operation == "split_size":
        group_size_raw = payload.get("group_size")
        group_size = 0
        try:
            group_size = int(group_size_raw or 0)
        except Exception:
            group_size = 0
        if group_size > 0:
            sizes = _fixed_sizes(len(source_members), group_size)
        else:
            try:
                min_size = int(payload.get("min_size") or 0)
                max_size = int(payload.get("max_size") or 0)
            except Exception:
                raise ValueError("min_size/max_size invalid")
            if min_size <= 0 or max_size <= 0 or min_size > max_size:
                raise ValueError("min_size/max_size invalid")
            k_resolved, _meta = _resolve_k_for_range(len(source_members), min_size, max_size, fallback_mode="strict")
            if k_resolved is None:
                raise ValueError("No es pot resoldre una particio valida amb aquesta forquilla")
            sizes = _balanced_sizes(len(source_members), k_resolved)
        if len([size for size in sizes if size > 0]) < 2:
            raise ValueError("split would not create multiple groups")
        parts = []
        offset = 0
        for size in sizes:
            parts.append({"members": source_members[offset:offset + size]})
            offset += size
        assignments = _group_transform_assignments_from_parts(competicio, source_group, parts)

    elif operation == "split_bucket":
        allowed_group_fields = get_allowed_group_fields(competicio)
        allowed_codes = {field["code"] for field in allowed_group_fields if isinstance(field, dict) and field.get("code")}
        bucket_codes = _normalize_group_workspace_bucket_fields(payload.get("bucket_fields"), allowed_codes)
        if not bucket_codes:
            raise ValueError("bucket_fields invalid")
        builtin_fields = [code for code in bucket_codes if hasattr(Inscripcio, code)]
        qs = Inscripcio.objects.filter(competicio=competicio, grup_competicio=source_group)
        qs = annotate_inscripcions_queryset_for_group_codes(qs, competicio, bucket_codes)
        records = list(qs.order_by("ordre_competicio", "ordre_sortida", "id").only("id", "extra", "data_naixement", *builtin_fields))
        resolution = _resolve_group_creation_buckets(competicio, records, group_codes=[], partition_codes=[], workspace_codes=bucket_codes, fallback_mode="strict")
        buckets = [bucket for bucket in (resolution.get("buckets") if resolution.get("ok") else []) or [] if bucket.get("ids")]
        if len(buckets) < 2:
            raise ValueError("split buckets invalid")
        record_by_id = {record.id: record for record in records}
        parts = []
        for bucket in buckets:
            members = [record_by_id[ins_id] for ins_id in normalize_inscripcio_ids(bucket.get("ids") or []) if ins_id in record_by_id]
            if not members:
                continue
            sources = list(bucket.get("sources") or [])
            source_row = {
                "label": _build_bucket_source_label(sources),
                "count": len(members),
                "kinds": _build_bucket_source_kinds(sources),
                "labels_by_kind": dict(_bucket_labels_by_kind(sources)),
                "components": list(_normalize_bucket_source_entries(sources)),
            }
            suggested = (_apply_group_suggested_names([{"sources": [source_row]}])[0] or {}).get("suggested_name") or ""
            parts.append({"members": members, "sources": [source_row], "suggested_name": suggested})
        if len(parts) < 2:
            raise ValueError("split buckets invalid")
        assignments = _group_transform_assignments_from_parts(competicio, source_group, parts, source_names=False, source_rows=True)

    elif operation == "extract_selection":
        selected_ids = set(normalize_inscripcio_ids(payload.get("selected_ids") or payload.get("ids") or []))
        source_ids = {member.id for member in source_members}
        extracted = [member for member in source_members if member.id in selected_ids and member.id in source_ids]
        if not extracted or len(extracted) >= len(source_members):
            raise ValueError("selected_ids invalid")
        remaining = [member for member in source_members if member.id not in {row.id for row in extracted}]
        max_num = (GrupCompeticio.objects.filter(competicio=competicio).aggregate(m=Max("display_num"))["m"] or 0)
        assignments = [
            _group_transform_assignment_row(source_group, remaining, impact_kind="updated"),
            _group_transform_created_row(max_num + 1, extracted, suggested_name=f"{group_label(source_group)} - seleccio"),
        ]

    elif operation == "rebalance":
        members = list(source_members)
        for group in target_groups:
            members.extend(target_members_by_group.get(group.id) or [])
        try:
            group_count = int(payload.get("group_count") or 0)
        except Exception:
            group_count = 0
        if group_count <= 0:
            group_count = len(affected_groups)
        if group_count < 1 or group_count > len(members):
            raise ValueError("group_count invalid")
        sizes = _balanced_sizes(len(members), group_count)
        reusable_groups = list(affected_groups[:len(sizes)])
        max_num = (GrupCompeticio.objects.filter(competicio=competicio).aggregate(m=Max("display_num"))["m"] or 0)
        created_index = 0
        offset = 0
        for idx, size in enumerate(sizes):
            part_members = members[offset:offset + size]
            offset += size
            if idx < len(reusable_groups):
                assignments.append(_group_transform_assignment_row(reusable_groups[idx], part_members, impact_kind="updated"))
            else:
                created_index += 1
                assignments.append(_group_transform_created_row(max_num + created_index, part_members, suggested_name=f"Reequilibri {created_index}"))
        deactivate_group_ids = [int(group.id) for group in affected_groups[len(sizes):]]

    if not assignments:
        raise ValueError("transform empty")

    affected_rows = []
    for group in affected_groups:
        if group.id == source_group.id:
            count = len(source_members)
        else:
            count = len(target_members_by_group.get(group.id) or [])
        affected_rows.append(_group_transform_group_row(group, count, impact_kind="affected"))

    planned_groups = []
    planned_groups.extend(assignments)
    for group in affected_groups:
        if int(group.id) in set(deactivate_group_ids):
            planned_groups.append(_group_transform_assignment_row(group, [], impact_kind="removed"))

    return {
        "operation": operation,
        "can_apply": True,
        "source_group_id": int(source_group.id),
        "affected_groups": affected_rows,
        "planned_groups": planned_groups,
        "assignments": assignments,
        "deactivate_group_ids": deactivate_group_ids,
        "members_total": sum(len(row.get("member_ids") or []) for row in assignments),
        "groups_total": len(assignments),
        "warnings": [],
    }


def _apply_group_transform_plan(competicio, plan):
    assignment_rows = []
    selected_group_id = None
    with transaction.atomic():
        for assignment in plan.get("assignments") or []:
            group = None
            if assignment.get("group_id"):
                group = GrupCompeticio.objects.select_for_update().filter(competicio=competicio, id=assignment["group_id"], actiu=True).first()
            if group is None:
                group = ensure_group_for_display_num(
                    competicio,
                    assignment.get("group_num"),
                    name=str(assignment.get("suggested_name") or "").strip(),
                )
            if group is None:
                raise ValueError("group invalid")
            member_ids = normalize_inscripcio_ids(assignment.get("member_ids") or [])
            members_by_id = {
                ins.id: ins
                for ins in Inscripcio.objects.select_for_update().filter(competicio=competicio, id__in=member_ids)
            }
            updates = []
            for order_idx, member_id in enumerate(member_ids, start=1):
                inscripcio = members_by_id.get(member_id)
                if inscripcio is None:
                    continue
                inscripcio.grup_competicio = group
                inscripcio.grup = group.display_num
                inscripcio.ordre_competicio = order_idx
                updates.append(inscripcio)
            if updates:
                Inscripcio.objects.bulk_update(updates, ["grup_competicio", "grup", "ordre_competicio"], batch_size=500)
            suggested_name = str(assignment.get("suggested_name") or "").strip()
            if suggested_name and (assignment.get("preview_kind") == "created" or (assignment.get("rename_existing") and not str(group.nom or "").strip())):
                if group.nom != suggested_name:
                    group.nom = suggested_name
                    group.save(update_fields=["nom"])
            if selected_group_id is None:
                selected_group_id = int(group.id)
            assignment_rows.append(get_group_detail_payload(group, member_limit=5))

        for group_id in _normalize_group_id_list(plan.get("deactivate_group_ids") or []):
            group = GrupCompeticio.objects.select_for_update().filter(competicio=competicio, id=group_id).first()
            if group is None:
                continue
            ok, reason = safe_deactivate_empty_group(group)
            if not ok:
                raise ValueError("group not empty" if reason == "group_not_empty" else "group invalid")
        sync_competicio_group_names_view(competicio)
    return {"groups": assignment_rows, "selected_group_id": selected_group_id}


def _parse_fallback_mode(raw):
    mode = str(raw or "all_filtered").strip().lower()
    if mode not in ("all_filtered", "strict", "adjust_k", "ignore_range"):
        mode = "all_filtered"
    return mode


def _resolve_k_for_range(n, min_size, max_size, preferred_k=None, fallback_mode="strict"):
    if n <= 0 or min_size <= 0 or max_size <= 0 or min_size > max_size:
        return None, {"used_fallback": True, "fallback_reason": "range_infeasible"}
    k_min = math.ceil(n / max_size)
    k_max = math.floor(n / min_size)
    meta = {"used_fallback": False, "fallback_reason": ""}
    feasible = k_min <= k_max and k_max >= 1
    if feasible:
        if preferred_k is None:
            k_target = int(round(n / ((min_size + max_size) / 2.0)))
            return max(k_min, min(k_target, k_max)), meta
        k = int(preferred_k)
        if k < k_min or k > k_max:
            if fallback_mode == "strict":
                return None, {"used_fallback": True, "fallback_reason": "k_out_of_range"}
            if fallback_mode in ("adjust_k", "all_filtered"):
                meta["used_fallback"] = True
                meta["fallback_reason"] = "k_adjusted_to_feasible_range"
                k = max(k_min, min(k, k_max))
            elif fallback_mode == "ignore_range":
                meta["used_fallback"] = True
                meta["fallback_reason"] = "range_ignored_for_k"
                k = max(1, min(k, max(1, n)))
        return k, meta
    if fallback_mode == "strict":
        return None, {"used_fallback": True, "fallback_reason": "range_infeasible"}
    k = max(1, min(int(preferred_k) if preferred_k is not None else math.ceil(n / max_size), max(1, n)))
    return k, {"used_fallback": True, "fallback_reason": "range_infeasible_auto_k"}


@require_POST
@csrf_protect
def groups_workspace(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    operation = str(payload.get("operation") or "").strip().lower()
    if operation == "resolve_filtered_ids":
        resolved = _resolve_group_workspace_filtered_target_ids(competicio, payload.get("filters"))
        return JsonResponse(with_inscripcions_history_payload({"ok": True, "operation": "resolve_filtered_ids", "filters": resolved["filters"], "target_ids": resolved["target_ids"], "total": len(resolved["target_ids"])}, request, competicio.id))
    if operation == "resolve_auto_context":
        auto_context = _build_group_workspace_auto_context(competicio, request, payload)
        return JsonResponse(with_inscripcions_history_payload({"ok": True, "operation": "resolve_auto_context", **auto_context}, request, competicio.id))
    if operation == "apply_auto_context_selection":
        selection_payload = _apply_group_workspace_auto_context_selection(competicio, request, payload)
        return JsonResponse(with_inscripcions_history_payload({"ok": True, **selection_payload}, request, competicio.id))
    workspace = _build_group_workspace_payload(competicio, payload)
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "workspace": workspace, **workspace}, request, competicio.id))


@require_POST
@csrf_protect
def groups_detail(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    group = _resolve_group_workspace_group(competicio, payload, include_inactive=True)
    if group is None:
        return HttpResponseBadRequest("group invalid")
    detail = get_group_detail_payload(group, member_limit=50, page=payload.get("page"), page_size=payload.get("page_size") or 10)
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "group": detail, "members": detail.get("members") or [], "members_total": int(detail.get("members_total") or 0), "members_page": int(detail.get("members_page") or 1), "members_page_size": int(detail.get("members_page_size") or 10), "members_total_pages": int(detail.get("members_total_pages") or 1), "members_has_prev": bool(detail.get("members_has_prev")), "members_has_next": bool(detail.get("members_has_next"))}, request, competicio.id))


@require_POST
@csrf_protect
def groups_preview(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    preview = _group_workspace_action_preview(competicio, payload)
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "preview": preview}, request, competicio.id))


@require_POST
@csrf_protect
def groups_transform_preview(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    try:
        plan = _build_group_transform_plan(competicio, payload)
    except ValueError as exc:
        return _group_transform_error(str(exc))
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "preview": plan}, request, competicio.id))


@require_POST
@csrf_protect
def groups_transform_apply(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    try:
        plan = _build_group_transform_plan(competicio, payload)
    except ValueError as exc:
        return _group_transform_error(str(exc))
    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    try:
        result = _apply_group_transform_plan(competicio, plan)
    except ValueError as exc:
        return _group_transform_error(str(exc))
    operation = str(plan.get("operation") or "transform").strip()
    label_by_operation = {
        "merge_into_current": "Unir grups",
        "split_count": "Dividir grup per nombre",
        "split_size": "Dividir grup per mida",
        "split_bucket": "Dividir grup per criteri",
        "extract_selection": "Extreure seleccio a grup nou",
        "rebalance": "Reequilibrar grups",
    }
    record_inscripcions_history_entry(
        request,
        competicio,
        action_type=f"groups_transform_{operation}",
        action_label=label_by_operation.get(operation, "Transformar grups"),
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "operation": operation,
                "preview": plan,
                "groups": result.get("groups") or [],
                "selected_group_id": result.get("selected_group_id"),
            },
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def groups_create(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    resolved = _resolve_group_workspace_target_ids(competicio, payload)
    target_ids = resolved["target_ids"]
    name = str(payload.get("name") or "").strip()
    blocked_groups = get_programmed_groups_emptied_by_ids(competicio, target_ids)
    if blocked_groups:
        return HttpResponseBadRequest(_message_for_emptied_programmed_groups(blocked_groups))
    warning_groups = _get_programmed_groups_warned_by_ids(competicio, target_ids)
    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    group = ensure_group_for_display_num(competicio, next_group_display_num(competicio), name=name)
    result = {"updated": 0, "moved_ids": [], "skipped_ids": [], "compacted_group_ids": []}
    if target_ids:
        result = move_inscripcions_to_group(group, target_ids)
    if name and group.nom != name:
        group.nom = name
        group.save(update_fields=["nom"])
    sync_competicio_group_names_view(competicio)
    record_inscripcions_history_entry(request, competicio, action_type="groups_create_manual", action_label="Crear grup manual", before_snapshot=before_snapshot, after_snapshot=capture_inscripcions_history_snapshot(request, competicio))
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "created": True,
                "updated": int(result.get("updated") or 0),
                "moved_ids": list(result.get("moved_ids") or []),
                "skipped_ids": list(result.get("skipped_ids") or []),
                "group": get_group_detail_payload(group, member_limit=5),
                "selection": _build_group_workspace_selection_summary(competicio, target_ids),
                "warnings": [group_label(row) for row in warning_groups],
                "notice": f"S'ha modificat un grup programat: {', '.join(group_label(row) for row in warning_groups)}." if warning_groups else "",
            },
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def groups_assign(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    group = _resolve_group_workspace_group(competicio, payload, include_inactive=True)
    if group is None:
        return HttpResponseBadRequest("group invalid")
    resolved = _resolve_group_workspace_target_ids(competicio, payload)
    target_ids = resolved["target_ids"]
    blocked_groups = get_programmed_groups_emptied_by_ids(competicio, target_ids, exclude_group_id=group.id)
    if blocked_groups:
        return HttpResponseBadRequest(_message_for_emptied_programmed_groups(blocked_groups))
    warning_groups = _get_programmed_groups_warned_by_ids(competicio, target_ids, exclude_group_id=group.id)
    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    result = move_inscripcions_to_group(group, target_ids)
    sync_competicio_group_names_view(competicio)
    record_inscripcions_history_entry(request, competicio, action_type="groups_assign_manual", action_label="Assignar seleccio a grup", before_snapshot=before_snapshot, after_snapshot=capture_inscripcions_history_snapshot(request, competicio))
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "updated": int(result.get("updated") or 0),
                "moved_ids": list(result.get("moved_ids") or []),
                "skipped_ids": list(result.get("skipped_ids") or []),
                "group": get_group_detail_payload(group, member_limit=5),
                "selection": _build_group_workspace_selection_summary(competicio, target_ids),
                "warnings": [group_label(row) for row in warning_groups],
                "notice": f"S'ha modificat un grup programat: {', '.join(group_label(row) for row in warning_groups)}." if warning_groups else "",
            },
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def groups_unassign(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    resolved = _resolve_group_workspace_target_ids(competicio, payload)
    target_ids = resolved["target_ids"]
    blocked_groups = get_programmed_groups_emptied_by_ids(competicio, target_ids)
    if blocked_groups:
        return HttpResponseBadRequest(_message_for_emptied_programmed_groups(blocked_groups))
    warning_groups = _get_programmed_groups_warned_by_ids(competicio, target_ids)
    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    result = clear_inscripcions_group(competicio, target_ids)
    sync_competicio_group_names_view(competicio)
    record_inscripcions_history_entry(request, competicio, action_type="groups_unassign_manual", action_label="Treure seleccio del grup", before_snapshot=before_snapshot, after_snapshot=capture_inscripcions_history_snapshot(request, competicio))
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "updated": int(result.get("updated") or 0),
                "cleared_ids": list(result.get("cleared_ids") or []),
                "selection": _build_group_workspace_selection_summary(competicio, target_ids),
                "warnings": [group_label(row) for row in warning_groups],
                "notice": f"S'ha modificat un grup programat: {', '.join(group_label(row) for row in warning_groups)}." if warning_groups else "",
            },
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def groups_delete(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    group = _resolve_group_workspace_group(competicio, payload, include_inactive=True)
    if group is None:
        return HttpResponseBadRequest("group invalid")
    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    ok, reason = safe_deactivate_empty_group(group)
    if not ok:
        return HttpResponseBadRequest("group not empty" if reason == "group_not_empty" else "group invalid")
    sync_competicio_group_names_view(competicio)
    record_inscripcions_history_entry(request, competicio, action_type="groups_delete_manual", action_label="Desactivar grup buit", before_snapshot=before_snapshot, after_snapshot=capture_inscripcions_history_snapshot(request, competicio))
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "deleted": True, "group": get_group_detail_payload(group, member_limit=5)}, request, competicio.id))


@require_POST
@csrf_protect
def groups_delete_empty(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return HttpResponseBadRequest("JSON invalid")
    groups = list(get_competicio_groups(competicio, include_inactive=False))
    deleted_ids = []
    skipped_ids = []
    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    for group in groups:
        payload = get_group_card_payload(group, member_limit=1)
        if int((payload or {}).get("members_count") or 0) > 0:
            continue
        ok, _reason = safe_deactivate_empty_group(group)
        if ok:
            deleted_ids.append(int(group.id))
        else:
            skipped_ids.append(int(group.id))
    sync_competicio_group_names_view(competicio)
    record_inscripcions_history_entry(request, competicio, action_type="groups_delete_empty", action_label="Desactivar grups buits", before_snapshot=before_snapshot, after_snapshot=capture_inscripcions_history_snapshot(request, competicio))
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "deleted": len(deleted_ids), "deleted_ids": deleted_ids, "skipped_ids": skipped_ids}, request, competicio.id))


@require_POST
@csrf_protect
@transaction.atomic
def groups_delete_all(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    groups = list(get_competicio_groups(competicio, include_inactive=False))
    programmed_group_ids = set(get_programmed_group_ids(competicio) or [])
    protected_groups = []
    deleted_groups = []
    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    for group in groups:
        if int(group.id) in programmed_group_ids:
            protected_groups.append({"id": int(group.id), "display_num": int(group.display_num or 0), "label": group_label(group)})
            continue
        member_ids = list(Inscripcio.objects.filter(grup_competicio=group).values_list("id", flat=True))
        if member_ids:
            clear_inscripcions_group(competicio, member_ids)
        ok, reason = safe_deactivate_empty_group(group)
        if ok:
            deleted_groups.append({"id": int(group.id), "display_num": int(group.display_num or 0), "label": group_label(group)})
        elif reason == "group_not_empty":
            return HttpResponseBadRequest("group not empty after clearing")
    sync_competicio_group_names_view(competicio)
    record_inscripcions_history_entry(request, competicio, action_type="groups_delete_all", action_label="Desactivar tots els grups no programats", before_snapshot=before_snapshot, after_snapshot=capture_inscripcions_history_snapshot(request, competicio))
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "deleted": len(deleted_groups), "deleted_groups": deleted_groups, "protected": len(protected_groups), "protected_groups": protected_groups}, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_group_competition_order_preview(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")
    try:
        group_num = int(payload.get("group_num"))
    except Exception:
        return HttpResponseBadRequest("group_num invalid")
    if group_num <= 0:
        return HttpResponseBadRequest("group_num invalid")
    group = get_group_for_display_num(competicio, group_num)
    if group is None:
        return HttpResponseBadRequest("group_num invalid")

    rows = []
    group_rows = Inscripcio.objects.filter(competicio=competicio, grup_competicio=group).order_by("ordre_competicio", "ordre_sortida", "id").only("id", "nom_i_cognoms", "entitat", "ordre_competicio", "ordre_sortida")
    for idx, inscripcio in enumerate(group_rows, start=1):
        label = str(getattr(inscripcio, "nom_i_cognoms", "") or "").strip() or f"Inscripcio {inscripcio.id}"
        secondary = str(getattr(inscripcio, "entitat", "") or "").strip()
        saved_order = getattr(inscripcio, "ordre_competicio", None)
        rows.append({"id": inscripcio.id, "label": label, "secondary_label": secondary, "saved_order": int(saved_order) if saved_order is not None else idx})

    return JsonResponse(
        {
            "ok": True,
            "group_num": group_num,
            "group_label": str(getattr(group, "nom", "") or "").strip() or f"Grup {group.display_num}",
            "total_count": len(rows),
            "can_edit": bool(user_has_competicio_capability(request.user, competicio, "inscripcions.edit")),
            "rows": rows,
        }
    )


def _normalize_bulk_group_ids(raw_values):
    ids = []
    values = raw_values if isinstance(raw_values, list) else []
    for value in values:
        try:
            clean = int(value)
        except Exception:
            continue
        if clean > 0 and clean not in ids:
            ids.append(clean)
    return ids


def _bulk_group_order_sort_label(sort_fields, sort_key):
    for field in sort_fields or []:
        if not isinstance(field, dict):
            continue
        if field.get("code") == sort_key:
            return field.get("ui_label") or field.get("label") or sort_key
    return sort_key


def _current_competition_order_key(record):
    current_order = normalize_positive_int(getattr(record, "ordre_competicio", None))
    visual_order = normalize_positive_int(getattr(record, "ordre_sortida", None))
    return (
        current_order if current_order is not None else 10**12,
        visual_order if visual_order is not None else 10**12,
        int(getattr(record, "id", 0) or 0),
    )


def _build_bulk_group_competition_order_plan(competicio, payload):
    sort_fields = get_available_sort_fields(competicio)
    sort_codes = {field["code"] for field in sort_fields if isinstance(field, dict) and field.get("code")}
    raw_sort_key = str(payload.get("sort_key") or "").strip()
    sort_key = raw_sort_key
    if sort_key not in sort_codes:
        raise ValueError("sort_key invalid")

    sort_dir = str(payload.get("sort_dir") or "asc").strip().lower()
    if sort_dir not in {"asc", "desc", "custom"}:
        raise ValueError("sort_dir invalid")

    scope = str(payload.get("scope") or "all").strip().lower()
    if scope not in {"all", "visible", "selected"}:
        scope = "all"

    group_ids = _normalize_bulk_group_ids(payload.get("group_ids"))
    if scope in {"visible", "selected"} and not group_ids:
        raise ValueError("Cal seleccionar almenys un grup")

    groups_qs = GrupCompeticio.objects.filter(competicio=competicio, actiu=True)
    if group_ids:
        groups_qs = groups_qs.filter(id__in=group_ids)
    groups = list(groups_qs.order_by("display_num", "id").only("id", "display_num", "nom"))
    groups_by_id = {group.id: group for group in groups}
    if scope in {"visible", "selected"} and not groups_by_id:
        raise ValueError("No hi ha grups valids per aquest ambit")

    rows_qs = Inscripcio.objects.filter(competicio=competicio, grup_competicio_id__isnull=False)
    if groups_by_id:
        rows_qs = rows_qs.filter(grup_competicio_id__in=list(groups_by_id.keys()))
    elif scope == "all":
        rows_qs = rows_qs.filter(grup_competicio__actiu=True)

    records = list(_build_sort_records_queryset(rows_qs, [sort_key, "grup"], include_competition_order=True))
    records_by_group_id = {}
    for record in records:
        group_id = getattr(record, "grup_competicio_id", None)
        if not group_id:
            continue
        group = groups_by_id.get(group_id)
        if group is None and scope == "all":
            group = getattr(record, "grup_competicio", None)
            if group is not None and getattr(group, "actiu", True):
                groups_by_id[group_id] = group
        if group is None:
            continue
        records_by_group_id.setdefault(group_id, []).append(record)

    custom_rank_map = get_competicio_custom_sort_rank_map(competicio, sort_key, allowed_sort_codes=sort_codes) if sort_dir == "custom" else {}
    descending = sort_dir == "desc"
    groups_out = []
    total_members = 0
    changed_members = 0
    changed_groups = 0
    for group in sorted(groups_by_id.values(), key=lambda item: (normalize_positive_int(getattr(item, "display_num", None)) or 10**9, item.id)):
        group_records = records_by_group_id.get(group.id) or []
        if not group_records:
            continue
        group_records = sorted(group_records, key=_current_competition_order_key)
        ordered_records = sort_records_by_field_stable(group_records, sort_key, descending=descending, custom_rank_map=custom_rank_map)
        before_ids = [record.id for record in group_records]
        after_ids = [record.id for record in ordered_records]
        moved_count = sum(1 for idx, ins_id in enumerate(after_ids) if idx >= len(before_ids) or before_ids[idx] != ins_id)
        total_members += len(group_records)
        changed_members += moved_count
        if moved_count:
            changed_groups += 1
        sample_rows = []
        old_position_by_id = {ins_id: idx for idx, ins_id in enumerate(before_ids, start=1)}
        for new_idx, record in enumerate(ordered_records[:8], start=1):
            label = str(getattr(record, "nom_i_cognoms", "") or "").strip() or f"Inscripcio {record.id}"
            secondary = str(getattr(record, "entitat", "") or "").strip()
            sample_rows.append(
                {
                    "id": record.id,
                    "label": label,
                    "secondary_label": secondary,
                    "old_order": old_position_by_id.get(record.id),
                    "new_order": new_idx,
                }
            )
        groups_out.append(
            {
                "group_id": group.id,
                "group_num": int(getattr(group, "display_num", None) or 0),
                "group_label": str(getattr(group, "nom", "") or "").strip() or f"Grup {getattr(group, 'display_num', '')}",
                "members_count": len(group_records),
                "changed_count": moved_count,
                "ordered_ids": after_ids,
                "sample_rows": sample_rows,
            }
        )

    return {
        "sort_key": sort_key,
        "sort_label": _bulk_group_order_sort_label(sort_fields, sort_key),
        "sort_dir": sort_dir,
        "scope": scope,
        "groups": groups_out,
        "groups_total": len(groups_out),
        "changed_groups": changed_groups,
        "members_total": total_members,
        "changed_members": changed_members,
        "can_apply": bool(groups_out),
    }


@require_POST
@csrf_protect
def inscripcions_bulk_group_competition_order_preview(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")
    try:
        plan = _build_bulk_group_competition_order_plan(competicio, payload if isinstance(payload, dict) else {})
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    return JsonResponse({"ok": True, "preview": plan})


@require_POST
@csrf_protect
def inscripcions_bulk_group_competition_order_apply(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")
    try:
        plan = _build_bulk_group_competition_order_plan(competicio, payload if isinstance(payload, dict) else {})
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if not plan["groups"]:
        return JsonResponse(with_inscripcions_history_payload({"ok": True, "updated": 0, "groups_total": 0, "members_total": 0, "changed_groups": 0, "changed_members": 0}, request, competicio.id))

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    updated = 0
    groups_by_id = {
        group.id: group
        for group in GrupCompeticio.objects.filter(
            competicio=competicio,
            id__in=[row["group_id"] for row in plan["groups"]],
        )
    }
    try:
        with transaction.atomic():
            for row in plan["groups"]:
                group = groups_by_id.get(row["group_id"])
                if group is None:
                    continue
                updated += save_group_competition_order(group, row["ordered_ids"])
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    record_inscripcions_history_entry(
        request,
        competicio,
        action_type="bulk_group_competition_order",
        action_label="Reordenar ordre de competicio dels grups",
        before_snapshot=before_snapshot,
        after_snapshot=capture_inscripcions_history_snapshot(request, competicio),
    )
    return JsonResponse(
        with_inscripcions_history_payload(
            {
                "ok": True,
                "updated": updated,
                "groups_total": plan["groups_total"],
                "members_total": plan["members_total"],
                "changed_groups": plan["changed_groups"],
                "changed_members": plan["changed_members"],
                "sort_key": plan["sort_key"],
                "sort_label": plan["sort_label"],
                "sort_dir": plan["sort_dir"],
            },
            request,
            competicio.id,
        )
    )


@require_POST
@csrf_protect
def inscripcions_groups_from_sort(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    has_rotacions = competicio_has_rotacions(competicio)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    strategy = str(payload.get("strategy") or "per_bucket").strip().lower()
    if strategy not in ("per_bucket", "count", "size_fixed", "size_balanced", "range_balanced", "count_with_range"):
        return HttpResponseBadRequest("strategy invalid")

    preview_only = bool(payload.get("preview_only"))
    fallback_mode = _parse_fallback_mode(payload.get("fallback_mode"))
    scope = str(payload.get("scope") or "filtered").strip().lower()
    if scope not in {"selected", "filtered"}:
        scope = "filtered"
    selected_ids = normalize_inscripcio_ids(payload.get("selected_ids") or [])
    raw_filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
    sort_context_filters_raw = payload.get("sort_context_filters") if isinstance(payload.get("sort_context_filters"), dict) else raw_filters

    group_state = str(raw_filters.get("group_state") or "all").strip().lower()
    if group_state not in {"all", "assigned", "unassigned"}:
        group_state = "all"
    group_ids = []
    raw_group_ids = raw_filters.get("group_ids")
    if isinstance(raw_group_ids, list):
        for value in raw_group_ids:
            try:
                clean = int(value)
            except Exception:
                continue
            if clean > 0 and clean not in group_ids:
                group_ids.append(clean)
    try:
        legacy_group_id = int(raw_filters.get("group_id"))
    except Exception:
        legacy_group_id = None
    if legacy_group_id and legacy_group_id > 0 and legacy_group_id not in group_ids:
        group_ids.append(legacy_group_id)

    allowed_group_fields = get_allowed_group_fields(competicio)
    allowed_group_codes = {field["code"] for field in allowed_group_fields}
    selected_group_codes_context = _normalize_sort_group_by(payload.get("group_by"), allowed_group_codes, fallback_group_by=competicio.group_by_default or [])
    workspace_filters = _normalize_sort_filters(raw_filters)
    filters = _normalize_sort_filters(sort_context_filters_raw)
    context_key = build_inscripcions_sort_context_key(competicio.id, filters=filters, group_by=selected_group_codes_context)
    sort_fields = get_available_sort_fields(competicio)
    sort_codes = {field["code"] for field in sort_fields}
    state = get_inscripcions_sort_context_state(request, context_key)
    stack_raw = state.get("stack") if isinstance(state.get("stack"), list) else []
    stack = []
    for item in stack_raw:
        normalized = _normalize_sort_criterion(item, sort_codes=sort_codes, allowed_group_codes=allowed_group_codes, fallback_group_by=selected_group_codes_context)
        if normalized is not None:
            stack.append(normalized)
    partition_codes = _extract_sort_partition_codes(stack)
    workspace_bucket_codes = _normalize_group_workspace_bucket_fields(
        payload.get("workspace_bucket_fields"),
        allowed_group_codes,
        used_codes=set(selected_group_codes_context) | set(partition_codes),
    )

    if scope == "selected":
        qs = Inscripcio.objects.filter(competicio=competicio, id__in=selected_ids)
    else:
        qs = _build_inscripcions_filtered_qs(competicio, filters)
        if group_ids:
            qs = qs.filter(grup_competicio_id__in=group_ids)
        if group_state == "assigned":
            qs = qs.filter(grup_competicio__isnull=False)
        elif group_state == "unassigned":
            qs = qs.filter(grup_competicio__isnull=True)
    records = list(qs.order_by("ordre_sortida", "id"))
    if not records:
        return JsonResponse(with_inscripcions_history_payload({"ok": True, "preview_only": preview_only, "updated": 0, "groups_created": 0, "buckets_total": 0, "buckets_applied": 0, "stack_used": partition_codes, "workspace_bucket_fields": workspace_bucket_codes, "resolution_mode": "auto", "layers_used": [], "effective_bucket_count": 0, "strategy": strategy, "used_fallback": False, "preview": {"groups_total": 0, "members_total": 0, "groups": [], "existing_groups_total": 0, "existing_members_total": 0, "existing_groups": [], "resolution_mode": "auto", "layers_used": [], "effective_bucket_count": 0, "strategy": strategy, "workspace_bucket_fields": workspace_bucket_codes} if preview_only else None}, request, competicio.id))

    resolution = _resolve_group_creation_buckets(competicio, records, group_codes=selected_group_codes_context, partition_codes=partition_codes, workspace_codes=workspace_bucket_codes, fallback_mode=fallback_mode)
    if not resolution.get("ok"):
        return HttpResponseBadRequest(resolution.get("error") or "No hi ha criteris resolubles per construir blocs d'origen")

    buckets = list(resolution.get("buckets") or [])
    layers_used = list(resolution.get("layers_used") or [])
    used_fallback = bool(resolution.get("used_fallback"))
    fallback_reason = str(resolution.get("fallback_reason") or "")
    bucket_by_key = {bucket["key"]: bucket for bucket in buckets}
    selected_keys_raw = payload.get("selected_keys")
    if not isinstance(selected_keys_raw, list):
        selected_keys_raw = payload.get("selected_bucket_keys")
    if not isinstance(selected_keys_raw, list):
        selected_keys_raw = payload.get("selected_tab_keys")
    selected_keys = []
    if isinstance(selected_keys_raw, list):
        for value in selected_keys_raw:
            if isinstance(value, str) and value in bucket_by_key and value not in selected_keys:
                selected_keys.append(value)
    if selected_keys:
        buckets_to_apply = [bucket_by_key[key] for key in selected_keys]
    elif str(payload.get("bucket_selection_mode") or "").strip().lower() == "none":
        buckets_to_apply = []
    else:
        buckets_to_apply = list(buckets)

    target_ids = []
    seen_ids = set()
    for bucket in buckets_to_apply:
        for ins_id in bucket["ids"]:
            if ins_id in seen_ids:
                continue
            seen_ids.add(ins_id)
            target_ids.append(ins_id)
    existing_groups_preview = _build_existing_groups_preview(competicio, records, bucket_sources_by_id=_build_bucket_sources_by_id(buckets), moving_ids=target_ids)
    existing_members_total = sum(group["members_count"] for group in existing_groups_preview)
    if not target_ids:
        return JsonResponse(with_inscripcions_history_payload({"ok": True, "preview_only": preview_only, "updated": 0, "groups_created": 0, "buckets_total": len(buckets), "buckets_applied": len(buckets_to_apply), "stack_used": partition_codes, "workspace_bucket_fields": workspace_bucket_codes, "resolution_mode": "auto", "layers_used": layers_used, "effective_bucket_count": len(buckets), "strategy": strategy, "used_fallback": used_fallback, "fallback_reason": fallback_reason, "preview": {"groups_total": 0, "members_total": 0, "groups": [], "existing_groups_total": len(existing_groups_preview), "existing_members_total": existing_members_total, "existing_groups": existing_groups_preview, "resolution_mode": "auto", "layers_used": layers_used, "effective_bucket_count": len(buckets), "strategy": strategy, "used_fallback": used_fallback, "fallback_reason": fallback_reason, "workspace_bucket_fields": workspace_bucket_codes} if preview_only else None}, request, competicio.id))

    id_to_record = {record.id: record for record in records}
    objs = [id_to_record[ins_id] for ins_id in target_ids if ins_id in id_to_record]
    n = len(objs)
    sizes = []
    if strategy == "per_bucket":
        sizes = [len(bucket["ids"]) for bucket in buckets_to_apply if len(bucket["ids"]) > 0]
    elif strategy == "count":
        try:
            k = int(payload.get("group_count") or 0)
        except Exception:
            return HttpResponseBadRequest("group_count invalid")
        if k < 1:
            return HttpResponseBadRequest("group_count invalid")
        sizes = _balanced_sizes(n, k)
    elif strategy in ("size_fixed", "size_balanced"):
        try:
            size = int(payload.get("group_size") or 0)
        except Exception:
            return HttpResponseBadRequest("group_size invalid")
        if size < 2:
            return HttpResponseBadRequest("group_size invalid")
        sizes = _fixed_sizes(n, size) if strategy == "size_fixed" else _balanced_sizes(n, math.ceil(n / size))
    else:
        try:
            min_size = int(payload.get("min_size") or 0)
            max_size = int(payload.get("max_size") or 0)
        except Exception:
            return HttpResponseBadRequest("min_size/max_size invalid")
        if min_size <= 0 or max_size <= 0 or min_size > max_size:
            return HttpResponseBadRequest("min_size/max_size invalid")
        preferred_k = None
        if strategy == "count_with_range":
            try:
                preferred_k = int(payload.get("group_count") or 0)
            except Exception:
                return HttpResponseBadRequest("group_count invalid")
            if preferred_k < 1:
                return HttpResponseBadRequest("group_count invalid")
        k_resolved, meta = _resolve_k_for_range(n, min_size, max_size, preferred_k=preferred_k, fallback_mode=fallback_mode)
        if k_resolved is None:
            return HttpResponseBadRequest("No es pot resoldre una particio valida amb aquesta forquilla")
        if meta.get("used_fallback"):
            used_fallback = True
            fallback_reason = meta.get("fallback_reason") or fallback_reason
        sizes = _balanced_sizes(n, k_resolved)

    max_grup = (GrupCompeticio.objects.filter(competicio=competicio).aggregate(m=Max("display_num"))["m"] or 0)
    preview_groups = _build_group_creation_preview(objs, sizes, start_group_num=max_grup, bucket_sources_by_id=_build_bucket_sources_by_id(buckets_to_apply), filter_name_sources=_build_group_name_filter_sources(filters, workspace_filters))
    if preview_only:
        return JsonResponse(with_inscripcions_history_payload({"ok": True, "preview_only": True, "updated": 0, "groups_created": len(preview_groups), "buckets_total": len(buckets), "buckets_applied": len(buckets_to_apply), "stack_used": partition_codes, "workspace_bucket_fields": workspace_bucket_codes, "resolution_mode": "auto", "layers_used": layers_used, "effective_bucket_count": len(buckets), "strategy": strategy, "used_fallback": used_fallback, "fallback_reason": fallback_reason, "size_min": min(sizes) if sizes else 0, "size_max": max(sizes) if sizes else 0, "preview": {"groups_total": len(preview_groups), "members_total": n, "groups": preview_groups, "existing_groups_total": len(existing_groups_preview), "existing_members_total": existing_members_total, "existing_groups": existing_groups_preview, "resolution_mode": "auto", "layers_used": layers_used, "effective_bucket_count": len(buckets), "strategy": strategy, "used_fallback": used_fallback, "fallback_reason": fallback_reason, "workspace_bucket_fields": workspace_bucket_codes, "buckets_total": len(buckets), "buckets_applied": len(buckets_to_apply), "size_min": min(sizes) if sizes else 0, "size_max": max(sizes) if sizes else 0}}, request, competicio.id))

    if has_rotacions:
        group_maps = get_group_maps(competicio)
        programmed_group_ids = get_programmed_group_ids(competicio)
        blocked_groups = []
        for row in existing_groups_preview:
            if str(row.get("impact_kind") or "") != "removed":
                continue
            group_num = row.get("group_num")
            if not group_num:
                continue
            group = group_maps["by_display_num"].get(group_num)
            if group is None or group.id not in programmed_group_ids:
                continue
            blocked_groups.append(group)
        if blocked_groups:
            return HttpResponseBadRequest(_message_for_emptied_programmed_groups(blocked_groups))

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    updates = list(objs)
    _assign_group_sizes_in_order(objs, sizes, max_grup)
    with transaction.atomic():
        qs.filter(id__in=target_ids).update(grup=None)
        Inscripcio.objects.bulk_update(updates, ["grup"], batch_size=500)
        sync_stable_groups_from_legacy(competicio)
        _persist_group_suggested_names(competicio, preview_groups)
    record_inscripcions_history_entry(request, competicio, action_type="groups_from_sort", action_label="Crear grups des del panell", before_snapshot=before_snapshot, after_snapshot=capture_inscripcions_history_snapshot(request, competicio))
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "updated": len(updates), "groups_created": len(sizes), "buckets_total": len(buckets), "buckets_applied": len(buckets_to_apply), "stack_used": partition_codes, "workspace_bucket_fields": workspace_bucket_codes, "resolution_mode": "auto", "layers_used": layers_used, "effective_bucket_count": len(buckets), "strategy": strategy, "used_fallback": used_fallback, "fallback_reason": fallback_reason, "size_min": min(sizes) if sizes else 0, "size_max": max(sizes) if sizes else 0}, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_reorder(request, pk):
    try:
        payload = json.loads(request.body.decode("utf-8"))
        ids = payload.get("ids", [])
        moved_id = payload.get("moved_id")
        new_index = payload.get("new_index")
        target_group = payload.get("target_group")
        reorder_mode = str(payload.get("mode") or "visual").strip().lower()
        raw_filters = payload.get("filters")
        raw_group_by = payload.get("group_by")
        if not isinstance(ids, list) or not ids:
            return HttpResponseBadRequest("Payload invalid")
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    wanted = [int(value) for value in ids if str(value).isdigit()]
    if not wanted:
        return HttpResponseBadRequest("IDs buits")
    if reorder_mode not in ("visual", "group_edit"):
        return HttpResponseBadRequest("mode invalid")
    competicio = get_object_or_404(Competicio, pk=pk)

    if moved_id is not None:
        try:
            moved_id = int(moved_id)
        except Exception:
            return HttpResponseBadRequest("moved_id invalid")
    if new_index is not None:
        try:
            new_index = int(new_index)
        except Exception:
            return HttpResponseBadRequest("new_index invalid")
    if target_group in ("", None):
        target_group = None
    else:
        try:
            target_group = int(target_group)
        except Exception:
            return HttpResponseBadRequest("target_group invalid")
        if target_group <= 0:
            return HttpResponseBadRequest("target_group invalid")

    qs = Inscripcio.objects.filter(competicio=competicio, id__in=wanted)
    found = set(qs.values_list("id", flat=True))
    if set(wanted) != found:
        return HttpResponseBadRequest("IDs no valids per aquesta competicio")

    id_to_group = dict(qs.values_list("id", "grup"))
    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    group_maps = get_group_maps(competicio)
    groups_by_display = group_maps["by_display_num"]

    with transaction.atomic():
        target_order_by_id = {ins_id: idx for idx, ins_id in enumerate(wanted, start=1)}
        order_updates = []
        for obj in qs.only("id", "ordre_sortida"):
            next_ord = target_order_by_id.get(obj.id)
            if next_ord is not None and obj.ordre_sortida != next_ord:
                obj.ordre_sortida = next_ord
                order_updates.append(obj)
        if order_updates:
            Inscripcio.objects.bulk_update(order_updates, ["ordre_sortida"], batch_size=500)

        if reorder_mode == "group_edit" and moved_id is not None and new_index is not None and moved_id in wanted:
            next_group = None
            should_update_group = False
            if target_group is not None:
                next_group = target_group
                should_update_group = True
            elif new_index > 0:
                prev_id = wanted[new_index - 1]
                next_group = id_to_group.get(prev_id)
                should_update_group = True
            if should_update_group:
                target_group_obj = groups_by_display.get(next_group)
                moved = Inscripcio.objects.select_related("grup_competicio").get(id=moved_id, competicio=competicio)
                if target_group_obj is not None:
                    move_inscripcio_to_group(moved, target_group_obj)
                else:
                    old_group = moved.grup_competicio
                    Inscripcio.objects.filter(id=moved_id).update(grup=None, grup_competicio=None, ordre_competicio=None)
                    compact_competition_order_for_group(old_group)

    sync_competicio_group_names_view(competicio)
    filters = _normalize_sort_filters(raw_filters)
    allowed_group_fields = get_allowed_group_fields(competicio)
    allowed_group_codes = {field["code"] for field in allowed_group_fields}
    selected_group_codes_context = _normalize_sort_group_by(raw_group_by, allowed_group_codes, fallback_group_by=competicio.group_by_default or [])
    context_key = build_inscripcions_sort_context_key(competicio.id, filters=filters, group_by=selected_group_codes_context)
    filtered_ids = list(_build_inscripcions_filtered_qs(competicio, filters).order_by("ordre_sortida", "id").values_list("id", flat=True))
    if len(filtered_ids) == len(wanted) and set(filtered_ids) == set(wanted):
        reconcile_inscripcions_sort_context_state(request, context_key, wanted)

    record_inscripcions_history_entry(request, competicio, action_type="reorder" if reorder_mode == "visual" else "move_group_member", action_label="Reordenar inscripcions" if reorder_mode == "visual" else "Editar contingut de grups", before_snapshot=before_snapshot, after_snapshot=capture_inscripcions_history_snapshot(request, competicio))
    return JsonResponse(with_inscripcions_history_payload({"ok": True}, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_save_group_competition_order(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")
    try:
        group_num = int(payload.get("group_num"))
    except Exception:
        return HttpResponseBadRequest("group_num invalid")
    ordered_ids = payload.get("ids")
    if not isinstance(ordered_ids, list) or not ordered_ids:
        return HttpResponseBadRequest("ids invalid")
    group = get_group_for_display_num(competicio, group_num)
    if group is None:
        return HttpResponseBadRequest("group_num invalid")

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    try:
        updated = save_group_competition_order(group, ordered_ids)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    record_inscripcions_history_entry(request, competicio, action_type="set_group_competition_order", action_label="Desar ordre de competicio", before_snapshot=before_snapshot, after_snapshot=capture_inscripcions_history_snapshot(request, competicio))
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "group_num": group_num, "updated": updated}, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_merge_tabs(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    try:
        payload = json.loads(request.body.decode("utf-8"))
        group_field = payload.get("group_field")
        source_key = payload.get("source_key")
        target_key = payload.get("target_key")
    except Exception:
        return HttpResponseBadRequest("JSON invalid")
    if not group_field:
        return HttpResponseBadRequest("group_field buit")
    if not source_key or not target_key or source_key == target_key:
        return HttpResponseBadRequest("claus invalides")

    merges = competicio.tab_merges or {}
    current = merges.get(group_field, [])

    def normalize_key_to_simple_list(key):
        try:
            value = json.loads(key)
        except Exception:
            return [key]
        if isinstance(value, list) and value and all(isinstance(item, str) for item in value) and all(item.strip().startswith("[") for item in value):
            return value
        if isinstance(value, list):
            return [key]
        return [key]

    source_list = normalize_key_to_simple_list(source_key)
    target_list = normalize_key_to_simple_list(target_key)
    desired = []
    for item in (target_list + source_list):
        if item not in desired:
            desired.append(item)

    consumed_idx = []
    merged_all = []
    for idx, group in enumerate(current):
        if any(item in group for item in desired):
            merged_all.extend(group)
            consumed_idx.append(idx)
    for idx in sorted(consumed_idx, reverse=True):
        current.pop(idx)
    merged_all.extend(desired)
    final = []
    for item in merged_all:
        if item not in final:
            final.append(item)

    current.append(final)
    merges[group_field] = current
    competicio.tab_merges = merges
    competicio.save(update_fields=["tab_merges"])
    record_inscripcions_history_entry(request, competicio, action_type="merge_tabs", action_label="Fusionar pestanyes", before_snapshot=before_snapshot, after_snapshot=capture_inscripcions_history_snapshot(request, competicio))
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "merged": final}, request, competicio.id))


__all__ = [
    "groups_assign",
    "groups_create",
    "groups_delete",
    "groups_delete_all",
    "groups_delete_empty",
    "groups_detail",
    "groups_preview",
    "groups_transform_apply",
    "groups_transform_preview",
    "groups_unassign",
    "groups_workspace",
    "inscripcions_bulk_group_competition_order_apply",
    "inscripcions_bulk_group_competition_order_preview",
    "inscripcions_group_competition_order_preview",
    "inscripcions_groups_from_sort",
    "inscripcions_merge_tabs",
    "inscripcions_reorder",
    "inscripcions_save_group_competition_order",
]
