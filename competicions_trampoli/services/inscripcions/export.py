import json

from .queries import (
    _label_with_source,
    _normalize_schema_extra_code,
    _reserved_inscripcio_codes,
    get_inscripcio_value,
)


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

LEGACY_EXCEL_COL_MAP = {
    "nom": "nom_i_cognoms",
    "dni": "document",
    "naixement": "data_naixement",
    "ordre": "ordre_sortida",
}


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
        kind = col.get("kind") or "extra"
        if kind == "extra":
            code = _normalize_schema_extra_code(code, reserved)
        out.add(code)
    return out


def get_available_excel_columns(competicio):
    out = []
    seen = set()
    excel_codes = _excel_schema_codes(competicio)
    reserved = _reserved_inscripcio_codes()
    for field in BUILTIN_EXCEL_FIELDS:
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
            if not code or code in seen:
                continue
            kind = col.get("kind") or "extra"
            if kind != "extra":
                continue
            code = _normalize_schema_extra_code(code, reserved)
            if code in seen:
                continue
            label = col.get("label") or code
            out.append(
                {"code": code, "label": label, "kind": "extra", "source": "excel", "ui_label": _label_with_source(label, "excel")}
            )
            seen.add(code)
    return out


def get_excel_export_value(obj, code):
    value = get_inscripcio_value(obj, code)
    if code == "data_naixement":
        return value.strftime("%d/%m/%Y") if value else "-"
    if value in (None, ""):
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


__all__ = [
    "BUILTIN_EXCEL_FIELDS",
    "LEGACY_EXCEL_COL_MAP",
    "get_available_excel_columns",
    "get_excel_export_value",
]
