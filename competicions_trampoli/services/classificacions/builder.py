import json

from django.db import models
from django.utils import timezone

from ...models import Equip, Inscripcio
from ...models.classificacions import ClassificacioConfig
from ...models.competicio import CompeticioAparell
from ...models.scoring import ScoringSchema
from .classificacio_templates import (
    json_clone,
    normalize_particions_custom,
    normalize_particions_schema,
)
from .compute import DEFAULT_SCHEMA
from .filters import (
    EXERCISE_SELECTION_SCOPE_INHERIT,
    EXERCISE_SELECTION_SCOPE_PER_MEMBER,
    infer_team_mode_from_comp_aparells,
    normalize_classificacio_equips_cfg,
    normalize_classificacio_filters,
    normalize_equip_assignment_source,
    normalize_exercise_selection_scope,
    normalize_team_mode,
)
from .partitions import (
    normalize_particions_v2_entries,
    normalize_schema_legacy_team_birth_partition,
)
from .pipeline_runtime import (
    build_main_scoring_pipeline_from_schema,
    materialize_desempat_item,
)
from .validation import (
    build_scoreable_meta_for_schema,
    get_team_context_capabilities,
    selected_app_ids_from_schema,
    validate_schema_for_competicio_detailed,
)
from ..teams.equip_contexts import (
    NATIVE_EQUIP_CONTEXT_CODE,
    get_equip_context,
    get_equip_context_payload,
    normalize_equip_context_code,
)
from ..inscripcions.queries import get_allowed_group_fields, get_inscripcio_value
from ..scoring.team_scoring import is_team_context_app


def _particio_value_to_text(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, (list, dict)):
        try:
            return json.dumps(raw, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(raw)
    return str(raw).strip()


def is_fk(model_cls, field_name: str) -> bool:
    try:
        field = model_cls._meta.get_field(field_name)
        return isinstance(field, (models.ForeignKey, models.OneToOneField))
    except Exception:
        return False


def distinct_values(qs, field_name: str):
    values = qs.values_list(field_name, flat=True).distinct()
    out = []
    seen = set()
    for value in values:
        if value is None:
            continue
        label = str(value).strip()
        if not label:
            continue
        key = " ".join(label.split()).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def distinct_fk(qs, field_name: str):
    rel = qs.select_related(field_name).values_list(f"{field_name}_id", f"{field_name}__nom").distinct()
    out = []
    seen = set()
    for value_id, label in rel:
        if value_id is None or value_id in seen:
            continue
        seen.add(value_id)
        out.append({"value": value_id, "label": label or str(value_id)})
    return out


def collect_particio_value_choices(ins_list, field_codes, max_per_field=200):
    out = {}
    for code in field_codes:
        unique_labels = {}
        unique_counts = {}
        for inscripcio in ins_list:
            text = _particio_value_to_text(get_inscripcio_value(inscripcio, code))
            if not text:
                continue
            key = " ".join(text.split()).casefold()
            if key in unique_labels:
                unique_counts[key] = int(unique_counts.get(key, 0) or 0) + 1
                continue
            if len(unique_labels) >= max_per_field:
                continue
            unique_labels[key] = text
            unique_counts[key] = 1
        entries = []
        for key, value in unique_labels.items():
            entries.append(
                {
                    "value": value,
                    "label": value,
                    "count": int(unique_counts.get(key, 0) or 0),
                }
            )
        entries.sort(key=lambda item: str(item.get("label") or "").casefold())
        out[code] = entries
    return out


def _classification_assignment_source(raw_cfg):
    return normalize_equip_assignment_source(raw_cfg if isinstance(raw_cfg, dict) else {})


def _classification_teams_queryset(competicio, raw_cfg):
    cfg = normalize_classificacio_equips_cfg(raw_cfg if isinstance(raw_cfg, dict) else {})
    context = get_equip_context(competicio, normalize_equip_context_code(cfg.get("context_code")))
    if context is None:
        return Equip.objects.none()
    return Equip.objects.filter(competicio=competicio, context=context)


def _parse_positive_int_list(raw):
    if raw is None:
        return []
    if isinstance(raw, str):
        values = []
        for part in raw.split(","):
            label = str(part or "").strip()
            if not label:
                continue
            try:
                value = int(label)
            except Exception:
                continue
            if value > 0:
                values.append(value)
        return values
    if isinstance(raw, (list, tuple)):
        values = []
        for item in raw:
            try:
                value = int(item)
            except Exception:
                continue
            if value > 0:
                values.append(value)
        return values
    return []


def _normalize_tie_camps_for_validation(tie_obj) -> list:
    if not isinstance(tie_obj, dict):
        return []
    out = []
    raw = tie_obj.get("camps")
    if isinstance(raw, list):
        out = [str(x).strip() for x in raw if str(x).strip()]
    elif isinstance(raw, str):
        out = [x.strip() for x in raw.split(",") if x and x.strip()]
    if not out:
        legacy = str(tie_obj.get("camp") or "").strip()
        if legacy:
            out = [legacy]
    dedup = []
    seen = set()
    for code in out:
        if code in seen:
            continue
        seen.add(code)
        dedup.append(code)
    return dedup


def _is_derived_team_scope_enabled(*, tipus="individual", team_mode="") -> bool:
    return (
        str(tipus or "").strip().lower() == "equips"
        and normalize_team_mode(team_mode) == "derived_from_individual"
    )


def _effective_tie_exercise_selection_scope(tie: dict, *, main_scope=None):
    tie_scope = normalize_exercise_selection_scope(
        (tie or {}).get("exercise_selection_scope"),
        allow_inherit=True,
    )
    if tie_scope == EXERCISE_SELECTION_SCOPE_INHERIT:
        return main_scope or EXERCISE_SELECTION_SCOPE_PER_MEMBER
    return tie_scope


def _materialize_desempat_item_for_builder(
    tie,
    *,
    idx: int,
    tipus="individual",
    team_mode="",
    selected_main_ids=None,
    allow_app_scope=True,
    allow_participants=True,
    fallback_pipeline=None,
):
    item = materialize_desempat_item(
        tie,
        tipus=tipus,
        team_mode=team_mode,
        selected_app_ids=selected_main_ids,
        default_id=f"tie_{idx + 1}",
        default_nom=f"Criteri {idx + 1}",
        allow_participants=allow_participants,
        fallback_pipeline=fallback_pipeline,
    )
    if not isinstance(item, dict):
        return None
    if not allow_app_scope:
        scope = item.get("scope") if isinstance(item.get("scope"), dict) else {}
        scope.pop("aparells", None)
        item["scope"] = scope
    return item


def build_cfg_status(competicio, tipus, schema_local):
    _schema_with_legacy, legacy_info = normalize_schema_legacy_team_birth_partition(
        competicio,
        schema_local or {},
        tipus=tipus,
        persist=False,
    )
    schema_local, errors, _details = validate_schema_for_competicio_detailed(
        competicio,
        schema_local or {},
        tipus=tipus,
    )
    equips_cfg = normalize_classificacio_equips_cfg(schema_local.get("equips") or {})
    selected_ids = selected_app_ids_from_schema(schema_local)
    selected_apps = list(
        CompeticioAparell.objects
        .filter(competicio=competicio, id__in=selected_ids)
        .select_related("aparell")
    )
    selected_apps_by_id = {int(comp_aparell.id): comp_aparell for comp_aparell in selected_apps}
    missing_selected_ids = [app_id for app_id in selected_ids if int(app_id) not in selected_apps_by_id]
    for app_id in missing_selected_ids:
        errors.append(f"puntuacio.aparells.ids: l'aparell {app_id} no valid o no actiu.")
    capabilities = get_team_context_capabilities(competicio, equips_cfg.get("context_code"))
    inferred_team_mode = infer_team_mode_from_comp_aparells(selected_apps) if str(tipus or "") == "equips" else ""
    explicit_team_mode = normalize_team_mode(equips_cfg.get("team_mode"))
    effective_team_mode = explicit_team_mode or inferred_team_mode
    mode_resolution = equips_cfg.get("mode_resolution") or {}

    return {
        "context_code": capabilities["context_code"],
        "effective_team_mode": effective_team_mode,
        "inferred_team_mode": inferred_team_mode,
        "has_team_apps": capabilities["has_team_apps"],
        "eligible_team_app_ids": capabilities["eligible_team_app_ids"],
        "eligible_team_app_ids_at_save": list(mode_resolution.get("eligible_team_app_ids_at_save") or []),
        "resolved_at": str(mode_resolution.get("resolved_at") or "").strip(),
        "is_stale": bool(errors),
        "compatibility_errors": errors,
        "legacy_inferred": bool(legacy_info.get("legacy_inferred")),
    }


def scoreable_codes_by_app_id(competicio, *, tipus=None, assignment_context_code=None, team_mode=None):
    active_apps = list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("aparell")
    )
    schemas_by_aparell = {
        s.aparell_id: (s.schema or {})
        for s in ScoringSchema.objects.filter(aparell_id__in=[ca.aparell_id for ca in active_apps]).only("aparell_id", "schema")
    }
    normalized_team_mode = normalize_team_mode(team_mode)
    eligible_team_app_ids = set()
    if normalized_team_mode == "native_team":
        eligible_team_app_ids = set(
            get_team_context_capabilities(competicio, assignment_context_code).get("eligible_team_app_ids", [])
        )
    out = {}
    for comp_aparell in active_apps:
        if is_team_context_app(comp_aparell):
            if str(tipus or "").strip().lower() != "equips" or normalized_team_mode != "native_team":
                continue
            if int(comp_aparell.id) not in eligible_team_app_ids:
                continue
        elif str(tipus or "").strip().lower() == "equips" and normalized_team_mode == "native_team":
            continue
        schema = schemas_by_aparell.get(comp_aparell.aparell_id, {}) or {}
        meta = build_scoreable_meta_for_schema(schema, strict_unknown=True)
        out[int(comp_aparell.id)] = {code for code, info in (meta or {}).items() if (info or {}).get("scoreable")}
    return out


def _normalize_candidate_source_mode(raw_mode):
    mode = str(raw_mode or "raw_exercise").strip().lower()
    if mode in {"raw_exercise", "participant_aggregate", "team_aggregate"}:
        return mode
    return "raw_exercise"


def _sanitize_candidate_source_cfg(raw_cfg, fallback=None):
    fb = fallback if isinstance(fallback, dict) else {}
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}

    mode = str(cfg.get("mode") or fb.get("mode") or "tots").strip().lower()
    allowed_modes = {"tots", "millor_1", "millor_n", "pitjor_1", "pitjor_n", "primer", "ultim", "index", "llista"}
    if mode not in allowed_modes:
        mode = str(fb.get("mode") or "tots").strip().lower()
        if mode not in allowed_modes:
            mode = "tots"

    try:
        best_n = int(cfg.get("best_n", fb.get("best_n", 1)))
    except Exception:
        best_n = 1
    best_n = max(1, best_n)

    try:
        index = int(cfg.get("index", fb.get("index", 1)))
    except Exception:
        index = 1
    index = max(1, index)

    ids = []
    ids_raw = cfg.get("ids", fb.get("ids", []))
    if isinstance(ids_raw, str):
        ids_raw = [x.strip() for x in ids_raw.split(",") if x and x.strip()]
    if isinstance(ids_raw, (list, tuple)):
        seen = set()
        for item in ids_raw:
            try:
                value = int(item)
            except Exception:
                continue
            if value > 0 and value not in seen:
                seen.add(value)
                ids.append(value)

    agg = str(cfg.get("agregacio_exercicis", fb.get("agregacio_exercicis", "sum")) or "sum").strip().lower()
    if agg not in {"sum", "avg", "median", "max", "min"}:
        agg = str(fb.get("agregacio_exercicis") or "sum").strip().lower()
        if agg not in {"sum", "avg", "median", "max", "min"}:
            agg = "sum"

    return {
        "mode": mode,
        "best_n": best_n,
        "index": index,
        "ids": ids,
        "agregacio_exercicis": agg,
    }


def _normalize_agregacio_camps_value(raw_value):
    agg = str(raw_value or "sum").strip().lower()
    if agg not in {"sum", "avg", "median", "max", "min"}:
        return "sum"
    return agg


def _sanitize_agregacio_camps_per_aparell(raw_map, *, fallback="sum"):
    out = {}
    if not isinstance(raw_map, dict):
        return out
    fallback_value = _normalize_agregacio_camps_value(fallback)
    for raw_key, raw_value in raw_map.items():
        try:
            app_id = int(raw_key)
        except Exception:
            continue
        if app_id <= 0:
            continue
        agg = _normalize_agregacio_camps_value(raw_value or fallback_value)
        out[str(app_id)] = agg
    return out


def _sanitize_agregacio_exercicis_per_aparell(raw_map, *, fallback="sum"):
    return _sanitize_agregacio_camps_per_aparell(raw_map, fallback=fallback)


def _sanitize_candidate_source_entry(raw_entry, *, fallback_mode="raw_exercise", fallback_cfg=None):
    entry = raw_entry if isinstance(raw_entry, dict) else {}
    mode = _normalize_candidate_source_mode(entry.get("mode") or fallback_mode)
    out = {"mode": mode}
    if mode in {"participant_aggregate", "team_aggregate"}:
        out["cfg"] = _sanitize_candidate_source_cfg(entry.get("cfg"), fallback=fallback_cfg)
    return out


def _sanitize_candidate_source_per_aparell(raw_map, *, fallback_mode="raw_exercise", fallback_cfg=None):
    out = {}
    if not isinstance(raw_map, dict):
        return out
    for raw_key, raw_value in raw_map.items():
        try:
            app_id = int(raw_key)
        except Exception:
            continue
        if app_id <= 0:
            continue
        out[str(app_id)] = _sanitize_candidate_source_entry(
            raw_value,
            fallback_mode=fallback_mode,
            fallback_cfg=fallback_cfg,
        )
    return out


def _is_candidate_source_enabled(*, tipus="individual", team_mode=""):
    tipus_norm = str(tipus or "").strip().lower()
    team_mode_norm = str(team_mode or "").strip().lower()
    return (
        tipus_norm == "individual"
        or (tipus_norm == "equips" and team_mode_norm in {"derived_from_individual", "native_team"})
    )


def prepare_schema_for_builder_hydration(competicio, schema_local, tipus="individual"):
    """Normalize builder payload shape without dropping stale or legacy selections."""
    schema, _errors, _details = validate_schema_for_competicio_detailed(
        competicio,
        schema_local or {},
        tipus=tipus,
    )
    schema = normalize_particions_schema(json_clone(schema or {}))
    schema["filtres"] = normalize_classificacio_filters(schema.get("filtres") or {})
    schema["equips"] = normalize_classificacio_equips_cfg(schema.get("equips") or {})

    punt = schema.get("puntuacio") or {}
    if not isinstance(punt, dict):
        punt = {}
    schema["puntuacio"] = punt
    punt.pop("camp", None)
    punt.pop("agregacio", None)
    punt.pop("best_n", None)

    apps_cfg = punt.get("aparells") or {}
    if not isinstance(apps_cfg, dict):
        apps_cfg = {}
    ids_out = []
    seen_ids = set()
    raw_mode = str(apps_cfg.get("mode") or "seleccionar").strip().lower()
    ids_in = apps_cfg.get("ids") or []
    if raw_mode == "tots":
        tipus_norm = str(tipus or "").strip().lower()
        equips_cfg = schema.get("equips") or {}
        assignment_source = (
            equips_cfg.get("assignment_source")
            if isinstance(equips_cfg.get("assignment_source"), dict)
            else {}
        )
        context_code = normalize_equip_context_code(
            assignment_source.get("context_code") or equips_cfg.get("context_code")
        )
        capabilities = get_team_context_capabilities(competicio, context_code)
        active_apps = list(
            CompeticioAparell.objects
            .filter(competicio=competicio, actiu=True)
            .select_related("aparell")
            .order_by("ordre", "id")
        )
        team_mode = normalize_team_mode(equips_cfg.get("team_mode"))
        if tipus_norm == "equips" and not team_mode:
            team_mode = infer_team_mode_from_comp_aparells(active_apps) or "derived_from_individual"
        eligible_team_ids = set(capabilities.get("eligible_team_app_ids") or [])
        ids_in = []
        for comp_aparell in active_apps:
            if tipus_norm == "individual":
                if is_team_context_app(comp_aparell):
                    continue
            elif tipus_norm == "equips":
                if team_mode == "native_team":
                    if not is_team_context_app(comp_aparell):
                        continue
                    if eligible_team_ids and int(comp_aparell.id) not in eligible_team_ids:
                        continue
                elif is_team_context_app(comp_aparell):
                    continue
            ids_in.append(int(comp_aparell.id))
    for raw in ids_in if isinstance(ids_in, list) else []:
        try:
            app_id = int(raw)
        except Exception:
            continue
        if app_id > 0 and app_id not in seen_ids:
            seen_ids.add(app_id)
            ids_out.append(app_id)
    punt["aparells"] = {
        **apps_cfg,
        "mode": "seleccionar",
        "ids": ids_out,
    }

    camps_in = punt.get("camps_per_aparell") or {}
    camps_out = {}
    if isinstance(camps_in, dict):
        for raw_key, raw_codes in camps_in.items():
            try:
                app_id = int(raw_key)
            except Exception:
                continue
            if app_id <= 0:
                continue
            if isinstance(raw_codes, str):
                codes = [x.strip() for x in raw_codes.split(",") if x and x.strip()]
            elif isinstance(raw_codes, list):
                codes = [str(x).strip() for x in raw_codes if str(x).strip()]
            else:
                continue
            if codes:
                camps_out[str(app_id)] = codes
    punt["camps_per_aparell"] = camps_out
    fallback_agg_camps = _normalize_agregacio_camps_value(punt.get("agregacio_camps"))
    agg_camps_map = _sanitize_agregacio_camps_per_aparell(
        punt.get("agregacio_camps_per_aparell") or {},
        fallback=fallback_agg_camps,
    )
    for app_id in ids_out:
        agg_camps_map.setdefault(str(app_id), fallback_agg_camps)
    punt["agregacio_camps_per_aparell"] = agg_camps_map

    punt["exercicis"] = punt.get("exercicis") if isinstance(punt.get("exercicis"), dict) else {}
    punt["candidate_source_mode"] = _normalize_candidate_source_mode(punt.get("candidate_source_mode"))
    punt["candidate_source_cfg"] = _sanitize_candidate_source_cfg(punt.get("candidate_source_cfg"))
    candidate_source_map = _sanitize_candidate_source_per_aparell(
        punt.get("candidate_source_per_aparell") or {},
        fallback_mode=punt.get("candidate_source_mode"),
        fallback_cfg=punt.get("candidate_source_cfg"),
    )
    for app_id in ids_out:
        candidate_source_map.setdefault(
            str(app_id),
            _sanitize_candidate_source_entry(
                {},
                fallback_mode=punt.get("candidate_source_mode"),
                fallback_cfg=punt.get("candidate_source_cfg"),
            ),
        )
    punt["candidate_source_per_aparell"] = candidate_source_map
    ex_per_app_in = punt.get("exercicis_per_aparell") or {}
    ex_per_app_out = {}
    if isinstance(ex_per_app_in, dict):
        for raw_key, cfg in ex_per_app_in.items():
            try:
                app_id = int(raw_key)
            except Exception:
                continue
            if app_id > 0:
                ex_per_app_out[str(app_id)] = cfg
    punt["exercicis_per_aparell"] = ex_per_app_out
    punt["agregacio_exercicis_per_aparell"] = _sanitize_agregacio_exercicis_per_aparell(
        punt.get("agregacio_exercicis_per_aparell") or {},
        fallback=punt.get("agregacio_exercicis", "sum"),
    )

    victories = punt.get("victories") or {}
    if not isinstance(victories, dict):
        victories = {}
    victories["desempat_comparacio"] = list(victories.get("desempat_comparacio") or []) if isinstance(victories.get("desempat_comparacio"), list) else []
    punt["victories"] = victories

    selected_ids_hydration = punt.get("aparells", {}).get("ids") or []
    hydration_team_mode = normalize_team_mode((schema.get("equips") or {}).get("team_mode", ""))
    fallback_pipeline = build_main_scoring_pipeline_from_schema(
        {"puntuacio": punt},
        tipus=tipus,
        team_mode=hydration_team_mode,
    )
    des_in = schema.get("desempat") or []
    des_out = []
    if isinstance(des_in, list):
        for idx, tie in enumerate(des_in):
            if not isinstance(tie, dict):
                continue
            item = _materialize_desempat_item_for_builder(
                tie,
                idx=idx,
                tipus=tipus,
                team_mode=hydration_team_mode,
                selected_main_ids=selected_ids_hydration,
                allow_app_scope=True,
                allow_participants=(str(tipus or "").strip().lower() == "equips" and hydration_team_mode != "native_team"),
                fallback_pipeline=fallback_pipeline,
            )
            if item:
                des_out.append(item)
    schema["desempat"] = des_out
    schema["particions"] = list(schema.get("particions") or []) if isinstance(schema.get("particions"), list) else []
    schema["particions_v2"] = list(schema.get("particions_v2") or []) if isinstance(schema.get("particions_v2"), list) else []
    schema["particions_custom"] = schema.get("particions_custom") if isinstance(schema.get("particions_custom"), dict) else {}

    presentacio = schema.get("presentacio") or {}
    if not isinstance(presentacio, dict):
        presentacio = {}
    detail_cfg = presentacio.get("detall") or {}
    if not isinstance(detail_cfg, dict):
        detail_cfg = {}
    presentacio["columnes"] = list(presentacio.get("columnes") or []) if isinstance(presentacio.get("columnes"), list) else list((DEFAULT_SCHEMA.get("presentacio") or {}).get("columnes") or [])
    presentacio["detall"] = detail_cfg
    schema["presentacio"] = presentacio

    return schema


def sanitize_schema_for_builder(competicio, schema_local, tipus="individual"):
    """Build a compatibility-pruned schema for execution-oriented flows, not UI hydration."""
    schema = normalize_particions_schema(json_clone(schema_local or {}))
    schema["filtres"] = normalize_classificacio_filters(schema.get("filtres") or {})
    active_apps = list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("aparell")
        .order_by("ordre", "id")
    )
    by_id = {int(ca.id): ca for ca in active_apps}
    active_ids = [int(ca.id) for ca in active_apps]
    active_set = set(active_ids)
    equips_cfg = normalize_classificacio_equips_cfg(schema.get("equips") or {})
    schema["equips"] = equips_cfg
    scoreable_by_app = scoreable_codes_by_app_id(
        competicio,
        tipus=tipus,
        assignment_context_code=equips_cfg.get("context_code"),
        team_mode=equips_cfg.get("team_mode"),
    )

    punt = schema.get("puntuacio") or {}
    if not isinstance(punt, dict):
        punt = {}
    schema["puntuacio"] = punt
    punt.pop("camp", None)
    punt.pop("agregacio", None)
    punt.pop("best_n", None)

    apps_cfg = punt.get("aparells") or {}
    if not isinstance(apps_cfg, dict):
        apps_cfg = {}
    ids_in = apps_cfg.get("ids") or []
    selected_ids = []
    seen_ids = set()
    for raw in ids_in if isinstance(ids_in, list) else []:
        try:
            app_id = int(raw)
        except Exception:
            continue
        if app_id in active_set and app_id not in seen_ids:
            seen_ids.add(app_id)
            selected_ids.append(app_id)
    selected_set = set(selected_ids)
    apps_cfg["mode"] = "seleccionar"
    apps_cfg["ids"] = selected_ids
    punt["aparells"] = apps_cfg
    effective_team_mode = equips_cfg.get("team_mode") or infer_team_mode_from_comp_aparells(
        [by_id[app_id] for app_id in selected_ids if app_id in by_id]
    )

    def normalize_codes(raw_codes):
        if isinstance(raw_codes, str):
            return [x.strip() for x in raw_codes.split(",") if x and x.strip()]
        if isinstance(raw_codes, list):
            return [str(x).strip() for x in raw_codes if str(x).strip()]
        return []

    def sanitize_codes_for_app(app_id: int, raw_codes):
        allowed = scoreable_by_app.get(int(app_id), set())
        kept = []
        seen = set()
        for code in normalize_codes(raw_codes):
            if code in allowed and code not in seen:
                seen.add(code)
                kept.append(code)
        return kept

    camps_in = punt.get("camps_per_aparell") or {}
    camps_out = {}
    for app_id in selected_ids:
        raw_codes = None
        if isinstance(camps_in, dict):
            raw_codes = camps_in.get(str(app_id))
            if raw_codes is None:
                raw_codes = camps_in.get(app_id)
        kept = sanitize_codes_for_app(app_id, raw_codes)
        if kept:
            camps_out[str(app_id)] = kept
    punt["camps_per_aparell"] = camps_out
    punt["agregacio_camps_per_aparell"] = {
        str(app_id): _normalize_agregacio_camps_value(raw_value)
        for app_id in selected_ids
        for raw_value in [
            (
                ((punt.get("agregacio_camps_per_aparell") or {}).get(str(app_id)))
                if isinstance(punt.get("agregacio_camps_per_aparell"), dict)
                else None
            )
        ]
    }
    for app_id in selected_ids:
        punt["agregacio_camps_per_aparell"].setdefault(
            str(app_id),
            _normalize_agregacio_camps_value(punt.get("agregacio_camps")),
        )

    ex_per_app_in = punt.get("exercicis_per_aparell") or {}
    ex_per_app_out = {}
    if isinstance(ex_per_app_in, dict):
        for raw_key, cfg in ex_per_app_in.items():
            try:
                app_id = int(raw_key)
            except Exception:
                continue
            if app_id in active_set and app_id in selected_set:
                ex_per_app_out[str(app_id)] = cfg
    punt["exercicis_per_aparell"] = ex_per_app_out
    agg_ex_per_app_in = punt.get("agregacio_exercicis_per_aparell") or {}
    agg_ex_per_app_out = {}
    if isinstance(agg_ex_per_app_in, dict):
        for raw_key, raw_value in agg_ex_per_app_in.items():
            try:
                app_id = int(raw_key)
            except Exception:
                continue
            if app_id in active_set and app_id in selected_set:
                agg_ex_per_app_out[str(app_id)] = raw_value
    punt["agregacio_exercicis_per_aparell"] = _sanitize_agregacio_exercicis_per_aparell(
        agg_ex_per_app_out,
        fallback=punt.get("agregacio_exercicis", "sum"),
    )
    allow_exercise_scope = _is_derived_team_scope_enabled(
        tipus=tipus,
        team_mode=effective_team_mode,
    )
    allow_candidate_source = _is_candidate_source_enabled(
        tipus=tipus,
        team_mode=effective_team_mode,
    )
    if allow_exercise_scope:
        punt["exercise_selection_scope"] = normalize_exercise_selection_scope(
            punt.get("exercise_selection_scope")
        )
    else:
        punt.pop("exercise_selection_scope", None)
    if allow_candidate_source:
        punt["candidate_source_mode"] = _normalize_candidate_source_mode(punt.get("candidate_source_mode"))
        punt["candidate_source_cfg"] = _sanitize_candidate_source_cfg(punt.get("candidate_source_cfg"))
        candidate_source_map = _sanitize_candidate_source_per_aparell(
            punt.get("candidate_source_per_aparell") or {},
            fallback_mode=punt.get("candidate_source_mode"),
            fallback_cfg=punt.get("candidate_source_cfg"),
        )
        for app_id in selected_ids:
            candidate_source_map.setdefault(
                str(app_id),
                _sanitize_candidate_source_entry(
                    {},
                    fallback_mode=punt.get("candidate_source_mode"),
                    fallback_cfg=punt.get("candidate_source_cfg"),
                ),
            )
        punt["candidate_source_per_aparell"] = {
            str(app_id): candidate_source_map[str(app_id)]
            for app_id in selected_ids
            if str(app_id) in candidate_source_map
        }
    else:
        punt.pop("candidate_source_mode", None)
        punt.pop("candidate_source_cfg", None)
        punt.pop("candidate_source_per_aparell", None)
    main_exercise_scope = punt.get("exercise_selection_scope") or EXERCISE_SELECTION_SCOPE_PER_MEMBER
    fallback_pipeline = build_main_scoring_pipeline_from_schema(
        {"puntuacio": punt},
        tipus=tipus,
        team_mode=effective_team_mode,
    )

    def sanitize_tie_item(raw_tie, *, idx: int, selected_main_ids, allow_app_scope: bool, allow_participants: bool):
        if not isinstance(raw_tie, dict):
            return None

        target_ids = [x for x in selected_main_ids if x in active_set]
        if allow_app_scope:
            scope = raw_tie.get("scope") or {}
            if isinstance(scope, dict):
                app_scope = scope.get("aparells") or {}
                if isinstance(app_scope, dict) and str(app_scope.get("mode") or "hereta").strip().lower() == "seleccionar":
                    scoped_ids = [x for x in _parse_positive_int_list(app_scope.get("ids")) if x in active_set]
                    if scoped_ids:
                        target_ids = scoped_ids

        if not target_ids:
            return None

        item = _materialize_desempat_item_for_builder(
            raw_tie,
            idx=idx,
            tipus=tipus,
            team_mode=effective_team_mode,
            selected_main_ids=target_ids,
            allow_app_scope=allow_app_scope,
            allow_participants=allow_participants,
            fallback_pipeline=fallback_pipeline,
        )
        if not item:
            return None

        valid_camps = []
        seen_camps = set()
        for code in _normalize_tie_camps_for_validation(item):
            if not code or code in seen_camps:
                continue
            if all(code in scoreable_by_app.get(app_id, set()) for app_id in target_ids):
                seen_camps.add(code)
                valid_camps.append(code)
        if not valid_camps:
            return None

        item["camps"] = valid_camps
        item["camp"] = valid_camps[0]
        scope = item.get("scope") if isinstance(item.get("scope"), dict) else {}
        effective_tie_scope = _effective_tie_exercise_selection_scope(item, main_scope=main_exercise_scope)
        if effective_tie_scope == "team_pool":
            scope.pop("exercicis", None)
            scope.pop("participants", None)
            item.pop("agregacio_participants", None)
            item.pop("mode_seleccio_exercicis", None)
            item.pop("exercicis_per_aparell", None)
            item.pop("agregacio_exercicis_per_aparell", None)

        ex_map_in = item.get("exercicis_per_aparell") or {}
        ex_map_out = {}
        if effective_tie_scope != "team_pool" and isinstance(ex_map_in, dict):
            for raw_key, cfg in ex_map_in.items():
                try:
                    app_id = int(raw_key)
                except Exception:
                    continue
                if app_id in target_ids:
                    ex_map_out[str(app_id)] = cfg
        if ex_map_out:
            item["exercicis_per_aparell"] = ex_map_out
        else:
            item.pop("exercicis_per_aparell", None)

        agg_ex_map_in = item.get("agregacio_exercicis_per_aparell") or {}
        agg_ex_map_out = {}
        if (
            effective_tie_scope != "team_pool"
            and str(item.get("mode_seleccio_exercicis") or "hereta").strip().lower() == "per_aparell_override"
            and isinstance(agg_ex_map_in, dict)
        ):
            for raw_key, raw_value in agg_ex_map_in.items():
                try:
                    app_id = int(raw_key)
                except Exception:
                    continue
                if app_id in target_ids:
                    agg_ex_map_out[str(app_id)] = raw_value
        if agg_ex_map_out:
            item["agregacio_exercicis_per_aparell"] = _sanitize_agregacio_exercicis_per_aparell(
                agg_ex_map_out,
                fallback=item.get("agregacio_exercicis", "sum"),
            )
        else:
            item.pop("agregacio_exercicis_per_aparell", None)

        if allow_exercise_scope:
            tie_scope = normalize_exercise_selection_scope(item.get("exercise_selection_scope"), allow_inherit=True)
            if tie_scope == EXERCISE_SELECTION_SCOPE_INHERIT:
                item.pop("exercise_selection_scope", None)
            else:
                item["exercise_selection_scope"] = tie_scope
        else:
            item.pop("exercise_selection_scope", None)
            pipeline = item.get("pipeline")
            if isinstance(pipeline, dict):
                # Keep this cleanup local to the builder/save path. If the shared
                # pipeline materialization helpers start dropping this key too,
                # tie rehydration in the builder changes shape and breaks when
                # reopening existing classificacions.
                pipeline.pop("exercise_selection_scope", None)

        return item

    des_in = schema.get("desempat") or []
    des_out = []
    if isinstance(des_in, list):
        for tie in des_in:
            item = sanitize_tie_item(
                tie,
                idx=len(des_out),
                selected_main_ids=selected_ids,
                allow_app_scope=True,
                allow_participants=(tipus == "equips"),
            )
            if item:
                des_out.append(item)
    schema["desempat"] = des_out

    victories = punt.get("victories") or {}
    if isinstance(victories, dict):
        victories_out = dict(victories)
        compare_ties = victories_out.get("desempat_comparacio") or []
        compare_out = []
        if isinstance(compare_ties, list):
            for tie in compare_ties:
                item = sanitize_tie_item(
                    tie,
                    idx=len(compare_out),
                    selected_main_ids=selected_ids,
                    allow_app_scope=False,
                    allow_participants=False,
                )
                if item:
                    compare_out.append(item)
        victories_out["desempat_comparacio"] = compare_out
        punt["victories"] = victories_out

    presentacio = schema.get("presentacio") or {}
    if not isinstance(presentacio, dict):
        presentacio = {}
    cols_in = presentacio.get("columnes") or []
    cols_out = []
    if isinstance(cols_in, list):
        for col in cols_in:
            if not isinstance(col, dict):
                cols_out.append(col)
                continue
            item = json_clone(col)
            ctype = str(item.get("type") or "builtin").strip().lower()
            if ctype != "raw":
                cols_out.append(item)
                continue
            src = item.get("source") if isinstance(item.get("source"), dict) else {}
            src = dict(src)
            try:
                app_id = int(src.get("aparell_id"))
            except Exception:
                app_id = None
            camp = str(src.get("camp") or "").strip()
            if (
                app_id in active_set
                and app_id in selected_set
                and camp in scoreable_by_app.get(app_id, set())
            ):
                src["aparell_id"] = app_id
                src.pop("aparell_codi", None)
                item["source"] = src
                item.pop("aparell_id", None)
                item.pop("aparell_codi", None)
                cols_out.append(item)
    presentacio["columnes"] = cols_out
    schema["presentacio"] = presentacio

    return schema


def with_mode_resolution(competicio, tipus, schema_local):
    schema_out = normalize_particions_schema(json_clone(schema_local or {}))
    if str(tipus or "").strip().lower() != "equips":
        return schema_out
    equips_cfg = normalize_classificacio_equips_cfg(schema_out.get("equips") or {})
    capabilities = get_team_context_capabilities(competicio, equips_cfg.get("context_code"))
    equips_cfg["mode_resolution"] = {
        "resolved_at": timezone.now().isoformat(),
        "eligible_team_app_ids_at_save": capabilities["eligible_team_app_ids"],
    }
    schema_out["equips"] = equips_cfg
    return schema_out


def build_force_minimal_schema(competicio, schema_local):
    schema = normalize_particions_schema(json_clone(schema_local or {}))
    active_ids = list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .values_list("id", flat=True)
    )
    punt = schema.get("puntuacio") or {}
    if not isinstance(punt, dict):
        punt = {}
    punt["aparells"] = {"mode": "seleccionar", "ids": active_ids}
    punt["camps_per_aparell"] = {str(app_id): ["total"] for app_id in active_ids}
    punt["agregacio_camps_per_aparell"] = {str(app_id): "sum" for app_id in active_ids}
    punt["mode_seleccio_exercicis"] = "per_aparell_global"
    punt["exercicis_per_aparell"] = {}
    punt["agregacio_exercicis_per_aparell"] = {str(app_id): "sum" for app_id in active_ids}
    punt["agregacio_camps"] = "sum"
    punt["candidate_source_mode"] = "raw_exercise"
    punt["candidate_source_cfg"] = {
        "mode": "tots",
        "best_n": 1,
        "index": 1,
        "ids": [],
        "agregacio_exercicis": "sum",
    }
    punt["candidate_source_per_aparell"] = {
        str(app_id): {"mode": "raw_exercise"}
        for app_id in active_ids
    }
    punt["agregacio_exercicis"] = "sum"
    punt["agregacio_aparells"] = "sum"
    punt["mode_resultat_aparells"] = "score"
    punt["victories"] = {
        "punts_victoria": 1,
        "punts_empat": 0.5,
        "sense_nota_mode": "skip",
        "mode_camps": "agregat",
        "mode_exercicis": "agregat",
        "mode_seleccio_exercicis_camps_separats": "per_camp",
        "agregacio_victories_camps": "sum",
        "agregacio_victories_exercicis": "sum",
        "desempat_comparacio": [],
    }
    punt["ordre"] = "desc"
    punt["camp"] = "total"
    punt["agregacio"] = "sum"
    punt["best_n"] = 1
    schema["puntuacio"] = punt
    schema["particions"] = []
    schema["particions_v2"] = []
    schema["particions_custom"] = {}
    schema["desempat"] = []
    presentacio = schema.get("presentacio") or {}
    if not isinstance(presentacio, dict):
        presentacio = {}
    if not isinstance(presentacio.get("columnes"), list) or not presentacio.get("columnes"):
        presentacio["columnes"] = json_clone((DEFAULT_SCHEMA.get("presentacio") or {}).get("columnes") or [])
    presentacio["mostrar_empats"] = bool(presentacio.get("mostrar_empats", True))
    presentacio["top_n"] = int(presentacio.get("top_n") or 0)
    schema["presentacio"] = presentacio
    return schema


def _parse_fallback_mode(raw) -> str:
    mode = str(raw or "strict").strip().lower()
    if mode not in {"strict", "assistit", "force"}:
        return "strict"
    return mode


def autofix_schema_for_competicio(competicio, schema_local, mode: str, tipus=None):
    mode = _parse_fallback_mode(mode)
    schema = normalize_particions_schema(json_clone(schema_local or {}))
    schema["filtres"] = normalize_classificacio_filters(schema.get("filtres") or {})
    warnings = []
    dropped = []

    if mode == "strict":
        return schema, warnings, dropped

    active_apps = list(
        CompeticioAparell.objects
        .filter(competicio=competicio, actiu=True)
        .select_related("aparell")
        .order_by("ordre", "id")
    )
    active_ids = [int(ca.id) for ca in active_apps]
    active_set = set(active_ids)
    equips_cfg = normalize_classificacio_equips_cfg(schema.get("equips") or {})
    if str(tipus or "").strip().lower() == "equips":
        requested_context_code = normalize_equip_context_code(
            equips_cfg.get("context_code") or (equips_cfg.get("assignment_source") or {}).get("context_code")
        )
        capabilities = get_team_context_capabilities(competicio, requested_context_code)
        if not capabilities.get("exists"):
            equips_cfg["context_code"] = NATIVE_EQUIP_CONTEXT_CODE
            equips_cfg["assignment_source"] = {
                "mode": "context",
                "context_code": NATIVE_EQUIP_CONTEXT_CODE,
                "fallback": NATIVE_EQUIP_CONTEXT_CODE,
            }
            warnings.append(
                f"{mode.capitalize()}: equips.context_code '{requested_context_code}' no existeix; s'ha substituit pel context Base."
            )
            dropped.append(f"equips.context_code: {requested_context_code} -> {NATIVE_EQUIP_CONTEXT_CODE}")
    schema["equips"] = equips_cfg
    scoreable_by_app = scoreable_codes_by_app_id(
        competicio,
        tipus=tipus,
        assignment_context_code=equips_cfg.get("context_code"),
        team_mode=equips_cfg.get("team_mode"),
    )

    punt = schema.get("puntuacio") or {}
    if not isinstance(punt, dict):
        punt = {}
    schema["puntuacio"] = punt

    apps_cfg = punt.get("aparells") or {}
    if not isinstance(apps_cfg, dict):
        apps_cfg = {}
    ids_raw = apps_cfg.get("ids") or []
    selected_ids = []
    seen = set()
    for raw in ids_raw if isinstance(ids_raw, list) else []:
        try:
            app_id = int(raw)
        except Exception:
            continue
        if app_id in active_set and app_id not in seen:
            seen.add(app_id)
            selected_ids.append(app_id)
    if mode == "force" and not selected_ids and active_ids:
        selected_ids = list(active_ids)
        warnings.append("FORCE: no hi havia aparells seleccionats; s'han seleccionat tots els actius.")
    apps_cfg["mode"] = "seleccionar"
    apps_cfg["ids"] = selected_ids
    punt["aparells"] = apps_cfg

    camps_in = punt.get("camps_per_aparell") or {}
    camps_out = {}
    for app_id in list(selected_ids):
        raw_codes = None
        if isinstance(camps_in, dict):
            raw_codes = camps_in.get(str(app_id))
            if raw_codes is None:
                raw_codes = camps_in.get(app_id)
        if isinstance(raw_codes, str):
            req_codes = [x.strip() for x in raw_codes.split(",") if x.strip()]
        elif isinstance(raw_codes, list):
            req_codes = [str(x).strip() for x in raw_codes if str(x).strip()]
        else:
            req_codes = []

        allowed = scoreable_by_app.get(app_id, {"total", "TOTAL"})
        kept = [code for code in req_codes if code in allowed]
        if not kept and mode == "assistit":
            dropped.append(f"puntuacio.aparells.ids: {app_id} (sense camps compatibles)")
            warnings.append(f"Assistit: s'ha descartat aparell {app_id} per manca de camps compatibles.")
            continue
        if not kept and mode == "force":
            kept = ["total"]
            warnings.append(f"FORCE: aparell {app_id} sense camps compatibles; s'ha aplicat camp 'total'.")
        camps_out[str(app_id)] = kept

    selected_ids_after = [app_id for app_id in selected_ids if str(app_id) in camps_out]
    if mode == "force" and not selected_ids_after and active_ids:
        for app_id in active_ids:
            camps_out[str(app_id)] = ["total"]
        selected_ids_after = list(active_ids)
        warnings.append("FORCE: no quedaven aparells vàlids; s'han activat tots amb camp 'total'.")

    apps_cfg["ids"] = selected_ids_after
    punt["camps_per_aparell"] = camps_out

    ex_per_app_in = punt.get("exercicis_per_aparell") or {}
    ex_per_app_out = {}
    if isinstance(ex_per_app_in, dict):
        for raw_key, cfg in ex_per_app_in.items():
            try:
                app_id = int(raw_key)
            except Exception:
                continue
            if app_id in selected_ids_after:
                ex_per_app_out[str(app_id)] = cfg
    punt["exercicis_per_aparell"] = ex_per_app_out
    agg_ex_per_app_in = punt.get("agregacio_exercicis_per_aparell") or {}
    agg_ex_per_app_out = {}
    if isinstance(agg_ex_per_app_in, dict):
        for raw_key, raw_value in agg_ex_per_app_in.items():
            try:
                app_id = int(raw_key)
            except Exception:
                continue
            if app_id in selected_ids_after:
                agg_ex_per_app_out[str(app_id)] = raw_value
    punt["agregacio_exercicis_per_aparell"] = _sanitize_agregacio_exercicis_per_aparell(
        agg_ex_per_app_out,
        fallback=punt.get("agregacio_exercicis", "sum"),
    )

    allowed_particio_codes = {
        str(item.get("code") or "").strip()
        for item in get_allowed_group_fields(competicio)
        if str(item.get("code") or "").strip()
    }
    part_entries_in = normalize_particions_v2_entries(
        schema.get("particions_v2") or [],
        fallback_codes=schema.get("particions") or [],
    )
    part_entries_out = []
    parts_out = []
    for entry in part_entries_in:
        code = str(entry.get("code") or "").strip()
        if code in allowed_particio_codes:
            part_entries_out.append(entry)
            parts_out.append(code)
        else:
            dropped.append(f"particions: {code}")
            warnings.append(f"Assistit/FORCE: s'ha eliminat la particio no compatible '{code}'.")
    schema["particions"] = parts_out
    schema["particions_v2"] = part_entries_out

    custom_in = normalize_particions_custom(schema.get("particions_custom") or {})
    custom_out = {}
    for code, cfg in custom_in.items():
        if code in allowed_particio_codes and code in parts_out:
            custom_out[code] = cfg
        else:
            dropped.append(f"particions_custom: {code}")
            warnings.append(f"Assistit/FORCE: s'ha eliminat la configuracio custom de particio '{code}'.")
    schema["particions_custom"] = custom_out

    des_in = schema.get("desempat") or []
    des_out = []
    for idx, tie in enumerate(des_in if isinstance(des_in, list) else []):
        if not isinstance(tie, dict):
            continue
        item = materialize_desempat_item(
            tie,
            tipus=tipus,
            team_mode=equips_cfg.get("team_mode", ""),
            selected_app_ids=selected_ids_after,
            default_id=f"tie_{idx + 1}",
            default_nom=f"Criteri {idx + 1}",
            allow_participants=(str(tipus or "").strip().lower() == "equips" and normalize_team_mode(equips_cfg.get("team_mode")) != "native_team"),
            fallback_pipeline=build_main_scoring_pipeline_from_schema(
                {"puntuacio": punt},
                tipus=tipus,
                team_mode=equips_cfg.get("team_mode", ""),
            ),
        )
        if not isinstance(item, dict):
            continue
        camps = _normalize_tie_camps_for_validation(item)
        if not camps:
            dropped.append(f"desempat[{idx}] (sense camps)")
            warnings.append(f"Assistit/FORCE: desempat[{idx}] eliminat per manca de camps.")
            continue

        scope = item.get("scope") or {}
        if not isinstance(scope, dict):
            scope = {}
        app_scope = scope.get("aparells") or {}
        if not isinstance(app_scope, dict):
            app_scope = {}
        app_mode = str(app_scope.get("mode") or "hereta").strip().lower()

        if app_mode == "seleccionar":
            target_ids = [x for x in _parse_positive_int_list(app_scope.get("ids")) if x in set(selected_ids_after)]
            app_scope["ids"] = target_ids
            scope["aparells"] = app_scope
            item["scope"] = scope
            if not target_ids:
                dropped.append(f"desempat[{idx}] (sense aparells d'abast)")
                warnings.append(f"Assistit/FORCE: desempat[{idx}] eliminat per manca d'aparells compatibles.")
                continue
        else:
            target_ids = list(selected_ids_after)
            if not target_ids:
                dropped.append(f"desempat[{idx}] (sense aparells heretats)")
                warnings.append(f"Assistit/FORCE: desempat[{idx}] eliminat per manca d'aparells heretats.")
                continue

        valid_camps = []
        for code in camps:
            is_valid_for_all = True
            for app_id in target_ids:
                allowed = scoreable_by_app.get(app_id, {"total", "TOTAL"})
                if code not in allowed:
                    is_valid_for_all = False
                    break
            if is_valid_for_all:
                valid_camps.append(code)
        if not valid_camps:
            dropped.append(f"desempat[{idx}] (camps incompatibles)")
            warnings.append(f"Assistit/FORCE: desempat[{idx}] eliminat per camps incompatibles.")
            continue
        item["camps"] = valid_camps
        item["camp"] = valid_camps[0]

        ex_map_in = item.get("exercicis_per_aparell") or {}
        ex_map_out = {}
        if isinstance(ex_map_in, dict):
            for raw_key, cfg in ex_map_in.items():
                try:
                    app_id = int(raw_key)
                except Exception:
                    continue
                if app_id in target_ids:
                    ex_map_out[str(app_id)] = cfg
        item["exercicis_per_aparell"] = ex_map_out
        agg_ex_map_in = item.get("agregacio_exercicis_per_aparell") or {}
        agg_ex_map_out = {}
        if isinstance(agg_ex_map_in, dict):
            for raw_key, raw_value in agg_ex_map_in.items():
                try:
                    app_id = int(raw_key)
                except Exception:
                    continue
                if app_id in target_ids:
                    agg_ex_map_out[str(app_id)] = raw_value
        item["agregacio_exercicis_per_aparell"] = _sanitize_agregacio_exercicis_per_aparell(
            agg_ex_map_out,
            fallback=item.get("agregacio_exercicis", "sum"),
        )
        des_out.append(item)
    schema["desempat"] = des_out

    presentacio = schema.get("presentacio") or {}
    if not isinstance(presentacio, dict):
        presentacio = {}
    cols_in = presentacio.get("columnes") or []
    cols_out = []
    for idx, col in enumerate(cols_in if isinstance(cols_in, list) else []):
        if not isinstance(col, dict):
            continue
        item = json_clone(col)
        ctype = str(item.get("type") or "builtin").strip().lower()
        if ctype != "raw":
            cols_out.append(item)
            continue
        src = item.get("source") if isinstance(item.get("source"), dict) else {}
        try:
            app_id = int(src.get("aparell_id"))
        except Exception:
            app_id = None
        camp = str(src.get("camp") or "total").strip() or "total"
        if not app_id or app_id not in set(selected_ids_after):
            dropped.append(f"presentacio.columnes[{idx}] raw (aparell invalid)")
            warnings.append(f"Assistit/FORCE: s'ha eliminat columna raw {idx + 1} per aparell no compatible.")
            continue
        allowed = scoreable_by_app.get(app_id, {"total", "TOTAL"})
        if camp not in allowed:
            dropped.append(f"presentacio.columnes[{idx}] raw (camp invalid)")
            warnings.append(f"Assistit/FORCE: s'ha eliminat columna raw {idx + 1} per camp no compatible.")
            continue
        cols_out.append(item)

    if not cols_out:
        cols_out = json_clone((DEFAULT_SCHEMA.get("presentacio") or {}).get("columnes") or [])
        warnings.append("Assistit/FORCE: no quedaven columnes; s'han aplicat columnes per defecte.")
    presentacio["columnes"] = cols_out
    schema["presentacio"] = presentacio

    equips_cfg = schema.get("equips") or {}
    if isinstance(equips_cfg, dict):
        assignment_source = _classification_assignment_source(equips_cfg.get("assignment_source"))
        equips_cfg["assignment_source"] = assignment_source
        teams = list(_classification_teams_queryset(competicio, assignment_source).only("id", "nom"))
        valid_team_ids = {int(team.id) for team in teams}
        id_by_name = {}
        for team in teams:
            key = str(team.nom or "").strip().casefold()
            if key and key not in id_by_name:
                id_by_name[key] = int(team.id)
        manual_in = equips_cfg.get("particions_manuals") or []
        manual_out = []
        for idx, item in enumerate(manual_in if isinstance(manual_in, list) else []):
            if not isinstance(item, dict):
                continue
            ids = []
            seen_ids = set()
            for raw_id in (item.get("equip_ids") or []):
                try:
                    equip_id = int(raw_id)
                except Exception:
                    continue
                if equip_id in valid_team_ids and equip_id not in seen_ids:
                    seen_ids.add(equip_id)
                    ids.append(equip_id)
            unresolved_names = []
            for raw_name in (item.get("equips_noms") or []):
                key = str(raw_name or "").strip().casefold()
                if not key:
                    continue
                equip_id = id_by_name.get(key)
                if not equip_id:
                    unresolved_names.append(str(raw_name or "").strip())
                    continue
                if equip_id in seen_ids:
                    continue
                seen_ids.add(equip_id)
                ids.append(equip_id)
            row = dict(item)
            row["equip_ids"] = ids
            label = str(row.get("label") or row.get("key") or f"Particio {idx + 1}").strip()
            if unresolved_names:
                dropped.append(
                    f"equips.particions_manuals[{idx}]: equips no trobats ({', '.join(unresolved_names)})"
                )
                warnings.append(
                    f"{mode.capitalize()}: la particio manual '{label}' no ha pogut resoldre tots els equips al context actiu."
                )
            if ids:
                manual_out.append(row)
            elif mode == "assistit":
                manual_out.append(row)
            else:
                warnings.append(f"FORCE: s'ha eliminat particio manual d'equips {idx + 1} sense equips mapejats.")
        equips_cfg["particions_manuals"] = manual_out
        schema["equips"] = equips_cfg

    return schema, warnings, dropped


def next_cfg_ordre_for_competicio(competicio):
    last = (
        ClassificacioConfig.objects
        .filter(competicio=competicio)
        .order_by("-ordre", "-id")
        .values_list("ordre", flat=True)
        .first()
    )
    try:
        return int(last or 0) + 1
    except Exception:
        return 1


__all__ = [
    "autofix_schema_for_competicio",
    "build_cfg_status",
    "build_force_minimal_schema",
    "collect_particio_value_choices",
    "distinct_fk",
    "distinct_values",
    "get_equip_context_payload",
    "get_team_context_capabilities",
    "get_allowed_group_fields",
    "is_fk",
    "next_cfg_ordre_for_competicio",
    "normalize_classificacio_equips_cfg",
    "normalize_classificacio_filters",
    "normalize_exercise_selection_scope",
    "normalize_particions_schema",
    "normalize_team_mode",
    "prepare_schema_for_builder_hydration",
    "scoreable_codes_by_app_id",
    "selected_app_ids_from_schema",
    "sanitize_schema_for_builder",
    "with_mode_resolution",
]
