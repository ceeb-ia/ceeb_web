import json

from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Count
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .models import Competicio, Equip, Inscripcio
from .models_trampoli import CompeticioAparell, InscripcioAparellExclusio
from .views import (
    InscripcionsListView,
    get_allowed_group_fields,
    build_inscripcions_sort_context_key,
    get_inscripcions_sort_context_state,
    clear_inscripcions_sort_context_state,
    compute_inscripcions_order_signature_for_queryset,
)


BUILTIN_TABLE_FIELDS = [
    {"code": "nom_i_cognoms", "label": "Nom i cognoms", "kind": "builtin"},
    {"code": "document", "label": "DNI/Document", "kind": "builtin"},
    {"code": "sexe", "label": "Sexe", "kind": "builtin"},
    {"code": "data_naixement", "label": "Data naixement", "kind": "builtin"},
    {"code": "entitat", "label": "Entitat", "kind": "builtin"},
    {"code": "categoria", "label": "Categoria", "kind": "builtin"},
    {"code": "subcategoria", "label": "Subcategoria", "kind": "builtin"},
    {"code": "grup", "label": "Grup", "kind": "builtin"},
    {"code": "equip", "label": "Equip", "kind": "builtin"},
    {"code": "__aparells__", "label": "Aparells", "kind": "ui"},
    {"code": "ordre_sortida", "label": "Ordre", "kind": "builtin"},
]

SYSTEM_NATIVE_TABLE_CODES = {"grup", "equip", "ordre_sortida", "__aparells__", "__actions__"}


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


def _normalize_schema_extra_code(code: str, reserved_codes):
    code = (code or "").strip()
    if not code:
        return code
    if code.startswith("excel__"):
        return code
    if code in reserved_codes:
        return f"excel__{code}"
    return code


def _label_with_source(label: str, source: str):
    suffix = "Excel" if source == "excel" else "Nativa"
    return f"{label} ({suffix})"


def get_available_table_columns(competicio):
    """
    Retorna llista [{code, label, kind}] amb builtins + extras detectats + accions.
    """
    out = []
    seen = set()
    reserved = _reserved_inscripcio_codes()

    schema = competicio.inscripcions_schema or {}
    columns = schema.get("columns") or []
    excel_codes = set()
    if isinstance(columns, list):
        for col in columns:
            if not isinstance(col, dict):
                continue
            code = col.get("code")
            if not code:
                continue
            kind = col.get("kind") or "extra"
            if kind == "extra":
                code = _normalize_schema_extra_code(code, reserved)
            excel_codes.add(code)

    for field in BUILTIN_TABLE_FIELDS:
        if field["code"] not in seen:
            source = "native" if field["code"] in SYSTEM_NATIVE_TABLE_CODES else ("excel" if field["code"] in excel_codes else "native")
            out.append(
                {
                    **field,
                    "source": source,
                    "ui_label": _label_with_source(field["label"], source),
                }
            )
            seen.add(field["code"])

    if isinstance(columns, list):
        for col in columns:
            if not isinstance(col, dict):
                continue
            code = col.get("code")
            if not code:
                continue
            kind = col.get("kind") or "extra"
            if kind == "extra":
                code = _normalize_schema_extra_code(code, reserved)
            if code in seen:
                continue
            label = col.get("label") or code
            out.append(
                {
                    "code": code,
                    "label": label,
                    "kind": kind,
                    "source": "excel",
                    "ui_label": _label_with_source(label, "excel"),
                }
            )
            seen.add(code)

    out.append(
        {
            "code": "__actions__",
            "label": "Accions",
            "kind": "ui",
            "source": "native",
            "ui_label": _label_with_source("Accions", "native"),
        }
    )
    return out


def get_selected_table_columns(competicio, available_cols):
    """
    Retorna columnes seleccionades i ordenades segons competicio.inscripcions_view["table_columns"].
    """
    view_cfg = competicio.inscripcions_view or {}
    selected_codes = view_cfg.get("table_columns")
    if not isinstance(selected_codes, list) or not selected_codes:
        selected_codes = [
            "nom_i_cognoms",
            "document",
            "sexe",
            "data_naixement",
            "entitat",
            "categoria",
            "subcategoria",
            "grup",
            "equip",
            "__aparells__",
            "ordre_sortida",
            "__actions__",
        ]

    by_code = {c["code"]: c for c in available_cols}
    selected = [by_code[c] for c in selected_codes if c in by_code]
    if not selected and "nom_i_cognoms" in by_code:
        selected = [by_code["nom_i_cognoms"]]
    return selected


class InscripcionsListNewView(InscripcionsListView):
    """
    Merge proposat:
    - Manté la logica robusta de views.InscripcionsListView
    - Afegeix la capa UI del borrador (columnes configurables + noms de grup)
    """

    template_name = "competicio/inscricpions_list_new.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filtered_qs = self.get_queryset_base_filtrada()
        ctx["inscrits_filtered_count"] = filtered_qs.count()
        ctx["inscrits_total_count"] = Inscripcio.objects.filter(
            competicio=self.competicio
        ).count()

        available_table_columns = get_available_table_columns(self.competicio)
        selected_table_columns = get_selected_table_columns(
            self.competicio, available_table_columns
        )

        ctx["available_table_columns"] = available_table_columns
        ctx["selected_table_columns"] = selected_table_columns
        ctx["table_colspan"] = len(selected_table_columns) if selected_table_columns else 1
        sort_options = ctx.get("sort_field_options") or []
        ctx["sortable_table_column_codes"] = [
            s.get("code")
            for s in sort_options
            if isinstance(s, dict) and s.get("code")
        ]
        sortable_codes = set(ctx["sortable_table_column_codes"])

        active_group_by = list(ctx.get("selected_group_fields") or [])
        active_filters = {
            "q": self.request.GET.get("q") or "",
            "categoria": self.request.GET.get("categoria") or "",
            "subcategoria": self.request.GET.get("subcategoria") or "",
            "entitat": self.request.GET.get("entitat") or "",
        }
        sort_context_key = build_inscripcions_sort_context_key(
            self.competicio.id,
            filters=active_filters,
            group_by=active_group_by,
        )
        sort_state = get_inscripcions_sort_context_state(self.request, sort_context_key)
        sort_stack = [
            entry
            for entry in (sort_state.get("stack") or [])
            if isinstance(entry, dict) and entry.get("sort_key") in sortable_codes
        ]

        current_order_sig = compute_inscripcions_order_signature_for_queryset(
            filtered_qs.order_by("ordre_sortida", "id")
        )
        saved_order_sig = sort_state.get("order_sig") or ""
        if sort_stack and saved_order_sig and saved_order_sig != current_order_sig:
            clear_inscripcions_sort_context_state(self.request, sort_context_key)
            sort_stack = []
            saved_order_sig = ""

        dir_to_symbol = {
            "asc": "↑",
            "desc": "↓",
            "arrow_asc": "↕↑",
            "arrow_desc": "↕↓",
        }
        dir_to_label = {
            "asc": "Ascendent",
            "desc": "Descendent",
            "arrow_asc": "Fletxa ascendent",
            "arrow_desc": "Fletxa descendent",
        }
        indicator_by_code = {}
        for priority, entry in enumerate(sort_stack, start=1):
            sort_code = str(entry.get("sort_key") or "")
            if not sort_code or sort_code in indicator_by_code:
                continue
            sort_dir = str(entry.get("sort_dir") or "asc")
            scope = str(entry.get("scope") or "all")
            scope_short = "T"
            scope_label = "Totes les inscripcions"
            if scope == "tab":
                scope_short = "P"
                scope_label = "Dins de cada pestanya"
            elif scope == "group":
                group_num = entry.get("group_num")
                scope_short = f"G{group_num}" if group_num else "G"
                scope_label = f"Nomes grup {group_num}" if group_num else "Nomes un grup numeric"

            symbol = dir_to_symbol.get(sort_dir, "↑")
            indicator_by_code[sort_code] = {
                "priority": priority,
                "remove_priority": priority,
                "symbol": symbol,
                "scope_short": scope_short,
                "title": f"#{priority} - {dir_to_label.get(sort_dir, sort_dir)} - {scope_label}",
            }

        ctx["column_sort_context_key"] = sort_context_key
        ctx["column_sort_stack"] = sort_stack
        ctx["column_sort_has_stack"] = bool(sort_stack)
        ctx["column_sort_stack_count"] = len(sort_stack)
        ctx["column_sort_indicator_by_code"] = indicator_by_code

        view_cfg = self.competicio.inscripcions_view or {}
        group_names = view_cfg.get("group_names") or {}
        if isinstance(group_names, dict):
            ctx["group_names"] = {str(k): (v or "") for k, v in group_names.items()}
        else:
            ctx["group_names"] = {}

        team_fields = get_allowed_group_fields(self.competicio)
        team_field_codes = {f["code"] for f in team_fields}
        default_team_fields = [c for c in ("entitat", "subcategoria", "sexe") if c in team_field_codes]
        teams = (
            Equip.objects.filter(competicio=self.competicio)
            .annotate(membres_count=Count("membres"))
            .order_by("nom", "id")
        )
        teams_list = list(teams)
        ctx["team_partition_fields"] = team_fields
        ctx["team_partition_default_fields"] = default_team_fields
        ctx["equips_existing"] = teams_list
        ctx["equip_name_map"] = {str(e.id): e.nom for e in teams_list}

        # Pas 8 del pla: dades necessàries per a la columna "Aparells".
        aparells_cfg = list(
            CompeticioAparell.objects
            .filter(competicio=self.competicio, actiu=True)
            .select_related("aparell")
            .order_by("ordre", "id")
        )
        active_app_ids = [a.id for a in aparells_cfg]
        ctx["inscripcio_aparells_cfg"] = aparells_cfg
        ctx["inscripcio_aparells_active_ids"] = active_app_ids

        visible_ins_ids = set()
        records_grouped = ctx.get("records_grouped")
        if records_grouped:
            for _label, rows, _group_key in records_grouped:
                for r in rows:
                    if getattr(r, "id", None):
                        visible_ins_ids.add(r.id)
        else:
            for r in (ctx.get("records") or []):
                if getattr(r, "id", None):
                    visible_ins_ids.add(r.id)

        excluded_map = {str(ins_id): [] for ins_id in visible_ins_ids}
        if visible_ins_ids and active_app_ids:
            excl_pairs = (
                InscripcioAparellExclusio.objects
                .filter(
                    inscripcio_id__in=visible_ins_ids,
                    comp_aparell_id__in=active_app_ids,
                )
                .values_list("inscripcio_id", "comp_aparell_id")
            )
            for ins_id, app_id in excl_pairs:
                excluded_map.setdefault(str(ins_id), []).append(app_id)
            for ins_id in excluded_map.keys():
                excluded_map[ins_id].sort()

        ctx["inscripcio_aparells_excluded_map"] = excluded_map

        return ctx


@require_POST
@csrf_protect
def inscripcions_save_table_columns(request, pk):
    """
    Desa columnes seleccionades + ordre de la taula d'inscripcions.
    """
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    cols = payload.get("table_columns") or payload.get("columns") or []
    if not isinstance(cols, list):
        return HttpResponseBadRequest("table_columns ha de ser una llista")

    available = get_available_table_columns(competicio)
    allowed_codes = {item["code"] for item in available}

    cleaned = []
    for value in cols:
        if not isinstance(value, str):
            continue
        if value in allowed_codes and value not in cleaned:
            cleaned.append(value)

    if not cleaned:
        return HttpResponseBadRequest("No hi ha cap columna valida")

    view_cfg = competicio.inscripcions_view or {}
    view_cfg["table_columns"] = cleaned
    competicio.inscripcions_view = view_cfg
    competicio.save(update_fields=["inscripcions_view"])
    return JsonResponse({"ok": True, "table_columns": cleaned})


@require_POST
@csrf_protect
def inscripcions_set_group_name(request, pk):
    """
    Desa el nom d'un grup numeric (Inscripcio.grup).
    """
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    group = payload.get("group")
    name = (payload.get("name") or "").strip()
    try:
        group_int = int(group)
    except Exception:
        return HttpResponseBadRequest("group invalid")

    view_cfg = competicio.inscripcions_view or {}
    group_names = view_cfg.get("group_names")
    if not isinstance(group_names, dict):
        group_names = {}

    key = str(group_int)
    if name:
        group_names[key] = name
    else:
        group_names.pop(key, None)

    view_cfg["group_names"] = group_names
    competicio.inscripcions_view = view_cfg
    competicio.save(update_fields=["inscripcions_view"])
    return JsonResponse({"ok": True, "group": group_int, "name": name})


@require_POST
@csrf_protect
def inscripcions_set_aparells(request, pk):
    """
    Desa els aparells on competeix una inscripció.
    Semàntica:
    - selected_comp_aparell_ids = aparells actius on SI competeix
    - la resta d'aparells actius queden exclosos (InscripcioAparellExclusio)
    """
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON invalid")

    inscripcio_id = payload.get("inscripcio_id")
    selected_ids_raw = payload.get("selected_comp_aparell_ids") or []

    try:
        inscripcio_id = int(inscripcio_id)
    except Exception:
        return HttpResponseBadRequest("inscripcio_id invalid")

    if not isinstance(selected_ids_raw, list):
        return HttpResponseBadRequest("selected_comp_aparell_ids ha de ser una llista")

    inscripcio = get_object_or_404(Inscripcio, pk=inscripcio_id, competicio=competicio)

    active_ids = list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .values_list("id", flat=True)
    )
    active_set = set(active_ids)

    selected_set = set()
    for value in selected_ids_raw:
        try:
            v = int(value)
        except Exception:
            return HttpResponseBadRequest("selected_comp_aparell_ids conte valors invalids")
        if v not in active_set:
            return HttpResponseBadRequest("selected_comp_aparell_ids conte aparells no valids per la competicio")
        selected_set.add(v)

    excluded_ids = [app_id for app_id in active_ids if app_id not in selected_set]

    with transaction.atomic():
        # Reemplaça només exclusions dels aparells actius de la competició.
        InscripcioAparellExclusio.objects.filter(
            inscripcio=inscripcio,
            comp_aparell_id__in=active_ids,
        ).delete()

        if excluded_ids:
            InscripcioAparellExclusio.objects.bulk_create(
                [
                    InscripcioAparellExclusio(
                        inscripcio_id=inscripcio.id,
                        comp_aparell_id=app_id,
                    )
                    for app_id in excluded_ids
                ]
            )

    selected_ids = [app_id for app_id in active_ids if app_id in selected_set]
    return JsonResponse(
        {
            "ok": True,
            "inscripcio_id": inscripcio.id,
            "active_comp_aparell_ids": active_ids,
            "selected_comp_aparell_ids": selected_ids,
            "excluded_comp_aparell_ids": excluded_ids,
        }
    )
