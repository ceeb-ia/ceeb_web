import json

from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .models import Competicio
from .views import InscripcionsListView


BUILTIN_TABLE_FIELDS = [
    {"code": "nom_i_cognoms", "label": "Nom i cognoms", "kind": "builtin"},
    {"code": "document", "label": "DNI/Document", "kind": "builtin"},
    {"code": "sexe", "label": "Sexe", "kind": "builtin"},
    {"code": "data_naixement", "label": "Data naixement", "kind": "builtin"},
    {"code": "entitat", "label": "Entitat", "kind": "builtin"},
    {"code": "categoria", "label": "Categoria", "kind": "builtin"},
    {"code": "subcategoria", "label": "Subcategoria", "kind": "builtin"},
    {"code": "grup", "label": "Grup", "kind": "builtin"},
    {"code": "ordre_sortida", "label": "Ordre", "kind": "builtin"},
]


def get_available_table_columns(competicio):
    """
    Retorna llista [{code, label, kind}] amb builtins + extras detectats + accions.
    """
    out = []
    seen = set()

    for field in BUILTIN_TABLE_FIELDS:
        if field["code"] not in seen:
            out.append(field)
            seen.add(field["code"])

    schema = competicio.inscripcions_schema or {}
    columns = schema.get("columns") or []
    if isinstance(columns, list):
        for col in columns:
            if not isinstance(col, dict):
                continue
            code = col.get("code")
            if not code or code in seen:
                continue
            out.append(
                {
                    "code": code,
                    "label": col.get("label") or code,
                    "kind": col.get("kind") or "extra",
                }
            )
            seen.add(code)

    out.append({"code": "__actions__", "label": "Accions", "kind": "ui"})
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

        available_table_columns = get_available_table_columns(self.competicio)
        selected_table_columns = get_selected_table_columns(
            self.competicio, available_table_columns
        )

        ctx["available_table_columns"] = available_table_columns
        ctx["selected_table_columns"] = selected_table_columns
        ctx["table_colspan"] = len(selected_table_columns) if selected_table_columns else 1

        view_cfg = self.competicio.inscripcions_view or {}
        group_names = view_cfg.get("group_names") or {}
        if isinstance(group_names, dict):
            ctx["group_names"] = {str(k): (v or "") for k, v in group_names.items()}
        else:
            ctx["group_names"] = {}

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
