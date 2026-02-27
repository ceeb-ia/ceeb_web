import random
import hashlib
from django.shortcuts import render
import math
from datetime import date, datetime
from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import CreateView, FormView, ListView, TemplateView, DeleteView
from django.shortcuts import redirect
from django.db.models import Q
from .forms import ImportInscripcionsExcelForm
from .models import Competicio, Inscripcio
from .forms import CompeticioForm
from .services.import_excel import importar_inscripcions_excel
import json
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect
from django.db import transaction
from django.views.generic import UpdateView
from django.urls import reverse
from .forms import InscripcioForm
from io import BytesIO
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter
from django.db.models import Q, Max, Min, Case, When, IntegerField
from collections import defaultdict
from collections import OrderedDict


BUILTIN_SORT_FIELDS = [
    {"code": "nom_i_cognoms", "label": "Nom (A-Z)", "kind": "builtin"},
    {"code": "data_naixement", "label": "Edat / Data naixement", "kind": "builtin"},
    {"code": "document", "label": "Document", "kind": "builtin"},
    {"code": "sexe", "label": "Sexe", "kind": "builtin"},
    {"code": "entitat", "label": "Entitat", "kind": "builtin"},
    {"code": "categoria", "label": "Categoria", "kind": "builtin"},
    {"code": "subcategoria", "label": "Subcategoria", "kind": "builtin"},
    {"code": "grup", "label": "Grup", "kind": "builtin"},
]

# Compatibilitat amb URLs antigues (?sort_key=nom|edat)
LEGACY_SORT_KEY_MAP = {
    "nom": "nom_i_cognoms",
    "edat": "data_naixement",
}

BUILTIN_EXCEL_FIELDS = [
    {"code": "nom_i_cognoms", "label": "Nom i cognoms", "kind": "builtin"},
    {"code": "document", "label": "DNI", "kind": "builtin"},
    {"code": "sexe", "label": "Sexe", "kind": "builtin"},
    {"code": "data_naixement", "label": "Data naixement", "kind": "builtin"},
    {"code": "entitat", "label": "Entitat", "kind": "builtin"},
    {"code": "categoria", "label": "Categoria", "kind": "builtin"},
    {"code": "subcategoria", "label": "Subcategoria", "kind": "builtin"},
    {"code": "grup", "label": "Grup", "kind": "builtin"},
    {"code": "ordre_sortida", "label": "Ordre", "kind": "builtin"},
]

# Compatibilitat amb URLs antigues (?excel_cols=nom|dni|naixement|ordre)
LEGACY_EXCEL_COL_MAP = {
    "nom": "nom_i_cognoms",
    "dni": "document",
    "naixement": "data_naixement",
    "ordre": "ordre_sortida",
}

# Camps built-in del model que volem permetre agrupar sempre
BUILTIN_GROUP_FIELDS = [
    {"code": "categoria", "label": "Categoria", "kind": "builtin"},
    {"code": "subcategoria", "label": "Subcategoria", "kind": "builtin"},
    {"code": "entitat", "label": "Entitat", "kind": "builtin"},
    {"code": "sexe", "label": "Sexe", "kind": "builtin"},
    {"code": "data_naixement", "label": "Data naixement", "kind": "builtin"},
    {"code": "document", "label": "Document", "kind": "builtin"},
]


def _reserved_inscripcio_codes():
    out = set()
    for f in Inscripcio._meta.concrete_fields:
        name = str(getattr(f, "name", "") or "").strip()
        attname = str(getattr(f, "attname", "") or "").strip()
        if name:
            out.add(name)
        if attname:
            out.add(attname)
    return out


def _normalize_schema_extra_code(code: str, reserved_codes=None):
    code = (code or "").strip()
    if not code:
        return code
    if code.startswith("excel__"):
        return code
    if reserved_codes is None:
        reserved_codes = _reserved_inscripcio_codes()
    if code in reserved_codes:
        return f"excel__{code}"
    return code


def _excel_schema_codes(competicio):
    schema = competicio.inscripcions_schema or {}
    cols = schema.get("columns") or []
    if not isinstance(cols, list):
        return set()
    reserved = _reserved_inscripcio_codes()
    out = set()
    for c in cols:
        if not isinstance(c, dict):
            continue
        code = c.get("code")
        if not code:
            continue
        kind = c.get("kind") or "extra"
        if kind == "extra":
            code = _normalize_schema_extra_code(code, reserved)
        out.add(code)
    return out


def _label_with_source(label: str, source: str):
    suffix = "Excel" if source == "excel" else "Nativa"
    return f"{label} ({suffix})"


# Per mostrar/ordenar values
def _s(v):
    return "(Sense valor)" if v in (None, "") else str(v)

def _norm_val(v):
    return "__NULL__" if v in (None, "") else str(v)

def get_inscripcio_value(obj, code: str):
    """
    Retorna valor per a un camp d'agrupació.
    - built-in: getattr
    - extra: obj.extra.get(code)
    """
    extra = getattr(obj, "extra", None) or {}
    if isinstance(extra, dict) and isinstance(code, str) and code.startswith("excel__"):
        if code in extra:
            return extra.get(code)
        legacy_code = code[len("excel__"):]
        if legacy_code in extra:
            return extra.get(legacy_code)
    if hasattr(obj, code):
        return getattr(obj, code)
    if isinstance(extra, dict) and code in extra:
        return extra.get(code)
    return extra.get(code)

def get_allowed_group_fields(competicio):
    """
    Retorna llista [{code,label,kind}, ...] = builtins + extras detectats a schema.
    """
    out = []
    seen = set()
    excel_codes = _excel_schema_codes(competicio)
    reserved = _reserved_inscripcio_codes()

    # builtins sempre
    for f in BUILTIN_GROUP_FIELDS:
        if f["code"] not in seen:
            source = "excel" if f["code"] in excel_codes else "native"
            out.append(
                {
                    **f,
                    "source": source,
                    "ui_label": _label_with_source(f["label"], source),
                }
            )
            seen.add(f["code"])

    schema = competicio.inscripcions_schema or {}
    cols = schema.get("columns") or []
    if isinstance(cols, list):
        for c in cols:
            if not isinstance(c, dict):
                continue
            code = c.get("code")
            if not code:
                continue
            kind = c.get("kind") or "extra"
            if kind != "extra":
                continue
            code = _normalize_schema_extra_code(code, reserved)
            label = c.get("label") or code
            if code not in seen:
                out.append(
                    {
                        "code": code,
                        "label": label,
                        "kind": "extra",
                        "source": "excel",
                        "ui_label": _label_with_source(label, "excel"),
                    }
                )
                seen.add(code)

    return out


def get_available_sort_fields(competicio):
    """
    Camps ordenables: builtins + extras detectats a schema.columns.
    """
    out = []
    seen = set()
    excel_codes = _excel_schema_codes(competicio)
    reserved = _reserved_inscripcio_codes()

    for f in BUILTIN_SORT_FIELDS:
        if f["code"] not in seen:
            source = "excel" if f["code"] in excel_codes else "native"
            out.append(
                {
                    **f,
                    "source": source,
                    "ui_label": _label_with_source(f["label"], source),
                }
            )
            seen.add(f["code"])

    schema = competicio.inscripcions_schema or {}
    cols = schema.get("columns") or []
    if isinstance(cols, list):
        for c in cols:
            if not isinstance(c, dict):
                continue
            code = c.get("code")
            if not code or code in seen:
                continue
            kind = c.get("kind") or "extra"
            if kind != "extra":
                continue
            code = _normalize_schema_extra_code(code, reserved)
            if code in seen:
                continue
            label = c.get("label") or code
            out.append(
                {
                    "code": code,
                    "label": label,
                    "kind": "extra",
                    "source": "excel",
                    "ui_label": _label_with_source(label, "excel"),
                }
            )
            seen.add(code)

    return out


def get_available_excel_columns(competicio):
    """
    Columnes exportables a Excel: builtins + extras detectats al schema.
    """
    out = []
    seen = set()
    excel_codes = _excel_schema_codes(competicio)
    reserved = _reserved_inscripcio_codes()

    for f in BUILTIN_EXCEL_FIELDS:
        if f["code"] not in seen:
            source = "excel" if f["code"] in excel_codes else "native"
            out.append(
                {
                    **f,
                    "source": source,
                    "ui_label": _label_with_source(f["label"], source),
                }
            )
            seen.add(f["code"])

    schema = competicio.inscripcions_schema or {}
    cols = schema.get("columns") or []
    if isinstance(cols, list):
        for c in cols:
            if not isinstance(c, dict):
                continue
            code = c.get("code")
            if not code or code in seen:
                continue
            kind = c.get("kind") or "extra"
            if kind != "extra":
                continue
            code = _normalize_schema_extra_code(code, reserved)
            if code in seen:
                continue
            label = c.get("label") or code
            out.append(
                {
                    "code": code,
                    "label": label,
                    "kind": "extra",
                    "source": "excel",
                    "ui_label": _label_with_source(label, "excel"),
                }
            )
            seen.add(code)

    return out


def get_excel_export_value(obj, code):
    v = get_inscripcio_value(obj, code)
    if code == "data_naixement":
        return v.strftime("%d/%m/%Y") if v else "-"
    if v in (None, ""):
        return "-"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def _sort_scalar(v):
    if isinstance(v, (int, float)):
        return (0, float(v))
    if isinstance(v, (date, datetime)):
        return (1, v.isoformat())
    return (2, str(v).casefold())


def sort_records_by_field(records, sort_code, descending=False):
    """
    Ordenació portable (builtins + extra JSON), amb buits al final.
    """
    filled = []
    empty = []

    for o in records:
        v = get_inscripcio_value(o, sort_code)
        if v in (None, ""):
            empty.append(o)
        else:
            filled.append((o, v))

    # tiebreak estable per id asc, independent de l'ordre asc/desc
    filled.sort(key=lambda t: t[0].id)
    filled.sort(key=lambda t: _sort_scalar(t[1]), reverse=descending)
    empty.sort(key=lambda o: o.id)

    return [o for (o, _v) in filled] + empty


def sort_records_by_field_stable(records, sort_code, descending=False):
    """
    Ordenacio estable (acumulativa): en empats conserva l'ordre d'entrada.
    Els buits continuen al final, conservant ordre relatiu.
    """
    filled = []
    empty = []

    for o in records:
        v = get_inscripcio_value(o, sort_code)
        if v in (None, ""):
            empty.append(o)
        else:
            filled.append((o, v))

    # Python sort es estable: en valors iguals manté l'ordre previ.
    filled.sort(key=lambda t: _sort_scalar(t[1]), reverse=descending)

    return [o for (o, _v) in filled] + empty


def _s(v):
    return "(Sense valor)" if v in (None, "") else str(v)

def arrow_positions(n: int) -> list[int]:
    """
    Retorna la seqüència de posicions "fletxa" per un grup de mida n.

    Exemple n=8 -> [3,4,2,5,1,6,0,7]
    (index del registre ordenat) -> (posició dins del grup)
    """
    if n <= 0:
        return []

    seq = []
    if n % 2 == 0:
        left = n // 2 - 1
        right = n // 2
        while left >= 0 or right < n:
            if left >= 0:
                seq.append(left)
                left -= 1
            if right < n:
                seq.append(right)
                right += 1
    else:
        center = n // 2
        seq.append(center)
        step = 1
        while center - step >= 0 or center + step < n:
            if center - step >= 0:
                seq.append(center - step)
            if center + step < n:
                seq.append(center + step)
            step += 1

    return seq

def init_ordre_sortida(competicio_id):
    qs = Inscripcio.objects.filter(competicio_id=competicio_id).order_by("id")
    with transaction.atomic():
        for i, obj in enumerate(qs, start=1):
            Inscripcio.objects.filter(id=obj.id).update(ordre_sortida=i)

def shuffle_ordre_sortida(qs):
    ids = list(qs.values_list("id", flat=True))
    random.shuffle(ids)

    with transaction.atomic():
        for idx, ins_id in enumerate(ids, start=1):
            Inscripcio.objects.filter(id=ins_id).update(ordre_sortida=idx)



UNDO_SESSION_KEY = "inscripcions_undo_state"
INSCRIPCIONS_SORT_STACK_SESSION_KEY = "inscripcions_sort_stack_v1"

def save_undo_state(request, qs):
    """
    Desa a sessió l'estat actual (grup + ordre_sortida)
    del queryset passat.
    """
    request.session[UNDO_SESSION_KEY] = list(
        qs.values("id", "grup", "ordre_sortida")
    )
    request.session.modified = True


def restore_undo_state(request):
    """
    Restaura l'últim estat guardat.
    Retorna nombre de registres restaurats.
    """
    data = request.session.get(UNDO_SESSION_KEY)
    if not data:
        return 0

    with transaction.atomic():
        for row in data:
            Inscripcio.objects.filter(id=row["id"]).update(
                grup=row["grup"],
                ordre_sortida=row["ordre_sortida"],
            )

    del request.session[UNDO_SESSION_KEY]
    request.session.modified = True
    return len(data)


def _normalize_sort_filters(raw_filters):
    data = raw_filters if isinstance(raw_filters, dict) else {}
    return {
        "q": str(data.get("q") or "").strip(),
        "categoria": str(data.get("categoria") or "").strip(),
        "subcategoria": str(data.get("subcategoria") or "").strip(),
        "entitat": str(data.get("entitat") or "").strip(),
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
    return [g for g in fallback if g in allowed_group_codes]


def build_inscripcions_sort_context_key(competicio_id, filters=None, group_by=None):
    clean_filters = _normalize_sort_filters(filters)
    clean_group_by = []
    if isinstance(group_by, list):
        for g in group_by:
            if isinstance(g, str) and g not in clean_group_by:
                clean_group_by.append(g)

    parts = [
        str(competicio_id),
        clean_filters["q"],
        clean_filters["categoria"],
        clean_filters["subcategoria"],
        clean_filters["entitat"],
        "|".join(clean_group_by),
    ]
    return "||".join(parts)


def compute_inscripcions_order_signature_from_ids(ids):
    h = hashlib.sha1()
    for ins_id in ids:
        h.update(str(ins_id).encode("utf-8"))
        h.update(b",")
    return h.hexdigest()


def compute_inscripcions_order_signature_for_queryset(qs):
    ids = qs.values_list("id", flat=True)
    return compute_inscripcions_order_signature_from_ids(ids)


def _read_sort_stack_store(request):
    raw = request.session.get(INSCRIPCIONS_SORT_STACK_SESSION_KEY)
    if not isinstance(raw, dict):
        return {}
    return raw


def _write_sort_stack_store(request, store):
    request.session[INSCRIPCIONS_SORT_STACK_SESSION_KEY] = store
    request.session.modified = True


def get_inscripcions_sort_context_state(request, context_key):
    if not context_key:
        return {"stack": [], "order_sig": "", "base_ids": []}
    store = _read_sort_stack_store(request)
    state = store.get(context_key)
    if not isinstance(state, dict):
        return {"stack": [], "order_sig": "", "base_ids": []}
    stack = state.get("stack")
    if not isinstance(stack, list):
        stack = []
    order_sig = state.get("order_sig")
    if not isinstance(order_sig, str):
        order_sig = ""
    base_ids = state.get("base_ids")
    if not isinstance(base_ids, list):
        base_ids = []
    return {"stack": stack, "order_sig": order_sig, "base_ids": base_ids}


def save_inscripcions_sort_context_state(request, context_key, stack=None, order_sig=None, base_ids=None):
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
    if not state.get("stack"):
        store.pop(context_key, None)
    else:
        store[context_key] = state
    _write_sort_stack_store(request, store)


def append_inscripcions_sort_stack_entry(request, context_key, entry, order_sig="", base_ids=None):
    state = get_inscripcions_sort_context_state(request, context_key)
    stack = list(state.get("stack") or [])
    stack.append(entry)
    # Evita creixements infinits en sessions llargues.
    if len(stack) > 20:
        stack = stack[-20:]
    save_inscripcions_sort_context_state(
        request,
        context_key,
        stack=stack,
        order_sig=order_sig,
        base_ids=base_ids if base_ids is not None else state.get("base_ids"),
    )
    return stack


def pop_inscripcions_sort_stack_entry(request, context_key, order_sig=None):
    state = get_inscripcions_sort_context_state(request, context_key)
    stack = list(state.get("stack") or [])
    popped = None
    if stack:
        popped = stack.pop()
    save_inscripcions_sort_context_state(
        request,
        context_key,
        stack=stack,
        order_sig=order_sig if order_sig is not None else state.get("order_sig", ""),
        base_ids=state.get("base_ids"),
    )
    return popped, stack


def clear_inscripcions_sort_context_state(request, context_key):
    save_inscripcions_sort_context_state(request, context_key, stack=[], order_sig="")


def _build_inscripcions_filtered_qs(competicio, filters):
    q = (filters.get("q") or "").strip()
    categoria = (filters.get("categoria") or "").strip()
    subcategoria = (filters.get("subcategoria") or "").strip()
    entitat = (filters.get("entitat") or "").strip()

    qs = Inscripcio.objects.filter(competicio=competicio)
    if subcategoria:
        qs = qs.filter(subcategoria__iexact=subcategoria)
    if entitat:
        qs = qs.filter(entitat__icontains=entitat)
    if q:
        qs = qs.filter(
            Q(nom_i_cognoms__icontains=q) |
            Q(document__icontains=q) |
            Q(entitat__icontains=q)
        )
    if categoria:
        qs = qs.filter(categoria__iexact=categoria)
    return qs


def _normalize_sort_criterion(raw, sort_codes, allowed_group_codes, fallback_group_by=None):
    if not isinstance(raw, dict):
        return None

    c_sort_key_raw = str(raw.get("sort_key") or "").strip()
    c_sort_key = LEGACY_SORT_KEY_MAP.get(c_sort_key_raw, c_sort_key_raw)
    if c_sort_key not in sort_codes:
        return None

    c_sort_dir = str(raw.get("sort_dir") or "asc").strip()
    if c_sort_dir not in ("asc", "desc", "arrow_asc", "arrow_desc"):
        c_sort_dir = "asc"

    c_scope = str(raw.get("scope") or "all").strip().lower()
    if c_scope not in ("all", "tab", "group"):
        c_scope = "all"

    c_group_num = None
    if c_scope == "group":
        try:
            c_group_num = int(raw.get("group_num"))
        except Exception:
            return None
        if c_group_num <= 0:
            return None

    c_group_by = _normalize_sort_group_by(
        raw.get("group_by"),
        allowed_group_codes,
        fallback_group_by=fallback_group_by or [],
    )

    return {
        "sort_key": c_sort_key,
        "sort_dir": c_sort_dir,
        "scope": c_scope,
        "group_num": c_group_num,
        "group_by": c_group_by,
    }


def _apply_single_sort_criterion(ids_in_order, id_to_record, criterion, competicio):
    seq_records = [id_to_record[i] for i in ids_in_order if i in id_to_record]
    if not seq_records:
        return list(ids_in_order)

    c_sort_key = criterion["sort_key"]
    c_sort_dir = criterion["sort_dir"]
    c_scope = criterion["scope"]
    c_group_num = criterion["group_num"]
    c_group_by = list(criterion.get("group_by") or [])

    c_desc = c_sort_dir in ("desc", "arrow_desc")
    c_arrow = c_sort_dir in ("arrow_asc", "arrow_desc")

    def _ordered_subset(subset_records):
        ordered = sort_records_by_field_stable(subset_records, c_sort_key, descending=c_desc)
        if not c_arrow:
            return ordered
        n = len(ordered)
        pos = arrow_positions(n)
        placed = [None] * n
        for i, obj in enumerate(ordered):
            placed[pos[i]] = obj
        return placed

    if c_scope == "all":
        return [o.id for o in _ordered_subset(seq_records)]

    if c_scope == "group":
        ids_out = list(ids_in_order)
        id_to_index = {rid: idx for idx, rid in enumerate(ids_out)}
        target_records = [r for r in seq_records if int(r.grup or 0) == c_group_num]
        target_idxs = [id_to_index[r.id] for r in target_records if r.id in id_to_index]
        ordered_target = _ordered_subset(target_records)
        for i, obj in zip(target_idxs, ordered_target):
            ids_out[i] = obj.id
        return ids_out

    # c_scope == "tab"
    if not c_group_by:
        return [o.id for o in _ordered_subset(seq_records)]

    grouping_sig = "|".join(c_group_by)
    merges = (competicio.tab_merges or {}).get(grouping_sig, [])
    merge_map = {}
    for group_keys in merges:
        t = tuple(group_keys)
        for x in group_keys:
            merge_map[x] = t

    ids_out = list(ids_in_order)
    id_to_index = {rid: idx for idx, rid in enumerate(ids_out)}
    tab_to_records = OrderedDict()
    for r in seq_records:
        vals = [_norm_val(get_inscripcio_value(r, code)) for code in c_group_by]
        simple = json.dumps(vals, ensure_ascii=False)
        mid = merge_map.get(simple)
        tab_key = json.dumps(list(mid), ensure_ascii=False) if mid else simple
        tab_to_records.setdefault(tab_key, []).append(r)

    for _tab_key, tab_records in tab_to_records.items():
        tab_idxs = [id_to_index[r.id] for r in tab_records if r.id in id_to_index]
        ordered_tab = _ordered_subset(tab_records)
        for i, obj in zip(tab_idxs, ordered_tab):
            ids_out[i] = obj.id

    return ids_out


def _apply_sort_stack(ids_base, id_to_record, stack, competicio):
    final_ids = list(ids_base)
    # Primer criteri = mes important, per tant s'aplica l'stack en ordre invers.
    for criterion in reversed(stack):
        final_ids = _apply_single_sort_criterion(final_ids, id_to_record, criterion, competicio)
    return final_ids

def assign_groups_balanced(objs, size, start_group_num):
    """
    Reparteix objs en k grups, on k = ceil(n/size),
    i distribueix mides perquè difereixin com a màxim 1.
    Retorna el nou start_group_num (últim grup assignat).
    """
    n = len(objs)
    if n == 0:
        return start_group_num

    k = math.ceil(n / size)           # nombre de grups
    base = n // k                     # mida base de cada grup
    rem = n % k                       # els primers 'rem' grups tindran +1

    idx = 0
    group_num = start_group_num
    for g in range(k):
        group_num += 1
        this_size = base + (1 if g < rem else 0)
        for _ in range(this_size):
            objs[idx].grup = group_num
            idx += 1

    return group_num

def renumber_groups_for_competicio(competicio):
    """
    Re-numera grups consecutivament 1..N dins la competició, evitant forats.
    L'ordre de renumeració segueix la seva aparició a la llista (min ordre_sortida).
    """
    base = Inscripcio.objects.filter(competicio=competicio, grup__isnull=False)

    groups = list(
        base.values("grup")
            .annotate(min_ord=Min("ordre_sortida"))
            .order_by("min_ord", "grup")
    )
    if not groups:
        return

    mapping = {g["grup"]: i + 1 for i, g in enumerate(groups)}

    whens = [When(grup=old, then=new) for old, new in mapping.items()]
    base.update(
        grup=Case(
            *whens,
            default=None,
            output_field=IntegerField(),
        )
    )

def assign_groups_k(objs, k, start_group_num):
    """
    Reparteix objs en k grups (k fix), equilibrant mides (difereixen com a màxim 1).
    """
    n = len(objs)
    if n == 0 or k <= 0:
        return start_group_num

    k = min(k, n)  # no té sentit més grups que persones

    base = n // k
    rem = n % k

    idx = 0
    group_num = start_group_num
    for g in range(k):
        group_num += 1
        this_size = base + (1 if g < rem else 0)
        for _ in range(this_size):
            objs[idx].grup = group_num
            idx += 1

    return group_num

# ------------------------------------------------------------------------------------------------
#
#
#           CREACIÓ COMPETICIONS
#
#
# ------------------------------------------------------------------------------------------------




class CompeticioHomeView(TemplateView):
    template_name = "competicio/home.html"


class CompeticioCreateView(CreateView):
    model = Competicio
    form_class = CompeticioForm
    template_name = "competicio/competicio_form.html"
    success_url = reverse_lazy("created")


class CompeticioDeleteView(DeleteView):
    model = Competicio
    template_name = "competicio/competicio_confirm_delete.html"
    success_url = reverse_lazy("created")

class CompeticioListView(ListView):
    model = Competicio
    template_name = "competicio/competicio_created_list.html"
    context_object_name = "competicions"
    paginate_by = 20



def notes_home_router(request, pk):
    c = get_object_or_404(Competicio, pk=pk)

    if c.tipus == Competicio.Tipus.TRAMPOLI:
        return redirect("scoring_notes_home", pk=pk)

    # futurs:
    # if c.tipus == Competicio.Tipus.NATACIO: return redirect(...)
    # ...

    return redirect("created")


# ------------------------------------------------------------------------------------------------
#
#
#           TRACTAMENT INSCRIPCIONS
#
#
# ------------------------------------------------------------------------------------------------

class InscripcionsImportExcelView(FormView):
    template_name = "competicio/inscripcions_import.html"
    form_class = ImportInscripcionsExcelForm

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["competicio"] = self.competicio
        return ctx

    def form_valid(self, form):
        fitxer = form.cleaned_data["fitxer"]
        sheet = form.cleaned_data.get("sheet") or ""

        result = importar_inscripcions_excel(fitxer, self.competicio, sheet)
        messages.success(
            self.request,
            f"Importació OK. Full: {result['full']} | Creats: {result['creats']} | "
            f"Actualitzats: {result['actualitzats']} | Ignorats: {result['ignorats']} | "
            f"Ambiguos: {result.get('ambiguos', 0)}"
        )
        warnings = result.get("warnings") or []
        if warnings:
            parts = []
            for w in warnings:
                code = str(w.get("code") or "").strip()
                remapped = str(w.get("remapped_code") or w.get("suggested_code") or "").strip()
                if code and remapped:
                    parts.append(f"{code} -> {remapped}")
                elif code:
                    parts.append(code)
            if parts:
                messages.warning(
                    self.request,
                    "S'han detectat columnes d'Excel amb noms reservats i s'han remapejat automaticament "
                    f"({', '.join(parts)}).",
                )
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("inscripcions_list", kwargs={"pk": self.competicio.pk})


def recalcular_ordre_sortida(qs, group_codes):
    """
    Recalcula ordre_sortida segons camps d'agrupació (codes).
    Compatible amb:
    - builtins (camps del model)
    - extras (JSON: Inscripcio.extra)
    """
    records = list(qs.order_by("ordre_sortida", "id"))

    def sort_key(o):
        gvals = tuple(_norm_val(get_inscripcio_value(o, code)) for code in group_codes)
        prev = o.ordre_sortida if o.ordre_sortida is not None else 10**12
        return (gvals, prev, o.id)

    records.sort(key=sort_key)

    with transaction.atomic():
        for idx, obj in enumerate(records, start=1):
            if obj.ordre_sortida != idx:
                Inscripcio.objects.filter(id=obj.id).update(ordre_sortida=idx)


class InscripcionsListView(ListView):
    template_name = "competicio/inscripcions_list.html"
    context_object_name = "records"
    paginate_by = 25

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return self.get_queryset_base_filtrada().order_by("ordre_sortida", "id")

    def get_queryset_base_filtrada(self):
        qs = Inscripcio.objects.filter(competicio=self.competicio)

        q = self.request.GET.get("q")
        categoria = self.request.GET.get("categoria")
        subcategoria = self.request.GET.get("subcategoria")
        entitat = self.request.GET.get("entitat")

        if subcategoria:
            qs = qs.filter(subcategoria__iexact=subcategoria)
        if entitat:
            qs = qs.filter(entitat__icontains=entitat)
        if q:
            qs = qs.filter(
                Q(nom_i_cognoms__icontains=q) |
                Q(document__icontains=q) |
                Q(entitat__icontains=q)
            )
        if categoria:
            qs = qs.filter(categoria__iexact=categoria)

        return qs

    def get(self, request, *args, **kwargs):
        allowed = get_allowed_group_fields(self.competicio)
        allowed_codes = {f["code"] for f in allowed}
        sort_fields = get_available_sort_fields(self.competicio)
        sort_allowed_codes = {f["code"] for f in sort_fields}
        default_sort_code = "nom_i_cognoms" if "nom_i_cognoms" in sort_allowed_codes else (next(iter(sort_allowed_codes), ""))

        def resolve_sort_key(raw_key):
            k = LEGACY_SORT_KEY_MAP.get((raw_key or "").strip(), (raw_key or "").strip())
            if k in sort_allowed_codes:
                return k
            return default_sort_code

        def get_active_group_codes():
            selected = [g for g in request.GET.getlist("group_by") if g in allowed_codes]
            if not selected:
                selected = [g for g in (self.competicio.group_by_default or []) if g in allowed_codes]
            return selected

        def simple_key_for_obj(obj, group_codes):
            vals = [_norm_val(get_inscripcio_value(obj, c)) for c in group_codes]
            return json.dumps(vals, ensure_ascii=False)

        def pretty_label_from_simple_key(simple_key):
            try:
                vals = json.loads(simple_key)
                return " · ".join("(Sense valor)" if v in (None, "", "__NULL__") else str(v) for v in vals)
            except Exception:
                return simple_key
        # 0z) UNDO
        if request.GET.get("undo") == "1":
            restored = restore_undo_state(request)
            active_group_by = get_active_group_codes()
            active_filters = {
                "q": request.GET.get("q") or "",
                "categoria": request.GET.get("categoria") or "",
                "subcategoria": request.GET.get("subcategoria") or "",
                "entitat": request.GET.get("entitat") or "",
            }
            undo_context_key = build_inscripcions_sort_context_key(
                self.competicio.id,
                filters=active_filters,
                group_by=active_group_by,
            )
            if restored:
                filtered_qs = self.get_queryset_base_filtrada().order_by("ordre_sortida", "id")
                order_sig = compute_inscripcions_order_signature_for_queryset(filtered_qs)
                pop_inscripcions_sort_stack_entry(request, undo_context_key, order_sig=order_sig)
                messages.success(request, f"S'ha desfet l'última acció ({restored} inscripcions).")
            else:
                messages.info(request, "No hi ha cap acció per desfer.")
            query = request.GET.copy()
            query.pop("undo", None)
            return redirect(f"{request.path}?{query.urlencode()}")

        # 0x) EXPORT EXCEL
        if request.GET.get("export_excel") == "1":
            available_excel = get_available_excel_columns(self.competicio)
            by_code = {c["code"]: c for c in available_excel}

            selected_cols_raw = request.GET.getlist("excel_cols")
            selected_codes = []
            for raw in selected_cols_raw:
                code = LEGACY_EXCEL_COL_MAP.get(raw, raw)
                if code in by_code and code not in selected_codes:
                    selected_codes.append(code)

            if not selected_codes:
                selected_codes = list(by_code.keys())

            if not selected_codes and "nom_i_cognoms" in by_code:
                selected_codes = ["nom_i_cognoms"]

            columns = [(by_code[c]["label"], c) for c in selected_codes]

            group_codes = get_active_group_codes()
            grouping_sig = "|".join(group_codes) if group_codes else ""
            qs_base = self.get_queryset_base_filtrada()

            wb = Workbook()
            ws = wb.active
            ws.title = "Inscripcions"

            title_font = Font(bold=True, size=12)
            header_font = Font(bold=True)
            header_fill = PatternFill("solid", fgColor="E9EEF7")
            group_fill = PatternFill("solid", fgColor="DDE7FF")

            def write_table_header(r):
                for col_i, (label, _) in enumerate(columns, start=1):
                    c = ws.cell(row=r, column=col_i, value=label)
                    c.font = header_font
                    c.fill = header_fill
                    c.alignment = Alignment(vertical="center")

            def write_row(r, obj):
                for col_i, (_label, code) in enumerate(columns, start=1):
                    ws.cell(row=r, column=col_i, value=get_excel_export_value(obj, code))

            qs_all = qs_base.annotate(
                grup_null=Case(
                    When(grup__isnull=True, then=1),
                    default=0,
                    output_field=IntegerField(),
                )
            ).order_by("grup_null", "grup", "ordre_sortida", "id")

            merges = (self.competicio.tab_merges or {}).get(grouping_sig, [])
            merge_map = {}
            merged_label_map = {}

            for group_keys in merges:
                t = tuple(group_keys)
                for x in group_keys:
                    merge_map[x] = t
                merged_key = json.dumps(list(t), ensure_ascii=False)
                merged_label_map[merged_key] = " + ".join(pretty_label_from_simple_key(x) for x in t)

            def tab_label_for_obj(obj):
                if not group_codes:
                    return "Sense agrupació"
                simple = simple_key_for_obj(obj, group_codes)
                mid = merge_map.get(simple)
                if mid:
                    mk = json.dumps(list(mid), ensure_ascii=False)
                    return merged_label_map.get(mk, mk)
                return pretty_label_from_simple_key(simple)

            SENTINEL = object()
            current_grp = SENTINEL
            buffer = []
            row = 1

            def flush_group(objs, grp_num):
                nonlocal row
                if not objs:
                    return
                tab_label = tab_label_for_obj(objs[0])
                group_title = f"{tab_label} · Sense grup" if grp_num is None else f"{tab_label} · Grup {grp_num}"

                ws.cell(row=row, column=1, value=group_title).font = title_font
                ws.cell(row=row, column=1).fill = group_fill
                ws.cell(row=row, column=1).alignment = Alignment(vertical="center")
                ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(columns))
                row += 1

                write_table_header(row)
                row += 1
                for o in objs:
                    write_row(row, o)
                    row += 1
                row += 1

            for obj in qs_all:
                g = obj.grup
                if current_grp is SENTINEL:
                    current_grp = g
                if g != current_grp:
                    flush_group(buffer, current_grp)
                    buffer = []
                    current_grp = g
                buffer.append(obj)

            flush_group(buffer, current_grp)

            for i, (label, _) in enumerate(columns, start=1):
                ws.column_dimensions[get_column_letter(i)].width = max(12, min(35, len(label) + 4))

            out = BytesIO()
            wb.save(out)
            out.seek(0)

            filename = f"inscripcions_competicio_{self.competicio.pk}.xlsx"
            resp = HttpResponse(
                out.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            resp["Content-Disposition"] = f'attachment; filename="{filename}"'
            return resp

        # 0) CLEAR GROUPS
        if request.GET.get("clear_groups") == "1":
            qs = self.get_queryset_base_filtrada()
            save_undo_state(request, qs)
            with transaction.atomic():
                qs.update(grup=None)
                renumber_groups_for_competicio(self.competicio)
            query = request.GET.copy()
            query.pop("clear_groups", None)
            return redirect(f"{request.path}?{query.urlencode()}")

        # 0c) MAKE INDEPENDENT GROUP (subgrup o pestanya)
        if request.GET.get("make_independent_group") == "1":
            lvl = request.GET.get("lvl")  # "g1","g2","g3"

            group_codes = get_active_group_codes()
            if not group_codes:
                messages.error(request, "No hi ha agrupació activa per poder crear un grup independent.")
                query = request.GET.copy()
                for k in ("make_independent_group", "lvl", "v1", "v2", "v3"):
                    query.pop(k, None)
                return redirect(f"{request.path}?{query.urlencode()}")

            v1 = request.GET.get("v1")
            v2 = request.GET.get("v2")
            v3 = request.GET.get("v3")

            def build_filter_ids_from_vals(vals):
                qs_base = self.get_queryset_base_filtrada()
                # en memòria per suportar extra
                builtin_fields = [c for c in group_codes if hasattr(Inscripcio, c)]
                recs = list(qs_base.only("id", "extra", *builtin_fields))
                ids = []
                for r in recs:
                    ok = True
                    for code, vv in zip(group_codes, vals):
                        if _norm_val(get_inscripcio_value(r, code)) != vv:
                            ok = False
                            break
                    if ok:
                        ids.append(r.id)
                return ids

            # CAS: nivell g1 i v1 és una key JSON (simple o merged)
            if lvl == "g1" and v1 and v1.strip().startswith("["):
                try:
                    parsed = json.loads(v1)
                except Exception:
                    parsed = None

                base_qs = self.get_queryset_base_filtrada()

                # merged: llista de strings que són JSON arrays
                if isinstance(parsed, list) and parsed and all(isinstance(x, str) and x.strip().startswith("[") for x in parsed):
                    save_undo_state(request, base_qs)

                    # IDs totals (unió de totes les pestanyes simples)
                    all_ids = []
                    for simple in parsed:
                        try:
                            vals = json.loads(simple)
                        except Exception:
                            continue
                        vals = [_norm_val(x) for x in vals]
                        all_ids.extend(build_filter_ids_from_vals(vals))

                    sub_qs = base_qs.filter(id__in=all_ids)

                # simple: llista de valors
                elif isinstance(parsed, list):
                    vals = [_norm_val(x) for x in parsed]
                    ids = build_filter_ids_from_vals(vals)
                    sub_qs = base_qs.filter(id__in=ids)
                    save_undo_state(request, base_qs)

                else:
                    sub_qs = None

                if sub_qs is not None:
                    existing_groups = list(sub_qs.exclude(grup__isnull=True).values_list("grup", flat=True).distinct())
                    if existing_groups:
                        new_group_num = min(existing_groups)
                        with transaction.atomic():
                            Inscripcio.objects.filter(competicio=self.competicio, grup=new_group_num).update(grup=None)
                            updated = sub_qs.update(grup=new_group_num)
                            renumber_groups_for_competicio(self.competicio)
                    else:
                        max_grup = Inscripcio.objects.filter(competicio=self.competicio).aggregate(m=Max("grup"))["m"] or 0
                        new_group_num = max_grup + 1
                        with transaction.atomic():
                            updated = sub_qs.update(grup=new_group_num)
                            renumber_groups_for_competicio(self.competicio)

                    messages.success(request, f"Creat el grup {new_group_num} amb {updated} inscripcions del subgrup.")
                    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
                    if is_ajax:
                        return JsonResponse({"ok": True, "new_group_num": new_group_num, "updated": updated})

                    query = request.GET.copy()
                    for k in ("make_independent_group", "lvl", "v1", "v2", "v3"):
                        query.pop(k, None)
                    return redirect(f"{request.path}?{query.urlencode()}")

            # CAS clàssic: g1/g2/g3 amb v1/v2/v3 (valors normalitzats)
            level = {"g1": 1, "g2": 2, "g3": 3}.get(lvl, 1)
            vals = []
            if level >= 1:
                vals.append(_norm_val(v1))
            if level >= 2:
                vals.append(_norm_val(v2))
            if level >= 3:
                vals.append(_norm_val(v3))

            ids = build_filter_ids_from_vals(vals)
            base_qs = self.get_queryset_base_filtrada()
            sub_qs = base_qs.filter(id__in=ids)

            save_undo_state(request, base_qs)

            existing_groups = list(sub_qs.exclude(grup__isnull=True).values_list("grup", flat=True).distinct())
            if existing_groups:
                new_group_num = min(existing_groups)
                with transaction.atomic():
                    Inscripcio.objects.filter(competicio=self.competicio, grup=new_group_num).update(grup=None)
                    updated = sub_qs.update(grup=new_group_num)
                    renumber_groups_for_competicio(self.competicio)
            else:
                max_grup = Inscripcio.objects.filter(competicio=self.competicio).aggregate(m=Max("grup"))["m"] or 0
                new_group_num = max_grup + 1
                with transaction.atomic():
                    updated = sub_qs.update(grup=new_group_num)
                    renumber_groups_for_competicio(self.competicio)

            messages.success(request, f"Creat el grup {new_group_num} amb {updated} inscripcions del subgrup.")
            is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
            if is_ajax:
                return JsonResponse({"ok": True, "new_group_num": new_group_num, "updated": updated})

            query = request.GET.copy()
            for k in ("make_independent_group", "lvl", "v1", "v2", "v3"):
                query.pop(k, None)
            return redirect(f"{request.path}?{query.urlencode()}")

        # 0e) SORT BY GROUPING (sense crear grups)
        if request.GET.get("sort_by_grouping") == "1":
            sort_key = resolve_sort_key(request.GET.get("sort_key"))
            sort_dir = request.GET.get("sort_dir") or "asc"
            if sort_dir not in ("asc", "desc", "arrow_asc", "arrow_desc"):
                sort_dir = "asc"

            if not sort_key:
                messages.error(request, "Camp d'ordenació no vàlid.")
                query = request.GET.copy()
                query.pop("sort_by_grouping", None)
                return redirect(f"{request.path}?{query.urlencode()}")

            group_codes = get_active_group_codes()
            grouping_sig = "|".join(group_codes) if group_codes else ""

            qs = self.get_queryset_base_filtrada()
            save_undo_state(request, qs)

            updates = []
            idx = 1
            descending = sort_dir in ("desc", "arrow_desc")
            sort_builtin_fields = [sort_key] if hasattr(Inscripcio, sort_key) else []

            if not group_codes:
                base_records = list(
                    qs.order_by("ordre_sortida", "id").only("id", "extra", *sort_builtin_fields)
                )
                base_list = sort_records_by_field(base_records, sort_key, descending=descending)
                if sort_dir in ("arrow_asc", "arrow_desc"):
                    n = len(base_list)
                    pos = arrow_positions(n)
                    placed = [None] * n
                    for i, obj in enumerate(base_list):
                        placed[pos[i]] = obj
                    for obj in placed:
                        obj.ordre_sortida = idx
                        updates.append(obj)
                        idx += 1
                else:
                    for obj in base_list:
                        obj.ordre_sortida = idx
                        updates.append(obj)
                        idx += 1
            else:
                merges = (self.competicio.tab_merges or {}).get(grouping_sig, [])
                merge_map = {}
                for group_keys in merges:
                    t = tuple(group_keys)
                    for x in group_keys:
                        merge_map[x] = t

                builtin_fields = [c for c in group_codes if hasattr(Inscripcio, c)]
                records = list(
                    qs.order_by("ordre_sortida", "id").only("id", "extra", *builtin_fields, *sort_builtin_fields)
                )
                id_to_record = {r.id: r for r in records}

                tab_to_ids = OrderedDict()
                for r in records:
                    simple = simple_key_for_obj(r, group_codes)
                    mid = merge_map.get(simple)
                    tab_key = json.dumps(list(mid), ensure_ascii=False) if mid else simple
                    tab_to_ids.setdefault(tab_key, []).append(r.id)

                for tab_key, tab_ids in tab_to_ids.items():
                    tab_records = [id_to_record[i] for i in tab_ids if i in id_to_record]
                    base_list = sort_records_by_field(tab_records, sort_key, descending=descending)

                    if sort_dir in ("arrow_asc", "arrow_desc"):
                        n = len(base_list)
                        pos = arrow_positions(n)
                        placed = [None] * n
                        for i, obj in enumerate(base_list):
                            placed[pos[i]] = obj
                        for obj in placed:
                            obj.ordre_sortida = idx
                            updates.append(obj)
                            idx += 1
                    else:
                        for obj in base_list:
                            obj.ordre_sortida = idx
                            updates.append(obj)
                            idx += 1

            with transaction.atomic():
                Inscripcio.objects.bulk_update(updates, ["ordre_sortida"], batch_size=500)

            messages.success(
                request,
                f"Inscripcions ordenades per agrupació ({', '.join(group_codes) or 'cap'}) i camp '{sort_key}' ({sort_dir})."
            )

            query = request.GET.copy()
            for k in ("sort_by_grouping", "sort_key", "sort_dir"):
                query.pop(k, None)
            return redirect(f"{request.path}?{query.urlencode()}")

        # 0d) SORT WITHIN GROUPS
        if request.GET.get("sort_within_groups") == "1":
            sort_key = resolve_sort_key(request.GET.get("sort_key"))
            sort_dir = request.GET.get("sort_dir") or "asc"
            if sort_dir not in ("asc", "desc", "arrow_asc", "arrow_desc"):
                sort_dir = "asc"

            if not sort_key:
                messages.error(request, "Camp d'ordenació no vàlid.")
                query = request.GET.copy()
                for k in ("sort_within_groups", "sort_key", "sort_dir"):
                    query.pop(k, None)
                return redirect(f"{request.path}?{query.urlencode()}")

            qs = self.get_queryset_base_filtrada()
            save_undo_state(request, qs)

            if not qs.exclude(grup__isnull=True).exists():
                messages.info(request, "No hi ha grups assignats per poder reendreçar dins de grup.")
                query = request.GET.copy()
                for k in ("sort_within_groups", "sort_key", "sort_dir"):
                    query.pop(k, None)
                return redirect(f"{request.path}?{query.urlencode()}")

            updates = []
            idx = 1
            descending = sort_dir in ("desc", "arrow_desc")
            sort_builtin_fields = [sort_key] if hasattr(Inscripcio, sort_key) else []

            group_nums = list(
                qs.exclude(grup__isnull=True)
                .order_by("grup")
                .values_list("grup", flat=True)
                .distinct()
            )

            with transaction.atomic():
                for g in group_nums:
                    group_qs = qs.filter(grup=g)
                    group_records = list(
                        group_qs.order_by("ordre_sortida", "id").only("id", "extra", *sort_builtin_fields)
                    )
                    base_list = sort_records_by_field(group_records, sort_key, descending=descending)

                    if sort_dir in ("arrow_asc", "arrow_desc"):
                        n = len(base_list)
                        pos = arrow_positions(n)
                        placed = [None] * n
                        for i, obj in enumerate(base_list):
                            placed[pos[i]] = obj

                        for obj in placed:
                            obj.ordre_sortida = idx
                            updates.append(obj)
                            idx += 1
                    else:
                        for obj in base_list:
                            obj.ordre_sortida = idx
                            updates.append(obj)
                            idx += 1

                Inscripcio.objects.bulk_update(updates, ["ordre_sortida"], batch_size=500)

            messages.success(request, f"Reendreçat dins dels grups per '{sort_key}' ({sort_dir}).")

            query = request.GET.copy()
            for k in ("sort_within_groups", "sort_key", "sort_dir"):
                query.pop(k, None)
            return redirect(f"{request.path}?{query.urlencode()}")

        # 0b) MAKE GROUPS COUNT (k grups per pestanya seleccionada)
        if request.GET.get("make_groups_count") == "1":
            try:
                k = int(request.GET.get("group_count") or 0)
            except ValueError:
                k = 0
            if k < 1:
                messages.error(request, "El nombre de grups ha de ser com a mínim 1.")
                query = request.GET.copy()
                query.pop("make_groups_count", None)
                return redirect(f"{request.path}?{query.urlencode()}")

            qs_base = self.get_queryset_base_filtrada()
            save_undo_state(request, qs_base)

            group_codes = get_active_group_codes()
            grouping_sig = "|".join(group_codes) if group_codes else ""
            tab_keys = request.GET.getlist("tab_keys")  # checkboxes de pestanyes

            # Si no hi ha agrupació -> una sola "pestanya" virtual
            if not group_codes:
                selected_tabs = [("__ALL__", list(qs_base.values_list("id", flat=True)))]
            else:
                merges = (self.competicio.tab_merges or {}).get(grouping_sig, [])
                merge_map = {}
                for group_keys in merges:
                    t = tuple(group_keys)
                    for x in group_keys:
                        merge_map[x] = t

                builtin_fields = [c for c in group_codes if hasattr(Inscripcio, c)]
                records = list(qs_base.order_by("ordre_sortida", "id").only("id", "extra", *builtin_fields))

                tab_to_ids = OrderedDict()
                for r in records:
                    simple = simple_key_for_obj(r, group_codes)
                    mid = merge_map.get(simple)
                    tab_key = json.dumps(list(mid), ensure_ascii=False) if mid else simple
                    tab_to_ids.setdefault(tab_key, []).append(r.id)

                # si user ha seleccionat pestanyes, filtrem
                if tab_keys:
                    selected_tabs = [(tk, tab_to_ids.get(tk, [])) for tk in tab_keys if tk in tab_to_ids]
                else:
                    selected_tabs = list(tab_to_ids.items())

            # Assignació: sobre la unió de pestanyes seleccionades
            selected_ids = []
            seen_ids = set()
            for _tab_key, ids in selected_tabs:
                for ins_id in ids:
                    if ins_id not in seen_ids:
                        seen_ids.add(ins_id)
                        selected_ids.append(ins_id)

            if selected_ids:
                sub_qs = qs_base.filter(id__in=selected_ids).order_by("ordre_sortida", "id")
                objs = list(sub_qs.only("id", "grup"))
                if objs:
                    max_grup = Inscripcio.objects.filter(competicio=self.competicio).aggregate(m=Max("grup"))["m"] or 0
                    assign_groups_k(objs, k, max_grup)
                    Inscripcio.objects.bulk_update(objs, ["grup"], batch_size=500)

            renumber_groups_for_competicio(self.competicio)

            query = request.GET.copy()
            query.pop("make_groups_count", None)
            query.pop("group_count", None)
            query.setlist("tab_keys", [])
            return redirect(f"{request.path}?{query.urlencode()}")

        # 0b) MAKE GROUPS SIZE (mida N)
        if request.GET.get("make_groups") == "1":
            try:
                size = int(request.GET.get("group_size") or 0)
            except ValueError:
                size = 0

            if size < 2:
                messages.error(request, "La mida del grup ha de ser com a mínim 2.")
                query = request.GET.copy()
                query.pop("make_groups", None)
                return redirect(f"{request.path}?{query.urlencode()}")

            group_mode = request.GET.get("group_mode") or "fixed"  # fixed / balanced
            group_codes = get_active_group_codes()

            qs = self.get_queryset_base_filtrada().order_by("ordre_sortida", "id")
            save_undo_state(request, qs)

            builtin_fields = [c for c in group_codes if hasattr(Inscripcio, c)]
            objs = list(qs.only("id", "grup", "extra", *builtin_fields))

            global_group_num = 0

            if not group_codes:
                if group_mode == "balanced":
                    global_group_num = assign_groups_balanced(objs, size, global_group_num)
                else:
                    for idx, obj in enumerate(objs, start=1):
                        obj.grup = (idx - 1) // size + 1
            else:
                if group_mode == "balanced":
                    current_key = None
                    buffer = []

                    def flush_buffer():
                        nonlocal global_group_num, buffer
                        if buffer:
                            global_group_num = assign_groups_balanced(buffer, size, global_group_num)
                            buffer = []

                    for obj in objs:
                        key = tuple(_norm_val(get_inscripcio_value(obj, c)) for c in group_codes)
                        if key != current_key:
                            flush_buffer()
                            current_key = key
                        buffer.append(obj)

                    flush_buffer()
                else:
                    current_key = None
                    count_in_chunk = 0
                    for obj in objs:
                        key = tuple(_norm_val(get_inscripcio_value(obj, c)) for c in group_codes)
                        if key != current_key:
                            current_key = key
                            count_in_chunk = 0
                        if count_in_chunk == 0:
                            global_group_num += 1
                        obj.grup = global_group_num
                        count_in_chunk += 1
                        if count_in_chunk >= size:
                            count_in_chunk = 0

            with transaction.atomic():
                Inscripcio.objects.bulk_update(objs, ["grup"], batch_size=500)
                renumber_groups_for_competicio(self.competicio)

            query = request.GET.copy()
            query.pop("make_groups", None)
            return redirect(f"{request.path}?{query.urlencode()}")

        # 1) CLEAR GROUPING SETTINGS
        if request.GET.get("clear_group") == "1":
            self.competicio.group_by_default = []
            self.competicio.tab_merges = {}
            self.competicio.save(update_fields=["group_by_default", "tab_merges"])

            query = request.GET.copy()
            query.pop("clear_group", None)
            query.setlist("group_by", [])
            return redirect(f"{request.path}?{query.urlencode()}")

        # 2) RECALC ORDER
        if request.GET.get("recalc_order") == "1":
            group_codes = [g for g in request.GET.getlist("group_by") if g in allowed_codes]

            qs = self.get_queryset_base_filtrada()
            save_undo_state(request, qs)

            # versió portable (builtins+extra) -> si tu ja has substituït la funció global recalcular_ordre_sortida,
            # això ja funciona. Si no, fes-ho servir com a fallback:
            records = list(qs.order_by("ordre_sortida", "id"))

            def sort_key(o):
                gvals = tuple(_norm_val(get_inscripcio_value(o, code)) for code in group_codes)
                prev = o.ordre_sortida if o.ordre_sortida is not None else 10**12
                return (gvals, prev, o.id)

            records.sort(key=sort_key)
            with transaction.atomic():
                for idx, obj in enumerate(records, start=1):
                    if obj.ordre_sortida != idx:
                        Inscripcio.objects.filter(id=obj.id).update(ordre_sortida=idx)

            renumber_groups_for_competicio(self.competicio)

            query = request.GET.copy()
            query.pop("recalc_order", None)
            return redirect(f"{request.path}?{query.urlencode()}")

        # 3) SHUFFLE
        if request.GET.get("shuffle_order") == "1":
            qs = self.get_queryset_base_filtrada()
            save_undo_state(request, qs)
            shuffle_ordre_sortida(qs)
            query = request.GET.copy()
            query.pop("shuffle_order", None)
            return redirect(f"{request.path}?{query.urlencode()}")

        # 4) Persistència group_by
        if "group_by" in request.GET:
            selected = [g for g in request.GET.getlist("group_by") if g in allowed_codes]
            if selected != (self.competicio.group_by_default or []):
                self.competicio.group_by_default = selected
                self.competicio.save(update_fields=["group_by_default"])
        else:
            saved = [g for g in (self.competicio.group_by_default or []) if g in allowed_codes]
            if saved:
                query = request.GET.copy()
                for g in saved:
                    query.appendlist("group_by", g)
                return redirect(f"{request.path}?{query.urlencode()}")

        return super().get(request, *args, **kwargs)

    def get_paginate_by(self, queryset):
        if self.request.GET.getlist("group_by"):
            return None

        per_page = self.request.GET.get("per_page")
        if not per_page or per_page == "all":
            return None

        try:
            return int(per_page)
        except ValueError:
            return None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["competicio"] = self.competicio

        allowed = get_allowed_group_fields(self.competicio)
        allowed_codes = {f["code"] for f in allowed}

        ctx["allowed_group_fields"] = allowed
        ctx["current_query"] = self.request.GET.urlencode()
        ctx["title_fields_selected"] = self.request.GET.getlist("title_fields")
        sort_fields = get_available_sort_fields(self.competicio)
        sort_codes = {f["code"] for f in sort_fields}
        raw_sort_key = self.request.GET.get("sort_key") or "nom_i_cognoms"
        sort_key_selected = LEGACY_SORT_KEY_MAP.get(raw_sort_key, raw_sort_key)
        if sort_key_selected not in sort_codes:
            sort_key_selected = "nom_i_cognoms" if "nom_i_cognoms" in sort_codes else (next(iter(sort_codes), ""))
        ctx["sort_field_options"] = sort_fields
        ctx["sort_key_selected"] = sort_key_selected

        selected = self.request.GET.getlist("group_by")
        if not selected:
            selected = self.competicio.group_by_default or []
        selected = [g for g in selected if g in allowed_codes]
        ctx["selected_group_fields"] = selected

        records = self.get_queryset_base_filtrada().order_by("ordre_sortida", "id")
        grouping_sig = "|".join(selected) if selected else ""
        ctx["grouping_sig"] = grouping_sig

        def pretty_val(v):
            return "(Sense valor)" if v in (None, "") else str(v)

        if selected:
            grouped = OrderedDict()
            label_map = {}

            for r in records:
                vals = [_norm_val(get_inscripcio_value(r, code)) for code in selected]
                key = json.dumps(vals, ensure_ascii=False)
                grouped.setdefault(key, []).append(r)

                if key not in label_map:
                    parts = [pretty_val(get_inscripcio_value(r, code)) for code in selected]
                    label_map[key] = " · ".join(parts)

            merges = (self.competicio.tab_merges or {}).get(grouping_sig, [])
            merge_map = {}
            for group_keys in merges:
                if not group_keys:
                    continue
                t = tuple(group_keys)
                for k in group_keys:
                    merge_map[k] = t

            grouped_merged = OrderedDict()
            label_map_merged = {}

            for k, rows in grouped.items():
                merged_tuple = merge_map.get(k)
                if merged_tuple:
                    tab_key = json.dumps(list(merged_tuple), ensure_ascii=False)
                    grouped_merged.setdefault(tab_key, []).extend(rows)
                    if tab_key not in label_map_merged:
                        parts = []
                        for sk in merged_tuple:
                            p = label_map.get(sk, sk)
                            if p not in parts:
                                parts.append(p)
                        label_map_merged[tab_key] = " + ".join(parts)
                else:
                    tab_key = k
                    grouped_merged.setdefault(tab_key, []).extend(rows)
                    if tab_key not in label_map_merged:
                        label_map_merged[tab_key] = label_map.get(k, k)


            records_grouped = [
                (label_map_merged.get(k, k), rows, k)
                for k, rows in grouped_merged.items()
            ]
            ctx["tabs"] = [
                {"key": group_key, "label": group_label, "count": len(group_records)}
                for (group_label, group_records, group_key) in records_grouped
            ]
            
            ctx["records_grouped"] = records_grouped
        else:
            ctx["records_grouped"] = None

        excel_cols = get_available_excel_columns(self.competicio)
        excel_codes = {c["code"] for c in excel_cols}
        ctx["allowed_excel_columns"] = [(c["code"], c.get("ui_label") or c["label"]) for c in excel_cols]

        sel_cols_raw = self.request.GET.getlist("excel_cols")
        sel_cols = []
        for raw in sel_cols_raw:
            code = LEGACY_EXCEL_COL_MAP.get(raw, raw)
            if code in excel_codes and code not in sel_cols:
                sel_cols.append(code)
        if not sel_cols:
            sel_cols = [c["code"] for c in excel_cols]
        ctx["excel_cols_selected"] = sel_cols

        base = self.get_queryset_base_filtrada()
        ctx["categories_distinct"] = list(base.order_by().values_list("categoria", flat=True).distinct())
        ctx["cats_selected"] = self.request.GET.getlist("cats")

        return ctx

class InscripcioUpdateView(UpdateView):
    model = Inscripcio
    pk_url_kwarg = "ins_id"
    form_class = InscripcioForm
    template_name = "competicio/inscripcio_form.html"

    def get_queryset(self):
        # Seguretat: només permet editar inscripcions de la competició del pk
        return Inscripcio.objects.filter(competicio_id=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["competicio"] = get_object_or_404(Competicio, pk=self.kwargs["pk"])
        ctx["next"] = self.request.GET.get("next", "")
        return ctx

    def get_success_url(self):
        nxt = self.request.GET.get("next")
        if nxt:
            return nxt
        return reverse("inscripcions_list", kwargs={"pk": self.kwargs["pk"]})


class InscripcioCreateView(CreateView):
    model = Inscripcio
    form_class = InscripcioForm
    template_name = "competicio/inscripcio_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["competicio"] = self.competicio
        ctx["next"] = self.request.GET.get("next", "")
        return ctx

    def form_valid(self, form):
        # Assign the competition before saving
        form.instance.competicio = self.competicio
        # If ordre_sortida not provided, append to the end
        if not form.instance.ordre_sortida:
            max_ord = Inscripcio.objects.filter(competicio=self.competicio).aggregate(m=Max("ordre_sortida"))["m"] or 0
            form.instance.ordre_sortida = max_ord + 1
        return super().form_valid(form)

    def get_success_url(self):
        nxt = self.request.GET.get("next")
        if nxt:
            return nxt
        return reverse("inscripcions_list", kwargs={"pk": self.kwargs["pk"]})


class InscripcioDeleteView(DeleteView):
    model = Inscripcio
    pk_url_kwarg = "ins_id"
    template_name = "competicio/inscripcio_confirm_delete.html"

    def get_queryset(self):
        return Inscripcio.objects.filter(competicio_id=self.kwargs["pk"])

    def get_success_url(self):
        nxt = self.request.GET.get("next")
        if nxt:
            return nxt
        return reverse("inscripcions_list", kwargs={"pk": self.kwargs["pk"]})


@require_POST
@csrf_protect
def inscripcions_sort_apply(request, pk):
    """
    Ordenacio per columna amb ambits:
      - all   : totes les inscripcions filtrades
      - tab   : dins de cada pestanya (group_by/tab_merges actius)
      - group : nomes un grup numeric (Inscripcio.grup)

    IMPORTANT:
      - Empats mantenen l'ordre previ (acumulacio real).
      - S'aplica sobre el queryset filtrat actual.
    """
    competicio = get_object_or_404(Competicio, pk=pk)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    # --- camp i mode ---
    sort_fields = get_available_sort_fields(competicio)
    sort_codes = {f["code"] for f in sort_fields}

    raw_sort_key = (payload.get("sort_key") or "").strip()
    sort_key = LEGACY_SORT_KEY_MAP.get(raw_sort_key, raw_sort_key)
    if sort_key not in sort_codes:
        return HttpResponseBadRequest("sort_key invalid")

    sort_dir = (payload.get("sort_dir") or "asc").strip()
    if sort_dir not in ("asc", "desc", "arrow_asc", "arrow_desc"):
        return HttpResponseBadRequest("sort_dir invalid")

    scope = (payload.get("scope") or "all").strip().lower()
    if scope not in ("all", "tab", "group"):
        return HttpResponseBadRequest("scope invalid")

    allowed_group_fields = get_allowed_group_fields(competicio)
    allowed_group_codes = {f["code"] for f in allowed_group_fields}
    selected_group_codes_context = _normalize_sort_group_by(
        payload.get("group_by"),
        allowed_group_codes,
        fallback_group_by=competicio.group_by_default or [],
    )

    group_num = payload.get("group_num")
    if scope == "group":
        try:
            group_num = int(group_num)
        except Exception:
            return HttpResponseBadRequest("group_num invalid")
        if group_num <= 0:
            return HttpResponseBadRequest("group_num invalid")

    # --- mateix filtre base que la llista ---
    filters = _normalize_sort_filters(payload.get("filters"))
    context_key = build_inscripcions_sort_context_key(
        competicio.id,
        filters=filters,
        group_by=selected_group_codes_context,
    )
    qs = _build_inscripcions_filtered_qs(competicio, filters)

    # Undo coherent amb la resta d'accions de la pantalla.
    save_undo_state(request, qs)

    records = list(qs.order_by("ordre_sortida", "id"))
    if not records:
        return JsonResponse({"ok": True, "updated": 0, "total": 0, "scope": scope, "stack_count": 0})

    id_to_record = {r.id: r for r in records}
    current_ids = [r.id for r in records]
    state = get_inscripcions_sort_context_state(request, context_key)
    stack_existing_raw = state.get("stack") if isinstance(state.get("stack"), list) else []
    saved_order_sig = str(state.get("order_sig") or "")
    current_order_sig = compute_inscripcions_order_signature_from_ids(current_ids)

    stack_existing = []
    for it in stack_existing_raw:
        normalized = _normalize_sort_criterion(
            it,
            sort_codes=sort_codes,
            allowed_group_codes=allowed_group_codes,
            fallback_group_by=selected_group_codes_context,
        )
        if normalized is not None:
            stack_existing.append(normalized)

    # Si hi ha divergencia d'ordre (canvis externs), reinicia stack.
    if stack_existing and saved_order_sig and saved_order_sig != current_order_sig:
        stack_existing = []

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

    stack_full = stack_existing + [new_entry]
    if len(stack_full) > 20:
        stack_full = stack_full[-20:]

    base_ids_state = state.get("base_ids") if isinstance(state.get("base_ids"), list) else []
    valid_base = (
        isinstance(base_ids_state, list)
        and len(base_ids_state) == len(current_ids)
        and set(base_ids_state) == set(current_ids)
    )
    if not valid_base or not stack_existing:
        base_ids = list(current_ids)
    else:
        base_ids = list(base_ids_state)

    final_ids = _apply_sort_stack(base_ids, id_to_record, stack_full, competicio)

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

    order_sig = compute_inscripcions_order_signature_from_ids(final_ids)
    save_inscripcions_sort_context_state(
        request,
        context_key,
        stack=stack_full,
        order_sig=order_sig,
        base_ids=base_ids,
    )

    return JsonResponse(
        {
            "ok": True,
            "scope": scope,
            "sort_key": sort_key,
            "sort_dir": sort_dir,
            "updated": len(updates),
            "total": len(records),
            "stack_count": len(stack_full),
        }
    )


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
    sort_codes = {f["code"] for f in sort_fields}
    allowed_group_fields = get_allowed_group_fields(competicio)
    allowed_group_codes = {f["code"] for f in allowed_group_fields}

    selected_group_codes_context = _normalize_sort_group_by(
        payload.get("group_by"),
        allowed_group_codes,
        fallback_group_by=competicio.group_by_default or [],
    )
    filters = _normalize_sort_filters(payload.get("filters"))
    context_key = build_inscripcions_sort_context_key(
        competicio.id,
        filters=filters,
        group_by=selected_group_codes_context,
    )

    qs = _build_inscripcions_filtered_qs(competicio, filters)
    records = list(qs.order_by("ordre_sortida", "id"))
    if not records:
        clear_inscripcions_sort_context_state(request, context_key)
        return JsonResponse({"ok": True, "removed": False, "stack_count": 0})

    id_to_record = {r.id: r for r in records}
    current_ids = [r.id for r in records]

    state = get_inscripcions_sort_context_state(request, context_key)
    stack_raw = state.get("stack") if isinstance(state.get("stack"), list) else []
    stack = []
    for it in stack_raw:
        norm = _normalize_sort_criterion(
            it,
            sort_codes=sort_codes,
            allowed_group_codes=allowed_group_codes,
            fallback_group_by=selected_group_codes_context,
        )
        if norm is not None:
            stack.append(norm)

    if not stack:
        clear_inscripcions_sort_context_state(request, context_key)
        return JsonResponse({"ok": True, "removed": False, "stack_count": 0})

    if priority > len(stack):
        return HttpResponseBadRequest("priority out of range")

    save_undo_state(request, qs)

    removed_idx = priority - 1
    removed = stack.pop(removed_idx)

    base_ids_state = state.get("base_ids") if isinstance(state.get("base_ids"), list) else []
    valid_base = (
        isinstance(base_ids_state, list)
        and len(base_ids_state) == len(current_ids)
        and set(base_ids_state) == set(current_ids)
    )
    base_ids = list(base_ids_state) if valid_base else list(current_ids)

    if stack:
        final_ids = _apply_sort_stack(base_ids, id_to_record, stack, competicio)
    else:
        final_ids = list(base_ids)

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

    if stack:
        order_sig = compute_inscripcions_order_signature_from_ids(final_ids)
        save_inscripcions_sort_context_state(
            request,
            context_key,
            stack=stack,
            order_sig=order_sig,
            base_ids=base_ids,
        )
    else:
        clear_inscripcions_sort_context_state(request, context_key)

    return JsonResponse(
        {
            "ok": True,
            "removed": True,
            "removed_priority": priority,
            "removed_sort_key": removed.get("sort_key"),
            "stack_count": len(stack),
            "updated": len(updates),
        }
    )


@require_POST
@csrf_protect
def inscripcions_sort_undo(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    allowed_group_fields = get_allowed_group_fields(competicio)
    allowed_group_codes = {f["code"] for f in allowed_group_fields}
    selected_group_codes_context = _normalize_sort_group_by(
        payload.get("group_by"),
        allowed_group_codes,
        fallback_group_by=competicio.group_by_default or [],
    )
    filters = _normalize_sort_filters(payload.get("filters"))
    context_key = build_inscripcions_sort_context_key(
        competicio.id,
        filters=filters,
        group_by=selected_group_codes_context,
    )

    q = filters["q"]
    categoria = filters["categoria"]
    subcategoria = filters["subcategoria"]
    entitat = filters["entitat"]

    qs = Inscripcio.objects.filter(competicio=competicio)
    if subcategoria:
        qs = qs.filter(subcategoria__iexact=subcategoria)
    if entitat:
        qs = qs.filter(entitat__icontains=entitat)
    if q:
        qs = qs.filter(
            Q(nom_i_cognoms__icontains=q) |
            Q(document__icontains=q) |
            Q(entitat__icontains=q)
        )
    if categoria:
        qs = qs.filter(categoria__iexact=categoria)

    restored = restore_undo_state(request)
    if not restored:
        state = get_inscripcions_sort_context_state(request, context_key)
        return JsonResponse(
            {
                "ok": True,
                "restored": 0,
                "stack_count": len(state.get("stack") or []),
            }
        )

    refreshed_qs = qs.order_by("ordre_sortida", "id")
    order_sig = compute_inscripcions_order_signature_for_queryset(refreshed_qs)
    popped, stack = pop_inscripcions_sort_stack_entry(request, context_key, order_sig=order_sig)

    return JsonResponse(
        {
            "ok": True,
            "restored": restored,
            "popped": bool(popped),
            "stack_count": len(stack),
        }
    )


@require_POST
@csrf_protect
def inscripcions_reorder(request, pk):
    """
    Rep:
      {
        "ids": [<id1>, <id2>, ...],   # ordre final després del drag
        "moved_id": <id>,            # el registre arrossegat
        "new_index": <int>           # posició nova (0-based) dins ids
      }

    Guarda ordre_sortida = 1..N
    I (NOU) només pel registre mogut: adopta el grup del registre immediatament superior.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
        ids = payload.get("ids", [])
        moved_id = payload.get("moved_id", None)
        new_index = payload.get("new_index", None)

        if not isinstance(ids, list) or not ids:
            return HttpResponseBadRequest("Payload invàlid")
    except Exception:
        return HttpResponseBadRequest("JSON invàlid")

    wanted = [int(x) for x in ids if str(x).isdigit()]
    if not wanted:
        return HttpResponseBadRequest("IDs buits")

    # Validació moved_id / new_index (opcional però recomanada)
    if moved_id is not None:
        try:
            moved_id = int(moved_id)
        except Exception:
            return HttpResponseBadRequest("moved_id invàlid")

    if new_index is not None:
        try:
            new_index = int(new_index)
        except Exception:
            return HttpResponseBadRequest("new_index invàlid")

    # Ens assegurem que només reordenem inscripcions d'aquesta competició
    qs = Inscripcio.objects.filter(competicio_id=pk, id__in=wanted)
    found = set(qs.values_list("id", flat=True))
    if set(wanted) != found:
        return HttpResponseBadRequest("IDs no vàlids per aquesta competició")

    # Diccionari id->grup (estat actual abans de canviar)
    id_to_group = dict(qs.values_list("id", "grup"))

    with transaction.atomic():
        # 1) actualitza ordre_sortida
        for idx, ins_id in enumerate(wanted, start=1):
            Inscripcio.objects.filter(id=ins_id).update(ordre_sortida=idx)

        # 2) (NOU) només el registre mogut adopta el grup del superior immediat
        if moved_id is not None and new_index is not None and moved_id in wanted:
            if new_index > 0:
                prev_id = wanted[new_index - 1]
                prev_group = id_to_group.get(prev_id)

                # Mateixa nota: si NO vols que None esborri el grup, fes:
                # if prev_group is not None:
                Inscripcio.objects.filter(id=moved_id).update(grup=prev_group)

    return JsonResponse({"ok": True})


@require_POST
@csrf_protect
def inscripcions_merge_tabs(request, pk):
    c = get_object_or_404(Competicio, pk=pk)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        group_field = payload.get("group_field")   # IMPORTANT: ha de ser la "signature" (grouping_sig)
        source_key = payload.get("source_key")
        target_key = payload.get("target_key")
    except Exception:
        return HttpResponseBadRequest("JSON invàlid")

    if not group_field:
        return HttpResponseBadRequest("group_field buit")
    if not source_key or not target_key or source_key == target_key:
        return HttpResponseBadRequest("claus invàlides")

    merges = c.tab_merges or {}
    lst = merges.get(group_field, [])

    def normalize_key_to_simple_list(k: str) -> list[str]:
        """
        Retorna SEMPRE una llista de 'simple keys' (strings JSON del tipus ["A","B"...]).
        - Si k és simple: retorna [k]
        - Si k és merged: retorna [sub1, sub2, ...] on cada subX és un string JSON d'una clau simple
        """
        try:
            v = json.loads(k)
        except Exception:
            return [k]

        # merged: ['["..."]','["..."]', ...]  (cada element és un JSON de llista)
        if (
            isinstance(v, list) and v
            and all(isinstance(x, str) for x in v)
            and all(x.strip().startswith("[") for x in v)
        ):
            return v

        # simple: ["ALEVI","FEMENI", ...]
        if isinstance(v, list):
            return [k]

        return [k]


    s_list = normalize_key_to_simple_list(source_key)
    t_list = normalize_key_to_simple_list(target_key)

    # Unim t + s preservant ordre i dedup
    desired = []
    for x in (t_list + s_list):
        if x not in desired:
            desired.append(x)

    # Si ja hi ha merges que contenen alguna d'aquestes keys, els absorbim
    consumed_idx = []
    merged_all = []
    for i, g in enumerate(lst):
        # g és una llista de simple keys
        if any(x in g for x in desired):
            merged_all.extend(g)
            consumed_idx.append(i)

    for i in sorted(consumed_idx, reverse=True):
        lst.pop(i)

    merged_all.extend(desired)

    final = []
    for x in merged_all:
        if x not in final:
            final.append(x)

    lst.append(final)
    merges[group_field] = lst
    c.tab_merges = merges
    c.save(update_fields=["tab_merges"])

    return JsonResponse({"ok": True, "merged": final})
