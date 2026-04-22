"""Frozen compute runtime moved out of the legacy package.

This module is a temporary runtime snapshot that keeps the public
classification compute path off `services/legacy/` while the extracted
engine modules continue converging on a smaller orchestrator.
"""

import json
import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.db import models
from django.utils import timezone

from ....models import Inscripcio
from ...shared.birth_year_ranges import (
    BIRTH_YEAR_RANGE_PARTITION_CODE,
    DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG,
    birth_year_range_partition_value,
    legacy_team_age_partition_to_birth_year_range_config,
    normalize_birth_year_range_partition_config,
)
from ...teams.equip_contexts import (
    NATIVE_EQUIP_CONTEXT_CODE,
    get_contextual_assignment_map,
    normalize_equip_context_code,
)
from ...scoring.team_scoring import is_team_context_app
from .detail_payload import (
    build_detail_runtime,
    get_detail_display_config as engine_get_detail_display_config,
    get_display_columns as engine_get_display_columns,
)
from .loaders import load_engine_orm_data
from .metrics_runtime import (
    _sanitize_desempat_for_tipus as engine_sanitize_desempat_for_tipus,
    build_metrics_runtime,
    build_metrics_runtime_adapters,
    calc_criterion_value as engine_calc_criterion_value,
)
from .ranking import _rank_v2 as engine_rank_rows
from .score_values import (
    _apply_simple_agg,
    _get_score_field,
    _to_float,
)
from .selection_runtime import build_selection_runtime
from .schema import normalize_schema as engine_normalize_schema
from .teams import _build_resolved_team_by_ins_id, _build_team_grouped, _build_team_rows
from .victories import (
    build_victories_adapters,
    _normalize_mode_resultat_aparells as engine_normalize_mode_resultat_aparells,
    _normalize_victories_cfg as engine_normalize_victories_cfg,
)

logger = logging.getLogger(__name__)

EXERCISE_SELECTION_SCOPE_PER_MEMBER = "per_member"
EXERCISE_SELECTION_SCOPE_TEAM_POOL = "team_pool"
EXERCISE_SELECTION_SCOPE_INHERIT = "hereta"
CLASSIFICACIO_FILTER_KEYS = (
    "entitats_in",
    "categories_in",
    "subcategories_in",
    "grups_in",
)

def _normalize_positive_int(value):
    try:
        num = int(value)
    except Exception:
        return None
    return num if num > 0 else None


def _normalized_text_token(value) -> str:
    txt = str(value or "")
    txt = " ".join(txt.split()).strip()
    return txt.casefold()


def _normalize_classificacio_filter_values(raw_values, *, groups=False):
    items = raw_values if isinstance(raw_values, list) else ([] if raw_values in (None, "") else [raw_values])
    out = []
    seen = set()
    for raw in items:
        if raw is None or isinstance(raw, bool):
            continue

        as_int = None
        if isinstance(raw, int):
            as_int = _normalize_positive_int(raw)
        elif isinstance(raw, Decimal):
            try:
                if raw == raw.to_integral_value():
                    as_int = _normalize_positive_int(int(raw))
            except Exception:
                as_int = None
        elif isinstance(raw, float):
            if raw.is_integer():
                as_int = _normalize_positive_int(int(raw))

        txt = ""
        if as_int is None:
            txt = str(raw).strip()
            if not txt:
                continue
            parsed = _normalize_positive_int(txt)
            if parsed is not None:
                as_int = parsed

        if groups:
            stored = str(as_int) if as_int is not None else txt
            token = ("group", _normalized_text_token(stored))
        elif as_int is not None:
            stored = int(as_int)
            token = ("id", int(as_int))
        else:
            stored = txt
            token = ("txt", _normalized_text_token(txt))

        if not stored or token in seen:
            continue
        seen.add(token)
        out.append(stored)
    return out


def _normalize_classificacio_filters(raw_filters):
    filters = raw_filters if isinstance(raw_filters, dict) else {}
    out = {}
    for key in CLASSIFICACIO_FILTER_KEYS:
        values = _normalize_classificacio_filter_values(
            filters.get(key),
            groups=(key == "grups_in"),
        )
        if values:
            out[key] = values
    return out


def _json_clone(value):
    try:
        return json.loads(json.dumps(value))
    except Exception:
        return value


def _normalized_group_filter_value(inscripcio) -> str:
    group_obj = getattr(inscripcio, "grup_competicio", None)
    display_num = _normalize_positive_int(getattr(group_obj, "display_num", None))
    if display_num is not None:
        return str(display_num)

    legacy_group = _normalize_positive_int(getattr(inscripcio, "grup", None))
    if legacy_group is not None:
        return str(legacy_group)

    raw_group = str(getattr(inscripcio, "grup", "") or "").strip()
    return raw_group


def _inscripcio_matches_filter_field(inscripcio, field_name: str, allowed_values) -> bool:
    if not allowed_values:
        return True

    if _is_relational_field(Inscripcio, field_name):
        candidate_id = _normalize_positive_int(getattr(inscripcio, f"{field_name}_id", None))
        candidate_text = _normalized_text_token(_display_value(inscripcio, field_name))
        for raw in allowed_values:
            raw_id = _normalize_positive_int(raw)
            if raw_id is not None and candidate_id is not None and raw_id == candidate_id:
                return True
            if candidate_text and candidate_text == _normalized_text_token(raw):
                return True
        return False

    candidate_text = _normalized_text_token(getattr(inscripcio, field_name, None))
    if not candidate_text:
        return False
    for raw in allowed_values:
        if candidate_text == _normalized_text_token(raw):
            return True
    return False


def _inscripcio_matches_classificacio_filters(inscripcio, filtres) -> bool:
    filters = _normalize_classificacio_filters(filtres)
    if not filters:
        return True

    if not _inscripcio_matches_filter_field(inscripcio, "entitat", filters.get("entitats_in") or []):
        return False
    if not _inscripcio_matches_filter_field(inscripcio, "categoria", filters.get("categories_in") or []):
        return False
    if not _inscripcio_matches_filter_field(inscripcio, "subcategoria", filters.get("subcategories_in") or []):
        return False

    group_filters = filters.get("grups_in") or []
    if group_filters:
        candidate_group = _normalized_text_token(_normalized_group_filter_value(inscripcio))
        if not candidate_group:
            return False
        if all(candidate_group != _normalized_text_token(raw) for raw in group_filters):
            return False

    return True


def _native_team_members_match_classificacio_filters(member_rows, filtres) -> bool:
    resolved_members = []
    seen_ids = set()
    for item in member_rows or []:
        if not isinstance(item, (list, tuple)) or not item:
            return False
        member = item[0]
        member_id = _normalize_positive_int(getattr(member, "id", None))
        if member_id is None or member_id in seen_ids:
            continue
        seen_ids.add(member_id)
        resolved_members.append(member)

    if not resolved_members:
        return False

    for member in resolved_members:
        if not _inscripcio_matches_classificacio_filters(member, filtres):
            return False
    return True


# -----------------------------
# DEFAULTS (nova proposta)
# -----------------------------
DEFAULT_SCHEMA = {
    "particions": [],
    "particions_v2": [],
    "particions_custom": {},
    "particions_config": {
        BIRTH_YEAR_RANGE_PARTITION_CODE: {
            **DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG,
        },
    },
    "filtres": {
        "entitats_in": [],
        "categories_in": [],
        "subcategories_in": [],
        "grups_in": [],
    },

    # NOVA puntuaciÃ³ (per aparell), perÃ² mantenim claus legacy per no trencar res
    "puntuacio": {
        # legacy (si el front antic encara ho envia)
        "camp": "total",
        "agregacio": "sum",
        "best_n": 1,

        # exercicis (global): com es trien exercicis dins de cada aparell
        # - "tots": suma/agrega tots els exercicis disponibles (fins nombre_exercicis)
        # - "millor_1": tria el millor exercici
        # - "millor_n": tria els N millors
        # - "pitjor_1": tria el pitjor exercici
        # - "pitjor_n": tria els N pitjors
        "exercicis": {"mode": "tots", "index": 1, "ids": [], "max_per_participant": 0},
        "exercicis_best_n": 1,
        # mode de seleccio d'exercicis:
        # - per_aparell_global: regla global aplicada per aparell
        # - per_aparell_override: regla configurable per aparell
        # - global_pool: seleccio global amb tots els exercicis en un mateix sac
        "mode_seleccio_exercicis": "per_aparell_global",
        "exercicis_per_aparell": {},

        # aparells a incloure
        "aparells": {"mode": "tots", "ids": []},  # tots / seleccionar

        # --- NOU ---
        # camps per aparell: dict { "<comp_aparell_id>": ["TOTAL","E_total",...]}
        # (no validem contra allowed fixed; si el camp no existeix -> 0)
        "camps_mode_per_aparell": {},
        "camps_per_aparell": {},
        "camps_per_exercici_per_aparell": {},
        "agregacio_camps_per_aparell": {},
        "agregacio_camps_per_exercici_per_aparell": {},

        # agregaciÃ³ dels camps seleccionats DINS d'un exercici (nota)
        # sum/avg/median/max/min
        "agregacio_camps": "sum",
        "candidate_source_mode": "raw_exercise",
        "candidate_source_cfg": {
            "mode": "tots",
            "best_n": 1,
            "index": 1,
            "ids": [],
            "agregacio_exercicis": "sum",
        },
        "candidate_source_per_aparell": {},

        # agregaciÃ³ dels exercicis DINS d'un aparell (desprÃ©s de triar exercicis)
        # sum/avg/median/max/min
        "agregacio_exercicis": "sum",

        # agregaciÃ³ FINAL entre aparells
        # sum/avg/median/max/min
        "agregacio_aparells": "sum",

        # selecciÃ³ final de membres per aparell
        "participants_per_aparell": {},
        "agregacio_participants_per_aparell": {},

        # resultat comparable per aparell:
        # - score: usa directament el valor agregat per aparell
        # - victories: compara participants dins de cada aparell i suma victories
        "mode_resultat_aparells": "score",
        "victories": {
            "punts_victoria": 1,
            "punts_empat": 0.5,
            "sense_nota_mode": "skip",
            "mode_camps": "agregat",
            "mode_exercicis": "agregat",
            "mode_seleccio_exercicis_camps_separats": "per_camp",
            "agregacio_victories_camps": "sum",
            "agregacio_victories_exercicis": "sum",
            "desempat_comparacio": [],
        },

        # ordre principal del ranking
        "ordre": "desc",  # desc = mÃ©s punts millor
    },

    # desempats: admet format legacy i nou
    # legacy: {"camp":"execucio_total","ordre":"desc"}
    # nou: {"aparell_id": 12, "camp":"E_total", "ordre":"desc"}
    "desempat": [],

    "presentacio": {
        "top_n": 0,
        "mostrar_empats": True,
        "columnes": [
            {"type": "builtin", "key": "posicio", "label": "#", "align": "left"},
            {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
            {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
        ],
        "detall": {
            "enabled": False,
            "default_open": False,
            "sections": [],
        },
    },

    # Config additiva per tipus="equips"
    "equips": {
        "context_code": NATIVE_EQUIP_CONTEXT_CODE,
        "team_mode": "",
        "mode_resolution": {
            "resolved_at": "",
            "eligible_team_app_ids_at_save": [],
        },
        "assignment_source": {
            "mode": "context",
            "context_code": NATIVE_EQUIP_CONTEXT_CODE,
            "fallback": NATIVE_EQUIP_CONTEXT_CODE,
        },
        "incloure_sense_equip": False,
        "particions_manuals": [],  # [{key,label,equip_ids:[...]}]
        "particio_edat": {
            "activa": False,
            "llindars": [],
            "sense_data_label": "Sense edat",
        },
        "combinar_manual_i_edat": False,
    },
}

# -----------------------------
# utils existents (mantenim)
# -----------------------------
def _is_relational_field(model_cls, field_name: str) -> bool:
    try:
        f = model_cls._meta.get_field(field_name)
        return isinstance(f, (models.ForeignKey, models.OneToOneField))
    except Exception:
        return False


def _filter_in(qs, model_cls, field_name: str, ids: list):
    if not ids:
        return qs
    if _is_relational_field(model_cls, field_name):
        return qs.filter(**{f"{field_name}_id__in": ids})
    return qs.filter(**{f"{field_name}__in": ids})


def _display_value(ins, field_name: str) -> str:
    val = getattr(ins, field_name, None)
    if val is None:
        return ""
    if hasattr(val, "_meta"):
        return getattr(val, "nom", None) or str(val)
    return str(val)


def _json_clone_value(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except Exception:
        return value


def _merge_schema(schema: dict) -> dict:
    out = {**DEFAULT_SCHEMA}
    schema = schema or {}
    raw_parts = schema.get("particions", DEFAULT_SCHEMA["particions"]) or []
    raw_parts_v2 = schema.get("particions_v2", DEFAULT_SCHEMA["particions_v2"]) or []
    part_entries = normalize_particions_v2_entries(raw_parts_v2, fallback_codes=raw_parts)
    out["particions_v2"] = part_entries
    out["particions"] = particio_codes_from_entries(part_entries)
    raw_custom = schema.get("particions_custom", DEFAULT_SCHEMA["particions_custom"]) or {}
    out["particions_custom"] = raw_custom if isinstance(raw_custom, dict) else {}
    out["particions_config"] = normalize_particions_config(
        schema.get("particions_config", DEFAULT_SCHEMA["particions_config"]) or {}
    )
    out["filtres"] = _normalize_classificacio_filters(schema.get("filtres") or {})
    out["puntuacio"] = {**DEFAULT_SCHEMA["puntuacio"], **(schema.get("puntuacio") or {})}
    out["puntuacio"]["victories"] = {
        **DEFAULT_SCHEMA["puntuacio"]["victories"],
        **((((schema.get("puntuacio") or {}).get("victories")) or {}) if isinstance(schema.get("puntuacio"), dict) else {}),
    }
    out["presentacio"] = {**DEFAULT_SCHEMA["presentacio"], **(schema.get("presentacio") or {})}
    out["presentacio"]["detall"] = {
        **DEFAULT_SCHEMA["presentacio"]["detall"],
        **(((schema.get("presentacio") or {}).get("detall")) or {}),
    }
    raw_detail = ((schema.get("presentacio") or {}).get("detall")) or {}
    if isinstance(raw_detail, dict) and "columnes" in raw_detail:
        out["presentacio"]["detall"]["columnes"] = _json_clone_value(raw_detail.get("columnes"))
    if not isinstance(out["presentacio"]["detall"].get("sections"), list):
        out["presentacio"]["detall"]["sections"] = []
    out["desempat"] = schema.get("desempat", DEFAULT_SCHEMA["desempat"]) or []
    out["equips"] = _normalize_classificacio_equips_cfg(schema.get("equips") or {})
    return out


def normalize_particions_config(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    return {
        BIRTH_YEAR_RANGE_PARTITION_CODE: normalize_birth_year_range_partition_config(
            cfg.get(BIRTH_YEAR_RANGE_PARTITION_CODE)
        ),
    }


def _normalize_equip_assignment_source(raw_cfg):
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


def _resolve_classificacio_equips_context_code(raw_context_code=None, raw_assignment_source=None, normalized_assignment_source=None):
    assignment_source = (
        normalized_assignment_source
        if isinstance(normalized_assignment_source, dict)
        else _normalize_equip_assignment_source(raw_assignment_source)
    )
    assignment_source_provided = isinstance(raw_assignment_source, dict) and bool(raw_assignment_source)
    if assignment_source_provided:
        return normalize_equip_context_code(assignment_source.get("context_code"))
    if str(raw_context_code or "").strip():
        return normalize_equip_context_code(raw_context_code)
    return normalize_equip_context_code(assignment_source.get("context_code"))


def _get_effective_team_context_code(equips_cfg):
    cfg = equips_cfg if isinstance(equips_cfg, dict) else {}
    assignment_source = cfg.get("assignment_source")
    if isinstance(assignment_source, dict) and assignment_source:
        return normalize_equip_context_code(assignment_source.get("context_code"))
    return normalize_equip_context_code(cfg.get("context_code"))


def _normalize_team_mode(raw_mode) -> str:
    mode = str(raw_mode or "").strip().lower()
    if mode in {"derived_from_individual", "native_team"}:
        return mode
    return ""


def _normalize_exercise_selection_scope(raw_scope, *, allow_inherit=False):
    scope = str(raw_scope or "").strip().lower()
    allowed = {
        EXERCISE_SELECTION_SCOPE_PER_MEMBER,
        EXERCISE_SELECTION_SCOPE_TEAM_POOL,
    }
    if allow_inherit:
        allowed = allowed | {EXERCISE_SELECTION_SCOPE_INHERIT}
        if not scope:
            return EXERCISE_SELECTION_SCOPE_INHERIT
    if scope in allowed:
        return scope
    return (
        EXERCISE_SELECTION_SCOPE_INHERIT
        if allow_inherit
        else EXERCISE_SELECTION_SCOPE_PER_MEMBER
    )


def _normalize_mode_resolution(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    eligible_ids = []
    seen_ids = set()
    for raw_id in (cfg.get("eligible_team_app_ids_at_save") or []):
        try:
            app_id = int(raw_id)
        except Exception:
            continue
        if app_id > 0 and app_id not in seen_ids:
            seen_ids.add(app_id)
            eligible_ids.append(app_id)
    return {
        "resolved_at": str(cfg.get("resolved_at") or "").strip(),
        "eligible_team_app_ids_at_save": eligible_ids,
    }


def _normalize_classificacio_equips_cfg(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    raw_assignment_source = cfg.get("assignment_source")
    assignment_source = _normalize_equip_assignment_source(raw_assignment_source)
    context_code = _resolve_classificacio_equips_context_code(
        cfg.get("context_code"),
        raw_assignment_source,
        assignment_source,
    )
    if not (isinstance(raw_assignment_source, dict) and raw_assignment_source):
        assignment_source = {
            **assignment_source,
            "context_code": context_code,
        }
    return {
        **DEFAULT_SCHEMA["equips"],
        **cfg,
        "context_code": context_code,
        "team_mode": _normalize_team_mode(cfg.get("team_mode")),
        "mode_resolution": _normalize_mode_resolution(cfg.get("mode_resolution")),
        "assignment_source": assignment_source,
        "particio_edat": {
            **DEFAULT_SCHEMA["equips"]["particio_edat"],
            **(cfg.get("particio_edat") or {}),
        },
    }


def _competition_reference_date(competicio):
    ref_date = getattr(competicio, "data", None)
    return ref_date if isinstance(ref_date, date) else None


def _has_explicit_birth_year_team_rules(schema):
    if not isinstance(schema, dict):
        return False
    part_cfg = ((schema.get("particions_config") or {}).get(BIRTH_YEAR_RANGE_PARTITION_CODE)) or {}
    return isinstance(part_cfg, dict) and isinstance(part_cfg.get("team_rules"), dict)


def _has_explicit_birth_year_ranges(schema):
    if not isinstance(schema, dict):
        return False
    part_cfg = ((schema.get("particions_config") or {}).get(BIRTH_YEAR_RANGE_PARTITION_CODE)) or {}
    return bool((part_cfg if isinstance(part_cfg, dict) else {}).get("ranges"))


def normalize_schema_legacy_team_birth_partition(competicio, schema, *, tipus="individual", persist=False):
    raw_schema = schema if isinstance(schema, dict) else {}
    out = _merge_schema(raw_schema)
    info = {
        "legacy_inferred": False,
        "legacy_pending_review": False,
        "compatibility_errors": [],
    }

    if str(tipus or "").strip().lower() != "equips":
        return out, info

    equips_cfg = _normalize_classificacio_equips_cfg(out.get("equips") or {})
    age_cfg = equips_cfg.get("particio_edat") or {}
    age_active = bool(age_cfg.get("activa", False))
    if not age_active:
        if persist:
            equips_cfg["particio_edat"] = dict(DEFAULT_SCHEMA["equips"]["particio_edat"])
            equips_cfg["combinar_manual_i_edat"] = False
            out["equips"] = equips_cfg
        return out, info

    info["legacy_inferred"] = True
    if equips_cfg.get("particions_manuals") and not bool(equips_cfg.get("combinar_manual_i_edat", False)):
        info["legacy_pending_review"] = True
        info["compatibility_errors"].append(
            "La configuracio legacy amb particions manuals + edat maxima sense combinar no es pot convertir automaticament."
        )
    else:
        part_entries = normalize_particions_v2_entries(
            out.get("particions_v2") or [],
            fallback_codes=out.get("particions") or [],
        )
        if not any(str((entry or {}).get("code") or "").strip() == BIRTH_YEAR_RANGE_PARTITION_CODE for entry in part_entries):
            part_entries.append(
                {"code": BIRTH_YEAR_RANGE_PARTITION_CODE, "apply_mode": "all", "parent_values": []}
            )
        out["particions_v2"] = part_entries
        out["particions"] = particio_codes_from_entries(part_entries)

        current_cfg = dict((((raw_schema.get("particions_config") or {}).get(BIRTH_YEAR_RANGE_PARTITION_CODE)) or {}))
        if not _has_explicit_birth_year_ranges(raw_schema):
            ref_date = _competition_reference_date(competicio)
            if not isinstance(ref_date, date):
                info["legacy_pending_review"] = True
                info["compatibility_errors"].append(
                    "No es pot inferir la particio legacy d'edat maxima sense data de competicio."
                )
            else:
                current_cfg = {
                    **legacy_team_age_partition_to_birth_year_range_config(age_cfg, ref_date),
                    **current_cfg,
                }
        if not _has_explicit_birth_year_team_rules(raw_schema):
            current_cfg = {
                **current_cfg,
                "team_rules": {
                    "reference_mode": "oldest_member_birthdate",
                    "compliance_mode": "strict",
                    "max_members_outside_range": 0,
                    "missing_birthdate_policy": "outside_range",
                },
            }
        out["particions_config"] = {
            **(out.get("particions_config") or {}),
            BIRTH_YEAR_RANGE_PARTITION_CODE: normalize_birth_year_range_partition_config(current_cfg),
        }

    if persist:
        equips_cfg["particio_edat"] = dict(DEFAULT_SCHEMA["equips"]["particio_edat"])
        equips_cfg["combinar_manual_i_edat"] = False
    out["equips"] = equips_cfg
    return out, info


def _infer_team_mode_from_comp_aparells(comp_aparells) -> str:
    saw_individual = False
    saw_team = False
    for comp_aparell in comp_aparells or []:
        if is_team_context_app(comp_aparell):
            saw_team = True
        else:
            saw_individual = True
    if saw_individual and saw_team:
        return ""
    if saw_team:
        return "native_team"
    return "derived_from_individual"


_MISSING = object()


def _inscripcio_value_for_partition(ins: Inscripcio, field_code: str):
    code = (field_code or "").strip()
    if not code:
        return None

    extra = getattr(ins, "extra", None) or {}
    if isinstance(extra, dict) and code.startswith("excel__"):
        if code in extra:
            return extra.get(code)
        legacy_code = code[len("excel__") :]
        if legacy_code in extra:
            return extra.get(legacy_code)

    val = getattr(ins, code, _MISSING)
    if val is not _MISSING:
        return val

    if isinstance(extra, dict):
        if code in extra:
            return extra.get(code)
        if code.startswith("excel__"):
            legacy_code = code[len("excel__") :]
            if legacy_code in extra:
                return extra.get(legacy_code)
    return None


def _birth_year_range_partition_value(ins: Inscripcio, particions_config: dict):
    cfg = normalize_birth_year_range_partition_config(
        ((particions_config or {}).get(BIRTH_YEAR_RANGE_PARTITION_CODE))
    )
    return birth_year_range_partition_value(ins, cfg)


def _dedupe_int_ids_preserve_order(raw_ids):
    out = []
    seen = set()
    for raw_id in list(raw_ids or []):
        try:
            value = int(raw_id)
        except Exception:
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _birth_year_range_partition_value_for_team(member_rows, particions_config: dict):
    cfg = normalize_birth_year_range_partition_config(
        ((particions_config or {}).get(BIRTH_YEAR_RANGE_PARTITION_CODE))
    )
    team_rules = cfg.get("team_rules") or {}
    sense_label = cfg.get("sense_data_label") or DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG["sense_data_label"]
    outside_label = cfg.get("fora_rang_label") or DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG["fora_rang_label"]

    members = [item[0] for item in (member_rows or []) if isinstance(item, (list, tuple)) and item]
    birth_dates = [getattr(member, "data_naixement", None) for member in members if isinstance(getattr(member, "data_naixement", None), date)]
    if not birth_dates:
        return sense_label

    oldest_birth_date = min(birth_dates)
    candidate_label = birth_year_range_partition_value(
        SimpleNamespace(data_naixement=oldest_birth_date),
        cfg,
    )
    if candidate_label in {sense_label, outside_label}:
        return candidate_label

    outside_count = 0
    for member in members:
        birth_date = getattr(member, "data_naixement", None)
        if not isinstance(birth_date, date):
            outside_count += 1
            continue
        member_label = birth_year_range_partition_value(
            SimpleNamespace(data_naixement=birth_date),
            cfg,
        )
        if member_label != candidate_label:
            outside_count += 1

    compliance_mode = str(team_rules.get("compliance_mode") or "strict").strip().lower()
    if compliance_mode == "allow_outside_n":
        limit = max(0, int(team_rules.get("max_members_outside_range") or 0))
        return candidate_label if outside_count <= limit else outside_label
    return candidate_label if outside_count == 0 else outside_label


def _partition_raw_value(ins: Inscripcio, field_code: str, particions_config=None):
    code = (field_code or "").strip()
    if code == BIRTH_YEAR_RANGE_PARTITION_CODE:
        return _birth_year_range_partition_value(ins, particions_config or {})
    return _inscripcio_value_for_partition(ins, code)


def _partition_value_display(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "_meta"):
        return getattr(value, "nom", None) or str(value)
    if isinstance(value, (list, dict)):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(value)
    return str(value)


def _normalize_partition_token(value: str) -> str:
    txt = str(value or "")
    txt = " ".join(txt.split()).strip()
    return txt.casefold()


def _split_particio_custom_values(raw):
    if isinstance(raw, list):
        out = []
        for item in raw:
            txt = str(item or "").strip()
            if txt:
                out.append(txt)
        return out
    if isinstance(raw, str):
        return [x.strip() for x in raw.split(",") if x.strip()]
    return []


def _normalize_partition_parent_values(raw):
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
        key = _normalize_partition_token(txt)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(txt)
    return out


def normalize_particions_v2_entries(raw, fallback_codes=None):
    raw_list = raw if isinstance(raw, list) else []
    fallback = fallback_codes if isinstance(fallback_codes, list) else []
    source = raw_list if raw_list else fallback

    out = []
    seen = set()
    for idx, item in enumerate(source):
        if isinstance(item, dict):
            code = str(item.get("code") or "").strip()
            apply_mode = str(item.get("apply_mode") or "all").strip().lower()
            parent_values = _normalize_partition_parent_values(item.get("parent_values"))
        else:
            code = str(item or "").strip()
            apply_mode = "all"
            parent_values = []

        if not code or code in seen:
            continue
        seen.add(code)

        if idx == 0:
            apply_mode = "all"
            parent_values = []
        elif apply_mode not in {"all", "some_parents"}:
            apply_mode = "all"

        if apply_mode != "some_parents":
            parent_values = []

        out.append(
            {
                "code": code,
                "apply_mode": apply_mode,
                "parent_values": parent_values,
            }
        )

    return out


def particio_codes_from_entries(entries):
    out = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip()
        if code:
            out.append(code)
    return out


def _build_particions_custom_index(raw_cfg):
    out = {}
    if not isinstance(raw_cfg, dict):
        return out

    for field_code, cfg in raw_cfg.items():
        code = str(field_code or "").strip()
        if not code or not isinstance(cfg, dict):
            continue

        mode = str(cfg.get("mode") or "raw").strip().lower()
        fallback_label = str(cfg.get("fallback_label") or "").strip()
        value_map = {}

        for idx, grp in enumerate(cfg.get("grups") or []):
            if not isinstance(grp, dict):
                continue
            grp_label = (
                str(grp.get("label") or grp.get("key") or f"Grup {idx + 1}").strip()
                or f"Grup {idx + 1}"
            )
            for raw_val in _split_particio_custom_values(grp.get("values")):
                norm = _normalize_partition_token(raw_val)
                if norm and norm not in value_map:
                    value_map[norm] = grp_label

        out[code] = {
            "mode": "custom" if mode == "custom" else "raw",
            "fallback_label": fallback_label,
            "value_map": value_map,
        }
    return out


def _resolve_partition_display(field_code: str, raw_display: str, custom_idx: dict) -> str:
    cfg = (custom_idx or {}).get(field_code) or {}
    if (cfg.get("mode") or "raw") != "custom":
        return raw_display

    norm = _normalize_partition_token(raw_display)
    mapped = (cfg.get("value_map") or {}).get(norm)
    if mapped is not None:
        return mapped

    fallback = str(cfg.get("fallback_label") or "").strip()
    if fallback:
        return fallback
    return raw_display


def _partition_key(ins: Inscripcio, fields: list, particions_custom_index=None, particions_config=None):
    parts = []
    for f in fields or []:
        f = (f or "").strip()
        if not f:
            continue
        raw_value = _partition_raw_value(ins, f, particions_config=particions_config)
        display_value = _partition_value_display(raw_value)
        resolved = _resolve_partition_display(f, display_value, particions_custom_index or {})
        parts.append(f"{f}:{resolved}")
    return "|".join(parts) if parts else "global"


def _partition_key_from_entries(ins: Inscripcio, entries: list, particions_custom_index=None, particions_config=None):
    part_entries = normalize_particions_v2_entries(entries)
    if not part_entries:
        return "global"

    parts = []
    parent_resolved = None
    for idx, entry in enumerate(part_entries):
        code = str((entry or {}).get("code") or "").strip()
        if not code:
            continue

        if idx > 0:
            if parent_resolved is None:
                break
            apply_mode = str((entry or {}).get("apply_mode") or "all").strip().lower()
            if apply_mode == "some_parents":
                allowed = {
                    _normalize_partition_token(val)
                    for val in _normalize_partition_parent_values((entry or {}).get("parent_values"))
                }
                if not allowed or _normalize_partition_token(parent_resolved) not in allowed:
                    parent_resolved = None
                    break

        raw_value = _partition_raw_value(ins, code, particions_config=particions_config)
        display_value = _partition_value_display(raw_value)
        resolved = _resolve_partition_display(code, display_value, particions_custom_index or {})
        parts.append(f"{code}:{resolved}")
        parent_resolved = resolved

    return "|".join(parts) if parts else "global"


def _partition_key_from_entries_for_team(member_rows, entries: list, particions_custom_index=None, particions_config=None):
    part_entries = normalize_particions_v2_entries(entries)
    if not part_entries:
        return "global"

    ref_member = None
    for item in member_rows or []:
        if isinstance(item, (list, tuple)) and item:
            ref_member = item[0]
            break

    parts = []
    parent_resolved = None
    for idx, entry in enumerate(part_entries):
        code = str((entry or {}).get("code") or "").strip()
        if not code:
            continue

        if idx > 0:
            if parent_resolved is None:
                break
            apply_mode = str((entry or {}).get("apply_mode") or "all").strip().lower()
            if apply_mode == "some_parents":
                allowed = {
                    _normalize_partition_token(val)
                    for val in _normalize_partition_parent_values((entry or {}).get("parent_values"))
                }
                if not allowed or _normalize_partition_token(parent_resolved) not in allowed:
                    parent_resolved = None
                    break

        if code == BIRTH_YEAR_RANGE_PARTITION_CODE:
            raw_value = _birth_year_range_partition_value_for_team(member_rows, particions_config or {})
        elif ref_member is not None:
            raw_value = _partition_raw_value(ref_member, code, particions_config=particions_config)
        else:
            raw_value = None
        display_value = _partition_value_display(raw_value)
        resolved = _resolve_partition_display(code, display_value, particions_custom_index or {})
        parts.append(f"{code}:{resolved}")
        parent_resolved = resolved

    return "|".join(parts) if parts else "global"


def _pick_exercicis(vals, mode: str, best_n: int):
    """
    vals: llista de valors (1 per exercici) ja agregats per exercici
    """
    xs = [_to_float(x) for x in (vals or [])]
    if not xs:
        return []

    m = (mode or "tots").lower().strip()
    if m == "tots":
        return xs
    if m == "millor_1":
        return [max(xs)]
    if m == "millor_n":
        n = max(1, int(best_n or 1))
        return sorted(xs, reverse=True)[:n]
    if m == "pitjor_1":
        return [min(xs)]
    if m == "pitjor_n":
        n = max(1, int(best_n or 1))
        return sorted(xs)[:n]

    # fallback
    return xs

def _pick_exercicis_rows(
    rows,
    mode: str,
    best_n: int,
    index=None,
    ids=None,
    max_per_participant=0,
    participant_key="inscripcio_id",
):
    """
    rows: [{"idx": int, "value": float, ...}, ...]
    retorna les files seleccionades (mantenint metadades).
    """
    xs = []
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        try:
            idx = int(r.get("idx"))
        except Exception:
            continue
        item = dict(r)
        item["idx"] = idx
        item["value"] = _to_float(r.get("value"))
        xs.append(item)
    if not xs:
        return []

    m = (mode or "tots").lower().strip()

    try:
        max_pp = int(max_per_participant or 0)
    except Exception:
        max_pp = 0
    max_pp = max(0, max_pp)

    def _participant_id_for_row(row):
        pid = row.get(participant_key)
        if pid in (None, ""):
            return "__single__"
        return str(pid)

    def _take_with_cap(rows_iter, limit=None):
        if max_pp <= 0:
            if limit is None:
                return list(rows_iter)
            return list(rows_iter)[:limit]

        counts = defaultdict(int)
        out = []
        for r in rows_iter:
            pid = _participant_id_for_row(r)
            if counts[pid] >= max_pp:
                continue
            counts[pid] += 1
            out.append(r)
            if limit is not None and len(out) >= limit:
                break
        return out

    if m == "tots":
        return _take_with_cap(xs)

    if m == "millor_1":
        ordered = sorted(xs, key=lambda r: (-_to_float(r.get("value")), r.get("idx", 0)))
        return _take_with_cap(ordered, limit=1)

    if m == "millor_n":
        n = max(1, int(best_n or 1))
        ordered = sorted(xs, key=lambda r: (-_to_float(r.get("value")), r.get("idx", 0)))
        return _take_with_cap(ordered, limit=n)

    if m == "pitjor_1":
        ordered = sorted(xs, key=lambda r: (_to_float(r.get("value")), r.get("idx", 0)))
        return _take_with_cap(ordered, limit=1)

    if m == "pitjor_n":
        n = max(1, int(best_n or 1))
        ordered = sorted(xs, key=lambda r: (_to_float(r.get("value")), r.get("idx", 0)))
        return _take_with_cap(ordered, limit=n)

    if m == "primer":
        first_idx = min(r.get("idx", 0) for r in xs)
        for r in xs:
            if r.get("idx") == first_idx:
                return [r]
        return []

    if m == "ultim":
        last_idx = max(r.get("idx", 0) for r in xs)
        for r in xs:
            if r.get("idx") == last_idx:
                return [r]
        return []

    if m == "index":
        try:
            idx = int(index or 1)
        except Exception:
            idx = 1
        for r in xs:
            if r.get("idx") == idx:
                return [r]
        return []

    if m == "llista":
        wanted = set()
        for x in (ids or []):
            try:
                iv = int(x)
            except Exception:
                continue
            if iv > 0:
                wanted.add(iv)
        return _take_with_cap([r for r in xs if r.get("idx") in wanted])

    return _take_with_cap(xs)


def _pick_exercicis_tuples(
    ex_vals,
    mode: str,
    best_n: int,
    index=None,
    ids=None,
    max_per_participant=0,
    participant_key="inscripcio_id",
):
    """
    ex_vals: [(ex_idx, value), ...]
    retorna: [values...]
    """
    rows = []
    for item in (ex_vals or []):
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            idx = int(item[0])
        except Exception:
            continue
        rows.append({"idx": idx, "value": _to_float(item[1])})

    picked = _pick_exercicis_rows(
        rows,
        mode,
        best_n,
        index=index,
        ids=ids,
        max_per_participant=max_per_participant,
        participant_key=participant_key,
    )
    return [_to_float(r.get("value")) for r in picked]


def _normalize_exercicis_cfg(raw_cfg, fallback=None):
    fb = fallback or {}
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}

    mode = str(cfg.get("mode") or fb.get("mode") or "tots").lower().strip()
    allowed_modes = ("tots", "millor_1", "millor_n", "pitjor_1", "pitjor_n", "primer", "ultim", "index", "llista")
    if mode not in allowed_modes:
        mode = str(fb.get("mode") or "tots").lower().strip()
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

    try:
        max_per_participant = int(cfg.get("max_per_participant", fb.get("max_per_participant", 0)))
    except Exception:
        max_per_participant = 0
    max_per_participant = max(0, max_per_participant)

    ids_raw = cfg.get("ids", fb.get("ids", []))
    ids = []
    if isinstance(ids_raw, str):
        parts = [x.strip() for x in ids_raw.split(",") if x.strip()]
        for p in parts:
            try:
                iv = int(p)
            except Exception:
                continue
            if iv > 0:
                ids.append(iv)
    elif isinstance(ids_raw, (list, tuple)):
        for x in ids_raw:
            try:
                iv = int(x)
            except Exception:
                continue
            if iv > 0:
                ids.append(iv)

    return {
        "mode": mode,
        "best_n": best_n,
        "index": index,
        "ids": ids,
        "max_per_participant": max_per_participant,
    }


def _normalize_candidate_source_mode(raw_mode):
    mode = str(raw_mode or "raw_exercise").lower().strip()
    if mode in ("raw_exercise", "participant_aggregate", "team_aggregate"):
        return mode
    return "raw_exercise"


def _normalize_candidate_source_cfg(raw_cfg, fallback=None):
    fb = fallback or {}
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    ex_cfg = _normalize_exercicis_cfg(cfg, fallback=fb)
    agg = str(cfg.get("agregacio_exercicis", fb.get("agregacio_exercicis", "sum")) or "sum").lower().strip()
    if agg not in ("sum", "avg", "median", "max", "min"):
        agg = str(fb.get("agregacio_exercicis") or "sum").lower().strip()
        if agg not in ("sum", "avg", "median", "max", "min"):
            agg = "sum"
    ex_cfg.pop("max_per_participant", None)
    ex_cfg["agregacio_exercicis"] = agg
    return ex_cfg


def _unique_nonempty_strings(raw_values):
    out = []
    seen = set()
    values = raw_values
    if isinstance(values, str):
        values = values.split(",")
    if not isinstance(values, (list, tuple)):
        return out
    for raw in values:
        txt = str(raw or "").strip()
        if not txt or txt in seen:
            continue
        seen.add(txt)
        out.append(txt)
    return out


def _normalize_field_mode(raw_mode):
    mode = str(raw_mode or "comu").strip().lower()
    if mode not in {"comu", "per_exercici"}:
        mode = "comu"
    return mode


def _normalize_optional_agg(raw_agg):
    agg = str(raw_agg or "").strip().lower()
    return agg if agg in {"sum", "avg", "median", "max", "min"} else ""


def _pick_participants(vals, mode: str, n: int):
    xs = [_to_float(x) for x in (vals or [])]
    if not xs:
        return []

    m = (mode or "tots").lower().strip()
    if m in ("hereta", "tots"):
        return xs
    if m == "millor_1":
        return [max(xs)]
    if m == "millor_n":
        k = max(1, int(n or 1))
        return sorted(xs, reverse=True)[:k]
    if m == "pitjor_1":
        return [min(xs)]
    if m == "pitjor_n":
        k = max(1, int(n or 1))
        return sorted(xs)[:k]
    return xs


def _normalize_participants_cfg(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    mode = str(cfg.get("mode") or "tots").strip().lower()
    if mode not in {"tots", "millor_1", "millor_n", "pitjor_1", "pitjor_n"}:
        mode = "tots"
    try:
        n_value = max(1, int(cfg.get("n") or cfg.get("best_n") or 1))
    except Exception:
        n_value = 1
    out = {"mode": mode}
    if mode in {"millor_n", "pitjor_n"}:
        out["n"] = n_value
    return out


def _years_old(birth_date, ref_date):
    if not isinstance(birth_date, date) or not isinstance(ref_date, date):
        return None
    years = ref_date.year - birth_date.year
    before_birthday = (ref_date.month, ref_date.day) < (birth_date.month, birth_date.day)
    return years - 1 if before_birthday else years


def _bucket_edat(age_max, llindars, sense_data_label):
    if age_max is None:
        txt = (sense_data_label or "Sense edat").strip() or "Sense edat"
        return f"edat:{txt}"

    ordered = sorted(set(int(x) for x in (llindars or [])))
    if not ordered:
        return f"edat:{age_max}"

    for th in ordered:
        if age_max <= th:
            return f"edat:<={th}"
    return f"edat:>{ordered[-1]}"


def _resolve_particio_equip(manual_key, age_key, combine):
    if combine:
        if manual_key or age_key:
            return f"{manual_key or 'manual:(cap)'}|{age_key or 'edat:(cap)'}"
        return "global"
    if manual_key:
        return manual_key
    if age_key:
        return age_key
    return "global"


def _normalize_tie_camps(crit: dict):
    raw = crit.get("camps", None)
    out = []

    if isinstance(raw, list):
        out = [str(x).strip() for x in raw if str(x).strip()]
    elif isinstance(raw, str):
        txt = raw.strip()
        if txt:
            out = [x.strip() for x in txt.split(",") if x.strip()]

    if not out:
        legacy = (crit.get("camp") or "").strip()
        if legacy:
            out = [legacy]

    dedup = []
    seen = set()
    for c in out:
        if c in seen:
            continue
        seen.add(c)
        dedup.append(c)
    return dedup


def _is_pipeline_tie(crit: dict) -> bool:
    return isinstance(crit, dict) and isinstance(crit.get("pipeline"), dict)


def _pipeline_tie_signature(crit: dict) -> str:
    if not isinstance(crit, dict):
        return ""
    try:
        pipeline_version = int(crit.get("pipeline_version") or 1)
    except Exception:
        pipeline_version = 1
    payload = {
        "id": str(crit.get("id") or "").strip(),
        "nom": str(crit.get("nom") or "").strip(),
        "ordre": str(crit.get("ordre") or "desc").lower().strip() or "desc",
        "pipeline_version": pipeline_version,
        "pipeline": _json_clone(crit.get("pipeline") or {}),
    }
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return str(payload)


def _tie_key(crit: dict) -> str:
    if _is_pipeline_tie(crit):
        tie_id = str((crit or {}).get("id") or "").strip()
        if tie_id:
            return tie_id
        return _pipeline_tie_signature(crit)

    camps = _normalize_tie_camps(crit)
    if not camps:
        return ""

    scope = crit.get("scope") or {}
    apps = scope.get("aparells") or {}
    ex = scope.get("exercicis") or {}
    parts = scope.get("participants") or {}

    mode = (apps.get("mode") or "").lower().strip()
    if mode == "seleccionar":
        ids = apps.get("ids") or []
        ids_norm = ",".join(str(int(x)) for x in ids) if ids else ""
        apps_sig = f"apps[{ids_norm}]"
    elif mode == "tots":
        apps_sig = "apps[all]"
    else:
        app_id = crit.get("aparell_id", None)
        apps_sig = f"app[{app_id}]" if app_id not in (None, "", 0, "0") else "apps[inherit]"

    ex_mode = (ex.get("mode") or "hereta").lower().strip()
    ex_sig = ex_mode
    if ex_mode in ("millor_n", "pitjor_n"):
        ex_sig += f":{ex.get('best_n') or ''}"
    elif ex_mode == "index":
        ex_sig += f":{ex.get('index') or 1}"
    elif ex_mode == "llista":
        ex_ids = ex.get("ids") or []
        ex_sig += ":" + ",".join(str(int(x)) for x in ex_ids)
    try:
        ex_max_pp = int(ex.get("max_per_participant") or 0)
    except Exception:
        ex_max_pp = 0
    if ex_max_pp > 0:
        ex_sig += f":mpp={ex_max_pp}"

    ex_sel_mode = (
        crit.get("mode_seleccio_exercicis")
        or ex.get("mode_seleccio_exercicis")
        or "hereta"
    )
    ex_sel_mode = str(ex_sel_mode).lower().strip()
    if ex_sel_mode not in ("hereta", "per_aparell_global", "per_aparell_override", "global_pool"):
        ex_sel_mode = "hereta"

    ex_sel_scope = _normalize_exercise_selection_scope(
        crit.get("exercise_selection_scope"),
        allow_inherit=True,
    )

    ex_per_app = (
        crit.get("exercicis_per_aparell")
        or ex.get("exercicis_per_aparell")
        or {}
    )
    ex_per_app_sig = ""
    if isinstance(ex_per_app, dict) and ex_per_app:
        chunks = []
        for k in sorted(ex_per_app.keys(), key=lambda x: str(x)):
            cfg = _normalize_exercicis_cfg(
                ex_per_app.get(k),
                fallback={"mode": "tots", "best_n": 1, "index": 1, "ids": [], "max_per_participant": 0},
            )
            c = f"{k}:{cfg.get('mode')}"
            if cfg.get("mode") in ("millor_n", "pitjor_n"):
                c += f":n={cfg.get('best_n')}"
            elif cfg.get("mode") == "index":
                c += f":i={cfg.get('index')}"
            elif cfg.get("mode") == "llista":
                ids_txt = ",".join(str(int(x)) for x in (cfg.get("ids") or []))
                c += f":ids={ids_txt}"
            if int(cfg.get("max_per_participant") or 0) > 0:
                c += f":mpp={int(cfg.get('max_per_participant') or 0)}"
            chunks.append(c)
        ex_per_app_sig = ";".join(chunks)
    agg_ex_per_app = crit.get("agregacio_exercicis_per_aparell") or {}
    agg_ex_per_app_sig = ""
    if isinstance(agg_ex_per_app, dict) and agg_ex_per_app:
        chunks = []
        for k in sorted(agg_ex_per_app.keys(), key=lambda x: str(x)):
            agg_value = str(agg_ex_per_app.get(k) or "sum").lower().strip()
            chunks.append(f"{k}:{agg_value}")
        agg_ex_per_app_sig = ";".join(chunks)

    p_mode = (parts.get("mode") or "hereta").lower().strip()
    p_sig = p_mode
    if p_mode in ("millor_n", "pitjor_n"):
        p_sig += f":{parts.get('n') or 1}"

    camps_sig = ",".join(camps)
    agg_c = (crit.get("agregacio_camps") or "hereta").lower().strip()
    agg_e = (crit.get("agregacio_exercicis") or "hereta").lower().strip()
    agg_a = (crit.get("agregacio_aparells") or "hereta").lower().strip()
    p_agg = (crit.get("agregacio_participants") or "sum").lower().strip()
    return (
        f"camps[{camps_sig}]|{apps_sig}|ex[{ex_sig}]"
        f"|ex_sel[{ex_sel_mode}]|ex_scope[{ex_sel_scope}]|ex_app[{ex_per_app_sig}]|agg_ex_app[{agg_ex_per_app_sig}]"
        f"|agg_c[{agg_c}]|agg_e[{agg_e}]|agg_a[{agg_a}]"
        f"|parts[{p_sig}]|parts_agg[{p_agg}]"
    )


def _pipeline_subject_key(row: dict):
    if not isinstance(row, dict):
        return None
    ins_id = _normalize_positive_int(row.get("inscripcio_id"))
    if ins_id is not None:
        return ("ins", ins_id)
    equip_id = _normalize_positive_int(row.get("equip_id"))
    if equip_id is not None:
        return ("equip", equip_id)
    member_ids = row.get("_member_ids")
    if isinstance(member_ids, (list, tuple)) and member_ids:
        mids = []
        for raw in member_ids:
            mid = _normalize_positive_int(raw)
            if mid is not None:
                mids.append(mid)
        if mids:
            return ("members", tuple(sorted(set(mids))))
    entitat_nom = str(row.get("entitat_nom") or "").strip()
    if entitat_nom:
        return ("entitat", _normalized_text_token(entitat_nom))
    participant = str(row.get("participant") or row.get("nom") or "").strip()
    if participant:
        return ("nom", _normalized_text_token(participant))
    return None


def _sanitize_desempat_for_tipus(desempat, tipus):
    arr = desempat or []
    out = []
    tipus = (tipus or "individual").lower().strip()

    for raw in arr:
        if not isinstance(raw, dict):
            continue

        item = dict(raw)
        if tipus != "equips":
            scope = item.get("scope")
            if isinstance(scope, dict):
                scope2 = dict(scope)
                scope2.pop("participants", None)
                item["scope"] = scope2
            item.pop("agregacio_participants", None)
        out.append(item)

    return out


def compute_classificacio(competicio, cfg_obj):
    """
    Retorna:
      { "particio_key": [ {row}, ... ] }

    row (individual) mÃ­nim:
      - inscripcio_id, nom, entitat_nom, score, tie{...}
      - posicio/punts els posa _rank()
    """
    tipus = (getattr(cfg_obj, "tipus", "individual") or "individual").lower().strip()
    schema, _legacy_info = engine_normalize_schema(
        competicio,
        getattr(cfg_obj, "schema", {}) or {},
        tipus=tipus,
        persist=False,
    )
    part_entries = schema.get("particions_v2") or normalize_particions_v2_entries(
        schema.get("particions") or []
    )
    part_custom_idx = _build_particions_custom_index(schema.get("particions_custom") or {})
    particions_config = normalize_particions_config(schema.get("particions_config") or {})
    filtres = _normalize_classificacio_filters(schema.get("filtres") or {})
    punt = schema["puntuacio"] or {}
    desempat = schema["desempat"] or []
    presentacio = schema["presentacio"] or {}
    display_columns = engine_get_display_columns(schema)
    equips_cfg = _normalize_classificacio_equips_cfg(schema.get("equips") or {})
    assignment_source = equips_cfg.get("assignment_source") or _normalize_equip_assignment_source({})
    team_context_code = _get_effective_team_context_code(equips_cfg)
    desempat = engine_sanitize_desempat_for_tipus(desempat, tipus)
    mode_resultat_aparells = engine_normalize_mode_resultat_aparells(punt.get("mode_resultat_aparells"))
    victories_cfg = engine_normalize_victories_cfg((punt.get("victories") or {}))
    if tipus != "individual" and mode_resultat_aparells == "victories":
        mode_resultat_aparells = "score"

    # 1) PRETRACTAMENT
    ordre_principal = (punt.get("ordre") or "desc").lower().strip()
    if ordre_principal not in ("asc", "desc"):
        ordre_principal = "desc"

    ex_cfg = punt.get("exercicis") or {}
    base_ex_cfg = _normalize_exercicis_cfg(
        {
            **(ex_cfg if isinstance(ex_cfg, dict) else {}),
            "best_n": (
                (ex_cfg.get("best_n") if isinstance(ex_cfg, dict) else None)
                or punt.get("exercicis_best_n")
                or 1
            ),
        },
        fallback={"mode": "tots", "best_n": 1, "index": 1, "ids": []},
    )
    exerc_mode = base_ex_cfg["mode"]
    ex_best_n = base_ex_cfg["best_n"]
    ex_index = base_ex_cfg["index"]
    ex_ids = base_ex_cfg["ids"]
    mode_seleccio_exercicis = str(punt.get("mode_seleccio_exercicis") or "per_aparell_global").lower().strip()
    if mode_seleccio_exercicis not in ("per_aparell_global", "per_aparell_override", "global_pool"):
        mode_seleccio_exercicis = "per_aparell_global"
    exercicis_per_aparell = punt.get("exercicis_per_aparell") or {}
    if not isinstance(exercicis_per_aparell, dict):
        exercicis_per_aparell = {}
    camps_mode_per_aparell = punt.get("camps_mode_per_aparell") or {}
    if not isinstance(camps_mode_per_aparell, dict):
        camps_mode_per_aparell = {}
    camps_per_exercici_per_aparell = punt.get("camps_per_exercici_per_aparell") or {}
    if not isinstance(camps_per_exercici_per_aparell, dict):
        camps_per_exercici_per_aparell = {}
    agregacio_camps_per_aparell = punt.get("agregacio_camps_per_aparell") or {}
    if not isinstance(agregacio_camps_per_aparell, dict):
        agregacio_camps_per_aparell = {}
    agregacio_camps_per_exercici_per_aparell = punt.get("agregacio_camps_per_exercici_per_aparell") or {}
    if not isinstance(agregacio_camps_per_exercici_per_aparell, dict):
        agregacio_camps_per_exercici_per_aparell = {}
    candidate_source_per_aparell = punt.get("candidate_source_per_aparell") or {}
    if not isinstance(candidate_source_per_aparell, dict):
        candidate_source_per_aparell = {}
    agregacio_exercicis_per_aparell = punt.get("agregacio_exercicis_per_aparell") or {}
    if not isinstance(agregacio_exercicis_per_aparell, dict):
        agregacio_exercicis_per_aparell = {}

    agg_camps = (punt.get("agregacio_camps") or "sum").lower().strip()
    candidate_source_mode = _normalize_candidate_source_mode(punt.get("candidate_source_mode"))
    candidate_source_cfg = _normalize_candidate_source_cfg(
        punt.get("candidate_source_cfg"),
        fallback={"mode": "tots", "best_n": 1, "index": 1, "ids": [], "agregacio_exercicis": "sum"},
    )
    agg_exercicis = (punt.get("agregacio_exercicis") or "sum").lower().strip()
    agg_aparells = (punt.get("agregacio_aparells") or "sum").lower().strip()

    orm_data = load_engine_orm_data(
        competicio,
        punt=punt,
        tipus=tipus,
        filtres=filtres,
        equips_cfg=equips_cfg,
    )
    aparells = orm_data.aparells
    team_mode = orm_data.team_mode if tipus == "equips" else ""
    team_context_code = orm_data.team_context_code or team_context_code
    detail_config = engine_get_detail_display_config(schema, tipus=tipus, team_mode=team_mode)
    detail_enabled = bool(detail_config.get("enabled"))
    exercise_selection_scope = EXERCISE_SELECTION_SCOPE_PER_MEMBER
    if tipus == "equips" and team_mode == "derived_from_individual":
        exercise_selection_scope = _normalize_exercise_selection_scope(
            punt.get("exercise_selection_scope")
        )
    allow_main_participant_selection_step = (
        tipus == "equips"
        and team_mode == "derived_from_individual"
        and exercise_selection_scope == EXERCISE_SELECTION_SCOPE_PER_MEMBER
        and mode_seleccio_exercicis != "global_pool"
    )
    participants_per_aparell = punt.get("participants_per_aparell") if isinstance(punt.get("participants_per_aparell"), dict) else {}
    agregacio_participants_per_aparell = (
        punt.get("agregacio_participants_per_aparell")
        if isinstance(punt.get("agregacio_participants_per_aparell"), dict)
        else {}
    )
    allow_candidate_source = (
        tipus == "individual"
        or (tipus == "equips" and team_mode in ("derived_from_individual", "native_team"))
    )
    if not allow_candidate_source:
        candidate_source_mode = "raw_exercise"

    def resolve_agregacio_camps_for_app(app_id: int):
        raw = agregacio_camps_per_aparell.get(str(app_id))
        if raw is None:
            raw = agregacio_camps_per_aparell.get(app_id)
        agg = str(raw or agg_camps or "sum").lower().strip()
        if agg not in ("sum", "avg", "median", "max", "min"):
            agg = str(agg_camps or "sum").lower().strip()
        if agg not in ("sum", "avg", "median", "max", "min"):
            agg = "sum"
        return agg

    def resolve_camps_mode_for_app(app_id: int):
        raw = camps_mode_per_aparell.get(str(app_id))
        if raw is None:
            raw = camps_mode_per_aparell.get(app_id)
        return _normalize_field_mode(raw)

    # si no hi ha aparells seleccionats -> retorn buit
    if not aparells:
        return {"global": []}

    # 3) INSCRIPCIONS per competiciÃ³, agrupades per aparell
    all_ins_list = orm_data.all_ins_list
    all_ins_by_id = orm_data.all_ins_by_id
    filtered_ins_list = orm_data.ins_list
    filtered_ins_by_id = orm_data.ins_by_id
    ins_list = filtered_ins_list
    ins_by_id = filtered_ins_by_id
    team_assignment_map = {}
    if tipus == "equips" and team_mode == "derived_from_individual" and assignment_source.get("mode") == "context":
        team_assignment_map = get_contextual_assignment_map(
            competicio,
            filtered_ins_list,
            team_context_code,
        )

    notes = orm_data.notes
    notes_by_app = orm_data.notes_by_app
    notes_by_key = orm_data.notes_by_key
    ins_ids_by_app = orm_data.ins_ids_by_app
    team_notes = orm_data.team_notes
    team_notes_by_app = orm_data.team_notes_by_app
    team_notes_by_key = orm_data.team_notes_by_key
    team_ids_by_app = orm_data.team_ids_by_app

    # 4) CAMPS per aparell (lliures)
    camps_per_aparell = punt.get("camps_per_aparell") or {}
    # fallback legacy: si no hi ha camps_per_aparell, usem camp legacy per tots els aparells
    legacy_camp = (punt.get("camp") or "total").strip()

    def _score_camps_for_app(app_id: int, *, include_per_exercise=False):
        raw = camps_per_aparell.get(str(app_id)) or camps_per_aparell.get(app_id)
        out = _unique_nonempty_strings(raw)
        if not out:
            # legacy
            out = [legacy_camp] if legacy_camp else ["total"]
        if include_per_exercise and resolve_camps_mode_for_app(app_id) == "per_exercici":
            raw_map = camps_per_exercici_per_aparell.get(str(app_id))
            if raw_map is None:
                raw_map = camps_per_exercici_per_aparell.get(app_id)
            for raw_fields in (raw_map.values() if isinstance(raw_map, dict) else []):
                for code in _unique_nonempty_strings(raw_fields):
                    if code not in out:
                        out.append(code)
        return out

    def resolve_score_fields_for_app_exercise(app_id: int, ex_idx: int):
        common_fields = list(_score_camps_for_app(app_id))
        common_agg = resolve_agregacio_camps_for_app(app_id)
        if resolve_camps_mode_for_app(app_id) != "per_exercici":
            return common_fields, common_agg

        raw_fields_by_ex = camps_per_exercici_per_aparell.get(str(app_id))
        if raw_fields_by_ex is None:
            raw_fields_by_ex = camps_per_exercici_per_aparell.get(app_id)
        raw_agg_by_ex = agregacio_camps_per_exercici_per_aparell.get(str(app_id))
        if raw_agg_by_ex is None:
            raw_agg_by_ex = agregacio_camps_per_exercici_per_aparell.get(app_id)

        ex_key = str(max(1, int(ex_idx or 1)))
        ex_fields = _unique_nonempty_strings(
            (raw_fields_by_ex or {}).get(ex_key) if isinstance(raw_fields_by_ex, dict) else []
        )
        ex_agg = _normalize_optional_agg(
            (raw_agg_by_ex or {}).get(ex_key) if isinstance(raw_agg_by_ex, dict) else None
        )
        if not ex_fields or not ex_agg:
            return common_fields, common_agg
        return ex_fields, ex_agg

    def camps_for_app(app_id: int):
        out = list(_score_camps_for_app(app_id, include_per_exercise=True))
        seen = set()
        for crit in desempat or []:
            if isinstance(crit, dict) and isinstance(crit.get("pipeline"), dict):
                pipeline = crit.get("pipeline") or {}
                app_cfg = pipeline.get("aparells") if isinstance(pipeline.get("aparells"), dict) else {}
                target_ids = []
                for raw_app_id in (app_cfg.get("ids") or []):
                    try:
                        target_ids.append(int(raw_app_id))
                    except Exception:
                        continue
                if not target_ids:
                    target_ids = [int(app_id)]
                if int(app_id) in target_ids:
                    camps_map = pipeline.get("camps_per_aparell") if isinstance(pipeline.get("camps_per_aparell"), dict) else {}
                    raw_camps = camps_map.get(str(app_id))
                    if raw_camps is None:
                        raw_camps = camps_map.get(app_id)
                    if raw_camps is None and len(target_ids) == 1:
                        raw_camps = next(iter(camps_map.values()), [])
                    if isinstance(raw_camps, list):
                        out.extend(str(x).strip() for x in raw_camps if str(x).strip())
                    elif isinstance(raw_camps, str) and raw_camps.strip():
                        out.extend(x.strip() for x in raw_camps.split(",") if x.strip())
                continue

            scope = (crit.get("scope") or {}) if isinstance(crit, dict) else {}
            app_scope = (scope.get("aparells") or {}) if isinstance(scope, dict) else {}
            app_mode = str(app_scope.get("mode") or "").strip().lower()
            target_ids = []
            if app_mode == "seleccionar":
                for raw_app_id in (app_scope.get("ids") or []):
                    try:
                        target_ids.append(int(raw_app_id))
                    except Exception:
                        continue
            elif crit.get("aparell_id") not in (None, "", 0, "0"):
                try:
                    target_ids.append(int(crit.get("aparell_id")))
                except Exception:
                    pass
            if not target_ids:
                target_ids = [int(app_id)]
            if int(app_id) in target_ids:
                out.extend(_normalize_tie_camps(crit))

        def _collect_raw_columns(raw_columns):
            if not isinstance(raw_columns, list):
                return
            for col in raw_columns:
                if not isinstance(col, dict):
                    continue
                if str(col.get("type") or "builtin").strip().lower() != "raw":
                    continue
                src = col.get("source") if isinstance(col.get("source"), dict) else {}
                try:
                    source_app_id = int(src.get("aparell_id"))
                except Exception:
                    continue
                if source_app_id != int(app_id):
                    continue
                camp = str(src.get("camp") or "").strip()
                if camp:
                    out.append(camp)

        presentacio = schema.get("presentacio") if isinstance(schema.get("presentacio"), dict) else {}
        _collect_raw_columns(presentacio.get("columnes"))
        detail_cfg = presentacio.get("detall") if isinstance(presentacio.get("detall"), dict) else {}
        _collect_raw_columns(detail_cfg.get("columnes"))
        for section in (detail_cfg.get("sections") or []):
            if isinstance(section, dict):
                _collect_raw_columns(section.get("columns"))

        dedup = []
        for code in out:
            if code in seen:
                continue
            seen.add(code)
            dedup.append(code)
        return dedup

    # 5) EXERCICIS per aparell segons CompeticioAparell.nombre_exercicis
    # 6) AGREGACIONS + construccio de score final per inscripcio
    per_ins = {}  # ins_id -> {"score":float, "by_app_base":{}, "by_app":{}, "tie":{...}}
    for ins in ins_list:
        per_ins[ins.id] = {"score": 0.0, "by_app_base": {}, "by_app": {}, "tie": {}}

    app_order = {ca.id: idx for idx, ca in enumerate(aparells, start=1)}
    app_fields_by_app = {}
    app_ex_rows_by_ins = defaultdict(dict)  # app_id -> ins_id -> [row]
    team_app_ex_rows_by_equip = defaultdict(dict)  # app_id -> equip_id -> [row]

    for ca in aparells:
        app_id = ca.id
        n_ex = int(getattr(ca, "nombre_exercicis", 1) or 1)
        n_ex = max(1, min(50, n_ex))
        score_fields = _score_camps_for_app(app_id)
        fields = camps_for_app(app_id)
        app_fields_by_app[app_id] = list(score_fields)

        if tipus == "equips" and is_team_context_app(ca):
            app_notes = team_notes_by_app.get(app_id, [])
            by_team_ex = defaultdict(dict)
            for nt in app_notes:
                ex_idx = int(getattr(nt, "exercici", 1) or 1)
                if ex_idx < 1:
                    ex_idx = 1
                if ex_idx > n_ex:
                    continue
                by_team_ex[nt.equip_id][ex_idx] = nt

            for equip_id in list(by_team_ex.keys()):
                vals_rows = []
                for ex_idx in range(1, n_ex + 1):
                    nt = by_team_ex.get(equip_id, {}).get(ex_idx)
                    if not nt:
                        continue
                    score_fields_for_ex, agg_camps_for_ex = resolve_score_fields_for_app_exercise(app_id, ex_idx)
                    fields_map = {f: _get_score_field(nt, f) for f in fields}
                    v_fields = [fields_map.get(f, 0.0) for f in score_fields_for_ex]
                    v_ex = _apply_simple_agg(v_fields, agg_camps_for_ex)
                    vals_rows.append(
                        {
                            "idx": int(ex_idx),
                            "value": _to_float(v_ex),
                            "app_id": app_id,
                            "app_order": app_order.get(app_id, 0),
                            "exercici": int(ex_idx),
                            "equip_id": int(equip_id),
                            "by_camp": fields_map,
                        }
                    )
                team_app_ex_rows_by_equip[app_id][equip_id] = vals_rows
            continue

        # notes d'aquest aparell
        app_notes = notes_by_app.get(app_id, [])
        # index: ins_id -> exercici -> note
        by_ins_ex = defaultdict(dict)
        for nt in app_notes:
            # normalitzem exercici al rang 1..n_ex
            ex_idx = int(getattr(nt, "exercici", 1) or 1)
            if ex_idx < 1:
                ex_idx = 1
            if ex_idx > n_ex:
                # si hi ha notes extra, les ignorem per coherencia amb configuracio d'aparell
                continue
            by_ins_ex[nt.inscripcio_id][ex_idx] = nt

        # calculem valor per exercici (agregant camps)
        for ins_id in list(ins_by_id.keys()):
            if ins_id not in ins_ids_by_app.get(app_id, set()):
                # no competeix en aquest aparell
                continue

            vals_ex = []
            vals_rows = []
            for ex_idx in range(1, n_ex + 1):
                nt = by_ins_ex.get(ins_id, {}).get(ex_idx)
                if not nt:
                    continue
                score_fields_for_ex, agg_camps_for_ex = resolve_score_fields_for_app_exercise(app_id, ex_idx)
                fields_map = {f: _get_score_field(nt, f) for f in fields}
                v_fields = [fields_map.get(f, 0.0) for f in score_fields_for_ex]

                v_ex = _apply_simple_agg(v_fields, agg_camps_for_ex)  # agregacio camps dins exercici
                vals_ex.append((ex_idx, v_ex))
                vals_rows.append(
                    {
                        "idx": int(ex_idx),
                        "value": _to_float(v_ex),
                        "app_id": app_id,
                        "app_order": app_order.get(app_id, 0),
                        "exercici": int(ex_idx),
                        "inscripcio_id": ins_id,
                        "by_camp": fields_map,
                    }
                )

            app_ex_rows_by_ins[app_id][ins_id] = vals_rows

    selection_runtime = build_selection_runtime(
        aparells=aparells,
        tipus=tipus,
        team_mode=team_mode,
        legacy_camp=legacy_camp,
        agg_camps=agg_camps,
        camps_per_aparell=camps_per_aparell,
        camps_mode_per_aparell=camps_mode_per_aparell,
        camps_per_exercici_per_aparell=camps_per_exercici_per_aparell,
        agregacio_camps_per_aparell=agregacio_camps_per_aparell,
        agregacio_camps_per_exercici_per_aparell=agregacio_camps_per_exercici_per_aparell,
        mode_seleccio_exercicis=mode_seleccio_exercicis,
        base_ex_cfg=base_ex_cfg,
        exercicis_per_aparell=exercicis_per_aparell,
        agg_exercicis=agg_exercicis,
        agregacio_exercicis_per_aparell=agregacio_exercicis_per_aparell,
        candidate_source_mode=candidate_source_mode,
        candidate_source_cfg=candidate_source_cfg,
        candidate_source_per_aparell=candidate_source_per_aparell,
        participants_per_aparell=participants_per_aparell,
        agregacio_participants_per_aparell=agregacio_participants_per_aparell,
        exercise_selection_scope=exercise_selection_scope,
        allow_candidate_source=allow_candidate_source,
        allow_main_participant_selection_step=allow_main_participant_selection_step,
        app_ex_rows_by_ins=app_ex_rows_by_ins,
        team_app_ex_rows_by_equip=team_app_ex_rows_by_equip,
    )
    selection_exports = selection_runtime.build_orchestrator_exports()

    resolve_agregacio_camps_for_app = selection_runtime.resolve_agregacio_camps_for_app
    resolve_camps_mode_for_app = selection_runtime.resolve_camps_mode_for_app
    resolve_candidate_source_for_app = selection_runtime.resolve_candidate_source_for_app
    resolve_agregacio_exercicis_for_app = selection_runtime.resolve_agregacio_exercicis_for_app
    resolve_participants_for_app = selection_runtime.resolve_participants_for_app
    _score_camps_for_app = selection_runtime._score_camps_for_app
    resolve_score_fields_for_app_exercise = selection_runtime.resolve_score_fields_for_app_exercise
    _resolve_ex_cfg_for_app = selection_runtime._resolve_ex_cfg_for_app
    _copy_ex_row_with_value = selection_exports["copy_ex_row_with_value"]
    _merge_source_rows = selection_runtime._merge_source_rows
    _build_candidate_rows_from_source_rows = selection_runtime._build_candidate_rows_from_source_rows
    _get_selected_rows_agg_for_ins = selection_exports["get_selected_rows_agg_for_ins"]
    _get_selected_rows_agg_for_team = selection_exports["get_selected_rows_agg_for_team"]
    _get_selected_rows_for_field = selection_exports["get_selected_rows_for_field"]
    _get_selected_team_rows_for_field = selection_exports["get_selected_team_rows_for_field"]
    _get_main_selected_rows_agg_for_team = selection_exports["get_main_selected_rows_agg_for_team"]
    _get_main_selected_team_rows_for_field = selection_exports["get_main_selected_team_rows_for_field"]
    _derived_team_cache_key = selection_runtime._derived_team_cache_key
    _get_selected_rows_agg_for_derived_team = selection_exports["get_selected_rows_agg_for_derived_team"]
    _get_main_selected_rows_for_group = selection_exports["get_main_selected_rows_for_group"]
    _get_main_selected_contributors_for_individual = selection_exports["get_main_selected_contributors_for_individual"]
    _get_main_selected_contributors_for_native_team = selection_exports["get_main_selected_contributors_for_native_team"]
    _get_main_selected_contributors_for_group = selection_exports["get_main_selected_contributors_for_group"]
    _get_selected_rows_for_derived_team_field = selection_exports["get_selected_rows_for_derived_team_field"]
    _get_main_selected_rows_for_group_field = selection_exports["get_main_selected_rows_for_group_field"]

    for ins_id, obj in per_ins.items():
        selected_rows_by_app = _get_selected_rows_agg_for_ins(ins_id)
        for ca in aparells:
            app_id = ca.id
            if ins_id not in ins_ids_by_app.get(app_id, set()):
                continue
            agg_exercicis_for_app = resolve_agregacio_exercicis_for_app(app_id)
            score_app = _apply_simple_agg(
                [_to_float(row.get("value")) for row in selected_rows_by_app.get(app_id, [])],
                agg_exercicis_for_app,
            )
            obj["by_app_base"][app_id] = float(score_app)

    # agregacio final entre aparells
    for ins_id, obj in per_ins.items():
        obj["by_app"] = dict(obj.get("by_app_base") or {})
        if mode_resultat_aparells == "score":
            app_vals = list((obj.get("by_app") or {}).values())
            obj["score"] = float(_apply_simple_agg(app_vals, agg_aparells))
        else:
            obj["by_app"] = {}
            obj["score"] = 0.0

    # 7) TIE-BREAKS segons ordre del front
    # suport:
    #  - legacy: {"camp":"execucio_total","ordre":"desc"} -> suma (o avg) sobre aparells/exercicis segons el pipeline
    #  - nou: {"aparell_id": X, "camp": "E_total", "ordre":"desc"} -> recalcula com "score d'aquell aparell perÃ² nomÃ©s amb aquell camp"
    #
    # IMPORTANT: per no duplicar molt codi, fem una funciÃ³ que calcula "valor criteri" reutilitzant el mateix pipeline,
    # perÃ² substituint camps per la llista [camp].
    metrics_runtime = build_metrics_runtime(
        tipus=tipus,
        team_mode=team_mode,
        selected_app_ids=[int(ca.id) for ca in aparells],
        derived_team_cache_key=_derived_team_cache_key,
        app_ex_rows_by_ins=app_ex_rows_by_ins,
        team_app_ex_rows_by_equip=team_app_ex_rows_by_equip,
        app_order=app_order,
        copy_ex_row_with_value=_copy_ex_row_with_value,
        to_float=_to_float,
        apply_simple_agg=_apply_simple_agg,
        pick_exercicis_rows=_pick_exercicis_rows,
        pick_exercicis_tuples=_pick_exercicis_tuples,
        pick_participants=_pick_participants,
        get_main_selected_contributors_for_individual=_get_main_selected_contributors_for_individual,
        get_main_selected_contributors_for_native_team=_get_main_selected_contributors_for_native_team,
        get_main_selected_rows_for_group=_get_main_selected_rows_for_group,
        get_main_selected_contributors_for_group=_get_main_selected_contributors_for_group,
        individual_ids=list(per_ins.keys()),
        per_ins=per_ins,
    )
    metrics_adapters = build_metrics_runtime_adapters(metrics_runtime)
    victories_adapters = build_victories_adapters(metrics_adapters["calc_metric_value_for_ins"])

    calc_criterion_value = lambda ins_id, crit, forced_app_ids=None, forced_exercici_ids=None, forced_camps=None: engine_calc_criterion_value(
        metrics_runtime,
        ins_id,
        crit,
        forced_app_ids=forced_app_ids,
        forced_exercici_ids=forced_exercici_ids,
        forced_camps=forced_camps,
    )
    calc_metric_value_for_ins = metrics_adapters["calc_metric_value_for_ins"]
    calc_metric_value_for_group = metrics_adapters["calc_metric_value_for_group"]
    calc_metric_value_for_native_team = metrics_adapters["calc_metric_value_for_native_team"]
    _pipeline_metric_map_for_crit = metrics_adapters["pipeline_metric_map_for_crit"]
    _apply_victories_per_app_to_rows = victories_adapters["apply_victories_per_app_to_rows"]
    _compute_victory_points_for_entries = victories_adapters["compute_victory_points_for_entries"]

    detail_runtime = build_detail_runtime(
        notes_by_key=notes_by_key,
        team_notes_by_key=team_notes_by_key,
        all_ins_by_id=all_ins_by_id,
        aparells=aparells,
        display_columns=display_columns,
        detail_enabled=detail_enabled,
        detail_config=detail_config,
        get_main_selected_rows_agg_for_team=_get_main_selected_rows_agg_for_team,
        get_main_selected_team_rows_for_field=_get_main_selected_team_rows_for_field,
        get_main_selected_rows_for_group_field=_get_main_selected_rows_for_group_field,
    )

    # guardem tie values (amb clau estable per UI)
    for crit in desempat:
        key = _tie_key(crit)
        if not key:
            continue
        for ins_id in per_ins.keys():
            per_ins[ins_id]["tie"][key] = calc_metric_value_for_ins(ins_id, crit)

    # 8) PARTICIONS + output rows
    per_particio = defaultdict(list)

    for ins in ins_list:
        pkey = _partition_key_from_entries(
            ins,
            part_entries,
            part_custom_idx,
            particions_config=particions_config,
        )
        participant = (
            getattr(ins, "nom_complet", None)
            or getattr(ins, "nom_i_cognoms", None)
            or getattr(ins, "nom", None)
            or str(ins)
        )

        row = {
            "inscripcio_id": ins.id,
            "nom": participant,
            "participant": participant,
            "entitat_nom": _display_value(ins, "entitat"),
            "score": float(per_ins[ins.id]["score"]),
            "tie": per_ins[ins.id]["tie"],
            # extra Ãºtil pel front (si vols mostrar detalls)
            "by_app": dict(per_ins[ins.id]["by_app"]),
            "by_app_base": dict(per_ins[ins.id]["by_app_base"]),
        }
        per_particio[pkey].append(row)

    metrics_runtime["per_particio"] = per_particio

    if tipus == "individual" and mode_resultat_aparells == "victories":
        target_app_ids = [ca.id for ca in aparells]
        mode_vict_camps = str(victories_cfg.get("mode_camps") or "agregat").lower().strip()
        mode_vict_exercicis = str(victories_cfg.get("mode_exercicis") or "agregat").lower().strip()
        camps_sep_ex_selection = str(
            victories_cfg.get("mode_seleccio_exercicis_camps_separats") or "per_camp"
        ).lower().strip()
        agg_victories_camps = str(victories_cfg.get("agregacio_victories_camps") or "sum").lower().strip()
        agg_victories_exercicis = str(
            victories_cfg.get("agregacio_victories_exercicis") or "sum"
        ).lower().strip()

        def _selected_field_rows_for_app(ins_id: int, app_id: int, field_code: str):
            if camps_sep_ex_selection == "per_camp":
                return _get_selected_rows_for_field(ins_id, field_code).get(app_id, [])
            return [
                _copy_ex_row_with_value(row, ((row.get("by_camp") or {}).get(field_code)))
                for row in (_get_selected_rows_agg_for_ins(ins_id).get(app_id, []) or [])
            ]

        for _pkey, rows in per_particio.items():
            for row in rows:
                row["by_app"] = {}

            if mode_vict_camps == "agregat" and mode_vict_exercicis == "agregat":
                _apply_victories_per_app_to_rows(
                    rows,
                    app_ids=target_app_ids,
                    ordre_principal=ordre_principal,
                    agg_aparells=agg_aparells,
                    victories_cfg=victories_cfg,
                )
                continue

            for app_id in target_app_ids:
                if app_id not in app_fields_by_app:
                    continue

                points_by_ins = defaultdict(list)
                points_by_ins_ex = defaultdict(lambda: defaultdict(list))

                if mode_vict_camps == "separat" and mode_vict_exercicis == "agregat":
                    for field_code in app_fields_by_app.get(app_id, []):
                        entries = []
                        for row in rows:
                            ins_id = row.get("inscripcio_id")
                            if ins_id in (None, ""):
                                continue
                            selected_rows = _selected_field_rows_for_app(ins_id, app_id, field_code)
                            if not selected_rows:
                                continue
                            agg_exercicis_for_app = resolve_agregacio_exercicis_for_app(app_id)
                            base_val = _apply_simple_agg(
                                [_to_float(item.get("value")) for item in selected_rows],
                                agg_exercicis_for_app,
                            )
                            entries.append({"row": row, "base": base_val})

                        unit_points = _compute_victory_points_for_entries(
                            entries,
                            ordre_principal,
                            victories_cfg,
                            calc_metric_value_for_ins,
                            forced_app_ids=[app_id],
                            forced_camps=[field_code],
                        )
                        for ins_id, pts in unit_points.items():
                            points_by_ins[ins_id].append(pts)

                    for row in rows:
                        ins_id = row.get("inscripcio_id")
                        if ins_id in (None, ""):
                            continue
                        row["by_app"][app_id] = float(
                            _apply_simple_agg(points_by_ins.get(ins_id, []), agg_victories_camps)
                        )
                    continue

                if mode_vict_camps == "agregat" and mode_vict_exercicis == "separat":
                    all_exercicis = set()
                    ex_rows_by_ins = {}
                    for row in rows:
                        ins_id = row.get("inscripcio_id")
                        if ins_id in (None, ""):
                            continue
                        selected_rows = _get_selected_rows_agg_for_ins(ins_id).get(app_id, [])
                        ex_map = {}
                        for item in selected_rows:
                            try:
                                ex_idx = int(item.get("exercici"))
                            except Exception:
                                continue
                            ex_map[ex_idx] = _to_float(item.get("value"))
                            all_exercicis.add(ex_idx)
                        ex_rows_by_ins[ins_id] = ex_map

                    for ex_idx in sorted(all_exercicis):
                        entries = []
                        for row in rows:
                            ins_id = row.get("inscripcio_id")
                            if ins_id in (None, ""):
                                continue
                            if ex_idx not in (ex_rows_by_ins.get(ins_id) or {}):
                                continue
                            entries.append({"row": row, "base": ex_rows_by_ins[ins_id][ex_idx]})

                        unit_points = _compute_victory_points_for_entries(
                            entries,
                            ordre_principal,
                            victories_cfg,
                            calc_metric_value_for_ins,
                            forced_app_ids=[app_id],
                            forced_exercici_ids=[ex_idx],
                        )
                        for ins_id, pts in unit_points.items():
                            points_by_ins[ins_id].append(pts)

                    for row in rows:
                        ins_id = row.get("inscripcio_id")
                        if ins_id in (None, ""):
                            continue
                        row["by_app"][app_id] = float(
                            _apply_simple_agg(points_by_ins.get(ins_id, []), agg_victories_exercicis)
                        )
                    continue

                if mode_vict_camps == "separat" and mode_vict_exercicis == "separat":
                    all_exercicis = set()
                    for field_code in app_fields_by_app.get(app_id, []):
                        ex_rows_by_ins = {}
                        for row in rows:
                            ins_id = row.get("inscripcio_id")
                            if ins_id in (None, ""):
                                continue
                            selected_rows = _selected_field_rows_for_app(ins_id, app_id, field_code)
                            ex_map = {}
                            for item in selected_rows:
                                try:
                                    ex_idx = int(item.get("exercici"))
                                except Exception:
                                    continue
                                ex_map[ex_idx] = _to_float(item.get("value"))
                                all_exercicis.add(ex_idx)
                            ex_rows_by_ins[ins_id] = ex_map

                        for ex_idx in sorted(all_exercicis):
                            entries = []
                            for row in rows:
                                ins_id = row.get("inscripcio_id")
                                if ins_id in (None, ""):
                                    continue
                                if ex_idx not in (ex_rows_by_ins.get(ins_id) or {}):
                                    continue
                                entries.append({"row": row, "base": ex_rows_by_ins[ins_id][ex_idx]})

                            unit_points = _compute_victory_points_for_entries(
                                entries,
                                ordre_principal,
                                victories_cfg,
                                calc_metric_value_for_ins,
                                forced_app_ids=[app_id],
                                forced_exercici_ids=[ex_idx],
                                forced_camps=[field_code],
                            )
                            for ins_id, pts in unit_points.items():
                                points_by_ins_ex[ins_id][ex_idx].append(pts)

                    for row in rows:
                        ins_id = row.get("inscripcio_id")
                        if ins_id in (None, ""):
                            continue
                        ex_totals = []
                        for ex_idx in sorted((points_by_ins_ex.get(ins_id) or {}).keys()):
                            ex_totals.append(
                                _apply_simple_agg(
                                    (points_by_ins_ex.get(ins_id) or {}).get(ex_idx, []),
                                    agg_victories_camps,
                                )
                            )
                        row["by_app"][app_id] = float(
                            _apply_simple_agg(ex_totals, agg_victories_exercicis)
                        )
                    continue

            for row in rows:
                row["score"] = float(_apply_simple_agg(list((row.get("by_app") or {}).values()), agg_aparells))

    out = {}

    if tipus == "equips":
        resolved_team_by_ins_id = _build_resolved_team_by_ins_id(
            ins_list,
            team_mode=team_mode,
            team_context_code=team_context_code,
            assignment_fallback=assignment_source.get("fallback"),
            team_assignment_map=team_assignment_map,
        )
        grouped = _build_team_grouped(
            ins_list=ins_list,
            team_mode=team_mode,
            equips_cfg=equips_cfg,
            aparells=aparells,
            team_notes_by_app=team_notes_by_app,
            all_ins_by_id=all_ins_by_id,
            filtres=filtres,
            part_entries=part_entries,
            part_custom_idx=part_custom_idx,
            particions_config=particions_config,
            team_context_code=team_context_code,
            assignment_fallback=assignment_source.get("fallback"),
            team_assignment_map=team_assignment_map,
            resolved_team_by_ins_id=resolved_team_by_ins_id,
        )
        metrics_runtime["grouped"] = grouped
        out = _build_team_rows(
            grouped,
            team_mode=team_mode,
            aparells=aparells,
            equips_cfg=equips_cfg,
            competicio=competicio,
            part_entries=part_entries,
            part_custom_idx=part_custom_idx,
            particions_config=particions_config,
            per_ins=per_ins,
            agg_aparells=agg_aparells,
            exercise_selection_scope=exercise_selection_scope,
            allow_main_participant_selection_step=allow_main_participant_selection_step,
            desempat=desempat,
            get_main_selected_rows_agg_for_team=_get_main_selected_rows_agg_for_team,
            get_selected_rows_agg_for_derived_team=_get_selected_rows_agg_for_derived_team,
            resolve_agregacio_exercicis_for_app=resolve_agregacio_exercicis_for_app,
            resolve_participants_for_app=resolve_participants_for_app,
            tie_key_resolver=_tie_key,
            is_pipeline_tie=_is_pipeline_tie,
            pipeline_metric_map_for_crit=_pipeline_metric_map_for_crit,
            calc_metric_value_for_native_team=calc_metric_value_for_native_team,
            calc_metric_value_for_group=calc_metric_value_for_group,
        )

        for pkey, rows in out.items():
            ranked = engine_rank_rows(rows, desempat, presentacio, ordre_principal=ordre_principal, entity_mode=True)
            out[pkey] = detail_runtime.attach_display_cells(ranked, entity_mode=True)
        return out

    if tipus == "entitat":
        for pkey, rows in per_particio.items():
            by_ent = defaultdict(list)
            for r in rows:
                by_ent[r.get("entitat_nom") or ""].append(r)

            ent_rows = []
            for ent_nom, items in by_ent.items():
                ent_score = sum([_to_float(x["score"]) for x in items])
                ent_tie = {}
                for t in desempat or []:
                    tkey = _tie_key(t)
                    if not tkey:
                        continue
                    if _is_pipeline_tie(t):
                        ent_tie[tkey] = float(
                            _pipeline_metric_map_for_crit(t).get(("entitat", _normalized_text_token(ent_nom)), 0.0)
                        )
                    else:
                        ent_tie[tkey] = sum([_to_float((x.get("tie") or {}).get(tkey, 0.0)) for x in items])

                ent_rows.append({
                    "entitat_nom": ent_nom,
                    "score": float(ent_score),
                    "tie": ent_tie,
                    "participants": len(items),
                    "_member_ids": [x.get("inscripcio_id") for x in items if x.get("inscripcio_id") is not None],
                })

            ranked = engine_rank_rows(ent_rows, desempat, presentacio, ordre_principal=ordre_principal, entity_mode=True)
            out[pkey] = detail_runtime.attach_display_cells(ranked, entity_mode=True)
        return out

    for pkey, rows in per_particio.items():
        ranked = engine_rank_rows(rows, desempat, presentacio, ordre_principal=ordre_principal, entity_mode=False)
        out[pkey] = detail_runtime.attach_display_cells(ranked, entity_mode=False)
    return out
