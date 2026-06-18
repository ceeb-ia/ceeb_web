import os

from django.conf import settings

from ...models.rotacions import (
    RotacioAssignacioGrup,
    RotacioAssignacioProgramUnit,
    RotacioAssignacioSerieEquip,
    RotacioEstacio,
)
from ...models.competicio import CompeticioAparell
from ...services.inscripcions.queries import (
    _normalize_schema_extra_code,
    _reserved_inscripcio_codes,
)
from ...services.rotacions.rotacions_ordering import (
    assignacio_grups,
    assignacio_program_units,
    assignacio_series,
    normalize_positive_int_list,
    unique_ordered,
)


def _normalize_grups(value):
    return normalize_positive_int_list(value)


def _assignacio_grups(assignacio):
    return assignacio_grups(assignacio)


def _group_display_nums_for_ids(group_ids, groups_by_id):
    out = []
    for group_id in group_ids:
        group = groups_by_id.get(group_id)
        if not group:
            continue
        out.append(group.display_num)
    return out


def _sync_assignacio_groups(assignacio, group_ids, groups_by_id):
    clean_ids = unique_ordered(_normalize_grups(group_ids))
    desired = []
    for idx, group_id in enumerate(clean_ids, start=1):
        group = groups_by_id.get(group_id)
        if not group:
            continue
        desired.append((group.id, idx))

    existing = {link.grup_id: link for link in assignacio.grup_links.all()}
    keep_ids = set()
    updates = []
    creates = []
    for group_id, order_idx in desired:
        keep_ids.add(group_id)
        link = existing.get(group_id)
        if link is None:
            creates.append(
                RotacioAssignacioGrup(assignacio=assignacio, grup_id=group_id, ordre=order_idx)
            )
            continue
        if link.ordre != order_idx:
            link.ordre = order_idx
            updates.append(link)

    stale_ids = [gid for gid in existing.keys() if gid not in keep_ids]
    if stale_ids:
        RotacioAssignacioGrup.objects.filter(assignacio=assignacio, grup_id__in=stale_ids).delete()
    if creates:
        RotacioAssignacioGrup.objects.bulk_create(creates, batch_size=200)
    if updates:
        RotacioAssignacioGrup.objects.bulk_update(updates, ["ordre"], batch_size=200)

    legacy_display_nums = _group_display_nums_for_ids(
        [group_id for group_id, _idx in desired],
        groups_by_id,
    )
    assignacio.grups = legacy_display_nums
    assignacio.grup = legacy_display_nums[0] if legacy_display_nums else None
    assignacio.save(update_fields=["grups", "grup"])
    return [group_id for group_id, _idx in desired]


def _normalize_program_keys(values):
    if values is None:
        return []
    raw_values = list(values) if isinstance(values, (list, tuple, set)) else [values]
    out = []
    seen = set()
    for raw in raw_values:
        key = str(raw or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _split_program_keys(values):
    group_ids = []
    serie_ids = []
    program_unit_ids = []
    for key in _normalize_program_keys(values):
        if key.startswith("g:"):
            try:
                group_id = int(key.split(":", 1)[1])
            except Exception:
                continue
            if group_id > 0:
                group_ids.append(group_id)
        elif key.startswith("s:"):
            try:
                serie_id = int(key.split(":", 1)[1])
            except Exception:
                continue
            if serie_id > 0:
                serie_ids.append(serie_id)
        elif key.startswith("pu:"):
            try:
                program_unit_id = int(key.split(":", 1)[1])
            except Exception:
                continue
            if program_unit_id > 0:
                program_unit_ids.append(program_unit_id)
    return unique_ordered(group_ids), unique_ordered(serie_ids), unique_ordered(program_unit_ids)


def _sync_assignacio_series(assignacio, serie_ids, series_by_id):
    clean_ids = unique_ordered(normalize_positive_int_list(serie_ids))
    desired = []
    for idx, serie_id in enumerate(clean_ids, start=1):
        serie = series_by_id.get(serie_id)
        if not serie:
            continue
        desired.append((serie.id, idx))

    existing = {link.serie_id: link for link in assignacio.serie_links.all()}
    keep_ids = set()
    updates = []
    creates = []
    for serie_id, order_idx in desired:
        keep_ids.add(serie_id)
        link = existing.get(serie_id)
        if link is None:
            creates.append(
                RotacioAssignacioSerieEquip(
                    assignacio=assignacio,
                    serie_id=serie_id,
                    ordre=order_idx,
                )
            )
            continue
        if link.ordre != order_idx:
            link.ordre = order_idx
            updates.append(link)

    stale_ids = [serie_id for serie_id in existing.keys() if serie_id not in keep_ids]
    if stale_ids:
        RotacioAssignacioSerieEquip.objects.filter(
            assignacio=assignacio,
            serie_id__in=stale_ids,
        ).delete()
    if creates:
        RotacioAssignacioSerieEquip.objects.bulk_create(creates, batch_size=200)
    if updates:
        RotacioAssignacioSerieEquip.objects.bulk_update(updates, ["ordre"], batch_size=200)
    return [serie_id for serie_id, _idx in desired]


def _sync_assignacio_program_units(assignacio, program_unit_ids, program_units_by_id):
    clean_ids = unique_ordered(normalize_positive_int_list(program_unit_ids))
    desired = []
    for idx, program_unit_id in enumerate(clean_ids, start=1):
        program_unit = program_units_by_id.get(program_unit_id)
        if not program_unit:
            continue
        desired.append((program_unit.id, idx))

    existing = {link.program_unit_id: link for link in assignacio.program_unit_links.all()}
    keep_ids = set()
    updates = []
    creates = []
    for program_unit_id, order_idx in desired:
        keep_ids.add(program_unit_id)
        link = existing.get(program_unit_id)
        if link is None:
            creates.append(
                RotacioAssignacioProgramUnit(
                    assignacio=assignacio,
                    program_unit_id=program_unit_id,
                    ordre=order_idx,
                )
            )
            continue
        if link.ordre != order_idx:
            link.ordre = order_idx
            updates.append(link)

    stale_ids = [program_unit_id for program_unit_id in existing.keys() if program_unit_id not in keep_ids]
    if stale_ids:
        RotacioAssignacioProgramUnit.objects.filter(
            assignacio=assignacio,
            program_unit_id__in=stale_ids,
        ).delete()
    if creates:
        RotacioAssignacioProgramUnit.objects.bulk_create(creates, batch_size=200)
    if updates:
        RotacioAssignacioProgramUnit.objects.bulk_update(updates, ["ordre"], batch_size=200)
    return [program_unit_id for program_unit_id, _idx in desired]


def _assignacio_program_keys(assignacio):
    estacio = getattr(assignacio, "estacio", None)
    is_team_station = bool(
        estacio
        and getattr(estacio, "tipus", "") == "aparell"
        and getattr(getattr(estacio, "comp_aparell", None), "aparell", None)
        and getattr(estacio.comp_aparell.aparell, "competition_unit", "") == "team"
    )
    if is_team_station:
        base_keys = [f"s:{serie_id}" for serie_id in assignacio_series(assignacio)]
    else:
        base_keys = [f"g:{group_id}" for group_id in _assignacio_grups(assignacio)]
    return base_keys + [f"pu:{unit_id}" for unit_id in assignacio_program_units(assignacio)]


ROTACIONS_EXPORT_BUILTIN_FIELDS = [
    {"code": "nom_i_cognoms", "label": "Nom i cognoms", "kind": "builtin"},
    {"code": "membres_equip", "label": "Membres de l'equip", "kind": "builtin"},
    {"code": "document", "label": "DNI/Document", "kind": "builtin"},
    {"code": "sexe", "label": "Sexe", "kind": "builtin"},
    {"code": "data_naixement", "label": "Data naixement", "kind": "builtin"},
    {"code": "entitat", "label": "Entitat", "kind": "builtin"},
    {"code": "categoria", "label": "Categoria", "kind": "builtin"},
    {"code": "subcategoria", "label": "Subcategoria", "kind": "builtin"},
    {"code": "grup", "label": "Grup", "kind": "builtin"},
    {"code": "ordre_sortida", "label": "Ordre", "kind": "builtin"},
]


def _rotacions_available_participant_fields(competicio):
    out = []
    seen = set()
    reserved = _reserved_inscripcio_codes()
    schema = competicio.inscripcions_schema or {}
    cols = schema.get("columns") or []
    excel_codes = set()

    if isinstance(cols, list):
        for column in cols:
            if not isinstance(column, dict):
                continue
            code = column.get("code")
            if not code:
                continue
            kind = column.get("kind") or "extra"
            if kind == "extra":
                code = _normalize_schema_extra_code(code, reserved)
            excel_codes.add(code)

    for field in ROTACIONS_EXPORT_BUILTIN_FIELDS:
        code = field["code"]
        if code in seen:
            continue
        source = "excel" if code in excel_codes else "native"
        out.append(
            {
                **field,
                "source": source,
                "ui_label": f'{field["label"]} ({"Excel" if source == "excel" else "Nativa"})',
            }
        )
        seen.add(code)

    if isinstance(cols, list):
        for column in cols:
            if not isinstance(column, dict):
                continue
            code = column.get("code")
            if not code:
                continue
            kind = column.get("kind") or "extra"
            if kind != "extra":
                continue
            code = _normalize_schema_extra_code(code, reserved)
            if code in seen:
                continue
            label = column.get("label") or code
            out.append(
                {
                    "code": code,
                    "label": label,
                    "kind": "extra",
                    "source": "excel",
                    "ui_label": f"{label} (Excel)",
                }
            )
            seen.add(code)

    return out


def _normalize_export_participant_fields(competicio, raw_fields):
    available = _rotacions_available_participant_fields(competicio)
    allowed_codes = {field["code"] for field in available}
    out = []
    seen = set()

    if isinstance(raw_fields, list):
        for raw in raw_fields:
            code = str(raw or "").strip()
            if not code or code not in allowed_codes or code in seen:
                continue
            seen.add(code)
            out.append(code)

    if out:
        return out
    if "nom_i_cognoms" in allowed_codes:
        return ["nom_i_cognoms"]
    if available:
        return [available[0]["code"]]
    return []


def _export_meta_defaults(competicio):
    data_default = ""
    if getattr(competicio, "data", None):
        try:
            data_default = competicio.data.strftime("%Y-%m-%d")
        except Exception:
            data_default = ""
    return {
        "title": getattr(competicio, "nom", "") or "",
        "venue": getattr(competicio, "seu", "") or "",
        "date": data_default,
        "logo_path": "",
        "participant_fields": ["nom_i_cognoms"],
    }


def _get_export_meta(competicio):
    defaults = _export_meta_defaults(competicio)
    view_cfg = competicio.inscripcions_view or {}
    raw = view_cfg.get("rotacions_export_meta") or {}
    if not isinstance(raw, dict):
        raw = {}

    out = dict(defaults)
    out["title"] = str(raw.get("title", defaults["title"]) or "").strip()
    out["venue"] = str(raw.get("venue", defaults["venue"]) or "").strip()
    out["date"] = str(raw.get("date", defaults["date"]) or "").strip()
    out["logo_path"] = str(raw.get("logo_path", "") or "").strip()
    out["participant_fields"] = _normalize_export_participant_fields(
        competicio,
        raw.get("participant_fields", defaults["participant_fields"]),
    )
    return out


def _save_export_meta(competicio, meta):
    cfg = competicio.inscripcions_view or {}
    raw = cfg.get("rotacions_export_meta") or {}
    if not isinstance(raw, dict):
        raw = {}
    raw.update(meta or {})
    cfg["rotacions_export_meta"] = raw
    competicio.inscripcions_view = cfg
    competicio.save(update_fields=["inscripcions_view"])


def _logo_url_from_path(logo_path: str) -> str:
    logo_path = str(logo_path or "").strip().lstrip("/").replace("\\", "/")
    if not logo_path:
        return ""
    media_url = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/")
    if not media_url.endswith("/"):
        media_url += "/"
    return f"{media_url}{logo_path}"


def _logo_abs_path(logo_path: str) -> str:
    rel = str(logo_path or "").strip().lstrip("/").replace("\\", os.sep)
    if not rel:
        return ""
    media_root = str(getattr(settings, "MEDIA_ROOT", "") or "")
    if not media_root:
        return ""
    return os.path.normpath(os.path.join(media_root, rel))


def _sync_estacions_aparells(competicio):
    comp_aps = list(
        CompeticioAparell.objects.filter(competicio=competicio, actiu=True).order_by("ordre", "id")
    )
    existents = set(
        RotacioEstacio.objects.filter(
            competicio=competicio,
            tipus="aparell",
            comp_aparell__isnull=False,
        ).values_list("comp_aparell_id", flat=True)
    )
    to_create = []
    for comp_aparell in comp_aps:
        if comp_aparell.id not in existents:
            to_create.append(
                RotacioEstacio(
                    competicio=competicio,
                    tipus="aparell",
                    comp_aparell=comp_aparell,
                    ordre=int(getattr(comp_aparell, "ordre", 1) or 1),
                    actiu=True,
                )
            )
    if to_create:
        RotacioEstacio.objects.bulk_create(to_create)


__all__ = [
    "ROTACIONS_EXPORT_BUILTIN_FIELDS",
    "_assignacio_grups",
    "_assignacio_program_keys",
    "_export_meta_defaults",
    "_get_export_meta",
    "_logo_abs_path",
    "_logo_url_from_path",
    "_normalize_export_participant_fields",
    "_normalize_grups",
    "_rotacions_available_participant_fields",
    "_save_export_meta",
    "_split_program_keys",
    "_sync_assignacio_groups",
    "_sync_assignacio_program_units",
    "_sync_assignacio_series",
    "_sync_estacions_aparells",
]
