import hashlib
import json
from collections import OrderedDict
from datetime import date, datetime

from django.db.models import Q

from ...models import Inscripcio
from ...models.rotacions import RotacioAssignacio
from ..shared.birth_year_ranges import (
    BIRTH_YEAR_RANGE_PARTITION_CODE,
    birth_year_range_partition_expression,
    birth_year_range_partition_value,
    get_cached_inscripcions_derived_group_config,
    get_inscripcions_derived_group_config,
)
from ..shared.competition_groups import get_group_maps, group_label, normalize_positive_int
from ..teams.equip_contexts import (
    NATIVE_EQUIP_CONTEXT_CODE,
    get_contextual_assignment_map,
    resolve_inscripcio_equip,
)
from .shared import INSCRIPCIONS_SORT_STACK_SESSION_KEY


BUILTIN_SORT_FIELDS = [
    {"code": "nom_i_cognoms", "label": "Nom (A-Z)", "kind": "builtin"},
    {"code": "data_naixement", "label": "Edat / Data naixement", "kind": "builtin"},
    {"code": "document", "label": "Document", "kind": "builtin"},
    {"code": "sexe", "label": "Sexe", "kind": "builtin"},
    {"code": "entitat", "label": "Entitat", "kind": "builtin"},
    {"code": "categoria", "label": "Categoria", "kind": "builtin"},
    {"code": "subcategoria", "label": "Subcategoria", "kind": "builtin"},
    {"code": "grup", "label": "Grup", "kind": "builtin"},
    {"code": "equip", "label": "Equip", "kind": "builtin"},
]

BUILTIN_COLUMN_FILTER_FIELDS = [
    {"code": "nom_i_cognoms", "label": "Nom i cognoms", "kind": "builtin"},
    {"code": "document", "label": "Document", "kind": "builtin"},
    {"code": "sexe", "label": "Sexe", "kind": "builtin"},
    {"code": "data_naixement", "label": "Data naixement", "kind": "builtin"},
    {"code": "entitat", "label": "Entitat", "kind": "builtin"},
    {"code": "categoria", "label": "Categoria", "kind": "builtin"},
    {"code": "subcategoria", "label": "Subcategoria", "kind": "builtin"},
    {"code": "grup", "label": "Grup", "kind": "builtin"},
    {"code": "equip", "label": "Equip", "kind": "builtin"},
    {"code": "ordre_sortida", "label": "Ordre", "kind": "builtin"},
]

BUILTIN_GROUP_FIELDS = [
    {"code": "categoria", "label": "Categoria", "kind": "builtin"},
    {"code": "subcategoria", "label": "Subcategoria", "kind": "builtin"},
    {"code": "entitat", "label": "Entitat", "kind": "builtin"},
    {"code": "sexe", "label": "Sexe", "kind": "builtin"},
    {"code": "data_naixement", "label": "Data naixement", "kind": "builtin"},
    {"code": "any_naixement_forquilla", "label": "Forquilla data naixement", "kind": "derived"},
    {"code": "document", "label": "Document", "kind": "builtin"},
]

COLUMN_FILTER_EMPTY_TOKEN = "__EMPTY__"
LEGACY_SORT_KEY_MAP = {
    "nom": "nom_i_cognoms",
    "edat": "data_naixement",
}

GROUP_NAME_SUGGESTION_IGNORED_LABELS = {
    "",
    "Sense bloc",
    "Totes les inscripcions filtrades",
    "(Sense valor)",
}
GROUP_NAME_COMPONENT_FIELD_ORDER = ("categoria", "subcategoria", "entitat")
GROUP_NAME_FILTER_MULTI_KEYS = {
    "categoria": "categories",
    "subcategoria": "subcategories",
    "entitat": "entitats",
}
MAX_GROUP_NAME_VALUES_PER_FIELD = 3


def _reserved_inscripcio_codes():
    out = set()
    for field in Inscripcio._meta.concrete_fields:
        name = str(getattr(field, "name", "") or "").strip()
        attname = str(getattr(field, "attname", "") or "").strip()
        if name:
            out.add(name)
        if attname:
            out.add(attname)
    return out


def _normalize_schema_extra_code(code: str, reserved_codes=None):
    code = str(code or "").strip()
    if not code:
        return code
    if code.startswith("excel__"):
        return code
    reserved = reserved_codes if reserved_codes is not None else _reserved_inscripcio_codes()
    if code in reserved:
        return f"excel__{code}"
    return code


def _excel_schema_codes(competicio):
    schema = competicio.inscripcions_schema or {}
    cols = schema.get("columns") or []
    if not isinstance(cols, list):
        return set()
    reserved = _reserved_inscripcio_codes()
    out = set()
    for col in cols:
        if not isinstance(col, dict):
            continue
        code = col.get("code")
        if not code:
            continue
        if (col.get("kind") or "extra") == "extra":
            code = _normalize_schema_extra_code(code, reserved)
        out.add(code)
    return out


def _label_with_source(label: str, source: str):
    if source == "excel":
        suffix = "Excel"
    elif source == "derived":
        suffix = "Derivada"
    else:
        suffix = "Nativa"
    return f"{label} ({suffix})"


def _s(value):
    return "(Sense valor)" if value in (None, "") else str(value)


def _norm_val(value):
    return "__NULL__" if value in (None, "") else str(value)


def _resolve_base_equip_for_inscripcio(obj, assignment_map=None):
    if obj is None:
        return None
    if assignment_map is None and getattr(obj, "_base_equip_cache_ready", False):
        return getattr(obj, "_base_equip_cache", None)
    equip = resolve_inscripcio_equip(
        obj,
        context_code=NATIVE_EQUIP_CONTEXT_CODE,
        fallback=None,
        assignment_map=assignment_map,
    )
    try:
        obj._base_equip_cache = equip
        obj._base_equip_cache_ready = True
        obj._base_equip_id_cache = getattr(equip, "id", None)
        obj._base_equip_name_cache = str(getattr(equip, "nom", "") or "").strip()
    except Exception:
        pass
    return equip


def _attach_base_equip_runtime(records):
    rows = list(records or [])
    if not rows:
        return {}
    competicio = next((getattr(obj, "competicio", None) for obj in rows if getattr(obj, "competicio", None) is not None), None)
    if competicio is None:
        return {}
    assignment_map = get_contextual_assignment_map(competicio, rows, NATIVE_EQUIP_CONTEXT_CODE)
    for obj in rows:
        equip = None
        row = assignment_map.get(getattr(obj, "id", None))
        if row is not None:
            equip = getattr(row, "equip", None)
        try:
            obj._base_equip_cache = equip
            obj._base_equip_cache_ready = True
            obj._base_equip_id_cache = getattr(equip, "id", None)
            obj._base_equip_name_cache = str(getattr(equip, "nom", "") or "").strip()
        except Exception:
            pass
    return assignment_map


def get_inscripcio_value(obj, code: str):
    extra = getattr(obj, "extra", None) or {}
    if code == BIRTH_YEAR_RANGE_PARTITION_CODE:
        annotated_value = getattr(obj, f"_derived_{BIRTH_YEAR_RANGE_PARTITION_CODE}", None)
        if annotated_value not in (None, ""):
            return annotated_value
        derived_cfg = getattr(obj, "_inscripcions_derived_group_config", None)
        if not isinstance(derived_cfg, dict):
            fields_cache = getattr(getattr(obj, "_state", None), "fields_cache", {}) or {}
            competicio = fields_cache.get("competicio")
            if competicio is not None:
                derived_cfg = get_inscripcions_derived_group_config(getattr(competicio, "inscripcions_view", None))
            else:
                derived_cfg = get_cached_inscripcions_derived_group_config(getattr(obj, "competicio_id", None))
        return birth_year_range_partition_value(
            obj,
            (derived_cfg or {}).get(BIRTH_YEAR_RANGE_PARTITION_CODE),
            empty_if_unconfigured=True,
        )
    if code == "equip":
        equip = _resolve_base_equip_for_inscripcio(obj)
        return getattr(equip, "nom", None)
    if isinstance(extra, dict) and isinstance(code, str) and code.startswith("excel__"):
        if code in extra:
            return extra.get(code)
        legacy_code = code[len("excel__") :]
        if legacy_code in extra:
            return extra.get(legacy_code)
    if hasattr(obj, code):
        return getattr(obj, code)
    if isinstance(extra, dict) and code in extra:
        return extra.get(code)
    return extra.get(code)


def annotate_birth_year_range_partition_queryset(qs, competicio, *, alias=None):
    alias = str(alias or f"_derived_{BIRTH_YEAR_RANGE_PARTITION_CODE}").strip() or f"_derived_{BIRTH_YEAR_RANGE_PARTITION_CODE}"
    if qs is None or competicio is None:
        return qs
    derived_cfg = get_inscripcions_derived_group_config(getattr(competicio, "inscripcions_view", None))
    partition_cfg = (derived_cfg or {}).get(BIRTH_YEAR_RANGE_PARTITION_CODE)
    if not isinstance(partition_cfg, dict) or not (partition_cfg.get("ranges") or []):
        return qs
    return qs.annotate(**{alias: birth_year_range_partition_expression(partition_cfg)})


def annotate_inscripcions_queryset_for_group_codes(qs, competicio, group_codes):
    codes = {str(code or "").strip() for code in (group_codes or []) if str(code or "").strip()}
    if BIRTH_YEAR_RANGE_PARTITION_CODE in codes:
        qs = annotate_birth_year_range_partition_queryset(qs, competicio)
    return qs


def get_allowed_group_fields(competicio):
    out = []
    seen = set()
    excel_codes = _excel_schema_codes(competicio)
    reserved = _reserved_inscripcio_codes()
    for field in BUILTIN_GROUP_FIELDS:
        if field["code"] in seen:
            continue
        source = "derived" if field.get("kind") == "derived" else ("excel" if field["code"] in excel_codes else "native")
        out.append({**field, "source": source, "ui_label": _label_with_source(field["label"], source)})
        seen.add(field["code"])
    schema = competicio.inscripcions_schema or {}
    cols = schema.get("columns") or []
    if isinstance(cols, list):
        for col in cols:
            if not isinstance(col, dict):
                continue
            code = col.get("code")
            if not code or (col.get("kind") or "extra") != "extra":
                continue
            code = _normalize_schema_extra_code(code, reserved)
            if code in seen:
                continue
            label = col.get("label") or code
            out.append({"code": code, "label": label, "kind": "extra", "source": "excel", "ui_label": _label_with_source(label, "excel")})
            seen.add(code)
    return out


def get_available_sort_fields(competicio):
    out = []
    seen = set()
    excel_codes = _excel_schema_codes(competicio)
    reserved = _reserved_inscripcio_codes()
    for field in BUILTIN_SORT_FIELDS:
        if field["code"] in seen:
            continue
        source = "excel" if field["code"] in excel_codes else "native"
        out.append({**field, "source": source, "ui_label": _label_with_source(field["label"], source)})
        seen.add(field["code"])
    schema = competicio.inscripcions_schema or {}
    cols = schema.get("columns") or []
    if isinstance(cols, list):
        for col in cols:
            if not isinstance(col, dict):
                continue
            code = col.get("code")
            if not code or code in seen or (col.get("kind") or "extra") != "extra":
                continue
            code = _normalize_schema_extra_code(code, reserved)
            if code in seen:
                continue
            label = col.get("label") or code
            out.append({"code": code, "label": label, "kind": "extra", "source": "excel", "ui_label": _label_with_source(label, "excel")})
            seen.add(code)
    return out


def get_available_column_filter_fields(competicio):
    out = []
    seen = set()
    excel_codes = _excel_schema_codes(competicio)
    reserved = _reserved_inscripcio_codes()
    for field in BUILTIN_COLUMN_FILTER_FIELDS:
        if field["code"] in seen:
            continue
        source = "excel" if field["code"] in excel_codes else "native"
        out.append({**field, "source": source, "ui_label": _label_with_source(field["label"], source)})
        seen.add(field["code"])
    schema = competicio.inscripcions_schema or {}
    cols = schema.get("columns") or []
    if isinstance(cols, list):
        for col in cols:
            if not isinstance(col, dict):
                continue
            code = col.get("code")
            if not code or (col.get("kind") or "extra") != "extra":
                continue
            code = _normalize_schema_extra_code(code, reserved)
            if code in seen:
                continue
            label = col.get("label") or code
            out.append({"code": code, "label": label, "kind": "extra", "source": "excel", "ui_label": _label_with_source(label, "excel")})
            seen.add(code)
    return out


def _normalize_custom_sort_token(value):
    if value in (None, ""):
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value).strip()


def _custom_sort_token_key(value):
    token = str(value or "").strip()
    return token.casefold()


def _normalize_column_filter_tokens(raw_tokens):
    out = []
    seen = set()
    values = raw_tokens if isinstance(raw_tokens, list) else [raw_tokens]
    for raw in values:
        token = str(raw or "").strip()
        if not token:
            continue
        key = _custom_sort_token_key(token)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(token)
    out.sort(key=_custom_sort_token_key)
    return out


def _normalize_column_filters(raw_column_filters, allowed_filter_codes=None):
    raw = raw_column_filters if isinstance(raw_column_filters, dict) else {}
    allowed = set(allowed_filter_codes or [])
    restrict = bool(allowed)
    out = {}
    for raw_code, raw_tokens in raw.items():
        if not isinstance(raw_code, str):
            continue
        code = LEGACY_SORT_KEY_MAP.get(raw_code.strip(), raw_code.strip())
        if not code:
            continue
        if restrict and code not in allowed:
            continue
        tokens = _normalize_column_filter_tokens(raw_tokens)
        if tokens:
            out[code] = tokens
    return out


def get_request_column_filters(request, competicio=None):
    allowed_codes = None
    if competicio is not None:
        allowed_codes = {field["code"] for field in get_available_column_filter_fields(competicio)}
    collected = {}
    for key, values in request.GET.lists():
        if not isinstance(key, str):
            continue
        raw_code = ""
        if key.startswith("cf__"):
            raw_code = key[4:].strip()
        elif key.startswith("cf_"):
            raw_code = key[3:].strip()
        else:
            continue
        code = LEGACY_SORT_KEY_MAP.get(raw_code, raw_code)
        if not code:
            continue
        if allowed_codes is not None and code not in allowed_codes:
            continue
        tokens = _normalize_column_filter_tokens(values)
        if tokens:
            collected[code] = tokens
    return collected


def get_request_inscripcio_filters(request, competicio=None):
    return {
        "q": str(request.GET.get("q") or "").strip(),
        "categoria": str(request.GET.get("categoria") or "").strip(),
        "subcategoria": str(request.GET.get("subcategoria") or "").strip(),
        "entitat": str(request.GET.get("entitat") or "").strip(),
        "column_filters": get_request_column_filters(request, competicio=competicio),
    }


def _normalize_custom_sort_order(raw_values):
    out = []
    seen = set()
    if not isinstance(raw_values, list):
        return out
    for raw in raw_values:
        token = _normalize_custom_sort_token(raw)
        if not token:
            continue
        key = _custom_sort_token_key(token)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _get_custom_sort_orders_map(competicio):
    cfg = competicio.inscripcions_view or {}
    raw = cfg.get("custom_sort_orders")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for raw_code, raw_values in raw.items():
        if not isinstance(raw_code, str):
            continue
        code = LEGACY_SORT_KEY_MAP.get(raw_code.strip(), raw_code.strip())
        if not code:
            continue
        values = _normalize_custom_sort_order(raw_values)
        if values:
            out[code] = values
    return out


def get_competicio_custom_sort_order_values(competicio, sort_code, allowed_sort_codes=None):
    code_raw = str(sort_code or "").strip()
    code = LEGACY_SORT_KEY_MAP.get(code_raw, code_raw)
    if not code:
        return []
    if allowed_sort_codes is not None and code not in set(allowed_sort_codes):
        return []
    return list((_get_custom_sort_orders_map(competicio)).get(code) or [])


def get_competicio_custom_sort_rank_map(competicio, sort_code, allowed_sort_codes=None):
    values = get_competicio_custom_sort_order_values(competicio, sort_code, allowed_sort_codes=allowed_sort_codes)
    out = {}
    for idx, token in enumerate(values):
        key = _custom_sort_token_key(token)
        if key and key not in out:
            out[key] = idx
    return out


def get_competicio_custom_sort_codes(competicio, allowed_sort_codes=None):
    data = _get_custom_sort_orders_map(competicio)
    if allowed_sort_codes is None:
        return sorted(data.keys())
    allowed = set(allowed_sort_codes)
    return sorted([code for code in data.keys() if code in allowed])


def _sort_scalar(value):
    if isinstance(value, (int, float)):
        return (0, float(value))
    if isinstance(value, (date, datetime)):
        return (1, value.isoformat())
    return (2, str(value).casefold())


def _build_sort_field_runtime_context(records, sort_code):
    code = str(sort_code or "").strip()
    if code == "equip":
        return {"base_assignment_map": _attach_base_equip_runtime(records)}
    if code != "grup":
        return {}
    competicio_id = None
    for obj in records or []:
        competicio_id = getattr(obj, "competicio_id", None)
        if competicio_id:
            break
    if not competicio_id:
        return {}
    return {"group_maps": get_group_maps(competicio_id)}


def _resolve_sort_field_runtime(obj, sort_code, context=None):
    code = str(sort_code or "").strip()
    ctx = context if isinstance(context, dict) else {}
    raw_value = get_inscripcio_value(obj, code)
    if code == "grup":
        group = getattr(obj, "grup_competicio", None)
        display_num = normalize_positive_int(getattr(obj, "grup", None))
        if not display_num and group is not None:
            display_num = normalize_positive_int(getattr(group, "display_num", None))
        if group is None and display_num:
            group = ((ctx.get("group_maps") or {}).get("by_display_num") or {}).get(display_num)
        token = str(display_num) if display_num else ""
        group_name = str(getattr(group, "nom", "") or "").strip() if group is not None else ""
        label = group_name or (f"Grup {display_num}" if display_num else "")
        return {
            "raw_value": display_num,
            "token": token,
            "label": label,
            "sort_scalar": _sort_scalar(display_num if display_num is not None else ""),
        }
    if code == "equip":
        equip = _resolve_base_equip_for_inscripcio(obj, assignment_map=ctx.get("base_assignment_map"))
        equip_id = getattr(equip, "id", None)
        equip_name = str(getattr(equip, "nom", "") or "").strip() if equip is not None else ""
        token = str(equip_id) if equip_id else ""
        label = equip_name or (f"Equip {equip_id}" if equip_id else "")
        return {
            "raw_value": equip_name,
            "token": token,
            "label": label,
            "sort_scalar": _sort_scalar(equip_name),
        }
    token = _normalize_custom_sort_token(raw_value)
    return {
        "raw_value": raw_value,
        "token": token,
        "label": _s(raw_value) if token else "",
        "sort_scalar": _sort_scalar(raw_value),
    }


def _build_sort_records_queryset(qs, sort_codes=None, include_competition_order=False):
    codes = []
    seen_codes = set()
    for raw_code in sort_codes or []:
        code = str(raw_code or "").strip()
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        codes.append(code)
    select_related_fields = []
    only_fields = ["id", "competicio_id", "extra", "ordre_sortida"]
    if include_competition_order:
        only_fields.extend(["grup", "ordre_competicio"])
    for code in codes:
        if code == "grup":
            select_related_fields.append("grup_competicio")
            only_fields.extend(["grup", "grup_competicio_id", "grup_competicio__display_num", "grup_competicio__nom"])
            continue
        if code == "equip":
            continue
        if hasattr(Inscripcio, code):
            only_fields.append(code)
    qs_out = qs
    if select_related_fields:
        qs_out = qs_out.select_related(*list(dict.fromkeys(select_related_fields)))
    if only_fields:
        qs_out = qs_out.only(*list(dict.fromkeys(only_fields)))
    return qs_out.order_by("ordre_sortida", "id")


def _normalize_sort_filters(raw_filters):
    data = raw_filters if isinstance(raw_filters, dict) else {}

    def _normalize_string_list(raw_values):
        out = []
        values = raw_values if isinstance(raw_values, list) else []
        for value in values:
            text = str(value or "").strip()
            if text and text not in out:
                out.append(text)
        return out

    return {
        "q": str(data.get("q") or "").strip(),
        "categoria": str(data.get("categoria") or "").strip(),
        "subcategoria": str(data.get("subcategoria") or "").strip(),
        "entitat": str(data.get("entitat") or "").strip(),
        "categories": _normalize_string_list(data.get("categories")),
        "subcategories": _normalize_string_list(data.get("subcategories")),
        "entitats": _normalize_string_list(data.get("entitats")),
        "column_filters": _normalize_column_filters(data.get("column_filters")),
    }


def _normalize_sort_group_by(raw_group_by, allowed_group_codes, fallback_group_by=None):
    out = []
    if isinstance(raw_group_by, list):
        for value in raw_group_by:
            if isinstance(value, str) and value in allowed_group_codes and value not in out:
                out.append(value)
    if out:
        return out
    fallback = fallback_group_by if isinstance(fallback_group_by, list) else []
    return [group for group in fallback if group in allowed_group_codes]


def build_inscripcions_sort_context_key(competicio_id, filters=None, group_by=None):
    clean_filters = _normalize_sort_filters(filters)
    clean_group_by = []
    if isinstance(group_by, list):
        for group in group_by:
            if isinstance(group, str) and group not in clean_group_by:
                clean_group_by.append(group)
    parts = [
        str(competicio_id),
        clean_filters["q"],
        clean_filters["categoria"],
        clean_filters["subcategoria"],
        clean_filters["entitat"],
        json.dumps(clean_filters.get("categories") or [], ensure_ascii=False),
        json.dumps(clean_filters.get("subcategories") or [], ensure_ascii=False),
        json.dumps(clean_filters.get("entitats") or [], ensure_ascii=False),
        json.dumps(clean_filters["column_filters"], ensure_ascii=False, sort_keys=True),
        "|".join(clean_group_by),
    ]
    return "||".join(parts)


def compute_inscripcions_order_signature_from_ids(ids):
    digest = hashlib.sha1()
    for ins_id in ids:
        digest.update(str(ins_id).encode("utf-8"))
        digest.update(b",")
    return digest.hexdigest()


def _read_sort_stack_store(request):
    raw = request.session.get(INSCRIPCIONS_SORT_STACK_SESSION_KEY)
    if not isinstance(raw, dict):
        return {}
    return raw


def _write_sort_stack_store(request, store):
    request.session[INSCRIPCIONS_SORT_STACK_SESSION_KEY] = store
    request.session.modified = True


def get_inscripcions_sort_context_state(request, context_key):
    empty = {
        "stack": [],
        "order_sig": "",
        "base_ids": [],
        "context_ids": [],
        "competition_order_tail": False,
        "competition_order_tail_explicit": False,
    }
    if not context_key:
        return dict(empty)
    state = _read_sort_stack_store(request).get(context_key)
    if not isinstance(state, dict):
        return dict(empty)
    stack = state.get("stack") if isinstance(state.get("stack"), list) else []
    order_sig = state.get("order_sig") if isinstance(state.get("order_sig"), str) else ""
    base_ids = state.get("base_ids") if isinstance(state.get("base_ids"), list) else []
    context_ids = state.get("context_ids") if isinstance(state.get("context_ids"), list) else []
    explicit = "competition_order_tail" in state
    competition_order_tail = bool(state.get("competition_order_tail")) if explicit else bool(stack)
    return {
        "stack": stack,
        "order_sig": order_sig,
        "base_ids": base_ids,
        "context_ids": context_ids,
        "competition_order_tail": competition_order_tail,
        "competition_order_tail_explicit": explicit,
    }


def save_inscripcions_sort_context_state(
    request,
    context_key,
    stack=None,
    order_sig=None,
    base_ids=None,
    context_ids=None,
    competition_order_tail=None,
):
    if not context_key:
        return
    store = _read_sort_stack_store(request)
    state = store.get(context_key)
    if not isinstance(state, dict):
        state = {}
    if stack is not None:
        state["stack"] = stack
    if order_sig is not None:
        state["order_sig"] = order_sig
    if base_ids is not None:
        state["base_ids"] = base_ids
    if context_ids is not None:
        state["context_ids"] = context_ids
    if competition_order_tail is not None:
        state["competition_order_tail"] = bool(competition_order_tail)
    if not state.get("stack"):
        store.pop(context_key, None)
    else:
        store[context_key] = state
    _write_sort_stack_store(request, store)


def clear_inscripcions_sort_context_state(request, context_key):
    save_inscripcions_sort_context_state(request, context_key, stack=[], order_sig="")


def reconcile_inscripcions_sort_context_state(request, context_key, current_ids, current_base_ids=None):
    state = get_inscripcions_sort_context_state(request, context_key)
    stack = state.get("stack") if isinstance(state.get("stack"), list) else []
    if not stack:
        return {
            "stack": [],
            "order_sig": "",
            "base_ids": [],
            "context_ids": [],
            "competition_order_tail": False,
            "competition_order_tail_explicit": False,
        }
    current_ids_list = list(current_ids or [])
    current_base_ids_list = list(current_base_ids or current_ids_list)
    current_sig = compute_inscripcions_order_signature_from_ids(current_base_ids_list)
    saved_sig = str(state.get("order_sig") or "")
    context_ids_state = state.get("context_ids") if isinstance(state.get("context_ids"), list) else []
    if not context_ids_state:
        context_ids_state = state.get("base_ids") if isinstance(state.get("base_ids"), list) else []
    if (not saved_sig) or saved_sig == current_sig:
        return {
            "stack": stack,
            "order_sig": saved_sig if saved_sig else current_sig,
            "base_ids": state.get("base_ids") if isinstance(state.get("base_ids"), list) else [],
            "context_ids": context_ids_state,
            "competition_order_tail": bool(state.get("competition_order_tail")),
            "competition_order_tail_explicit": bool(state.get("competition_order_tail_explicit")),
        }
    same_set = len(context_ids_state) == len(current_ids_list) and set(context_ids_state) == set(current_ids_list)
    if same_set:
        save_inscripcions_sort_context_state(
            request,
            context_key,
            stack=stack,
            order_sig=current_sig,
            base_ids=current_base_ids_list,
            context_ids=current_ids_list,
            competition_order_tail=state.get("competition_order_tail"),
        )
        return {
            "stack": stack,
            "order_sig": current_sig,
            "base_ids": current_base_ids_list,
            "context_ids": current_ids_list,
            "competition_order_tail": bool(state.get("competition_order_tail")),
            "competition_order_tail_explicit": bool(state.get("competition_order_tail_explicit")),
        }
    clear_inscripcions_sort_context_state(request, context_key)
    return {
        "stack": [],
        "order_sig": "",
        "base_ids": [],
        "context_ids": [],
        "competition_order_tail": False,
        "competition_order_tail_explicit": False,
    }


def _build_inscripcions_filtered_qs(competicio, filters):
    clean_filters = _normalize_sort_filters(filters)
    allowed_filter_codes = {field["code"] for field in get_available_column_filter_fields(competicio)}
    column_filters = _normalize_column_filters(clean_filters.get("column_filters"), allowed_filter_codes=allowed_filter_codes)
    qs = Inscripcio.objects.filter(competicio=competicio)
    subcategories = list(clean_filters.get("subcategories") or [])
    entitats = list(clean_filters.get("entitats") or [])
    categories = list(clean_filters.get("categories") or [])
    if subcategories:
        qs = qs.filter(subcategoria__in=subcategories)
    elif clean_filters["subcategoria"]:
        qs = qs.filter(subcategoria__iexact=clean_filters["subcategoria"])
    if entitats:
        qs = qs.filter(entitat__in=entitats)
    elif clean_filters["entitat"]:
        qs = qs.filter(entitat__icontains=clean_filters["entitat"])
    if clean_filters["q"]:
        q = clean_filters["q"]
        qs = qs.filter(Q(nom_i_cognoms__icontains=q) | Q(document__icontains=q) | Q(entitat__icontains=q))
    if categories:
        qs = qs.filter(categoria__in=categories)
    elif clean_filters["categoria"]:
        qs = qs.filter(categoria__iexact=clean_filters["categoria"])
    if not column_filters:
        return qs
    filter_codes = list(column_filters.keys())
    records = list(_build_sort_records_queryset(qs, filter_codes))
    if not records:
        return qs.none()
    runtime_contexts = {code: _build_sort_field_runtime_context(records, code) for code in filter_codes}
    matching_ids = []
    for obj in records:
        matches_all = True
        for code, tokens in column_filters.items():
            runtime = _resolve_sort_field_runtime(obj, code, context=runtime_contexts.get(code))
            token = runtime.get("token") or ""
            if token:
                if token not in tokens:
                    matches_all = False
                    break
            elif COLUMN_FILTER_EMPTY_TOKEN not in tokens:
                matches_all = False
                break
        if matches_all:
            matching_ids.append(obj.id)
    if not matching_ids:
        return qs.none()
    return qs.filter(id__in=matching_ids)


def _normalize_sort_criterion(raw, sort_codes, allowed_group_codes, fallback_group_by=None):
    if not isinstance(raw, dict):
        return None
    sort_key_raw = str(raw.get("sort_key") or "").strip()
    sort_key = LEGACY_SORT_KEY_MAP.get(sort_key_raw, sort_key_raw)
    if sort_key not in sort_codes:
        return None
    sort_dir = str(raw.get("sort_dir") or "asc").strip()
    if sort_dir not in ("asc", "desc", "arrow_asc", "arrow_desc", "custom"):
        sort_dir = "asc"
    scope = str(raw.get("scope") or "all").strip().lower()
    if scope not in ("all", "tab", "all_groups", "group"):
        scope = "all"
    group_num = None
    if scope == "group":
        try:
            group_num = int(raw.get("group_num"))
        except Exception:
            return None
        if group_num <= 0:
            return None
    group_by = _normalize_sort_group_by(raw.get("group_by"), allowed_group_codes, fallback_group_by=fallback_group_by or [])
    return {
        "sort_key": sort_key,
        "sort_dir": sort_dir,
        "scope": scope,
        "group_num": group_num,
        "group_by": group_by,
    }


def _extract_sort_partition_codes(stack):
    out = []
    seen = set()
    for criterion in stack:
        if not isinstance(criterion, dict):
            continue
        scope = str(criterion.get("scope") or "all").strip().lower()
        if scope not in ("all", "tab"):
            continue
        code = str(criterion.get("sort_key") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _clean_group_suggestion_label(raw_label):
    label = str(raw_label or "").strip()
    if not label or label in GROUP_NAME_SUGGESTION_IGNORED_LABELS:
        return ""
    return label


def _group_name_field_code(raw_code):
    code = str(raw_code or "").strip()
    return code if code in GROUP_NAME_COMPONENT_FIELD_ORDER else ""


def _build_group_name_source(*, kind="", key="", label="", field_code="", value_label="", origin_scope="bucket"):
    clean_label = _clean_group_suggestion_label(value_label or label)
    if not clean_label:
        return None
    normalized_field_code = _group_name_field_code(field_code)
    clean_kind = str(kind or "").strip().lower()
    clean_key = str(key or clean_label).strip() or clean_label
    clean_origin_scope = str(origin_scope or "bucket").strip().lower() or "bucket"
    return {
        "kind": clean_kind,
        "key": clean_key,
        "label": str(label or clean_label).strip() or clean_label,
        "field_code": normalized_field_code,
        "value_label": clean_label,
        "origin_scope": clean_origin_scope,
    }


def _source_values_from_normalized_filters(filters, field_code):
    data = filters if isinstance(filters, dict) else {}
    out = []
    single_value = _clean_group_suggestion_label(data.get(field_code))
    if single_value and single_value not in out:
        out.append(single_value)
    multi_key = GROUP_NAME_FILTER_MULTI_KEYS.get(field_code, "")
    raw_values = data.get(multi_key) if multi_key else []
    if isinstance(raw_values, list):
        for raw_value in raw_values:
            label = _clean_group_suggestion_label(raw_value)
            if label and label not in out:
                out.append(label)
    return out


def _build_group_name_filter_sources(main_filters=None, workspace_filters=None):
    out = []
    main_data = main_filters if isinstance(main_filters, dict) else {}
    workspace_data = workspace_filters if isinstance(workspace_filters, dict) else {}
    for field_code in GROUP_NAME_COMPONENT_FIELD_ORDER:
        workspace_values = _source_values_from_normalized_filters(workspace_data, field_code)
        main_values = _source_values_from_normalized_filters(main_data, field_code)
        active_values = workspace_values or main_values
        origin_scope = "workspace_filter" if workspace_values else ("main_filter" if main_values else "")
        if not origin_scope:
            continue
        for label in active_values:
            source = _build_group_name_source(
                kind="filter",
                key=f"{origin_scope}:{field_code}:{label}",
                label=label,
                field_code=field_code,
                value_label=label,
                origin_scope=origin_scope,
            )
            if source is not None:
                out.append(source)
    return out


def _render_group_name_values(values):
    rows = list(values or [])
    if not rows:
        return ""
    labels = [str(row.get("label") or "").strip() for row in rows[:MAX_GROUP_NAME_VALUES_PER_FIELD] if str(row.get("label") or "").strip()]
    remaining = max(0, len(rows) - len(labels))
    if remaining > 0:
        labels.append(f"{remaining} més")
    return " + ".join(labels)


def _normalize_bucket_source_entries(raw_sources, default_kind="", default_origin_scope="bucket"):
    if isinstance(raw_sources, dict):
        raw_sources = [raw_sources]
    out = []
    seen = set()
    for row in raw_sources or []:
        if not isinstance(row, dict):
            continue
        source = _build_group_name_source(
            kind=row.get("kind") or default_kind,
            key=row.get("key"),
            label=row.get("label"),
            field_code=row.get("field_code"),
            value_label=row.get("value_label"),
            origin_scope=row.get("origin_scope") or default_origin_scope,
        )
        if source is None:
            continue
        ident = (
            source["kind"],
            source["key"],
            source["label"],
            source["field_code"],
            source["value_label"],
            source["origin_scope"],
        )
        if ident in seen:
            continue
        seen.add(ident)
        out.append(source)
    return out


def _extract_group_name_components_from_row(row):
    components = _normalize_bucket_source_entries(row.get("components"), default_origin_scope="bucket")
    if components:
        return components
    fallback = []
    labels_by_kind = row.get("labels_by_kind")
    if isinstance(labels_by_kind, dict):
        for kind in ("tabs", "sort", ""):
            raw_labels = labels_by_kind.get(kind) or []
            if not isinstance(raw_labels, list):
                continue
            for label_order, raw_label in enumerate(raw_labels):
                source = _build_group_name_source(
                    kind=kind,
                    key=f"legacy:{kind}:{label_order}:{raw_label}",
                    label=raw_label,
                    value_label=raw_label,
                    origin_scope="bucket",
                )
                if source is not None:
                    fallback.append(source)
    if fallback:
        return fallback
    source = _build_group_name_source(
        kind="",
        key=f"legacy:{row.get('label')}",
        label=row.get("label"),
        value_label=row.get("label"),
        origin_scope="bucket",
    )
    return [source] if source is not None else []


def _build_group_suggested_name(sources, filter_sources=None):
    field_values = OrderedDict((field_code, OrderedDict()) for field_code in GROUP_NAME_COMPONENT_FIELD_ORDER)
    atomic_values = OrderedDict()

    def _register(source, *, weight, order_idx):
        if not isinstance(source, dict):
            return
        label = _clean_group_suggestion_label(source.get("value_label") or source.get("label"))
        if not label:
            return
        field_code = _group_name_field_code(source.get("field_code"))
        has_bucket_weight = weight > 0
        if field_code:
            bucket = field_values.setdefault(field_code, OrderedDict())
            key = label.casefold()
            meta = bucket.get(key)
            if meta is None:
                bucket[key] = {
                    "label": label,
                    "bucket_weight": weight if has_bucket_weight else 0,
                    "has_bucket_weight": has_bucket_weight,
                    "order_idx": order_idx,
                }
                return
            if has_bucket_weight:
                meta["bucket_weight"] += weight
                meta["has_bucket_weight"] = True
            meta["order_idx"] = min(meta["order_idx"], order_idx)
            return
        key = label.casefold()
        meta = atomic_values.get(key)
        if meta is None:
            atomic_values[key] = {
                "label": label,
                "bucket_weight": weight if has_bucket_weight else 0,
                "has_bucket_weight": has_bucket_weight,
                "order_idx": order_idx,
            }
            return
        if has_bucket_weight:
            meta["bucket_weight"] += weight
            meta["has_bucket_weight"] = True
        meta["order_idx"] = min(meta["order_idx"], order_idx)

    for row_idx, row in enumerate(sources or []):
        if not isinstance(row, dict):
            continue
        try:
            count = int(row.get("count") or 0)
        except Exception:
            count = 0
        count = max(0, count)
        for comp_idx, source in enumerate(_extract_group_name_components_from_row(row)):
            _register(source, weight=count, order_idx=(row_idx, comp_idx, 0))
    for filter_idx, source in enumerate(filter_sources or []):
        _register(source, weight=0, order_idx=(len(sources or []) + filter_idx, 0, 1))

    segments = []
    for field_code in GROUP_NAME_COMPONENT_FIELD_ORDER:
        rows = list((field_values.get(field_code) or {}).values())
        rows.sort(key=lambda item: (0 if item.get("has_bucket_weight") else 1, -int(item.get("bucket_weight") or 0), item.get("order_idx") or (0, 0, 0), str(item.get("label") or "").casefold()))
        segment = _render_group_name_values(rows)
        if segment:
            segments.append(segment)

    atomic_rows = list(atomic_values.values())
    atomic_rows.sort(key=lambda item: (0 if item.get("has_bucket_weight") else 1, -int(item.get("bucket_weight") or 0), item.get("order_idx") or (0, 0, 0), str(item.get("label") or "").casefold()))
    for row in atomic_rows:
        label = str(row.get("label") or "").strip()
        if label:
            segments.append(label)
    return " · ".join(segments)


def _apply_group_suggested_names(preview_groups, filter_sources=None):
    out = list(preview_groups or [])
    grouped_indexes = OrderedDict()
    for idx, row in enumerate(out):
        suggested_name = _build_group_suggested_name(row.get("sources"), filter_sources=filter_sources)
        row["suggested_name"] = suggested_name
        if not suggested_name:
            continue
        grouped_indexes.setdefault(suggested_name.casefold(), []).append((idx, suggested_name))
    for entries in grouped_indexes.values():
        if len(entries) <= 1:
            continue
        for order_idx, (group_idx, base_name) in enumerate(entries, start=1):
            out[group_idx]["suggested_name"] = f"{base_name} ({order_idx})"
    return out


def _bucket_labels_by_kind(sources):
    labels_by_kind = OrderedDict()
    for source in _normalize_bucket_source_entries(sources):
        kind = source["kind"]
        label = str(source.get("label") or "").strip()
        if not label:
            continue
        labels = labels_by_kind.setdefault(kind, [])
        if label not in labels:
            labels.append(label)
    return labels_by_kind


def _bucket_source_signature(sources):
    normalized = _normalize_bucket_source_entries(sources)
    return tuple((row["kind"], row["key"], row["label"], row.get("field_code") or "", row.get("value_label") or "", row.get("origin_scope") or "") for row in normalized)


def _build_bucket_source_label(sources):
    labels = []
    for source in _normalize_bucket_source_entries(sources):
        label = str(source.get("label") or "").strip()
        if label and label not in labels:
            labels.append(label)
    return " / ".join(labels) if labels else "Sense bloc"


def _build_bucket_source_kinds(sources):
    kinds = []
    for source in _normalize_bucket_source_entries(sources):
        kind = str(source.get("kind") or "").strip().lower()
        if kind and kind not in kinds:
            kinds.append(kind)
    return kinds


def _build_partition_signature_set(buckets):
    return {tuple(sorted(int(ins_id) for ins_id in (bucket.get("ids") or []))) for bucket in (buckets or []) if bucket.get("ids")}


def _partitions_are_equivalent(buckets_a, buckets_b):
    return _build_partition_signature_set(buckets_a) == _build_partition_signature_set(buckets_b)


def _decorate_buckets_with_sources(buckets, kind):
    out = []
    for bucket in buckets or []:
        label = str(bucket.get("label") or "Sense bloc")
        key = str(bucket.get("key") or "")
        sources = _normalize_bucket_source_entries(bucket.get("sources"), default_kind=kind, default_origin_scope="bucket")
        if not sources:
            fallback_source = _build_group_name_source(kind=kind, key=key or label, label=label, value_label=label, origin_scope="bucket")
            sources = [fallback_source] if fallback_source is not None else []
        out.append({**bucket, "label": label, "sources": sources})
    return out


def _build_sort_partition_buckets(records, partition_codes):
    buckets = OrderedDict()
    for record in records:
        raw_vals = [get_inscripcio_value(record, code) for code in partition_codes]
        norm_vals = [_norm_val(value) for value in raw_vals]
        bucket_key = json.dumps(norm_vals, ensure_ascii=False)
        bucket = buckets.get(bucket_key)
        if bucket is None:
            label_parts = [_s(value) for value in raw_vals]
            sources = []
            for code, raw_value, norm_value in zip(partition_codes, raw_vals, norm_vals):
                label = _clean_group_suggestion_label(_s(raw_value))
                if not label:
                    continue
                source = _build_group_name_source(kind="sort", key=f"sort:{code}:{json.dumps(norm_value, ensure_ascii=False)}", label=label, field_code=code, value_label=label, origin_scope="bucket")
                if source is not None:
                    sources.append(source)
            bucket = {"key": bucket_key, "label": " · ".join(label_parts) if label_parts else "(Sense valor)", "count": 0, "ids": [], "sources": sources}
            buckets[bucket_key] = bucket
        bucket["count"] += 1
        bucket["ids"].append(record.id)
    return list(buckets.values())


def _build_tabs_partition_buckets(competicio, records, group_codes):
    if not group_codes:
        return []
    grouping_sig = "|".join(group_codes)
    merges = (competicio.tab_merges or {}).get(grouping_sig, [])
    merge_map = {}
    for group_keys in merges:
        group_tuple = tuple(group_keys)
        for value in group_keys:
            merge_map[value] = group_tuple

    def _simple_label_from_obj(obj):
        parts = [_s(get_inscripcio_value(obj, code)) for code in group_codes]
        return " · ".join(parts) if parts else "(Sense valor)"

    simple_label_map = {}
    simple_values_by_id = {}
    simple_display_values_by_key = {}
    for record in records:
        vals = [_norm_val(get_inscripcio_value(record, code)) for code in group_codes]
        simple = json.dumps(vals, ensure_ascii=False)
        simple_values_by_id[record.id] = simple
        simple_display_values_by_key[simple] = [_s(get_inscripcio_value(record, code)) for code in group_codes]
        if simple not in simple_label_map:
            simple_label_map[simple] = _simple_label_from_obj(record)

    tab_to_ids = OrderedDict()
    tab_label_map = {}
    tab_simple_keys = OrderedDict()
    for record in records:
        simple = simple_values_by_id.get(record.id, "")
        merged_tuple = merge_map.get(simple)
        tab_key = json.dumps(list(merged_tuple), ensure_ascii=False) if merged_tuple else simple
        tab_to_ids.setdefault(tab_key, []).append(record.id)
        tab_simple_keys.setdefault(tab_key, [])
        if simple and simple not in tab_simple_keys[tab_key]:
            tab_simple_keys[tab_key].append(simple)
        if tab_key in tab_label_map:
            continue
        if not merged_tuple:
            tab_label_map[tab_key] = simple_label_map.get(simple, simple)
            continue
        parts = []
        for simple_key in merged_tuple:
            label = simple_label_map.get(simple_key, simple_key)
            if label not in parts:
                parts.append(label)
        tab_label_map[tab_key] = " + ".join(parts) if parts else tab_key

    out = []
    for tab_key, ids in tab_to_ids.items():
        sources = []
        for code_index, code in enumerate(group_codes):
            for simple_key in tab_simple_keys.get(tab_key, []):
                values = simple_display_values_by_key.get(simple_key) or []
                raw_label = values[code_index] if code_index < len(values) else ""
                label = _clean_group_suggestion_label(raw_label)
                if not label:
                    continue
                source = _build_group_name_source(kind="tabs", key=f"tabs:{code}:{label}", label=label, field_code=code, value_label=label, origin_scope="bucket")
                if source is not None and source not in sources:
                    sources.append(source)
        out.append({"key": tab_key, "label": tab_label_map.get(tab_key, tab_key), "count": len(ids), "ids": ids, "sources": sources})
    return out


def _build_combined_partition_buckets(records, layers):
    buckets = OrderedDict()
    for record in records or []:
        raw_sources = []
        for layer in layers or []:
            source_rows = layer.get("by_id", {}).get(record.id)
            if isinstance(source_rows, dict):
                source_rows = [source_rows]
            if not isinstance(source_rows, list):
                continue
            for source_row in source_rows:
                if not isinstance(source_row, dict):
                    continue
                raw_sources.append(
                    {
                        "kind": str(source_row.get("kind") or "").strip().lower(),
                        "key": str(source_row.get("key") or "").strip(),
                        "label": str(source_row.get("label") or "").strip(),
                        "field_code": str(source_row.get("field_code") or "").strip(),
                        "value_label": str(source_row.get("value_label") or "").strip(),
                        "origin_scope": str(source_row.get("origin_scope") or "").strip().lower() or "bucket",
                    }
                )
        sources = _normalize_bucket_source_entries(raw_sources)
        if not sources:
            continue
        bucket_key = json.dumps([{"kind": row["kind"], "key": row["key"]} for row in sources], ensure_ascii=False)
        bucket = buckets.get(bucket_key)
        if bucket is None:
            bucket = {"key": bucket_key, "label": _build_bucket_source_label(sources), "count": 0, "ids": [], "sources": sources}
            buckets[bucket_key] = bucket
        bucket["count"] += 1
        bucket["ids"].append(record.id)
    return list(buckets.values())


def _resolve_group_creation_buckets(competicio, records, *, group_codes=None, partition_codes=None, fallback_mode="all_filtered"):
    group_codes = list(group_codes or [])
    partition_codes = list(partition_codes or [])
    tabs_buckets = _build_tabs_partition_buckets(competicio, records, group_codes) if group_codes else []
    sort_buckets = _build_sort_partition_buckets(records, partition_codes) if partition_codes else []
    tabs_buckets = _decorate_buckets_with_sources(tabs_buckets, "tabs")
    sort_buckets = _decorate_buckets_with_sources(sort_buckets, "sort")
    if tabs_buckets and sort_buckets and _partitions_are_equivalent(tabs_buckets, sort_buckets):
        sort_buckets = []
    layers_used = []
    if tabs_buckets:
        layers_used.append("tabs")
    if sort_buckets:
        layers_used.append("sort")
    if not layers_used:
        if fallback_mode == "strict":
            return {"ok": False, "error": "No hi ha criteris resolubles per construir blocs d'origen", "buckets": [], "layers_used": [], "used_fallback": False, "fallback_reason": "no_resolvable_criteria"}
        return {
            "ok": True,
            "buckets": [{"key": "__ALL_FILTERED__", "label": "Totes les inscripcions filtrades", "count": len(records), "ids": [record.id for record in records], "sources": [{"kind": "fallback", "key": "__ALL_FILTERED__", "label": "Totes les inscripcions filtrades"}]}],
            "layers_used": [],
            "used_fallback": True,
            "fallback_reason": "no_resolvable_criteria_used_all_filtered",
        }
    if len(layers_used) == 1:
        buckets = tabs_buckets if tabs_buckets else sort_buckets
    else:
        layers = []
        if tabs_buckets:
            layers.append({"kind": "tabs", "by_id": {ins_id: list(bucket.get("sources") or []) for bucket in tabs_buckets for ins_id in (bucket.get("ids") or [])}})
        if sort_buckets:
            layers.append({"kind": "sort", "by_id": {ins_id: list(bucket.get("sources") or []) for bucket in sort_buckets for ins_id in (bucket.get("ids") or [])}})
        buckets = _build_combined_partition_buckets(records, layers)
    return {"ok": True, "buckets": buckets, "layers_used": layers_used, "used_fallback": False, "fallback_reason": ""}


def _build_existing_groups_preview(competicio, records, bucket_sources_by_id=None, moving_ids=None):
    bucket_sources_by_id = bucket_sources_by_id or {}
    moving_ids = set(moving_ids or [])
    groups_by_display_num = (get_group_maps(competicio).get("by_display_num") or {})
    visible_group_nums = []
    seen_group_nums = set()
    for record in records:
        group_num = normalize_positive_int(getattr(record, "grup", None))
        if not group_num or group_num in seen_group_nums:
            continue
        seen_group_nums.add(group_num)
        visible_group_nums.append(group_num)
    if not visible_group_nums:
        return []
    grouped = OrderedDict((group_num, []) for group_num in sorted(visible_group_nums))
    all_group_members = Inscripcio.objects.filter(competicio=competicio, grup__in=visible_group_nums).order_by("grup", "ordre_sortida", "id").only("id", "grup", "nom_i_cognoms", "ordre_sortida")
    for record in all_group_members:
        group_num = normalize_positive_int(getattr(record, "grup", None))
        if not group_num:
            continue
        grouped.setdefault(group_num, []).append(record)
    out = []
    for group_num in sorted(grouped.keys()):
        members = grouped.get(group_num) or []
        group_obj = groups_by_display_num.get(group_num)
        source_counts = OrderedDict()
        moving_members = []
        for obj in members:
            sources = bucket_sources_by_id.get(obj.id) or []
            source_key = _bucket_source_signature(sources)
            row = source_counts.get(source_key)
            if row is None:
                row = {"label": _build_bucket_source_label(sources) if sources else "Fora del filtre actual", "count": 0, "moving_count": 0, "remaining_count": 0, "kinds": _build_bucket_source_kinds(sources), "labels_by_kind": dict(_bucket_labels_by_kind(sources))}
                source_counts[source_key] = row
            row["count"] += 1
            if obj.id in moving_ids:
                row["moving_count"] += 1
                moving_members.append(obj)
            else:
                row["remaining_count"] += 1
        member_names = [str(getattr(obj, "nom_i_cognoms", "") or "").strip() for obj in members]
        member_names = [name for name in member_names if name]
        moving_member_names = [str(getattr(obj, "nom_i_cognoms", "") or "").strip() for obj in moving_members]
        moving_member_names = [name for name in moving_member_names if name]
        moving_members_count = len(moving_members)
        remaining_members_count = max(0, len(members) - moving_members_count)
        impact_kind = "unchanged"
        if moving_members_count > 0 and remaining_members_count <= 0:
            impact_kind = "removed"
        elif moving_members_count > 0:
            impact_kind = "reduced"
        out.append(
            {
                "preview_kind": "existing",
                "impact_kind": impact_kind,
                "group_num": group_num,
                "group_label": group_label(group_obj),
                "members_count": len(members),
                "moving_members_count": moving_members_count,
                "remaining_members_count": remaining_members_count,
                "sources": list(source_counts.values()),
                "member_names_preview": member_names[:4],
                "member_names_remaining": max(0, len(member_names) - 4),
                "moving_member_names_preview": moving_member_names[:4],
                "moving_member_names_remaining": max(0, len(moving_member_names) - 4),
            }
        )
    return out


def competicio_has_rotacions(competicio):
    return RotacioAssignacio.objects.filter(competicio=competicio).exists()


def _message_for_emptied_programmed_groups(groups):
    if not groups:
        return ""
    labels = []
    for group in groups:
        label = str(getattr(group, "nom", "") or "").strip()
        if not label:
            label = f"Grup {getattr(group, 'display_num', '?')}"
        labels.append(label)
    return f"No es pot deixar buit un grup inclos al programa de rotacions: {', '.join(labels)}."


__all__ = [
    "_build_sort_field_runtime_context",
    "_build_existing_groups_preview",
    "_build_inscripcions_filtered_qs",
    "_build_sort_partition_buckets",
    "_extract_sort_partition_codes",
    "_label_with_source",
    "_message_for_emptied_programmed_groups",
    "_normalize_schema_extra_code",
    "_normalize_sort_criterion",
    "_normalize_sort_filters",
    "_normalize_sort_group_by",
    "_reserved_inscripcio_codes",
    "_resolve_group_creation_buckets",
    "annotate_inscripcions_queryset_for_group_codes",
    "build_inscripcions_sort_context_key",
    "competicio_has_rotacions",
    "get_allowed_group_fields",
    "get_available_column_filter_fields",
    "get_available_sort_fields",
    "get_competicio_custom_sort_codes",
    "get_inscripcio_value",
    "get_inscripcions_sort_context_state",
    "get_request_inscripcio_filters",
    "reconcile_inscripcions_sort_context_state",
]
