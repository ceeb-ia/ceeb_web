import json

from django.utils.text import slugify

from ..models import Equip, EquipContext
from .equip_contexts import (
    NATIVE_EQUIP_CONTEXT_CODE,
    get_equip_context,
    normalize_equip_context_code,
)
from ..models_classificacions import ClassificacioTemplateGlobal
from ..models_scoring import ScoringSchema
from ..models_trampoli import Aparell, CompeticioAparell
from .services_classificacions_2 import (
    BIRTH_YEAR_RANGE_PARTITION_CODE,
    DEFAULT_SCHEMA,
    normalize_particions_config,
    normalize_particions_v2_entries,
    particio_codes_from_entries,
)
from .birth_year_ranges import validate_birth_year_range_partition_config


GLOBAL_NATIVE_PARTICIO_FIELDS = [
    {"code": "categoria", "label": "Categoria", "ui_label": "Categoria (Nativa)", "kind": "builtin", "source": "native"},
    {"code": "subcategoria", "label": "Subcategoria", "ui_label": "Subcategoria (Nativa)", "kind": "builtin", "source": "native"},
    {"code": "entitat", "label": "Entitat", "ui_label": "Entitat (Nativa)", "kind": "builtin", "source": "native"},
    {"code": "sexe", "label": "Sexe", "ui_label": "Sexe (Nativa)", "kind": "builtin", "source": "native"},
    {"code": "data_naixement", "label": "Data naixement", "ui_label": "Data naixement (Nativa)", "kind": "builtin", "source": "native"},
    {"code": BIRTH_YEAR_RANGE_PARTITION_CODE, "label": "Forquilla data naixement", "ui_label": "Forquilla data naixement (Derivada)", "kind": "derived", "source": "derived"},
    {"code": "document", "label": "Document", "ui_label": "Document (Nativa)", "kind": "builtin", "source": "native"},
    {"code": "grup", "label": "Grup", "ui_label": "Grup (Nativa)", "kind": "builtin", "source": "native"},
]

GLOBAL_FILTER_KEYS = {
    "entitats_in",
    "categories_in",
    "subcategories_in",
    "grups_in",
}


def json_clone(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except Exception:
        return {}


def _assignment_teams_queryset(competicio, raw_cfg):
    if isinstance(raw_cfg, dict) and raw_cfg.get("context_code"):
        context_code = normalize_equip_context_code(raw_cfg.get("context_code"))
    else:
        cfg = _normalize_assignment_source(raw_cfg)
        context_code = cfg.get("context_code")
    ctx = get_equip_context(competicio, context_code)
    if ctx is None:
        return Equip.objects.none()
    return Equip.objects.filter(competicio=competicio, context=ctx)


def _normalize_assignment_source(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    raw_mode = str(cfg.get("mode") or "native").strip().lower()
    mode = raw_mode if raw_mode in {"native", "context"} else "native"
    context_code = normalize_equip_context_code(cfg.get("context_code"))
    legacy_mode = mode == "native"
    if legacy_mode:
        mode = "context"
        context_code = NATIVE_EQUIP_CONTEXT_CODE
    fallback = str(cfg.get("fallback") or NATIVE_EQUIP_CONTEXT_CODE).strip().lower()
    if fallback != NATIVE_EQUIP_CONTEXT_CODE:
        fallback = NATIVE_EQUIP_CONTEXT_CODE
    return {
        "mode": mode,
        "context_code": context_code,
        "fallback": fallback,
        "legacy_mode": legacy_mode,
    }


def canon_app_code(raw) -> str:
    return str(raw or "").strip().upper()


def normalize_particions_v2(raw, fallback_codes=None):
    return normalize_particions_v2_entries(raw, fallback_codes=fallback_codes)


def split_particio_custom_values(raw):
    if isinstance(raw, list):
        values = [str(x or "").strip() for x in raw]
    elif isinstance(raw, str):
        values = [x.strip() for x in raw.split(",")]
    else:
        values = []

    out = []
    seen = set()
    for txt in values:
        if not txt:
            continue
        key = " ".join(txt.split()).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(txt)
    return out


def normalize_particions_custom(raw):
    out = {}
    if not isinstance(raw, dict):
        return out

    for field_code, cfg in raw.items():
        code = str(field_code or "").strip()
        if not code or not isinstance(cfg, dict):
            continue

        mode = str(cfg.get("mode") or "raw").strip().lower()
        if mode not in {"raw", "custom"}:
            mode = "raw"

        fallback_label = str(cfg.get("fallback_label") or "").strip()
        groups = []
        for idx, group in enumerate(cfg.get("grups") or []):
            if not isinstance(group, dict):
                continue
            label = (
                str(group.get("label") or group.get("key") or f"Grup {idx + 1}").strip()
                or f"Grup {idx + 1}"
            )
            values = split_particio_custom_values(group.get("values"))
            if not values and not label:
                continue
            groups.append(
                {
                    "key": str(group.get("key") or f"grp_{idx + 1}").strip() or f"grp_{idx + 1}",
                    "label": label,
                    "values": values,
                }
            )

        out[code] = {
            "mode": mode,
            "fallback_label": fallback_label,
            "grups": groups,
        }
    return out


def normalize_particions_schema(schema):
    if not isinstance(schema, dict):
        return {}
    out = dict(schema)
    part_entries = normalize_particions_v2(
        schema.get("particions_v2") or [],
        fallback_codes=schema.get("particions") or [],
    )
    out["particions_v2"] = part_entries
    out["particions"] = particio_codes_from_entries(part_entries)
    out["particions_custom"] = normalize_particions_custom(schema.get("particions_custom") or {})
    out["particions_config"] = normalize_particions_config(schema.get("particions_config") or {})
    return out


def validate_particions_config_global(schema: dict, *, tipus="individual"):
    schema = schema or {}
    errors = []
    part_entries = normalize_particions_v2(
        schema.get("particions_v2") or [],
        fallback_codes=schema.get("particions") or [],
    )
    parts = particio_codes_from_entries(part_entries)
    if BIRTH_YEAR_RANGE_PARTITION_CODE not in parts:
        return errors
    _cfg, cfg_errors = validate_birth_year_range_partition_config(
        ((schema.get("particions_config") or {}).get(BIRTH_YEAR_RANGE_PARTITION_CODE)),
        require_ranges=True,
    )
    for err in cfg_errors:
        errors.append(f"particions_config.any_naixement_forquilla: {err}")
    return errors


def extract_template_schema(payload_or_schema):
    if not isinstance(payload_or_schema, dict):
        return {}
    if isinstance(payload_or_schema.get("schema"), dict):
        return json_clone(payload_or_schema.get("schema") or {})
    return json_clone(payload_or_schema)


def _iter_presentacio_column_groups(presentacio):
    if not isinstance(presentacio, dict):
        return []
    groups = [("presentacio.columnes", presentacio.get("columnes"))]
    detail = presentacio.get("detall")
    if isinstance(detail, dict):
        groups.append(("presentacio.detall.columnes", detail.get("columnes")))
        sections = detail.get("sections") or []
        if isinstance(sections, list):
            for idx, section in enumerate(sections):
                if not isinstance(section, dict):
                    continue
                groups.append((f"presentacio.detall.sections[{idx}].columns", section.get("columns")))
    return groups


def _assign_presentacio_column_group(presentacio, path, cols_out):
    if path == "presentacio.columnes":
        presentacio["columnes"] = cols_out
        return
    detail = presentacio.get("detall") if isinstance(presentacio.get("detall"), dict) else {}
    if path == "presentacio.detall.columnes":
        detail["columnes"] = cols_out
        presentacio["detall"] = detail
        return
    if path.startswith("presentacio.detall.sections[") and path.endswith("].columns"):
        raw_idx = path[len("presentacio.detall.sections[") : -len("].columns")]
        try:
            idx = int(raw_idx)
        except Exception:
            return
        sections = detail.get("sections") if isinstance(detail.get("sections"), list) else []
        if 0 <= idx < len(sections) and isinstance(sections[idx], dict):
            sections[idx]["columns"] = cols_out
            detail["sections"] = sections
            presentacio["detall"] = detail


def get_comp_aparell_maps(competicio, active_only=True):
    qs = CompeticioAparell.objects.filter(competicio=competicio).select_related("aparell").order_by("ordre", "id")
    if active_only:
        qs = qs.filter(actiu=True)
    apps = list(qs)
    by_id = {int(ca.id): ca for ca in apps}
    by_code = {}
    for ca in apps:
        code = canon_app_code(getattr(ca.aparell, "codi", ""))
        if code and code not in by_code:
            by_code[code] = ca
    return apps, by_id, by_code


def get_global_aparell_maps(user, include_inactive=False, include_all_owners=False):
    qs = Aparell.objects.all().order_by("nom", "id")
    if not include_all_owners:
        qs = qs.filter(created_by=user)
    if not include_inactive:
        qs = qs.filter(actiu=True)
    apps = list(qs)
    by_id = {int(app.id): app for app in apps}
    by_code = {}
    for app in apps:
        code = canon_app_code(getattr(app, "codi", ""))
        if code and code not in by_code:
            by_code[code] = app
    return apps, by_id, by_code


def resolve_app_code_for_template(raw, by_id, by_code):
    if raw is None:
        return None
    if isinstance(raw, str):
        txt = raw.strip()
        if not txt:
            return None
        code = canon_app_code(txt)
        if code in by_code:
            return code
        try:
            app_id = int(txt)
        except Exception:
            return None
        obj = by_id.get(app_id)
        if not obj:
            return None
        app = getattr(obj, "aparell", obj)
        return canon_app_code(getattr(app, "codi", ""))
    try:
        app_id = int(raw)
    except Exception:
        return None
    obj = by_id.get(app_id)
    if not obj:
        return None
    app = getattr(obj, "aparell", obj)
    return canon_app_code(getattr(app, "codi", ""))


def resolve_app_id(raw, by_id, by_code):
    if raw is None:
        return None
    if isinstance(raw, str):
        txt = raw.strip()
        if not txt:
            return None
        code = canon_app_code(txt)
        if code in by_code:
            return int(by_code[code].id)
        try:
            app_id = int(txt)
        except Exception:
            return None
        return app_id if app_id in by_id else None
    try:
        app_id = int(raw)
    except Exception:
        return None
    return app_id if app_id in by_id else None


def next_template_slug(base_name: str, owner_id: int, exclude_template_id=None):
    base = slugify(base_name or "") or "classificacio-template"
    slug = base
    idx = 2
    qs = ClassificacioTemplateGlobal.objects.filter(created_by_id=owner_id)
    if exclude_template_id:
        qs = qs.exclude(id=exclude_template_id)
    existing = set(qs.values_list("slug", flat=True))
    while slug in existing:
        slug = f"{base}-{idx}"
        idx += 1
    return slug


def schema_to_template_schema(competicio, schema_local):
    schema = json_clone(schema_local or {})
    warnings = []

    _apps_all, by_id_all, by_code_all = get_comp_aparell_maps(competicio, active_only=False)
    punt = schema.get("puntuacio") or {}
    if not isinstance(punt, dict):
        punt = {}
    schema["puntuacio"] = punt

    raw_apps = punt.get("aparells") or {}
    if not isinstance(raw_apps, dict):
        raw_apps = {}
    ids_in = raw_apps.get("ids") or []
    ids_out = []
    seen_codes = set()
    for raw in ids_in if isinstance(ids_in, list) else []:
        code = resolve_app_code_for_template(raw, by_id_all, by_code_all)
        if not code:
            warnings.append(f"Aparell no exportat (ids): {raw}")
            continue
        if code in seen_codes:
            continue
        seen_codes.add(code)
        ids_out.append(code)
    punt["aparells"] = {"mode": "seleccionar", "ids": ids_out}

    def map_keys_to_codes(raw_map, field_label):
        out = {}
        if not isinstance(raw_map, dict):
            return out
        for raw_key, raw_value in raw_map.items():
            code = resolve_app_code_for_template(raw_key, by_id_all, by_code_all)
            if not code:
                warnings.append(f"{field_label}: aparell no exportat ({raw_key})")
                continue
            out[code] = raw_value
        return out

    def map_tie_item_to_codes(tie, prefix):
        if not isinstance(tie, dict):
            return tie
        item = dict(tie)
        raw_legacy_app = item.get("aparell_id")
        if raw_legacy_app not in (None, "", 0, "0"):
            code = resolve_app_code_for_template(raw_legacy_app, by_id_all, by_code_all)
            if code:
                item["aparell_codi"] = code
            else:
                warnings.append(f"{prefix}.aparell_id no exportat: {raw_legacy_app}")
            item.pop("aparell_id", None)

        scope = item.get("scope") or {}
        if isinstance(scope, dict):
            scope2 = dict(scope)
            apps = scope2.get("aparells") or {}
            if isinstance(apps, dict):
                ids_scope = apps.get("ids") or []
                ids_scope_out = []
                seen_scope = set()
                for raw in ids_scope if isinstance(ids_scope, list) else []:
                    code = resolve_app_code_for_template(raw, by_id_all, by_code_all)
                    if not code:
                        warnings.append(f"{prefix}.scope.aparells.ids no exportat: {raw}")
                        continue
                    if code in seen_scope:
                        continue
                    seen_scope.add(code)
                    ids_scope_out.append(code)
                apps2 = dict(apps)
                apps2["ids"] = ids_scope_out
                scope2["aparells"] = apps2
            item["scope"] = scope2

        item["exercicis_per_aparell"] = map_keys_to_codes(
            item.get("exercicis_per_aparell") or {},
            f"{prefix}.exercicis_per_aparell",
        )
        return item

    punt["camps_per_aparell"] = map_keys_to_codes(punt.get("camps_per_aparell") or {}, "camps_per_aparell")
    punt["exercicis_per_aparell"] = map_keys_to_codes(
        punt.get("exercicis_per_aparell") or {},
        "exercicis_per_aparell",
    )
    victories = punt.get("victories") or {}
    if isinstance(victories, dict):
        victories_out = dict(victories)
        compare_ties = victories_out.get("desempat_comparacio") or []
        if isinstance(compare_ties, list):
            victories_out["desempat_comparacio"] = [
                map_tie_item_to_codes(tie, f"puntuacio.victories.desempat_comparacio[{idx}]")
                for idx, tie in enumerate(compare_ties)
            ]
        punt["victories"] = victories_out

    desempat = schema.get("desempat") or []
    if not isinstance(desempat, list):
        desempat = []
    schema["desempat"] = [
        map_tie_item_to_codes(tie, f"desempat[{idx}]")
        for idx, tie in enumerate(desempat)
    ]

    presentacio = schema.get("presentacio") or {}
    if not isinstance(presentacio, dict):
        presentacio = {}
    for path, cols in _iter_presentacio_column_groups(presentacio):
        if not isinstance(cols, list):
            continue
        cols_out = []
        for idx, col in enumerate(cols):
            if not isinstance(col, dict):
                cols_out.append(col)
                continue
            item = dict(col)
            ctype = str(item.get("type") or "builtin").strip().lower()
            if ctype == "raw":
                src = item.get("source") if isinstance(item.get("source"), dict) else {}
                src2 = dict(src)
                code = resolve_app_code_for_template(src2.get("aparell_codi"), by_id_all, by_code_all)
                if not code:
                    code = resolve_app_code_for_template(src2.get("aparell_id"), by_id_all, by_code_all)
                if code:
                    src2["aparell_codi"] = code
                elif src2.get("aparell_id") not in (None, "", 0, "0"):
                    warnings.append(f"{path}[{idx}] raw: aparell no exportat")
                src2.pop("aparell_id", None)
                item.pop("aparell_id", None)
                item["source"] = src2
            elif ctype == "metric":
                code = resolve_app_code_for_template(item.get("aparell_codi"), by_id_all, by_code_all)
                if not code:
                    code = resolve_app_code_for_template(item.get("aparell_id"), by_id_all, by_code_all)
                if code:
                    item["aparell_codi"] = code
                item.pop("aparell_id", None)
            cols_out.append(item)
        _assign_presentacio_column_group(presentacio, path, cols_out)
    schema["presentacio"] = presentacio

    equips_cfg = schema.get("equips") or {}
    if isinstance(equips_cfg, dict):
        assignment_source = _normalize_assignment_source(equips_cfg.get("assignment_source"))
        context_code = normalize_equip_context_code(
            equips_cfg.get("context_code") or assignment_source.get("context_code")
        )
        if assignment_source.get("legacy_mode"):
            warnings.append("equips.assignment_source.mode='native' detectat; es normalitza al context Base.")
        equips_cfg["assignment_source"] = assignment_source
        equips_cfg["context_code"] = context_code
        manual = equips_cfg.get("particions_manuals") or []
        if isinstance(manual, list):
            team_name_by_id = {
                int(e.id): str(e.nom or "").strip()
                for e in _assignment_teams_queryset(competicio, {"context_code": context_code}).only("id", "nom")
            }
            manual_out = []
            for idx, item in enumerate(manual):
                if not isinstance(item, dict):
                    manual_out.append(item)
                    continue
                row = dict(item)
                names = []
                seen_names = set()
                for raw_id in (row.get("equip_ids") or []):
                    try:
                        eid = int(raw_id)
                    except Exception:
                        continue
                    name = str(team_name_by_id.get(eid) or "").strip()
                    if not name:
                        warnings.append(f"equips.particions_manuals[{idx}]: equip {eid} no exportat")
                        continue
                    key = name.casefold()
                    if key in seen_names:
                        continue
                    seen_names.add(key)
                    names.append(name)
                row.pop("equip_ids", None)
                row["equips_noms"] = names
                manual_out.append(row)
            equips_cfg["particions_manuals"] = manual_out
            schema["equips"] = equips_cfg

    return schema, warnings


def template_schema_to_competicio_schema(competicio, schema_tpl):
    schema = json_clone(schema_tpl or {})
    warnings = []
    compat_meta = {
        "portable": True,
        "missing_context_codes": [],
        "unresolved_manual_team_partitions": [],
    }

    _apps_active, by_id_active, by_code_active = get_comp_aparell_maps(competicio, active_only=True)
    mapping = {code: int(ca.id) for code, ca in by_code_active.items()}

    punt = schema.get("puntuacio") or {}
    if not isinstance(punt, dict):
        punt = {}
    schema["puntuacio"] = punt

    raw_apps = punt.get("aparells") or {}
    if not isinstance(raw_apps, dict):
        raw_apps = {}
    ids_in = raw_apps.get("ids") or []
    ids_out = []
    seen_ids = set()
    for raw in ids_in if isinstance(ids_in, list) else []:
        app_id = resolve_app_id(raw, by_id_active, by_code_active)
        if not app_id:
            warnings.append(f"Aparell no disponible a la competicio: {raw}")
            continue
        if app_id in seen_ids:
            continue
        seen_ids.add(app_id)
        ids_out.append(app_id)
    punt["aparells"] = {"mode": "seleccionar", "ids": ids_out}

    def map_keys_to_ids(raw_map, field_label):
        out = {}
        if not isinstance(raw_map, dict):
            return out
        for raw_key, raw_value in raw_map.items():
            app_id = resolve_app_id(raw_key, by_id_active, by_code_active)
            if not app_id:
                warnings.append(f"{field_label}: aparell no disponible ({raw_key})")
                continue
            out[str(app_id)] = raw_value
        return out

    def map_tie_item_to_ids(tie, prefix):
        if not isinstance(tie, dict):
            return tie
        item = dict(tie)
        raw_code = item.get("aparell_codi")
        if raw_code not in (None, "", 0, "0"):
            app_id = resolve_app_id(raw_code, by_id_active, by_code_active)
            if app_id:
                item["aparell_id"] = app_id
            else:
                warnings.append(f"{prefix}.aparell_codi no disponible: {raw_code}")
        item.pop("aparell_codi", None)

        scope = item.get("scope") or {}
        if isinstance(scope, dict):
            scope2 = dict(scope)
            apps = scope2.get("aparells") or {}
            if isinstance(apps, dict):
                ids_scope = apps.get("ids") or []
                ids_scope_out = []
                seen_scope = set()
                for raw in ids_scope if isinstance(ids_scope, list) else []:
                    app_id = resolve_app_id(raw, by_id_active, by_code_active)
                    if not app_id:
                        warnings.append(f"{prefix}.scope.aparells.ids no disponible: {raw}")
                        continue
                    if app_id in seen_scope:
                        continue
                    seen_scope.add(app_id)
                    ids_scope_out.append(app_id)
                apps2 = dict(apps)
                apps2["ids"] = ids_scope_out
                scope2["aparells"] = apps2
            item["scope"] = scope2

        item["exercicis_per_aparell"] = map_keys_to_ids(
            item.get("exercicis_per_aparell") or {},
            f"{prefix}.exercicis_per_aparell",
        )
        return item

    punt["camps_per_aparell"] = map_keys_to_ids(punt.get("camps_per_aparell") or {}, "camps_per_aparell")
    punt["exercicis_per_aparell"] = map_keys_to_ids(
        punt.get("exercicis_per_aparell") or {},
        "exercicis_per_aparell",
    )
    victories = punt.get("victories") or {}
    if isinstance(victories, dict):
        victories_out = dict(victories)
        compare_ties = victories_out.get("desempat_comparacio") or []
        if isinstance(compare_ties, list):
            victories_out["desempat_comparacio"] = [
                map_tie_item_to_ids(tie, f"puntuacio.victories.desempat_comparacio[{idx}]")
                for idx, tie in enumerate(compare_ties)
            ]
        punt["victories"] = victories_out

    desempat = schema.get("desempat") or []
    if not isinstance(desempat, list):
        desempat = []
    schema["desempat"] = [
        map_tie_item_to_ids(tie, f"desempat[{idx}]")
        for idx, tie in enumerate(desempat)
    ]

    presentacio = schema.get("presentacio") or {}
    if isinstance(presentacio, dict):
        for path, cols in _iter_presentacio_column_groups(presentacio):
            if not isinstance(cols, list):
                continue
            cols_out = []
            for idx, col in enumerate(cols):
                if not isinstance(col, dict):
                    cols_out.append(col)
                    continue
                item = dict(col)
                ctype = str(item.get("type") or "builtin").strip().lower()
                if ctype == "raw":
                    src = item.get("source") if isinstance(item.get("source"), dict) else {}
                    src2 = dict(src)
                    app_id = resolve_app_id(src2.get("aparell_codi"), by_id_active, by_code_active)
                    if not app_id:
                        app_id = resolve_app_id(src2.get("aparell_id"), by_id_active, by_code_active)
                    if app_id:
                        src2["aparell_id"] = app_id
                    elif src2.get("aparell_codi") not in (None, "", 0, "0") or src2.get("aparell_id") not in (None, "", 0, "0"):
                        warnings.append(f"{path}[{idx}] raw: aparell no disponible")
                    src2.pop("aparell_codi", None)
                    item["source"] = src2
                    item.pop("aparell_codi", None)
                elif ctype == "metric":
                    app_id = resolve_app_id(item.get("aparell_codi"), by_id_active, by_code_active)
                    if not app_id:
                        app_id = resolve_app_id(item.get("aparell_id"), by_id_active, by_code_active)
                    if app_id:
                        item["aparell_id"] = app_id
                    item.pop("aparell_codi", None)
                cols_out.append(item)
            _assign_presentacio_column_group(presentacio, path, cols_out)
        schema["presentacio"] = presentacio

    equips_cfg = schema.get("equips") or {}
    if isinstance(equips_cfg, dict):
        assignment_source = _normalize_assignment_source(equips_cfg.get("assignment_source"))
        context_code = normalize_equip_context_code(
            equips_cfg.get("context_code") or assignment_source.get("context_code")
        )
        valid_codes = set(
            EquipContext.objects
            .filter(competicio=competicio)
            .values_list("code", flat=True)
        )
        if context_code not in valid_codes:
            warnings.append(
                f"equips.context_code '{context_code}' no trobat a la competicio desti"
            )
            compat_meta["missing_context_codes"].append(context_code)
        equips_cfg["assignment_source"] = assignment_source
        equips_cfg["context_code"] = context_code
        manual = equips_cfg.get("particions_manuals") or []
        if isinstance(manual, list):
            teams = list(_assignment_teams_queryset(competicio, {"context_code": context_code}).only("id", "nom"))
            id_by_name = {}
            for t in teams:
                key = str(t.nom or "").strip().casefold()
                if key and key not in id_by_name:
                    id_by_name[key] = int(t.id)
            manual_out = []
            for idx, item in enumerate(manual):
                if not isinstance(item, dict):
                    manual_out.append(item)
                    continue
                row = dict(item)
                names = row.get("equips_noms") or []
                out_ids = []
                seen_eq = set()
                missing_names = []
                for raw_name in names if isinstance(names, list) else []:
                    key = str(raw_name or "").strip().casefold()
                    if not key:
                        continue
                    eid = id_by_name.get(key)
                    if not eid:
                        warnings.append(
                            f"equips.particions_manuals[{idx}]: equip '{raw_name}' no trobat al context seleccionat"
                        )
                        missing_names.append(str(raw_name or "").strip())
                        continue
                    if eid in seen_eq:
                        continue
                    seen_eq.add(eid)
                    out_ids.append(eid)
                row["equip_ids"] = out_ids
                if isinstance(names, list):
                    row["equips_noms"] = [str(name or "").strip() for name in names if str(name or "").strip()]
                if missing_names:
                    compat_meta["unresolved_manual_team_partitions"].append(
                        {
                            "index": idx,
                            "label": str(row.get("label") or row.get("key") or f"Particio {idx + 1}").strip(),
                            "context_code": context_code,
                            "missing_names": missing_names,
                        }
                    )
                manual_out.append(row)
            equips_cfg["particions_manuals"] = manual_out
            schema["equips"] = equips_cfg

    compat_meta["missing_context_codes"] = sorted(
        {normalize_equip_context_code(code) for code in compat_meta["missing_context_codes"] if str(code or "").strip()}
    )
    compat_meta["adaptable"] = bool(
        compat_meta["missing_context_codes"] or compat_meta["unresolved_manual_team_partitions"]
    )

    return schema, warnings, mapping, compat_meta


def template_schema_to_global_ui_schema(schema_tpl, by_id, by_code):
    schema = json_clone(schema_tpl or {})
    warnings = []

    punt = schema.get("puntuacio") or {}
    if not isinstance(punt, dict):
        punt = {}
    schema["puntuacio"] = punt

    raw_apps = punt.get("aparells") or {}
    if not isinstance(raw_apps, dict):
        raw_apps = {}
    ids_in = raw_apps.get("ids") or []
    ids_out = []
    seen_ids = set()
    for raw in ids_in if isinstance(ids_in, list) else []:
        app_id = resolve_app_id(raw, by_id, by_code)
        if not app_id:
            warnings.append(f"Aparell global no disponible: {raw}")
            continue
        if app_id in seen_ids:
            continue
        seen_ids.add(app_id)
        ids_out.append(app_id)
    punt["aparells"] = {"mode": "seleccionar", "ids": ids_out}

    def map_keys_to_ids(raw_map):
        out = {}
        if not isinstance(raw_map, dict):
            return out
        for raw_key, raw_value in raw_map.items():
            app_id = resolve_app_id(raw_key, by_id, by_code)
            if app_id:
                out[str(app_id)] = raw_value
        return out

    def map_tie_item_to_ids(tie):
        if not isinstance(tie, dict):
            return tie
        item = dict(tie)
        raw_code = item.get("aparell_codi")
        if raw_code not in (None, "", 0, "0"):
            app_id = resolve_app_id(raw_code, by_id, by_code)
            if app_id:
                item["aparell_id"] = app_id
        item.pop("aparell_codi", None)

        scope = item.get("scope") or {}
        if isinstance(scope, dict):
            scope2 = dict(scope)
            apps = scope2.get("aparells") or {}
            if isinstance(apps, dict):
                ids_scope = apps.get("ids") or []
                ids_scope_out = []
                seen_scope = set()
                for raw in ids_scope if isinstance(ids_scope, list) else []:
                    app_id = resolve_app_id(raw, by_id, by_code)
                    if not app_id or app_id in seen_scope:
                        continue
                    seen_scope.add(app_id)
                    ids_scope_out.append(app_id)
                apps2 = dict(apps)
                apps2["ids"] = ids_scope_out
                scope2["aparells"] = apps2
            item["scope"] = scope2
        item["exercicis_per_aparell"] = map_keys_to_ids(item.get("exercicis_per_aparell") or {})
        return item

    punt["camps_per_aparell"] = map_keys_to_ids(punt.get("camps_per_aparell") or {})
    punt["exercicis_per_aparell"] = map_keys_to_ids(punt.get("exercicis_per_aparell") or {})
    victories = punt.get("victories") or {}
    if isinstance(victories, dict):
        victories_out = dict(victories)
        compare_ties = victories_out.get("desempat_comparacio") or []
        if isinstance(compare_ties, list):
            victories_out["desempat_comparacio"] = [map_tie_item_to_ids(tie) for tie in compare_ties]
        punt["victories"] = victories_out

    desempat = schema.get("desempat") or []
    if isinstance(desempat, list):
        schema["desempat"] = [map_tie_item_to_ids(tie) for tie in desempat]

    presentacio = schema.get("presentacio") or {}
    if isinstance(presentacio, dict):
        for path, cols in _iter_presentacio_column_groups(presentacio):
            if not isinstance(cols, list):
                continue
            cols_out = []
            for col in cols:
                if not isinstance(col, dict):
                    cols_out.append(col)
                    continue
                item = dict(col)
                ctype = str(item.get("type") or "builtin").strip().lower()
                if ctype == "raw":
                    src = item.get("source") if isinstance(item.get("source"), dict) else {}
                    src2 = dict(src)
                    app_id = resolve_app_id(src2.get("aparell_codi"), by_id, by_code)
                    if app_id:
                        src2["aparell_id"] = app_id
                    src2.pop("aparell_codi", None)
                    item["source"] = src2
                elif ctype == "metric":
                    app_id = resolve_app_id(item.get("aparell_codi"), by_id, by_code)
                    if app_id:
                        item["aparell_id"] = app_id
                    item.pop("aparell_codi", None)
                cols_out.append(item)
            _assign_presentacio_column_group(presentacio, path, cols_out)
        schema["presentacio"] = presentacio

    return schema, warnings


def global_ui_schema_to_template_schema(schema_ui, by_id, by_code):
    schema = json_clone(schema_ui or {})
    warnings = []

    punt = schema.get("puntuacio") or {}
    if not isinstance(punt, dict):
        punt = {}
    schema["puntuacio"] = punt

    raw_apps = punt.get("aparells") or {}
    if not isinstance(raw_apps, dict):
        raw_apps = {}
    ids_in = raw_apps.get("ids") or []
    ids_out = []
    seen_codes = set()
    for raw in ids_in if isinstance(ids_in, list) else []:
        code = resolve_app_code_for_template(raw, by_id, by_code)
        if not code:
            warnings.append(f"Aparell global no exportat: {raw}")
            continue
        if code in seen_codes:
            continue
        seen_codes.add(code)
        ids_out.append(code)
    punt["aparells"] = {"mode": "seleccionar", "ids": ids_out}

    def map_keys_to_codes(raw_map):
        out = {}
        if not isinstance(raw_map, dict):
            return out
        for raw_key, raw_value in raw_map.items():
            code = resolve_app_code_for_template(raw_key, by_id, by_code)
            if code:
                out[code] = raw_value
        return out

    def map_tie_item_to_codes(tie):
        if not isinstance(tie, dict):
            return tie
        item = dict(tie)
        raw_legacy_app = item.get("aparell_id")
        if raw_legacy_app not in (None, "", 0, "0"):
            code = resolve_app_code_for_template(raw_legacy_app, by_id, by_code)
            if code:
                item["aparell_codi"] = code
            item.pop("aparell_id", None)

        scope = item.get("scope") or {}
        if isinstance(scope, dict):
            scope2 = dict(scope)
            apps = scope2.get("aparells") or {}
            if isinstance(apps, dict):
                ids_scope = apps.get("ids") or []
                ids_scope_out = []
                seen_scope = set()
                for raw in ids_scope if isinstance(ids_scope, list) else []:
                    code = resolve_app_code_for_template(raw, by_id, by_code)
                    if not code or code in seen_scope:
                        continue
                    seen_scope.add(code)
                    ids_scope_out.append(code)
                apps2 = dict(apps)
                apps2["ids"] = ids_scope_out
                scope2["aparells"] = apps2
            item["scope"] = scope2
        item["exercicis_per_aparell"] = map_keys_to_codes(item.get("exercicis_per_aparell") or {})
        return item

    punt["camps_per_aparell"] = map_keys_to_codes(punt.get("camps_per_aparell") or {})
    punt["exercicis_per_aparell"] = map_keys_to_codes(punt.get("exercicis_per_aparell") or {})
    victories = punt.get("victories") or {}
    if isinstance(victories, dict):
        victories_out = dict(victories)
        compare_ties = victories_out.get("desempat_comparacio") or []
        if isinstance(compare_ties, list):
            victories_out["desempat_comparacio"] = [map_tie_item_to_codes(tie) for tie in compare_ties]
        punt["victories"] = victories_out

    desempat = schema.get("desempat") or []
    if isinstance(desempat, list):
        schema["desempat"] = [map_tie_item_to_codes(tie) for tie in desempat]

    presentacio = schema.get("presentacio") or {}
    if isinstance(presentacio, dict):
        for path, cols in _iter_presentacio_column_groups(presentacio):
            if not isinstance(cols, list):
                continue
            cols_out = []
            for col in cols:
                if not isinstance(col, dict):
                    cols_out.append(col)
                    continue
                item = dict(col)
                ctype = str(item.get("type") or "builtin").strip().lower()
                if ctype == "raw":
                    src = item.get("source") if isinstance(item.get("source"), dict) else {}
                    src2 = dict(src)
                    code = resolve_app_code_for_template(src2.get("aparell_id"), by_id, by_code)
                    if code:
                        src2["aparell_codi"] = code
                    src2.pop("aparell_id", None)
                    item["source"] = src2
                elif ctype == "metric":
                    code = resolve_app_code_for_template(item.get("aparell_id"), by_id, by_code)
                    if code:
                        item["aparell_codi"] = code
                    item.pop("aparell_id", None)
                cols_out.append(item)
            _assign_presentacio_column_group(presentacio, path, cols_out)
        schema["presentacio"] = presentacio

    return schema, warnings


def collect_required_app_codes_from_template(schema_tpl):
    schema = schema_tpl or {}
    out = set()
    punt = schema.get("puntuacio") or {}
    if isinstance(punt, dict):
        apps = punt.get("aparells") or {}
        if isinstance(apps, dict):
            for raw in (apps.get("ids") or []):
                code = canon_app_code(raw)
                if code:
                    out.add(code)
        for raw_key in (punt.get("camps_per_aparell") or {}).keys() if isinstance(punt.get("camps_per_aparell"), dict) else []:
            code = canon_app_code(raw_key)
            if code:
                out.add(code)
        for raw_key in (punt.get("exercicis_per_aparell") or {}).keys() if isinstance(punt.get("exercicis_per_aparell"), dict) else []:
            code = canon_app_code(raw_key)
            if code:
                out.add(code)
    desempat = schema.get("desempat") or []
    if isinstance(desempat, list):
        for tie in desempat:
            if not isinstance(tie, dict):
                continue
            code = canon_app_code(tie.get("aparell_codi"))
            if code:
                out.add(code)
            scope = tie.get("scope") or {}
            if isinstance(scope, dict):
                apps = scope.get("aparells") or {}
                if isinstance(apps, dict):
                    for raw in (apps.get("ids") or []):
                        code = canon_app_code(raw)
                        if code:
                            out.add(code)
    presentacio = schema.get("presentacio") or {}
    if isinstance(presentacio, dict):
        for _path, cols in _iter_presentacio_column_groups(presentacio):
            for col in cols or []:
                if not isinstance(col, dict):
                    continue
                ctype = str(col.get("type") or "builtin").strip().lower()
                if ctype == "raw":
                    src = col.get("source") if isinstance(col.get("source"), dict) else {}
                    code = canon_app_code(src.get("aparell_codi"))
                    if code:
                        out.add(code)
                elif ctype == "metric":
                    code = canon_app_code(col.get("aparell_codi"))
                    if code:
                        out.add(code)
    return out


def build_template_requirements(schema_tpl, *, tipus=None):
    schema = schema_tpl or {}
    punt = schema.get("puntuacio") or {}
    if not isinstance(punt, dict):
        punt = {}

    part_entries = normalize_particions_v2(
        schema.get("particions_v2") or [],
        fallback_codes=schema.get("particions") or [],
    )
    equips_cfg = schema.get("equips") or {}
    if not isinstance(equips_cfg, dict):
        equips_cfg = {}
    assignment_source = _normalize_assignment_source(equips_cfg.get("assignment_source"))
    context_code = normalize_equip_context_code(
        equips_cfg.get("context_code") or assignment_source.get("context_code")
    ) if equips_cfg else ""
    team_mode = str(equips_cfg.get("team_mode") or "").strip().lower()
    manual_defs = equips_cfg.get("particions_manuals") or []

    req = {
        "tipus": str(tipus or schema.get("tipus") or "individual").strip().lower() or "individual",
        "aparells_codis": sorted(collect_required_app_codes_from_template(schema)),
        "particions": particio_codes_from_entries(part_entries),
        "camps_per_aparell": {},
        "desempat_camps": [],
        "team_mode": team_mode,
        "context_code": context_code if context_code else "",
        "uses_manual_team_partitions": bool(isinstance(manual_defs, list) and manual_defs),
        "uses_exercise_selection_scope": False,
        "exercise_selection_scope": "",
        "exercise_selection_scope_modes": [],
        "presentacio_raw_camps": [],
        "presentacio_metric_camps": [],
    }

    camps_map = punt.get("camps_per_aparell") or {}
    if isinstance(camps_map, dict):
        for raw_key, raw_codes in camps_map.items():
            code = canon_app_code(raw_key)
            if not code:
                continue
            vals = []
            if isinstance(raw_codes, list):
                vals = [str(x).strip() for x in raw_codes if str(x).strip()]
            elif isinstance(raw_codes, str):
                vals = [x.strip() for x in raw_codes.split(",") if x.strip()]
            req["camps_per_aparell"][code] = vals

    tie_codes = set()
    for tie in (schema.get("desempat") or []):
        if not isinstance(tie, dict):
            continue
        for code in normalize_tie_camps_for_validation(tie):
            if code:
                tie_codes.add(str(code).strip())
    victories = punt.get("victories") or {}
    for tie in (victories.get("desempat_comparacio") or []) if isinstance(victories, dict) else []:
        if not isinstance(tie, dict):
            continue
        for code in normalize_tie_camps_for_validation(tie):
            if code:
                tie_codes.add(str(code).strip())
    req["desempat_camps"] = sorted([c for c in tie_codes if c])

    exercise_scopes = set()
    main_scope = str(punt.get("exercise_selection_scope") or "").strip().lower()
    if main_scope:
        exercise_scopes.add(main_scope)
        req["exercise_selection_scope"] = main_scope
    for tie in (schema.get("desempat") or []):
        if not isinstance(tie, dict):
            continue
        tie_scope = str(tie.get("exercise_selection_scope") or "").strip().lower()
        if tie_scope:
            exercise_scopes.add(tie_scope)
    for tie in (victories.get("desempat_comparacio") or []) if isinstance(victories, dict) else []:
        if not isinstance(tie, dict):
            continue
        tie_scope = str(tie.get("exercise_selection_scope") or "").strip().lower()
        if tie_scope:
            exercise_scopes.add(tie_scope)
    req["uses_exercise_selection_scope"] = bool(exercise_scopes)
    req["exercise_selection_scope_modes"] = sorted(exercise_scopes)

    raw_camps = set()
    metric_camps = set()
    presentacio = schema.get("presentacio") or {}
    if isinstance(presentacio, dict):
        for _path, cols in _iter_presentacio_column_groups(presentacio):
            for col in cols or []:
                if not isinstance(col, dict):
                    continue
                ctype = str(col.get("type") or "builtin").strip().lower()
                if ctype == "raw":
                    src = col.get("source") if isinstance(col.get("source"), dict) else {}
                    camp = str(src.get("camp") or "").strip()
                    if camp:
                        raw_camps.add(camp)
                elif ctype == "metric":
                    criteri = col.get("criteri") if isinstance(col.get("criteri"), dict) else {}
                    for code in normalize_tie_camps_for_validation(criteri):
                        if code:
                            metric_camps.add(str(code).strip())
    req["presentacio_raw_camps"] = sorted(raw_camps)
    req["presentacio_metric_camps"] = sorted(metric_camps)
    return req


def build_global_native_particio_fields():
    return json_clone(GLOBAL_NATIVE_PARTICIO_FIELDS)


def collect_global_builder_legacy_keys(schema_tpl, *, allowed_particio_codes, allowed_filter_keys=None):
    schema = normalize_particions_schema(extract_template_schema(schema_tpl))
    allowed_particio_codes = {str(code or "").strip() for code in (allowed_particio_codes or []) if str(code or "").strip()}
    allowed_filter_keys = {str(key or "").strip() for key in (allowed_filter_keys or []) if str(key or "").strip()}

    legacy_particio_codes = set()
    for entry in normalize_particions_v2(
        schema.get("particions_v2") or [],
        fallback_codes=schema.get("particions") or [],
    ):
        code = str(entry.get("code") or "").strip()
        if code and code not in allowed_particio_codes:
            legacy_particio_codes.add(code)
    for code in normalize_particions_custom(schema.get("particions_custom") or {}):
        if code and code not in allowed_particio_codes:
            legacy_particio_codes.add(code)

    legacy_filter_keys = set()
    filtres = schema.get("filtres") or {}
    if isinstance(filtres, dict):
        for key in filtres:
            key_txt = str(key or "").strip()
            if key_txt and key_txt not in allowed_filter_keys:
                legacy_filter_keys.add(key_txt)

    return legacy_particio_codes, legacy_filter_keys


def merge_global_builder_schema(existing_schema_tpl, updated_schema_tpl, *, allowed_particio_codes, allowed_filter_keys=None):
    existing = normalize_particions_schema(extract_template_schema(existing_schema_tpl))
    updated = normalize_particions_schema(updated_schema_tpl or {})
    allowed_particio_codes = {str(code or "").strip() for code in (allowed_particio_codes or []) if str(code or "").strip()}
    allowed_filter_keys = {str(key or "").strip() for key in (allowed_filter_keys or []) if str(key or "").strip()}

    merged = json_clone(updated)

    existing_entries = normalize_particions_v2(
        existing.get("particions_v2") or [],
        fallback_codes=existing.get("particions") or [],
    )
    updated_entries = normalize_particions_v2(
        merged.get("particions_v2") or [],
        fallback_codes=merged.get("particions") or [],
    )
    legacy_entries = []
    for entry in existing_entries:
        code = str(entry.get("code") or "").strip()
        if code and code not in allowed_particio_codes:
            legacy_entries.append(json_clone(entry))
    if legacy_entries:
        merged["particions_v2"] = updated_entries + legacy_entries
        merged["particions"] = particio_codes_from_entries(merged["particions_v2"])

    existing_custom = normalize_particions_custom(existing.get("particions_custom") or {})
    updated_custom = normalize_particions_custom(merged.get("particions_custom") or {})
    for code, cfg in existing_custom.items():
        if code and code not in allowed_particio_codes and code not in updated_custom:
            updated_custom[code] = json_clone(cfg)
    merged["particions_custom"] = updated_custom

    existing_filters = existing.get("filtres") or {}
    updated_filters = merged.get("filtres") or {}
    if not isinstance(updated_filters, dict):
        updated_filters = {}
    if isinstance(existing_filters, dict):
        for key, value in existing_filters.items():
            key_txt = str(key or "").strip()
            if key_txt and key_txt not in allowed_filter_keys and key_txt not in updated_filters:
                updated_filters[key_txt] = json_clone(value)
    merged["filtres"] = updated_filters

    return merged


def build_global_aparell_field_options(aparells, scoreable_meta_builder):
    apps = list(aparells or [])
    schemas_by_aparell = {
        s.aparell_id: (s.schema or {})
        for s in ScoringSchema.objects.filter(aparell_id__in=[app.id for app in apps]).only("aparell_id", "schema")
    }
    out = {}
    for app in apps:
        sch = schemas_by_aparell.get(app.id, {}) or {}
        meta = scoreable_meta_builder(sch, strict_unknown=True)
        opts = []
        for f in (sch.get("fields") or []):
            if not isinstance(f, dict) or not f.get("code"):
                continue
            code = str(f["code"])
            info = meta.get(code) or {}
            if not info.get("scoreable", False):
                continue
            judges_count = 1
            judges = f.get("judges")
            if isinstance(judges, dict):
                try:
                    judges_count = int(judges.get("count") or 1)
                except Exception:
                    judges_count = 1
            opts.append({
                "code": code,
                "label": str(f.get("label") or code),
                "kind": "field",
                "judges_count": max(1, judges_count),
            })
        for c in (sch.get("computed") or []):
            if not isinstance(c, dict) or not c.get("code"):
                continue
            code = str(c["code"])
            info = meta.get(code) or {}
            if not info.get("scoreable", False):
                continue
            opts.append({
                "code": code,
                "label": str(c.get("label") or code),
                "kind": "computed",
                "judges_count": 1,
            })
        seen = set()
        dedup = []
        for item in opts:
            if item["code"] in seen:
                continue
            seen.add(item["code"])
            dedup.append(item)
        out[str(app.id)] = dedup
    return out


def parse_positive_int_list(raw):
    if raw is None:
        return []
    if isinstance(raw, str):
        out = []
        for part in raw.split(","):
            p = str(part or "").strip()
            if not p:
                continue
            try:
                iv = int(p)
            except Exception:
                continue
            if iv > 0:
                out.append(iv)
        return out
    if isinstance(raw, (list, tuple)):
        out = []
        for x in raw:
            try:
                iv = int(x)
            except Exception:
                continue
            if iv > 0:
                out.append(iv)
        return out
    return []


def normalize_tie_camps_for_validation(tie_obj) -> list:
    if not isinstance(tie_obj, dict):
        return []
    if isinstance(tie_obj.get("camps"), list):
        out = []
        seen = set()
        for raw in tie_obj.get("camps") or []:
            code = str(raw or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            out.append(code)
        if out:
            return out
    camp = str(tie_obj.get("camp") or "").strip()
    return [camp] if camp else []


def validate_victories_granular_options(victories, prefix="puntuacio.victories"):
    errors = []
    if not isinstance(victories, dict):
        return errors

    mode_camps = str(victories.get("mode_camps") or "agregat").strip().lower()
    if mode_camps not in {"agregat", "separat"}:
        errors.append(f"{prefix}.mode_camps invalid: {mode_camps}")

    mode_exercicis = str(victories.get("mode_exercicis") or "agregat").strip().lower()
    if mode_exercicis not in {"agregat", "separat"}:
        errors.append(f"{prefix}.mode_exercicis invalid: {mode_exercicis}")

    mode_sel = str(
        victories.get("mode_seleccio_exercicis_camps_separats") or "per_camp"
    ).strip().lower()
    if mode_sel not in {"per_camp", "global"}:
        errors.append(f"{prefix}.mode_seleccio_exercicis_camps_separats invalid: {mode_sel}")

    for key in ("agregacio_victories_camps", "agregacio_victories_exercicis"):
        raw = str(victories.get(key) or "sum").strip().lower()
        if raw not in {"sum", "avg", "median", "max", "min"}:
            errors.append(f"{prefix}.{key} invalid: {raw}")

    return errors


def validate_template_schema_global(
    schema_tpl,
    *,
    available_app_codes,
    scoreable_by_code,
    allowed_particio_codes,
    allowed_filter_keys=None,
    preserved_particio_codes=None,
    preserved_filter_keys=None,
    tipus="individual",
):
    schema = normalize_particions_schema(schema_tpl or {})
    errors = []
    allowed_particio_codes = {str(code or "").strip() for code in (allowed_particio_codes or []) if str(code or "").strip()}
    allowed_filter_keys = {str(key or "").strip() for key in (allowed_filter_keys or []) if str(key or "").strip()}
    preserved_particio_codes = {str(code or "").strip() for code in (preserved_particio_codes or []) if str(code or "").strip()}
    preserved_filter_keys = {str(key or "").strip() for key in (preserved_filter_keys or []) if str(key or "").strip()}

    punt = schema.get("puntuacio") or {}
    if not isinstance(punt, dict):
        punt = {}
        schema["puntuacio"] = punt

    selected_codes = []
    seen_codes = set()
    app_cfg = punt.get("aparells") or {}
    if str(app_cfg.get("mode") or "seleccionar").strip().lower() == "tots":
        errors.append("puntuacio.aparells.mode='tots' no esta permes; cal seleccionar aparells explicitament.")
    for raw in app_cfg.get("ids") or []:
        code = canon_app_code(raw)
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        selected_codes.append(code)
        if code not in available_app_codes:
            errors.append(f"Aparell global no disponible: {code}")

    part_entries = normalize_particions_v2(
        schema.get("particions_v2") or [],
        fallback_codes=schema.get("particions") or [],
    )
    for idx, entry in enumerate(part_entries):
        code = str(entry.get("code") or "").strip()
        if code not in allowed_particio_codes and code not in preserved_particio_codes:
            errors.append(f"particions: camp no permes al builder global: '{code}'")
        apply_mode = str(entry.get("apply_mode") or "all").strip().lower()
        if idx == 0 and apply_mode != "all":
            errors.append("particions_v2[0].apply_mode ha de ser 'all'.")
        if idx > 0 and apply_mode not in {"all", "some_parents"}:
            errors.append(f"particions_v2[{idx}].apply_mode invalid: {apply_mode}")
    custom_map = normalize_particions_custom(schema.get("particions_custom") or {})
    for code in custom_map:
        if code not in allowed_particio_codes and code not in preserved_particio_codes:
            errors.append(f"particions_custom['{code}']: camp no permes al builder global.")
    errors.extend(validate_particions_config_global(schema, tipus=tipus))

    filtres = schema.get("filtres") or {}
    if filtres and not isinstance(filtres, dict):
        errors.append("filtres ha de ser un objecte JSON.")
    elif isinstance(filtres, dict):
        for key in filtres:
            key_txt = str(key or "").strip()
            if key_txt and key_txt not in allowed_filter_keys and key_txt not in preserved_filter_keys:
                errors.append(f"filtres: clau no permesa al builder global: '{key_txt}'")

    camps_per_aparell = punt.get("camps_per_aparell") or {}
    if camps_per_aparell and not isinstance(camps_per_aparell, dict):
        errors.append("puntuacio.camps_per_aparell ha de ser un objecte {aparell_codi:[camps]}.")
    elif isinstance(camps_per_aparell, dict):
        for raw_key, raw_codes in camps_per_aparell.items():
            app_code = canon_app_code(raw_key)
            if app_code not in available_app_codes:
                errors.append(f"aparell global no valid a camps_per_aparell: {raw_key}")
                continue
            if selected_codes and app_code not in selected_codes:
                continue
            codes = [str(x).strip() for x in raw_codes] if isinstance(raw_codes, list) else []
            for code in [x for x in codes if x]:
                if code not in scoreable_by_code.get(app_code, {"total", "TOTAL"}):
                    errors.append(f"aparell {app_code}: camp '{code}' no es puntuable directament.")

    if str(punt.get("mode_resultat_aparells") or "score").strip().lower() == "victories" and str(tipus or "individual").strip().lower() != "individual":
        errors.append("puntuacio.mode_resultat_aparells='victories' nomes s'admet per tipus='individual'.")
    if str(punt.get("mode_resultat_aparells") or "score").strip().lower() == "victories":
        errors.extend(validate_victories_granular_options(punt.get("victories") or {}))

    for idx, tie in enumerate(schema.get("desempat") or []):
        if not isinstance(tie, dict):
            continue
        scope = tie.get("scope") or {}
        if not isinstance(scope, dict):
            scope = {}
        target_codes = []
        app_scope = scope.get("aparells") or {}
        if isinstance(app_scope, dict) and str(app_scope.get("mode") or "hereta").strip().lower() == "seleccionar":
            target_codes = [canon_app_code(raw) for raw in (app_scope.get("ids") or []) if canon_app_code(raw)]
        else:
            target_codes = list(selected_codes)
        for app_code in target_codes:
            for code in normalize_tie_camps_for_validation(tie):
                if code not in scoreable_by_code.get(app_code, {"total", "TOTAL"}):
                    errors.append(f"desempat[{idx}]: aparell {app_code}: camp '{code}' no es puntuable directament.")

    presentacio = schema.get("presentacio") or {}
    if isinstance(presentacio, dict):
        for path, cols in _iter_presentacio_column_groups(presentacio):
            for idx, col in enumerate(cols or []):
                if not isinstance(col, dict):
                    continue
                ctype = str(col.get("type") or "builtin").strip().lower()
                if ctype == "raw":
                    src = col.get("source") if isinstance(col.get("source"), dict) else {}
                    app_code = canon_app_code(src.get("aparell_codi"))
                    camp = str(src.get("camp") or "total").strip() or "total"
                    if app_code not in available_app_codes:
                        errors.append(f"{path}[{idx}] raw: aparell no disponible")
                        continue
                    if camp not in scoreable_by_code.get(app_code, {"total", "TOTAL"}):
                        errors.append(f"{path}[{idx}] raw: camp no puntuable")
                elif ctype == "metric":
                    app_code = canon_app_code(col.get("aparell_codi"))
                    if app_code and app_code not in available_app_codes:
                        errors.append(f"{path}[{idx}] metric: aparell no disponible")
                        continue
                    criteri = col.get("criteri") if isinstance(col.get("criteri"), dict) else {}
                    target_codes = [app_code] if app_code else []
                    if not target_codes:
                        scope = criteri.get("scope") if isinstance(criteri, dict) else {}
                        app_scope = scope.get("aparells") if isinstance(scope, dict) else {}
                        if isinstance(app_scope, dict) and str(app_scope.get("mode") or "").strip().lower() == "seleccionar":
                            target_codes = [
                                canon_app_code(raw)
                                for raw in (app_scope.get("ids") or [])
                                if canon_app_code(raw)
                            ]
                    for target_code in target_codes:
                        if target_code not in available_app_codes:
                            errors.append(f"{path}[{idx}] metric: aparell no disponible")
                            continue
                        for code in normalize_tie_camps_for_validation(criteri):
                            if code not in scoreable_by_code.get(target_code, {"total", "TOTAL"}):
                                errors.append(
                                    f"{path}[{idx}] metric: aparell {target_code}: camp '{code}' no es puntuable directament."
                                )

    return schema, errors
