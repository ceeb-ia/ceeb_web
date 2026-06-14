import json
from collections import OrderedDict

from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from ...models import Competicio, Inscripcio
from ...services.shared.competition_groups import normalize_positive_int
from ...services.inscripcions.history import (
    INSCRIPCIONS_HISTORY_DEPTH,
    _history_comp_key,
    _read_inscripcions_history_store,
    _write_inscripcions_history_store,
    apply_inscripcions_history_snapshot,
    capture_inscripcions_history_snapshot,
    record_inscripcions_history_entry,
    with_inscripcions_history_payload,
)
from ...services.inscripcions.queries import (
    COLUMN_FILTER_EMPTY_TOKEN,
    LEGACY_SORT_KEY_MAP,
    _build_sort_field_runtime_context,
    _build_inscripcions_filtered_qs,
    _build_sort_records_queryset,
    _custom_sort_token_key,
    _norm_val,
    _normalize_custom_sort_order,
    _normalize_custom_sort_token,
    _normalize_sort_criterion,
    _normalize_sort_filters,
    _normalize_sort_group_by,
    _resolve_sort_field_runtime,
    _sort_scalar,
    build_inscripcions_sort_context_key,
    clear_inscripcions_sort_context_state,
    compute_inscripcions_order_signature_from_ids,
    get_allowed_group_fields,
    get_available_column_filter_fields,
    get_available_sort_fields,
    get_competicio_custom_sort_order_values,
    get_competicio_custom_sort_rank_map,
    get_inscripcions_sort_context_state,
    get_inscripcio_value,
    reconcile_inscripcions_sort_context_state,
    save_inscripcions_sort_context_state,
)
from ...services.inscripcions.sorting import (
    _split_custom_sort_tokens,
    arrow_positions,
    set_competicio_custom_sort_order_values,
    sort_records_by_field_stable,
)


def _normalize_competition_order_tail_flag(raw_value):
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, (int, float)):
        return bool(raw_value)
    token = str(raw_value or "").strip().lower()
    return token in {"1", "true", "yes", "on"}


def _collect_column_filter_value_rows(records, column_code):
    out = OrderedDict()
    empty_count = 0
    context = _build_sort_field_runtime_context(records, column_code)
    for obj in records:
        runtime = _resolve_sort_field_runtime(obj, column_code, context=context)
        token = runtime.get("token") or ""
        if not token:
            empty_count += 1
            continue
        key = _custom_sort_token_key(token)
        if not key:
            continue
        row = out.get(key)
        if row is None:
            row = {
                "token": token,
                "label": runtime.get("label") or token,
                "count": 0,
                "sort_scalar": runtime.get("sort_scalar"),
            }
            out[key] = row
        row["count"] += 1

    values = list(out.values())
    values.sort(key=lambda row: row["sort_scalar"])
    if empty_count:
        values.append(
            {
                "token": COLUMN_FILTER_EMPTY_TOKEN,
                "label": "(Sense valor)",
                "count": empty_count,
                "sort_scalar": _sort_scalar(""),
            }
        )
    return values


def _collect_sort_field_value_stats(records, sort_code):
    out = OrderedDict()
    context = _build_sort_field_runtime_context(records, sort_code)
    for obj in records:
        runtime = _resolve_sort_field_runtime(obj, sort_code, context=context)
        token = runtime.get("token") or ""
        if not token:
            continue
        key = _custom_sort_token_key(token)
        if not key:
            continue
        row = out.get(key)
        if row is None:
            row = {
                "token": token,
                "label": runtime.get("label") or token,
                "count": 0,
                "sort_scalar": runtime.get("sort_scalar"),
            }
            out[key] = row
        row["count"] += 1
    return out


def _sort_criterion_identity(entry):
    if not isinstance(entry, dict):
        return ("", "all", None)
    sort_key = str(entry.get("sort_key") or "").strip()
    scope = str(entry.get("scope") or "all").strip().lower()
    if scope not in ("all", "tab", "all_groups", "group"):
        scope = "all"
    group_num = None
    if scope == "group":
        try:
            group_num = int(entry.get("group_num"))
        except Exception:
            group_num = None
    return (sort_key, scope, group_num)


def _upsert_sort_stack_entry_preserving_priority(stack, new_entry):
    if not isinstance(stack, list):
        stack = []
    if not isinstance(new_entry, dict):
        return list(stack)

    target_identity = _sort_criterion_identity(new_entry)
    out = []
    replaced = False
    for entry in stack:
        if _sort_criterion_identity(entry) == target_identity:
            if not replaced:
                out.append(new_entry)
                replaced = True
            continue
        out.append(entry)
    if not replaced:
        out.append(new_entry)
    return out


def _normalize_positive_group_num(value):
    try:
        group_num = int(value)
    except Exception:
        return None
    return group_num if group_num > 0 else None


def _collect_visible_group_nums(records):
    out = []
    seen = set()
    for record in records or []:
        group_num = _normalize_positive_group_num(getattr(record, "grup", None))
        if group_num is None or group_num in seen:
            continue
        seen.add(group_num)
        out.append(group_num)
    return out


def _stack_requires_full_groups(stack):
    for criterion in stack or []:
        scope = str((criterion or {}).get("scope") or "all").strip().lower()
        if scope in ("group", "all_groups"):
            return True
    return False


def _collect_stack_target_group_nums(stack, visible_group_nums):
    target_group_nums = set()
    visible_group_set = set(visible_group_nums or [])
    for criterion in stack or []:
        scope = str((criterion or {}).get("scope") or "all").strip().lower()
        if scope == "all_groups":
            target_group_nums.update(visible_group_set)
            continue
        if scope == "group":
            group_num = _normalize_positive_group_num((criterion or {}).get("group_num"))
            if group_num is not None:
                target_group_nums.add(group_num)
    return target_group_nums


def _build_sort_application_runtime(competicio, visible_records, sort_codes, stack, include_competition_order=False):
    visible_records = list(visible_records or [])
    visible_ids = [record.id for record in visible_records]
    visible_id_set = set(visible_ids)
    visible_group_nums = _collect_visible_group_nums(visible_records)
    sort_codes = [str(code or "").strip() for code in (sort_codes or []) if str(code or "").strip()]
    if "grup" not in sort_codes:
        sort_codes = sort_codes + ["grup"]

    record_by_id = {record.id: record for record in visible_records}
    application_ids = list(visible_ids)
    if _stack_requires_full_groups(stack):
        target_group_nums = _collect_stack_target_group_nums(stack, visible_group_nums)
        if target_group_nums:
            group_records = list(
                _build_sort_records_queryset(
                    Inscripcio.objects.filter(competicio=competicio, grup__in=sorted(target_group_nums)),
                    sort_codes,
                    include_competition_order=include_competition_order,
                )
            )
            for record in group_records:
                record_by_id[record.id] = record
            global_ids = list(
                Inscripcio.objects.filter(competicio=competicio).order_by("ordre_sortida", "id").values_list("id", flat=True)
            )
            application_ids = [ins_id for ins_id in global_ids if ins_id in record_by_id]

    return {
        "records": [record_by_id[ins_id] for ins_id in application_ids if ins_id in record_by_id],
        "id_to_record": record_by_id,
        "application_ids": application_ids,
        "visible_ids": visible_id_set,
        "visible_group_nums": visible_group_nums,
    }


def _apply_single_sort_criterion(ids_in_order, id_to_record, criterion, competicio, runtime=None):
    seq_records = [id_to_record[ins_id] for ins_id in ids_in_order if ins_id in id_to_record]
    if not seq_records:
        return list(ids_in_order)

    sort_key = criterion["sort_key"]
    sort_dir = criterion["sort_dir"]
    scope = criterion["scope"]
    group_num = criterion["group_num"]
    group_by = list(criterion.get("group_by") or [])
    runtime = runtime if isinstance(runtime, dict) else {}
    visible_ids = runtime.get("visible_ids")
    if not isinstance(visible_ids, set):
        visible_ids = set(ids_in_order)
    visible_group_nums = runtime.get("visible_group_nums")
    if not isinstance(visible_group_nums, list):
        visible_group_nums = _collect_visible_group_nums(seq_records)
    visible_group_set = set(visible_group_nums)

    descending = sort_dir in ("desc", "arrow_desc")
    arrow = sort_dir in ("arrow_asc", "arrow_desc")
    custom = sort_dir == "custom"
    custom_rank_map = get_competicio_custom_sort_rank_map(competicio, sort_key) if custom else {}

    def _ordered_subset(subset_records):
        ordered = sort_records_by_field_stable(subset_records, sort_key, descending=descending, custom_rank_map=custom_rank_map)
        if not arrow:
            return ordered
        positions = arrow_positions(len(ordered))
        placed = [None] * len(ordered)
        for idx, obj in enumerate(ordered):
            placed[positions[idx]] = obj
        return placed

    def _replace_subset(ids_base, subset_records):
        ids_out = list(ids_base)
        id_to_index = {rid: idx for idx, rid in enumerate(ids_out)}
        target_indexes = [id_to_index[obj.id] for obj in subset_records if obj.id in id_to_index]
        ordered_target = _ordered_subset(subset_records)
        for idx, obj in zip(target_indexes, ordered_target):
            ids_out[idx] = obj.id
        return ids_out

    if scope == "all":
        target_records = [record for record in seq_records if record.id in visible_ids]
        return _replace_subset(ids_in_order, target_records)

    if scope == "all_groups":
        ids_out = list(ids_in_order)
        id_to_index = {rid: idx for idx, rid in enumerate(ids_out)}
        group_to_records = OrderedDict()
        for record in seq_records:
            current_group_num = _normalize_positive_group_num(getattr(record, "grup", None))
            if current_group_num is None or current_group_num not in visible_group_set:
                continue
            group_to_records.setdefault(current_group_num, []).append(record)
        for group_records in group_to_records.values():
            target_indexes = [id_to_index[obj.id] for obj in group_records if obj.id in id_to_index]
            ordered_target = _ordered_subset(group_records)
            for idx, obj in zip(target_indexes, ordered_target):
                ids_out[idx] = obj.id
        return ids_out

    if scope == "group":
        target_records = [record for record in seq_records if _normalize_positive_group_num(getattr(record, "grup", None)) == group_num]
        return _replace_subset(ids_in_order, target_records)

    visible_seq_records = [record for record in seq_records if record.id in visible_ids]
    if not group_by:
        return _replace_subset(ids_in_order, visible_seq_records)

    grouping_sig = "|".join(group_by)
    merges = (competicio.tab_merges or {}).get(grouping_sig, [])
    merge_map = {}
    for group_keys in merges:
        group_tuple = tuple(group_keys)
        for group_key in group_keys:
            merge_map[group_key] = group_tuple

    ids_out = list(ids_in_order)
    id_to_index = {rid: idx for idx, rid in enumerate(ids_out)}
    tab_to_records = OrderedDict()
    for record in visible_seq_records:
        values = [_norm_val(get_inscripcio_value(record, code)) for code in group_by]
        simple = json.dumps(values, ensure_ascii=False)
        merged = merge_map.get(simple)
        tab_key = json.dumps(list(merged), ensure_ascii=False) if merged else simple
        tab_to_records.setdefault(tab_key, []).append(record)

    for tab_records in tab_to_records.values():
        target_indexes = [id_to_index[obj.id] for obj in tab_records if obj.id in id_to_index]
        ordered_tab = _ordered_subset(tab_records)
        for idx, obj in zip(target_indexes, ordered_tab):
            ids_out[idx] = obj.id
    return ids_out


def _apply_sort_stack(ids_base, id_to_record, stack, competicio, runtime=None):
    final_ids = list(ids_base)
    for criterion in reversed(stack):
        final_ids = _apply_single_sort_criterion(final_ids, id_to_record, criterion, competicio, runtime=runtime)
    return final_ids


def _competition_order_group_num(record):
    group_num = _normalize_positive_group_num(getattr(record, "grup", None))
    if group_num is not None:
        return group_num
    group = getattr(record, "grup_competicio", None)
    return normalize_positive_int(getattr(group, "display_num", None))


def _apply_competition_order_tail(ids_in_order, id_to_record, runtime=None):
    seq_records = [id_to_record[ins_id] for ins_id in ids_in_order if ins_id in id_to_record]
    if not seq_records:
        return list(ids_in_order)

    ids_out = list(ids_in_order)
    id_to_index = {rid: idx for idx, rid in enumerate(ids_out)}
    group_to_records = OrderedDict()
    for record in seq_records:
        group_num = _competition_order_group_num(record)
        if group_num is None:
            continue
        group_to_records.setdefault(group_num, []).append(record)

    for group_records in group_to_records.values():
        with_comp_order = []
        without_comp_order = []
        for pos, record in enumerate(group_records):
            comp_order = normalize_positive_int(getattr(record, "ordre_competicio", None))
            if comp_order is None:
                without_comp_order.append(record)
            else:
                with_comp_order.append((comp_order, pos, record))
        with_comp_order.sort(key=lambda item: (item[0], item[1]))
        ordered_records = [record for _comp_order, _pos, record in with_comp_order] + without_comp_order
        target_indexes = [id_to_index[record.id] for record in group_records if record.id in id_to_index]
        for idx, record in zip(target_indexes, ordered_records):
            ids_out[idx] = record.id
    return ids_out


def _apply_sort_pipeline(ids_base, id_to_record, stack, competicio, runtime=None, competition_order_tail=False):
    final_ids = list(ids_base)
    if competition_order_tail:
        final_ids = _apply_competition_order_tail(final_ids, id_to_record, runtime=runtime)
    return _apply_sort_stack(final_ids, id_to_record, stack, competicio, runtime=runtime)


def _persist_inscripcions_order_from_ids(id_to_record, final_ids):
    updates = []
    for idx, ins_id in enumerate(final_ids, start=1):
        obj = id_to_record.get(ins_id)
        if not obj:
            continue
        if obj.ordre_sortida != idx:
            obj.ordre_sortida = idx
            updates.append(obj)
    if updates:
        with transaction.atomic():
            Inscripcio.objects.bulk_update(updates, ["ordre_sortida"], batch_size=500)
    return len(updates)


def _perform_inscripcions_history_step(request, competicio, direction):
    if direction not in ("undo", "redo"):
        return None
    store = _read_inscripcions_history_store(request)
    comp_key = _history_comp_key(competicio.id)
    bucket = store.get(comp_key)
    if not isinstance(bucket, dict):
        bucket = {"undo": [], "redo": []}
    undo = bucket.get("undo")
    redo = bucket.get("redo")
    if not isinstance(undo, list):
        undo = []
    if not isinstance(redo, list):
        redo = []
    src = undo if direction == "undo" else redo
    dst = redo if direction == "undo" else undo
    if not src:
        return None
    entry = src[-1]
    if not isinstance(entry, dict):
        entry = {}
    target_snapshot = entry.get("before") if direction == "undo" else entry.get("after")
    apply_inscripcions_history_snapshot(request, competicio, target_snapshot)
    src.pop()
    dst.append(entry)
    if len(dst) > INSCRIPCIONS_HISTORY_DEPTH:
        dst[:] = dst[-INSCRIPCIONS_HISTORY_DEPTH:]
    bucket["undo"] = undo
    bucket["redo"] = redo
    store[comp_key] = bucket
    _write_inscripcions_history_store(request, store)
    return entry


@require_POST
@csrf_protect
def inscripcions_sort_apply(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    sort_fields = get_available_sort_fields(competicio)
    sort_codes = {field["code"] for field in sort_fields}
    raw_sort_key = str(payload.get("sort_key") or "").strip()
    sort_key = LEGACY_SORT_KEY_MAP.get(raw_sort_key, raw_sort_key)
    if sort_key not in sort_codes:
        return HttpResponseBadRequest("sort_key invalid")

    sort_dir = str(payload.get("sort_dir") or "asc").strip()
    if sort_dir not in ("asc", "desc", "arrow_asc", "arrow_desc", "custom"):
        return HttpResponseBadRequest("sort_dir invalid")

    scope = str(payload.get("scope") or "all").strip().lower()
    if scope not in ("all", "tab", "all_groups", "group"):
        return HttpResponseBadRequest("scope invalid")

    allowed_group_fields = get_allowed_group_fields(competicio)
    allowed_group_codes = {field["code"] for field in allowed_group_fields}
    selected_group_codes_context = _normalize_sort_group_by(payload.get("group_by"), allowed_group_codes, fallback_group_by=competicio.group_by_default or [])

    group_num = payload.get("group_num")
    if scope == "group":
        try:
            group_num = int(group_num)
        except Exception:
            return HttpResponseBadRequest("group_num invalid")
        if group_num <= 0:
            return HttpResponseBadRequest("group_num invalid")

    filters = _normalize_sort_filters(payload.get("filters"))
    context_key = build_inscripcions_sort_context_key(competicio.id, filters=filters, group_by=selected_group_codes_context)
    pre_state = get_inscripcions_sort_context_state(request, context_key)
    pre_stack_raw = pre_state.get("stack") if isinstance(pre_state.get("stack"), list) else []
    pre_stack = []
    for item in pre_stack_raw:
        normalized = _normalize_sort_criterion(item, sort_codes=sort_codes, allowed_group_codes=allowed_group_codes, fallback_group_by=selected_group_codes_context)
        if normalized is not None:
            pre_stack.append(normalized)

    new_entry = _normalize_sort_criterion(
        {
            "sort_key": sort_key,
            "sort_dir": sort_dir,
            "scope": scope,
            "group_num": group_num if scope == "group" else None,
            "group_by": selected_group_codes_context,
        },
        sort_codes=sort_codes,
        allowed_group_codes=allowed_group_codes,
        fallback_group_by=selected_group_codes_context,
    )
    if new_entry is None:
        return HttpResponseBadRequest("criteri invalid")

    qs = _build_inscripcions_filtered_qs(competicio, filters)
    record_sort_codes = [new_entry.get("sort_key")] + [entry.get("sort_key") for entry in pre_stack]
    records = list(_build_sort_records_queryset(qs, record_sort_codes + ["grup"]))
    if not records:
        return JsonResponse(with_inscripcions_history_payload({"ok": True, "updated": 0, "total": 0, "scope": scope, "stack_count": 0, "competition_order_tail": False}, request, competicio.id))

    current_ids = [record.id for record in records]
    pre_runtime = _build_sort_application_runtime(competicio, records, record_sort_codes, pre_stack)
    state = reconcile_inscripcions_sort_context_state(request, context_key, current_ids, current_base_ids=pre_runtime["application_ids"])
    competition_order_tail_explicit = bool(state.get("competition_order_tail_explicit"))
    stack_existing_raw = state.get("stack") if isinstance(state.get("stack"), list) else []
    stack_existing = []
    for item in stack_existing_raw:
        normalized = _normalize_sort_criterion(item, sort_codes=sort_codes, allowed_group_codes=allowed_group_codes, fallback_group_by=selected_group_codes_context)
        if normalized is not None:
            stack_existing.append(normalized)

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    stack_full = _upsert_sort_stack_entry_preserving_priority(stack_existing, new_entry)
    if len(stack_full) > 20:
        stack_full = stack_full[-20:]
    competition_order_tail_active = bool(state.get("competition_order_tail")) if competition_order_tail_explicit else bool(stack_full)

    runtime = _build_sort_application_runtime(competicio, records, [entry.get("sort_key") for entry in stack_full], stack_full, include_competition_order=competition_order_tail_active)
    id_to_record = runtime["id_to_record"]
    application_ids = runtime["application_ids"]
    base_ids_state = state.get("base_ids") if isinstance(state.get("base_ids"), list) else []
    valid_base = isinstance(base_ids_state, list) and len(base_ids_state) == len(application_ids) and set(base_ids_state) == set(application_ids)
    base_ids = list(base_ids_state) if valid_base and stack_existing else list(application_ids)

    final_ids = _apply_sort_pipeline(base_ids, id_to_record, stack_full, competicio, runtime=runtime, competition_order_tail=competition_order_tail_active)
    updated_count = _persist_inscripcions_order_from_ids(id_to_record, final_ids)
    order_sig = compute_inscripcions_order_signature_from_ids(final_ids)
    save_inscripcions_sort_context_state(request, context_key, stack=stack_full, order_sig=order_sig, base_ids=base_ids, context_ids=current_ids, competition_order_tail=competition_order_tail_active)
    record_inscripcions_history_entry(request, competicio, action_type="sort_apply", action_label="Aplicar ordenacio", before_snapshot=before_snapshot, after_snapshot=capture_inscripcions_history_snapshot(request, competicio))
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "scope": scope, "sort_key": sort_key, "sort_dir": sort_dir, "updated": updated_count, "total": len(runtime["records"]), "stack_count": len(stack_full), "competition_order_tail": competition_order_tail_active}, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_sort_remove(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}
    try:
        priority = int(payload.get("priority"))
    except Exception:
        return HttpResponseBadRequest("priority invalid")
    if priority <= 0:
        return HttpResponseBadRequest("priority invalid")

    sort_fields = get_available_sort_fields(competicio)
    sort_codes = {field["code"] for field in sort_fields}
    allowed_group_fields = get_allowed_group_fields(competicio)
    allowed_group_codes = {field["code"] for field in allowed_group_fields}
    selected_group_codes_context = _normalize_sort_group_by(payload.get("group_by"), allowed_group_codes, fallback_group_by=competicio.group_by_default or [])
    filters = _normalize_sort_filters(payload.get("filters"))
    context_key = build_inscripcions_sort_context_key(competicio.id, filters=filters, group_by=selected_group_codes_context)
    state = get_inscripcions_sort_context_state(request, context_key)
    stack_raw = state.get("stack") if isinstance(state.get("stack"), list) else []
    stack = []
    for item in stack_raw:
        normalized = _normalize_sort_criterion(item, sort_codes=sort_codes, allowed_group_codes=allowed_group_codes, fallback_group_by=selected_group_codes_context)
        if normalized is not None:
            stack.append(normalized)

    if not stack:
        clear_inscripcions_sort_context_state(request, context_key)
        return JsonResponse(with_inscripcions_history_payload({"ok": True, "removed": False, "stack_count": 0, "competition_order_tail": False}, request, competicio.id))

    qs = _build_inscripcions_filtered_qs(competicio, filters)
    record_sort_codes = [entry.get("sort_key") for entry in stack]
    competition_order_tail_active = bool(state.get("competition_order_tail"))
    records = list(_build_sort_records_queryset(qs, record_sort_codes + ["grup"], include_competition_order=competition_order_tail_active))
    if not records:
        clear_inscripcions_sort_context_state(request, context_key)
        return JsonResponse(with_inscripcions_history_payload({"ok": True, "removed": False, "stack_count": 0, "competition_order_tail": False}, request, competicio.id))

    current_ids = [record.id for record in records]
    runtime = _build_sort_application_runtime(competicio, records, record_sort_codes, stack, include_competition_order=competition_order_tail_active)
    id_to_record = runtime["id_to_record"]
    application_ids = runtime["application_ids"]
    if priority > len(stack):
        return HttpResponseBadRequest("priority out of range")

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    removed = stack.pop(priority - 1)
    base_ids_state = state.get("base_ids") if isinstance(state.get("base_ids"), list) else []
    valid_base = isinstance(base_ids_state, list) and len(base_ids_state) == len(application_ids) and set(base_ids_state) == set(application_ids)
    base_ids = list(base_ids_state) if valid_base else list(application_ids)
    final_ids = _apply_sort_pipeline(base_ids, id_to_record, stack, competicio, runtime=runtime, competition_order_tail=competition_order_tail_active) if stack else list(base_ids)
    updated_count = _persist_inscripcions_order_from_ids(id_to_record, final_ids)

    if stack:
        order_sig = compute_inscripcions_order_signature_from_ids(final_ids)
        save_inscripcions_sort_context_state(request, context_key, stack=stack, order_sig=order_sig, base_ids=base_ids, context_ids=current_ids, competition_order_tail=competition_order_tail_active)
    else:
        clear_inscripcions_sort_context_state(request, context_key)

    record_inscripcions_history_entry(request, competicio, action_type="sort_remove", action_label="Treure criteri d'ordenacio", before_snapshot=before_snapshot, after_snapshot=capture_inscripcions_history_snapshot(request, competicio))
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "removed": True, "removed_priority": priority, "removed_sort_key": removed.get("sort_key"), "stack_count": len(stack), "updated": updated_count, "competition_order_tail": bool(stack) and competition_order_tail_active}, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_sort_clear(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    allowed_group_fields = get_allowed_group_fields(competicio)
    allowed_group_codes = {field["code"] for field in allowed_group_fields}
    selected_group_codes_context = _normalize_sort_group_by(payload.get("group_by"), allowed_group_codes, fallback_group_by=competicio.group_by_default or [])
    filters = _normalize_sort_filters(payload.get("filters"))
    context_key = build_inscripcions_sort_context_key(competicio.id, filters=filters, group_by=selected_group_codes_context)
    sort_fields = get_available_sort_fields(competicio)
    sort_codes = {field["code"] for field in sort_fields}
    state = get_inscripcions_sort_context_state(request, context_key)
    stack_raw = state.get("stack") if isinstance(state.get("stack"), list) else []
    stack = []
    for item in stack_raw:
        norm = _normalize_sort_criterion(item, sort_codes=sort_codes, allowed_group_codes=allowed_group_codes, fallback_group_by=selected_group_codes_context)
        if norm is not None:
            stack.append(norm)

    if not stack:
        clear_inscripcions_sort_context_state(request, context_key)
        return JsonResponse(with_inscripcions_history_payload({"ok": True, "cleared": False, "stack_count": 0, "competition_order_tail": False}, request, competicio.id))

    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    clear_inscripcions_sort_context_state(request, context_key)
    record_inscripcions_history_entry(request, competicio, action_type="sort_clear", action_label="Netejar ordenacions", before_snapshot=before_snapshot, after_snapshot=capture_inscripcions_history_snapshot(request, competicio))
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "cleared": True, "stack_count": 0, "competition_order_tail": False}, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_sort_competition_tail_toggle(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    enabled = _normalize_competition_order_tail_flag(payload.get("enabled"))
    sort_fields = get_available_sort_fields(competicio)
    sort_codes = {field["code"] for field in sort_fields}
    allowed_group_fields = get_allowed_group_fields(competicio)
    allowed_group_codes = {field["code"] for field in allowed_group_fields}
    selected_group_codes_context = _normalize_sort_group_by(payload.get("group_by"), allowed_group_codes, fallback_group_by=competicio.group_by_default or [])
    filters = _normalize_sort_filters(payload.get("filters"))
    context_key = build_inscripcions_sort_context_key(competicio.id, filters=filters, group_by=selected_group_codes_context)

    qs = _build_inscripcions_filtered_qs(competicio, filters)
    current_ids = list(qs.order_by("ordre_sortida", "id").values_list("id", flat=True))
    state = reconcile_inscripcions_sort_context_state(request, context_key, current_ids)
    stack_raw = state.get("stack") if isinstance(state.get("stack"), list) else []
    stack = []
    for item in stack_raw:
        norm = _normalize_sort_criterion(item, sort_codes=sort_codes, allowed_group_codes=allowed_group_codes, fallback_group_by=selected_group_codes_context)
        if norm is not None:
            stack.append(norm)

    if not stack:
        clear_inscripcions_sort_context_state(request, context_key)
        return JsonResponse(with_inscripcions_history_payload({"ok": True, "applied": False, "updated": 0, "stack_count": 0, "competition_order_tail": False, "reason": "no_stack"}, request, competicio.id))

    records = list(_build_sort_records_queryset(qs, [entry.get("sort_key") for entry in stack] + ["grup"], include_competition_order=True))
    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)
    if not records:
        save_inscripcions_sort_context_state(request, context_key, stack=stack, order_sig="", base_ids=[], context_ids=[], competition_order_tail=enabled)
        return JsonResponse(with_inscripcions_history_payload({"ok": True, "applied": True, "updated": 0, "stack_count": len(stack), "competition_order_tail": enabled}, request, competicio.id))

    runtime = _build_sort_application_runtime(competicio, records, [entry.get("sort_key") for entry in stack], stack, include_competition_order=True)
    id_to_record = runtime["id_to_record"]
    application_ids = runtime["application_ids"]
    base_ids_state = state.get("base_ids") if isinstance(state.get("base_ids"), list) else []
    valid_base = len(base_ids_state) == len(application_ids) and set(base_ids_state) == set(application_ids)
    base_ids = list(base_ids_state) if valid_base else list(application_ids)
    final_ids = _apply_sort_pipeline(base_ids, id_to_record, stack, competicio, runtime=runtime, competition_order_tail=enabled)
    updated_count = _persist_inscripcions_order_from_ids(id_to_record, final_ids)
    order_sig = compute_inscripcions_order_signature_from_ids(final_ids)
    save_inscripcions_sort_context_state(request, context_key, stack=stack, order_sig=order_sig, base_ids=base_ids, context_ids=current_ids, competition_order_tail=enabled)
    record_inscripcions_history_entry(request, competicio, action_type="sort_competition_tail_toggle", action_label="Activar ordre de competicio" if enabled else "Desactivar ordre de competicio", before_snapshot=before_snapshot, after_snapshot=capture_inscripcions_history_snapshot(request, competicio))
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "applied": True, "updated": updated_count, "stack_count": len(stack), "competition_order_tail": enabled}, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_filter_values(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    filter_fields = get_available_column_filter_fields(competicio)
    filter_codes = {field["code"] for field in filter_fields}
    filter_label_by_code = {field["code"]: field.get("ui_label") or field.get("label") or field["code"] for field in filter_fields}
    raw_column_code = str(payload.get("column_code") or payload.get("sort_key") or "").strip()
    column_code = LEGACY_SORT_KEY_MAP.get(raw_column_code, raw_column_code)
    if column_code not in filter_codes:
        return HttpResponseBadRequest("column_code invalid")

    filters = _normalize_sort_filters(payload.get("filters"))
    selected_tokens = list(filters.get("column_filters", {}).get(column_code) or [])
    filters_without_self = dict(filters)
    filters_without_self["column_filters"] = dict(filters.get("column_filters") or {})
    filters_without_self["column_filters"].pop(column_code, None)
    qs = _build_inscripcions_filtered_qs(competicio, filters_without_self)
    records = list(_build_sort_records_queryset(qs, [column_code]))
    values = _collect_column_filter_value_rows(records, column_code)

    value_rows = []
    seen = set()
    for row in values:
        token = str(row.get("token") or "").strip()
        if not token:
            continue
        key = _custom_sort_token_key(token)
        seen.add(key)
        value_rows.append({"token": token, "label": row.get("label") or token, "count": int(row.get("count") or 0), "selected": token in selected_tokens})

    for token in selected_tokens:
        key = _custom_sort_token_key(token)
        if not key or key in seen:
            continue
        seen.add(key)
        value_rows.insert(0, {"token": token, "label": "(Sense valor)" if token == COLUMN_FILTER_EMPTY_TOKEN else token, "count": 0, "selected": True})

    return JsonResponse({"ok": True, "column_code": column_code, "column_label": filter_label_by_code.get(column_code, column_code), "values": value_rows, "selected_tokens": selected_tokens, "filters": filters})


@require_POST
@csrf_protect
def inscripcions_sort_custom_values(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    sort_fields = get_available_sort_fields(competicio)
    sort_codes = {field["code"] for field in sort_fields}
    sort_label_by_code = {field["code"]: field.get("ui_label") or field.get("label") or field["code"] for field in sort_fields if isinstance(field, dict) and field.get("code")}
    raw_sort_key = str(payload.get("sort_key") or payload.get("field_code") or "").strip()
    sort_key = LEGACY_SORT_KEY_MAP.get(raw_sort_key, raw_sort_key)
    if sort_key not in sort_codes:
        return HttpResponseBadRequest("sort_key invalid")

    allowed_group_fields = get_allowed_group_fields(competicio)
    allowed_group_codes = {field["code"] for field in allowed_group_fields}
    selected_group_codes_context = _normalize_sort_group_by(payload.get("group_by"), allowed_group_codes, fallback_group_by=competicio.group_by_default or [])
    filters = _normalize_sort_filters(payload.get("filters"))
    context_records = list(_build_sort_records_queryset(_build_inscripcions_filtered_qs(competicio, filters), [sort_key]))
    context_stats = _collect_sort_field_value_stats(context_records, sort_key)
    global_records = list(_build_sort_records_queryset(Inscripcio.objects.filter(competicio=competicio), [sort_key]))
    global_stats = _collect_sort_field_value_stats(global_records, sort_key)
    custom_order_raw = get_competicio_custom_sort_order_values(competicio, sort_key, allowed_sort_codes=sort_codes)
    custom_order, stale_order = _split_custom_sort_tokens(custom_order_raw, global_stats.keys())

    values = []
    seen = set()
    for token in custom_order:
        key = _custom_sort_token_key(token)
        if not key or key in seen:
            continue
        row = context_stats.get(key)
        if row is None:
            continue
        seen.add(key)
        values.append({"value": token, "label": row["label"], "count": row["count"], "detected": True, "in_custom": True})

    remaining = [row for key, row in context_stats.items() if key not in seen]
    remaining.sort(key=lambda row: row["sort_scalar"])
    for row in remaining:
        values.append({"value": row["token"], "label": row["label"], "count": row["count"], "detected": True, "in_custom": False})

    return JsonResponse({"ok": True, "sort_key": sort_key, "sort_label": sort_label_by_code.get(sort_key, sort_key), "custom_order": custom_order, "custom_order_raw": custom_order_raw, "values": values, "stale_values": stale_order, "detected_count": len(context_stats), "context_group_by": selected_group_codes_context, "context_filters": filters})


@require_POST
@csrf_protect
def inscripcions_sort_custom_save(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    sort_fields = get_available_sort_fields(competicio)
    sort_codes = {field["code"] for field in sort_fields}
    raw_sort_key = str(payload.get("sort_key") or payload.get("field_code") or "").strip()
    sort_key = LEGACY_SORT_KEY_MAP.get(raw_sort_key, raw_sort_key)
    if sort_key not in sort_codes:
        return HttpResponseBadRequest("sort_key invalid")

    clear = bool(payload.get("clear"))
    raw_order = payload.get("order")
    if (not clear) and (not isinstance(raw_order, list)):
        return HttpResponseBadRequest("order invalid")

    filters = _normalize_sort_filters(payload.get("filters"))
    allowed_group_fields = get_allowed_group_fields(competicio)
    allowed_group_codes = {field["code"] for field in allowed_group_fields}
    selected_group_codes_context = _normalize_sort_group_by(payload.get("group_by"), allowed_group_codes, fallback_group_by=competicio.group_by_default or [])
    context_key = build_inscripcions_sort_context_key(competicio.id, filters=filters, group_by=selected_group_codes_context)
    preserve_missing_context = bool(payload.get("preserve_missing_context", True))

    context_qs = _build_inscripcions_filtered_qs(competicio, filters)
    context_records = list(_build_sort_records_queryset(context_qs, [sort_key]))
    context_stats = _collect_sort_field_value_stats(context_records, sort_key)
    current_ids = [record.id for record in context_records]
    state = reconcile_inscripcions_sort_context_state(request, context_key, current_ids)
    stack_raw = state.get("stack") if isinstance(state.get("stack"), list) else []
    stack = []
    for item in stack_raw:
        norm = _normalize_sort_criterion(item, sort_codes=sort_codes, allowed_group_codes=allowed_group_codes, fallback_group_by=selected_group_codes_context)
        if norm is not None:
            stack.append(norm)
    competition_order_tail_active = bool(stack) and bool(state.get("competition_order_tail"))

    global_records = list(_build_sort_records_queryset(Inscripcio.objects.filter(competicio=competicio), [sort_key]))
    global_stats = _collect_sort_field_value_stats(global_records, sort_key)
    global_keys = set(global_stats.keys())
    existing_raw = get_competicio_custom_sort_order_values(competicio, sort_key, allowed_sort_codes=sort_codes)
    existing_active, existing_stale = _split_custom_sort_tokens(existing_raw, global_keys)
    before_snapshot = capture_inscripcions_history_snapshot(request, competicio)

    try:
        save_order = raw_order
        dropped_outside_competicio = 0
        preserved_outside_context = 0
        stale_removed = len(existing_stale)
        if not clear:
            incoming = _normalize_custom_sort_order(raw_order)
            incoming_active, _incoming_stale = _split_custom_sort_tokens(incoming, global_keys)
            dropped_outside_competicio = max(0, len(incoming) - len(incoming_active))
            incoming_keys = {_custom_sort_token_key(value) for value in incoming_active}
            if preserve_missing_context and existing_active:
                context_keys = set(context_stats.keys())
                for token in existing_active:
                    key = _custom_sort_token_key(token)
                    if not key or key in incoming_keys or key in context_keys:
                        continue
                    incoming_active.append(token)
                    incoming_keys.add(key)
                    preserved_outside_context += 1
            save_order = incoming_active

        saved_values = set_competicio_custom_sort_order_values(competicio, sort_key, raw_values=save_order, clear=clear, allowed_sort_codes=sort_codes)
    except ValueError:
        return HttpResponseBadRequest("sort_key invalid")

    reapplied = False
    reapplied_updated = 0
    if stack and current_ids and any(entry.get("sort_key") == sort_key and str(entry.get("sort_dir") or "") == "custom" for entry in stack):
        runtime = _build_sort_application_runtime(competicio, context_records, [entry.get("sort_key") for entry in stack] + [sort_key], stack, include_competition_order=competition_order_tail_active)
        id_to_record = runtime["id_to_record"]
        application_ids = runtime["application_ids"]
        base_ids_state = state.get("base_ids") if isinstance(state.get("base_ids"), list) else []
        valid_base = len(base_ids_state) == len(application_ids) and set(base_ids_state) == set(application_ids)
        base_ids = list(base_ids_state) if valid_base else list(application_ids)
        final_ids = _apply_sort_pipeline(base_ids, id_to_record, stack, competicio, runtime=runtime, competition_order_tail=competition_order_tail_active)
        reapplied_updated = _persist_inscripcions_order_from_ids(id_to_record, final_ids)
        order_sig = compute_inscripcions_order_signature_from_ids(final_ids)
        save_inscripcions_sort_context_state(request, context_key, stack=stack, order_sig=order_sig, base_ids=base_ids, context_ids=current_ids, competition_order_tail=competition_order_tail_active)
        reapplied = True

    record_inscripcions_history_entry(request, competicio, action_type="sort_custom_save", action_label="Desar ordre personalitzat", before_snapshot=before_snapshot, after_snapshot=capture_inscripcions_history_snapshot(request, competicio))
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "sort_key": sort_key, "custom_order": saved_values, "custom_active": bool(saved_values), "stale_removed": stale_removed if not clear else 0, "dropped_outside_competicio": dropped_outside_competicio if not clear else 0, "preserved_outside_context": preserved_outside_context if not clear else 0, "reapplied": reapplied, "reapplied_updated": reapplied_updated, "stack_count": len(stack), "competition_order_tail": competition_order_tail_active}, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_history_undo(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    entry = _perform_inscripcions_history_step(request, competicio, "undo")
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "applied": bool(entry), "direction": "undo", "action_type": str(entry.get("action_type") or "") if isinstance(entry, dict) else "", "action_label": str(entry.get("action_label") or "") if isinstance(entry, dict) else ""}, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_history_redo(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    entry = _perform_inscripcions_history_step(request, competicio, "redo")
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "applied": bool(entry), "direction": "redo", "action_type": str(entry.get("action_type") or "") if isinstance(entry, dict) else "", "action_label": str(entry.get("action_label") or "") if isinstance(entry, dict) else ""}, request, competicio.id))


@require_POST
@csrf_protect
def inscripcions_sort_undo(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    entry = _perform_inscripcions_history_step(request, competicio, "undo")
    return JsonResponse(with_inscripcions_history_payload({"ok": True, "restored": 1 if entry else 0, "applied": bool(entry), "direction": "undo", "action_type": str(entry.get("action_type") or "") if isinstance(entry, dict) else "", "action_label": str(entry.get("action_label") or "") if isinstance(entry, dict) else ""}, request, competicio.id))


__all__ = [
    "inscripcions_filter_values",
    "inscripcions_history_redo",
    "inscripcions_history_undo",
    "inscripcions_sort_apply",
    "inscripcions_sort_clear",
    "inscripcions_sort_competition_tail_toggle",
    "inscripcions_sort_custom_save",
    "inscripcions_sort_custom_values",
    "inscripcions_sort_remove",
    "inscripcions_sort_undo",
]
