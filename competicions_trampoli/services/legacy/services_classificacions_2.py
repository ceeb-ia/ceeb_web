# services_classificacions.py
import json
import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from django.db import models
from django.utils import timezone
from ...models import Inscripcio
from ..shared.birth_year_ranges import (
    BIRTH_YEAR_RANGE_PARTITION_CODE,
    DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG,
    birth_year_range_partition_value,
    legacy_team_age_partition_to_birth_year_range_config,
    normalize_birth_year_range_partition_config,
)
from ..teams.equip_contexts import (
    NATIVE_EQUIP_CONTEXT_CODE,
    get_contextual_assignment_map,
    normalize_equip_context_code,
    resolve_inscripcio_equip,
)
from ...models.competicio import CompeticioAparell
from ...models.scoring import ScoreEntry, TeamScoreEntry
from ..scoring.team_scoring import is_team_context_app, member_runtime_code

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


def _legacy_native_equip_for_classificacio(inscripcio):
    equip = getattr(inscripcio, "equip", None)
    if equip is not None:
        return equip
    equip_id = getattr(inscripcio, "equip_id", None)
    if not equip_id:
        return None
    return SimpleNamespace(id=int(equip_id), nom=str(getattr(inscripcio, "equip__nom", "") or "").strip())


def _resolve_inscripcio_equip_for_classificacio(inscripcio, *, context_code=None, fallback=None, assignment_map=None):
    resolved = resolve_inscripcio_equip(
        inscripcio,
        context_code=context_code,
        fallback=fallback,
        assignment_map=assignment_map,
    )
    if resolved is not None:
        return resolved

    code = normalize_equip_context_code(context_code)
    fallback_code = normalize_equip_context_code(fallback) if fallback not in (None, "") else ""
    if code != NATIVE_EQUIP_CONTEXT_CODE and fallback_code != NATIVE_EQUIP_CONTEXT_CODE:
        return None
    return _legacy_native_equip_for_classificacio(inscripcio)


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

    # NOVA puntuació (per aparell), però mantenim claus legacy per no trencar res
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
        "camps_per_aparell": {},
        "agregacio_camps_per_aparell": {},

        # agregació dels camps seleccionats DINS d'un exercici (nota)
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

        # agregació dels exercicis DINS d'un aparell (després de triar exercicis)
        # sum/avg/median/max/min
        "agregacio_exercicis": "sum",

        # agregació FINAL entre aparells
        # sum/avg/median/max/min
        "agregacio_aparells": "sum",

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
        "ordre": "desc",  # desc = més punts millor
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

DISPLAY_BUILTIN_KEYS = ("posicio", "participant", "nom", "entitat_nom", "participants", "punts")
DETAIL_DISPLAY_BUILTIN_KEYS = ("participant", "entitat_nom")
DETAIL_EXERCISE_BUILTIN_KEYS = ("exercise_index", "aparell_nom", "participant", "entitat_nom")
DETAIL_SECTION_TYPES = (
    "members_list",
    "members_table",
    "team_members_table",
    "team_metrics",
    "exercise_table",
    "entity_members_table",
)


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


def _to_float(v):
    try:
        if v is None or v == "":
            return 0.0
        if isinstance(v, Decimal):
            return float(v)
        return float(v)
    except Exception:
        return 0.0


def _try_strict_float(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def _numeric_scalar_or_1x1(v):
    """
    Accepta escalar numèric o estructura 1x1 (p.ex. [[7.5]] o [7.5]).
    Retorna float o None si no és puntuable com a escalar.
    """
    base = _try_strict_float(v)
    if base is not None:
        return base

    if not isinstance(v, list) or len(v) != 1:
        return None

    inner = v[0]
    if isinstance(inner, list):
        if len(inner) != 1:
            return None
        return _try_strict_float(inner[0])

    return _try_strict_float(inner)


def _field_value_from_entry(entry: ScoreEntry, code: str):
    c = (code or "").strip()
    if not c:
        return None

    if c.lower() == "total":
        return entry.total

    out = entry.outputs or {}
    if isinstance(out, dict) and c in out:
        return out.get(c)

    ins = entry.inputs or {}
    if isinstance(ins, dict) and c in ins:
        return ins.get(c)

    if isinstance(out, dict):
        if c == "TOTAL" and "TOTAL" in out:
            return out.get("TOTAL")
        if c == "total" and "total" in out:
            return out.get("total")

    return None


def _median(vals):
    xs = sorted([_to_float(x) for x in (vals or [])])
    n = len(xs)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return float(xs[mid])
    return float((xs[mid - 1] + xs[mid]) / 2.0)


def _apply_simple_agg(vals, mode: str):
    vals = [_to_float(x) for x in (vals or [])]
    if not vals:
        return 0.0
    m = (mode or "sum").lower().strip()
    if m == "sum":
        return float(sum(vals))
    if m == "avg":
        return float(sum(vals) / len(vals))
    if m == "max":
        return float(max(vals))
    if m == "min":
        return float(min(vals))
    if m == "median":
        return float(_median(vals))
    return float(sum(vals))


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


def _tie_key(crit: dict) -> str:
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
        f"|ex_sel[{ex_sel_mode}]|ex_scope[{ex_sel_scope}]|ex_app[{ex_per_app_sig}]"
        f"|agg_c[{agg_c}]|agg_e[{agg_e}]|agg_a[{agg_a}]"
        f"|parts[{p_sig}]|parts_agg[{p_agg}]"
    )


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


def _normalize_mode_resultat_aparells(raw_mode) -> str:
    mode = str(raw_mode or "score").lower().strip()
    if mode not in {"score", "victories"}:
        return "score"
    return mode


def _sanitize_victories_compare_ties(compare_ties):
    out = []
    for raw in (compare_ties or []):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item.pop("aparell_id", None)
        item.pop("agregacio_participants", None)

        scope = item.get("scope") or {}
        scope_out = {}
        if isinstance(scope, dict):
            ex_scope = scope.get("exercicis")
            if isinstance(ex_scope, dict):
                scope_out["exercicis"] = dict(ex_scope)
        item["scope"] = scope_out
        out.append(item)
    return out


def _normalize_victories_cfg(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    try:
        punts_victoria = float(cfg.get("punts_victoria", 1))
    except Exception:
        punts_victoria = 1.0
    try:
        punts_empat = float(cfg.get("punts_empat", 0.5))
    except Exception:
        punts_empat = 0.5
    sense_nota_mode = str(cfg.get("sense_nota_mode") or "skip").lower().strip()
    if sense_nota_mode not in {"skip"}:
        sense_nota_mode = "skip"

    mode_camps = str(cfg.get("mode_camps") or "agregat").lower().strip()
    if mode_camps not in {"agregat", "separat"}:
        mode_camps = "agregat"

    mode_exercicis = str(cfg.get("mode_exercicis") or "agregat").lower().strip()
    if mode_exercicis not in {"agregat", "separat"}:
        mode_exercicis = "agregat"

    mode_sel_camps_sep = str(
        cfg.get("mode_seleccio_exercicis_camps_separats") or "per_camp"
    ).lower().strip()
    if mode_sel_camps_sep not in {"per_camp", "global"}:
        mode_sel_camps_sep = "per_camp"

    agg_victories_camps = str(cfg.get("agregacio_victories_camps") or "sum").lower().strip()
    if agg_victories_camps not in {"sum", "avg", "median", "max", "min"}:
        agg_victories_camps = "sum"

    agg_victories_exercicis = str(cfg.get("agregacio_victories_exercicis") or "sum").lower().strip()
    if agg_victories_exercicis not in {"sum", "avg", "median", "max", "min"}:
        agg_victories_exercicis = "sum"

    return {
        "punts_victoria": punts_victoria,
        "punts_empat": punts_empat,
        "sense_nota_mode": sense_nota_mode,
        "mode_camps": mode_camps,
        "mode_exercicis": mode_exercicis,
        "mode_seleccio_exercicis_camps_separats": mode_sel_camps_sep,
        "agregacio_victories_camps": agg_victories_camps,
        "agregacio_victories_exercicis": agg_victories_exercicis,
        "desempat_comparacio": _sanitize_victories_compare_ties(cfg.get("desempat_comparacio") or []),
    }


def _row_base_for_app(row, app_id):
    by_app_base = row.get("by_app_base") or {}
    if app_id in by_app_base:
        return _to_float(by_app_base.get(app_id))
    return _to_float(by_app_base.get(str(app_id)))


def _row_has_app(row, app_id):
    by_app_base = row.get("by_app_base") or {}
    return app_id in by_app_base or str(app_id) in by_app_base


def _compute_victory_points_for_entries(
    entries,
    ordre_principal,
    victories_cfg,
    metric_value_getter,
    *,
    forced_app_ids=None,
    forced_exercici_ids=None,
    forced_camps=None,
):
    punts_victoria = _to_float(victories_cfg.get("punts_victoria", 1.0))
    punts_empat = _to_float(victories_cfg.get("punts_empat", 0.5))
    compare_ties = victories_cfg.get("desempat_comparacio") or []
    entries = entries or []
    if not entries:
        return {}

    entries_enriched = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        row = entry.get("row") or {}
        ins_id = row.get("inscripcio_id")
        if ins_id in (None, ""):
            continue
        compare_vals = []
        for crit in compare_ties:
            compare_vals.append(
                _to_float(
                    metric_value_getter(
                        ins_id,
                        crit,
                        forced_app_ids=forced_app_ids,
                        forced_exercici_ids=forced_exercici_ids,
                        forced_camps=forced_camps,
                    )
                )
            )
        entries_enriched.append(
            {
                "row": row,
                "base": _to_float(entry.get("base")),
                "compare_vals": compare_vals,
            }
        )

    if not entries_enriched:
        return {}

    def _sort_key(entry):
        key = [(-entry["base"]) if ordre_principal == "desc" else entry["base"]]
        for idx, crit in enumerate(compare_ties):
            ordre = str((crit or {}).get("ordre") or "desc").lower().strip()
            val = _to_float(entry["compare_vals"][idx])
            key.append(-val if ordre == "desc" else val)
        return tuple(key)

    entries_sorted = sorted(entries_enriched, key=_sort_key)
    groups = []
    last_key = None
    current = []
    for entry in entries_sorted:
        cur_key = _sort_key(entry)
        if last_key is None or cur_key == last_key:
            current.append(entry)
        else:
            groups.append(current)
            current = [entry]
        last_key = cur_key
    if current:
        groups.append(current)

    points = {}
    total = len(entries_sorted)
    seen = 0
    for group in groups:
        group_size = len(group)
        worse_count = total - seen - group_size
        pts = float((punts_victoria * worse_count) + (punts_empat * max(0, group_size - 1)))
        for entry in group:
            ins_id = entry["row"].get("inscripcio_id")
            if ins_id in (None, ""):
                continue
            points[ins_id] = pts
        seen += group_size

    return points


def _apply_victories_per_app_to_rows(
    rows,
    app_ids,
    ordre_principal,
    agg_aparells,
    victories_cfg,
    metric_value_getter,
):
    rows = rows or []
    app_ids = [int(x) for x in (app_ids or [])]
    if not rows or not app_ids:
        for row in rows:
            row["by_app"] = {}
            row["score"] = 0.0
        return rows

    for row in rows:
        row["by_app"] = {}

    for app_id in app_ids:
        entries = []
        for row in rows:
            ins_id = row.get("inscripcio_id")
            if ins_id in (None, ""):
                continue
            if not _row_has_app(row, app_id):
                continue
            entries.append({"row": row, "base": _row_base_for_app(row, app_id)})

        points = _compute_victory_points_for_entries(
            entries,
            ordre_principal,
            victories_cfg,
            metric_value_getter,
            forced_app_ids=[app_id],
        )
        for row in rows:
            ins_id = row.get("inscripcio_id")
            if ins_id in points:
                row["by_app"][app_id] = points[ins_id]

    for row in rows:
        row["score"] = float(_apply_simple_agg(list((row.get("by_app") or {}).values()), agg_aparells))

    return rows


def _normalize_display_columns(raw_cols, *, detail_mode=False, allowed_builtin_keys=None, default_cols=None):
    cols = raw_cols if isinstance(raw_cols, list) else []
    if default_cols is None:
        default_cols = (
            [
                {"type": "builtin", "key": "participant", "label": "Participant", "align": "left"},
            ]
            if detail_mode
            else [
                {"type": "builtin", "key": "posicio", "label": "#", "align": "left"},
                {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
                {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
            ]
        )
    if allowed_builtin_keys is None:
        allowed_builtin_keys = DETAIL_DISPLAY_BUILTIN_KEYS if detail_mode else DISPLAY_BUILTIN_KEYS
    if not cols:
        return _json_clone_value(default_cols)
    out = []
    seen_keys = set()
    metric_idx = 1
    for item in cols:
        if not isinstance(item, dict):
            continue

        ctype = str(item.get("type") or "builtin").strip().lower()
        label = str(item.get("label") or "").strip()
        align = str(item.get("align") or "").strip().lower()
        if align not in ("left", "right", "center"):
            align = "left" if ctype == "builtin" else "right"

        decimals = item.get("decimals", None)
        try:
            decimals = int(decimals) if decimals is not None else None
        except Exception:
            decimals = None
        if decimals is not None:
            decimals = max(0, min(6, decimals))

        if ctype == "raw":
            key = str(item.get("key") or "").strip() or f"raw_{metric_idx}"
            metric_idx += 1

            source = item.get("source") if isinstance(item.get("source"), dict) else {}
            app_id = source.get("aparell_id")
            exercici = source.get("exercici", item.get("exercici"))
            exercise_mode = str(source.get("exercise_mode", item.get("exercise_mode")) or "").strip().lower()
            if exercise_mode not in ("selected", "fixed"):
                exercise_mode = ""
            camp = str(source.get("camp") or "").strip()

            if app_id in (None, "", 0, "0"):
                app_id = item.get("aparell_id", item.get("app_id"))
            try:
                app_id = int(app_id)
            except Exception:
                app_id = None

            try:
                exercici = int(exercici)
            except Exception:
                exercici = 1
            exercici = max(1, exercici)

            if not camp:
                camp = str(item.get("camp") or "").strip() or "total"

            raw_jutges = source.get("jutges") if isinstance(source.get("jutges"), dict) else {}
            ids = raw_jutges.get("ids")
            if not isinstance(ids, list):
                ids = source.get("jutges_ids")
            if not isinstance(ids, list):
                ids = []
            jutges_ids = []
            for x in ids:
                try:
                    j = int(x)
                except Exception:
                    continue
                if j > 0 and j not in jutges_ids:
                    jutges_ids.append(j)

            if not label:
                label = camp
            if decimals is None:
                decimals = 3
            out_source = {
                "aparell_id": app_id,
                "exercici": exercici,
                "camp": camp,
                "jutges": {"ids": jutges_ids},
            }
            if exercise_mode:
                out_source["exercise_mode"] = exercise_mode
            out_item = {
                "type": "raw",
                "key": key,
                "label": label,
                "align": align,
                "decimals": decimals,
                "source": out_source,
            }
        elif ctype == "metric":
            # compat retroactiva: converteix mètrica antiga a raw simple.
            key = str(item.get("key") or "").strip() or f"raw_{metric_idx}"
            metric_idx += 1
            crit = item.get("criteri") if isinstance(item.get("criteri"), dict) else {}
            camps = _normalize_tie_camps(crit)
            camp = camps[0] if camps else "total"
            scope = crit.get("scope") or {}
            apps = scope.get("aparells") or {}
            mode = (apps.get("mode") or "").lower().strip()
            app_id = None
            if mode == "seleccionar":
                ids = apps.get("ids") or []
                if ids:
                    try:
                        app_id = int(ids[0])
                    except Exception:
                        app_id = None
            elif item.get("aparell_id") not in (None, "", 0, "0"):
                try:
                    app_id = int(item.get("aparell_id"))
                except Exception:
                    app_id = None
            ex = (scope.get("exercicis") or {})
            exercici = 1
            if str(ex.get("mode") or "").lower().strip() == "index":
                try:
                    exercici = max(1, int(ex.get("index") or 1))
                except Exception:
                    exercici = 1
            if not label:
                label = camp
            if decimals is None:
                decimals = 3
            out_item = {
                "type": "raw",
                "key": key,
                "label": label,
                "align": align,
                "decimals": decimals,
                "source": {
                    "aparell_id": app_id,
                    "exercici": exercici,
                    "camp": camp,
                    "jutges": {"ids": []},
                },
            }
        else:
            key = str(item.get("key") or "").strip()
            if key not in allowed_builtin_keys:
                continue
            if not label:
                label = {
                    "posicio": "#",
                    "participant": "Nom",
                    "nom": "Nom",
                    "entitat_nom": "Entitat",
                    "participants": "Participants",
                    "punts": "Punts",
                }.get(key, key)
            if decimals is None and key == "punts":
                decimals = 3
            out_item = {
                "type": "builtin",
                "key": key,
                "label": label,
                "align": align,
            }
            if decimals is not None:
                out_item["decimals"] = decimals

        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(out_item)

    return out or _json_clone_value(default_cols)


def _detail_section_builtin_keys(section_type: str):
    stype = str(section_type or "").strip().lower()
    if stype == "exercise_table":
        return DETAIL_EXERCISE_BUILTIN_KEYS
    if stype in ("members_table", "team_members_table", "entity_members_table", "team_metrics"):
        return DETAIL_DISPLAY_BUILTIN_KEYS
    return ()


def _detail_section_default(section_type: str):
    stype = str(section_type or "").strip().lower()
    if stype == "members_list":
        return {"type": "members_list", "label": "Participants"}
    if stype == "team_metrics":
        return {
            "type": "team_metrics",
            "label": "Notes equip",
            "aparell_id": None,
            "columns": [
                {"type": "raw", "key": "team_raw_1", "label": "Total", "align": "right", "decimals": 3,
                 "source": {"aparell_id": None, "exercici": 1, "camp": "total", "jutges": {"ids": []}}},
            ],
        }
    if stype == "exercise_table":
        return {
            "type": "exercise_table",
            "label": "Exercicis",
            "aparell_id": None,
            "columns": [
                {"type": "builtin", "key": "aparell_nom", "label": "Aparell", "align": "left"},
                {"type": "builtin", "key": "exercise_index", "label": "Ex.", "align": "left"},
                {"type": "raw", "key": "exercise_raw_1", "label": "Total", "align": "right", "decimals": 3,
                 "source": {"aparell_id": None, "exercici": 1, "camp": "total", "jutges": {"ids": []}}},
            ],
        }
    if stype == "entity_members_table":
        return {
            "type": "entity_members_table",
            "label": "Participants",
            "aparell_id": None,
            "columns": [
                {"type": "builtin", "key": "participant", "label": "Participant", "align": "left"},
            ],
        }
    if stype == "team_members_table":
        return {
            "type": "team_members_table",
            "label": "Notes per membre",
            "aparell_id": None,
            "columns": [
                {"type": "builtin", "key": "participant", "label": "Participant", "align": "left"},
            ],
        }
    return {
        "type": "members_table",
        "label": "Detall",
        "aparell_id": None,
        "columns": [
            {"type": "builtin", "key": "participant", "label": "Participant", "align": "left"},
        ],
    }


def _normalize_detail_section(section):
    if not isinstance(section, dict):
        return None
    stype = str(section.get("type") or "").strip().lower()
    if stype not in DETAIL_SECTION_TYPES:
        return None
    base = _detail_section_default(stype)
    out = {**base, **section, "type": stype}
    label = str(out.get("label") or base.get("label") or "").strip()
    out["label"] = label or str(base.get("label") or "").strip()
    section_app_id = _normalize_positive_int(out.get("aparell_id"))
    raw_app_ids = set()
    if "columns" in base or isinstance(section.get("columns"), list):
        out["columns"] = _normalize_display_columns(
            section.get("columns") if isinstance(section.get("columns"), list) else base.get("columns"),
            detail_mode=True,
            allowed_builtin_keys=_detail_section_builtin_keys(stype),
            default_cols=base.get("columns") or [],
        )
        for col in out.get("columns") or []:
            if str(col.get("type") or "").strip().lower() != "raw":
                continue
            src = col.get("source") if isinstance(col.get("source"), dict) else {}
            app_id = _normalize_positive_int(src.get("aparell_id"))
            if app_id is not None:
                raw_app_ids.add(app_id)
        if section_app_id is None and len(raw_app_ids) == 1:
            section_app_id = next(iter(raw_app_ids))
        if section_app_id is not None:
            for col in out.get("columns") or []:
                if str(col.get("type") or "").strip().lower() != "raw":
                    continue
                src = col.get("source") if isinstance(col.get("source"), dict) else {}
                if _normalize_positive_int(src.get("aparell_id")) is None:
                    src = {**src, "aparell_id": section_app_id}
                    col["source"] = src
    else:
        out.pop("columns", None)
    if stype == "members_list":
        out.pop("aparell_id", None)
    else:
        out["aparell_id"] = section_app_id
    return out


def _default_detail_sections_for_context(tipus="individual", team_mode=""):
    tipus = str(tipus or "individual").strip().lower()
    team_mode = str(team_mode or "").strip().lower()
    if tipus == "individual":
        return [_detail_section_default("exercise_table")]
    if tipus == "entitat":
        return [_detail_section_default("entity_members_table")]
    if tipus == "equips" and team_mode == "native_team":
        return [
            _detail_section_default("members_list"),
            _detail_section_default("team_metrics"),
        ]
    if tipus == "equips":
        return [_detail_section_default("members_table")]
    return []


def get_display_columns(schema_or_presentacio=None):
    """
    Retorna columnes normalitzades per a renderitzar live/preview.
    Admet:
      - schema complet (amb clau presentacio)
      - objecte presentacio directament
    """
    if not isinstance(schema_or_presentacio, dict):
        presentacio = {}
    elif "presentacio" in schema_or_presentacio:
        presentacio = schema_or_presentacio.get("presentacio") or {}
    else:
        presentacio = schema_or_presentacio or {}

    return _normalize_display_columns(presentacio.get("columnes"), detail_mode=False)


def get_detail_display_config(schema_or_presentacio=None, *, tipus="individual", team_mode=""):
    if not isinstance(schema_or_presentacio, dict):
        presentacio = {}
    elif "presentacio" in schema_or_presentacio:
        presentacio = schema_or_presentacio.get("presentacio") or {}
    else:
        presentacio = schema_or_presentacio or {}

    raw_detail = presentacio.get("detall") if isinstance(presentacio.get("detall"), dict) else {}
    raw_sections = raw_detail.get("sections") if isinstance(raw_detail.get("sections"), list) else []
    sections = []
    for item in raw_sections:
        norm = _normalize_detail_section(item)
        if norm is not None:
            sections.append(norm)
    if not sections and isinstance(raw_detail.get("columnes"), list):
        sections = [
            _normalize_detail_section(
                {
                    "type": "members_table",
                    "label": "Detall",
                    "columns": raw_detail.get("columnes") or [],
                }
            )
        ]
    return {
        "enabled": bool(raw_detail.get("enabled", False)),
        "default_open": bool(raw_detail.get("default_open", False)),
        "sections": [s for s in sections if s],
    }


def compute_classificacio(competicio, cfg_obj):
    """
    Retorna:
      { "particio_key": [ {row}, ... ] }

    row (individual) mínim:
      - inscripcio_id, nom, entitat_nom, score, tie{...}
      - posicio/punts els posa _rank()
    """
    tipus = (getattr(cfg_obj, "tipus", "individual") or "individual").lower().strip()
    schema, _legacy_info = normalize_schema_legacy_team_birth_partition(
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
    display_columns = get_display_columns(schema)
    equips_cfg = _normalize_classificacio_equips_cfg(schema.get("equips") or {})
    assignment_source = equips_cfg.get("assignment_source") or _normalize_equip_assignment_source({})
    team_context_code = _get_effective_team_context_code(equips_cfg)
    desempat = _sanitize_desempat_for_tipus(desempat, tipus)
    mode_resultat_aparells = _normalize_mode_resultat_aparells(punt.get("mode_resultat_aparells"))
    victories_cfg = _normalize_victories_cfg((punt.get("victories") or {}))
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
    agregacio_camps_per_aparell = punt.get("agregacio_camps_per_aparell") or {}
    if not isinstance(agregacio_camps_per_aparell, dict):
        agregacio_camps_per_aparell = {}
    candidate_source_per_aparell = punt.get("candidate_source_per_aparell") or {}
    if not isinstance(candidate_source_per_aparell, dict):
        candidate_source_per_aparell = {}

    agg_camps = (punt.get("agregacio_camps") or "sum").lower().strip()
    candidate_source_mode = _normalize_candidate_source_mode(punt.get("candidate_source_mode"))
    candidate_source_cfg = _normalize_candidate_source_cfg(
        punt.get("candidate_source_cfg"),
        fallback={"mode": "tots", "best_n": 1, "index": 1, "ids": [], "agregacio_exercicis": "sum"},
    )
    agg_exercicis = (punt.get("agregacio_exercicis") or "sum").lower().strip()
    agg_aparells = (punt.get("agregacio_aparells") or "sum").lower().strip()

    # 2) APARELLS sobre els quals es computa
    app_mode = ((punt.get("aparells") or {}).get("mode") or "tots").lower().strip()
    app_ids = (punt.get("aparells") or {}).get("ids") or []

    aparells_qs = CompeticioAparell.objects.filter(competicio=competicio, actiu=True).select_related("aparell")
    if app_mode == "seleccionar" and app_ids:
        aparells_qs = aparells_qs.filter(id__in=app_ids)
    aparells = list(aparells_qs.order_by("ordre", "id"))
    team_mode = ""
    if tipus == "equips":
        team_mode = _normalize_team_mode(equips_cfg.get("team_mode")) or _infer_team_mode_from_comp_aparells(aparells)
    detail_config = get_detail_display_config(schema, tipus=tipus, team_mode=team_mode)
    detail_enabled = bool(detail_config.get("enabled"))
    exercise_selection_scope = EXERCISE_SELECTION_SCOPE_PER_MEMBER
    if tipus == "equips" and team_mode == "derived_from_individual":
        exercise_selection_scope = _normalize_exercise_selection_scope(
            punt.get("exercise_selection_scope")
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

    def resolve_candidate_source_for_app(app_id: int):
        fallback_mode = candidate_source_mode
        fallback_cfg = candidate_source_cfg
        if not allow_candidate_source:
            return "raw_exercise", fallback_cfg
        raw = candidate_source_per_aparell.get(str(app_id))
        if raw is None:
            raw = candidate_source_per_aparell.get(app_id)
        entry = raw if isinstance(raw, dict) else {}
        mode = _normalize_candidate_source_mode(entry.get("mode") or fallback_mode)
        if tipus == "equips" and team_mode == "native_team":
            if mode != "team_aggregate":
                return "raw_exercise", fallback_cfg
        elif mode != "participant_aggregate":
            return "raw_exercise", fallback_cfg
        cfg = _normalize_candidate_source_cfg(entry.get("cfg"), fallback=fallback_cfg)
        return mode, cfg

    # si no hi ha aparells seleccionats -> retorn buit
    if not aparells:
        return {"global": []}

    # 3) INSCRIPCIONS per competició, agrupades per aparell
    all_ins_qs = Inscripcio.objects.filter(competicio=competicio)

    sr = []
    for f in ("entitat", "categoria", "subcategoria", "equip", "grup_competicio"):
        if _is_relational_field(Inscripcio, f):
            sr.append(f)
    if sr:
        all_ins_qs = all_ins_qs.select_related(*sr)

    all_ins_list = list(all_ins_qs)
    all_ins_by_id = {i.id: i for i in all_ins_list}
    filtered_ins_list = [
        ins for ins in all_ins_list
        if _inscripcio_matches_classificacio_filters(ins, filtres)
    ]
    filtered_ins_by_id = {i.id: i for i in filtered_ins_list}
    ins_list = filtered_ins_list
    ins_by_id = filtered_ins_by_id
    team_assignment_map = {}
    if tipus == "equips" and team_mode == "derived_from_individual" and assignment_source.get("mode") == "context":
        team_assignment_map = get_contextual_assignment_map(
            competicio,
            filtered_ins_list,
            team_context_code,
        )

    # notes per tots els aparells seleccionats (una query)
    notes_qs = (
        ScoreEntry.objects
      .filter(competicio=competicio, inscripcio__in=ins_list, comp_aparell__in=aparells)
      .select_related("inscripcio", "comp_aparell")
    )
    notes = list(notes_qs)
    team_notes = []
    if tipus == "equips" and team_mode == "native_team":
        team_apps = [ca for ca in aparells if is_team_context_app(ca)]
        if team_apps:
            team_notes = list(
                TeamScoreEntry.objects
                .filter(competicio=competicio, comp_aparell__in=team_apps)
                .select_related("team_subject__equip", "team_subject__context", "comp_aparell")
            )

    notes_by_app = defaultdict(list)  # app_id -> [notes...]
    notes_by_key = {}
    for n in notes:
        notes_by_app[n.comp_aparell_id].append(n)
        ex_idx = int(getattr(n, "exercici", 1) or 1)
        notes_by_key[(n.inscripcio_id, n.comp_aparell_id, ex_idx)] = n

    # inscripcions que realment "competeixen" a cada aparell (tenen notes)
    ins_ids_by_app = defaultdict(set)
    for app_id, lst in notes_by_app.items():
        for n in lst:
            ins_ids_by_app[app_id].add(n.inscripcio_id)
    team_notes_by_app = defaultdict(list)
    team_notes_by_key = {}
    team_ids_by_app = defaultdict(set)
    for n in team_notes:
        note_context_code = normalize_equip_context_code(
            getattr(getattr(getattr(n, "team_subject", None), "context", None), "code", "")
        )
        if note_context_code != team_context_code:
            continue
        team_notes_by_app[n.comp_aparell_id].append(n)
        ex_idx = int(getattr(n, "exercici", 1) or 1)
        team_notes_by_key[(n.equip_id, n.comp_aparell_id, ex_idx)] = n
        team_ids_by_app[n.comp_aparell_id].add(n.equip_id)

    # 4) CAMPS per aparell (lliures)
    camps_per_aparell = punt.get("camps_per_aparell") or {}
    # fallback legacy: si no hi ha camps_per_aparell, usem camp legacy per tots els aparells
    legacy_camp = (punt.get("camp") or "total").strip()

    def _score_camps_for_app(app_id: int):
        raw = camps_per_aparell.get(str(app_id)) or camps_per_aparell.get(app_id)
        if isinstance(raw, list) and raw:
            return [str(x).strip() for x in raw if str(x).strip()]
        if isinstance(raw, str) and raw.strip():
            # permet "total,execucio_total"
            return [x.strip() for x in raw.split(",") if x.strip()]
        # legacy
        return [legacy_camp] if legacy_camp else ["total"]

    def camps_for_app(app_id: int):
        out = list(_score_camps_for_app(app_id))
        seen = set()
        for crit in desempat or []:
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
        agg_camps_for_app = resolve_agregacio_camps_for_app(app_id)
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
                    fields_map = {f: _get_score_field(nt, f) for f in fields}
                    v_fields = [fields_map.get(f, 0.0) for f in score_fields]
                    v_ex = _apply_simple_agg(v_fields, agg_camps_for_app)
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
                fields_map = {f: _get_score_field(nt, f) for f in fields}
                v_fields = [fields_map.get(f, 0.0) for f in score_fields]

                v_ex = _apply_simple_agg(v_fields, agg_camps_for_app)  # agregacio camps dins exercici
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

    def _resolve_ex_cfg_for_app(app_id: int):
        if mode_seleccio_exercicis != "per_aparell_override":
            return base_ex_cfg
        raw = exercicis_per_aparell.get(str(app_id))
        if raw is None:
            raw = exercicis_per_aparell.get(app_id)
        return _normalize_exercicis_cfg(raw, fallback=base_ex_cfg)

    def _copy_ex_row_with_value(row, value):
        item = dict(row or {})
        item["value"] = _to_float(value)
        item["by_camp"] = dict((row or {}).get("by_camp") or {})
        return item

    def _build_candidate_rows_from_source_rows(rows_ex, app_id: int, *, participant_key="inscripcio_id"):
        base_rows = [
            _copy_ex_row_with_value(row, row.get("value"))
            for row in (rows_ex or [])
            if isinstance(row, dict)
        ]
        source_mode, source_cfg = resolve_candidate_source_for_app(app_id)
        if source_mode not in {"participant_aggregate", "team_aggregate"}:
            return base_rows
        if not base_rows:
            return []

        picked_rows = _pick_exercicis_rows(
            base_rows,
            source_cfg["mode"],
            source_cfg["best_n"],
            index=source_cfg["index"],
            ids=source_cfg["ids"],
            max_per_participant=0,
            participant_key=participant_key,
        )
        if not picked_rows:
            return []

        agg_value = _apply_simple_agg(
            [_to_float(row.get("value")) for row in picked_rows],
            source_cfg["agregacio_exercicis"],
        )
        all_field_codes = []
        seen_field_codes = set()
        for row in picked_rows:
            for code in dict((row or {}).get("by_camp") or {}).keys():
                code_str = str(code).strip()
                if code_str and code_str not in seen_field_codes:
                    seen_field_codes.add(code_str)
                    all_field_codes.append(code_str)
        by_camp = {}
        for code in all_field_codes:
            by_camp[code] = _apply_simple_agg(
                [_to_float(dict((row or {}).get("by_camp") or {}).get(code)) for row in picked_rows],
                source_cfg["agregacio_exercicis"],
            )

        first_row = picked_rows[0]
        candidate_row = _copy_ex_row_with_value(first_row, agg_value)
        candidate_row["idx"] = int(first_row.get("idx", 1) or 1)
        candidate_row["exercici"] = int(first_row.get("exercici", 1) or 1)
        candidate_row["by_camp"] = by_camp
        candidate_row["candidate_source_mode"] = source_mode
        candidate_row["candidate_source_count"] = len(picked_rows)
        return [candidate_row]

    selected_rows_agg_cache = {}
    selected_rows_field_cache = {}
    selected_team_rows_agg_cache = {}
    selected_team_rows_field_cache = {}

    def _get_selected_rows_agg_for_ins(ins_id: int):
        if ins_id in selected_rows_agg_cache:
            return selected_rows_agg_cache[ins_id]

        picked_by_app = defaultdict(list)
        if mode_seleccio_exercicis == "global_pool":
            pool_rows = []
            for ca in aparells:
                app_id = ca.id
                source_rows = _build_candidate_rows_from_source_rows(
                    app_ex_rows_by_ins.get(app_id, {}).get(ins_id, []),
                    app_id,
                    participant_key="inscripcio_id",
                )
                for row in source_rows:
                    item = _copy_ex_row_with_value(row, row.get("value"))
                    item["idx"] = 0
                    pool_rows.append(item)

            if pool_rows:
                pool_rows = sorted(
                    pool_rows,
                    key=lambda r: (r.get("app_order", 0), r.get("exercici", 0), r.get("app_id", 0)),
                )
                for idx, row in enumerate(pool_rows, start=1):
                    row["idx"] = idx
                picked_rows = _pick_exercicis_rows(
                    pool_rows,
                    exerc_mode,
                    ex_best_n,
                    index=ex_index,
                    ids=ex_ids,
                    max_per_participant=base_ex_cfg.get("max_per_participant", 0),
                    participant_key="inscripcio_id",
                )
                for row in picked_rows:
                    try:
                        app_id = int(row.get("app_id"))
                    except Exception:
                        continue
                    picked_by_app[app_id].append(_copy_ex_row_with_value(row, row.get("value")))
        else:
            for ca in aparells:
                app_id = ca.id
                rows_ex = _build_candidate_rows_from_source_rows(
                    app_ex_rows_by_ins.get(app_id, {}).get(ins_id, []),
                    app_id,
                    participant_key="inscripcio_id",
                )
                ex_cfg_app = _resolve_ex_cfg_for_app(app_id)
                picked = _pick_exercicis_rows(
                    rows_ex,
                    ex_cfg_app["mode"],
                    ex_cfg_app["best_n"],
                    index=ex_cfg_app["index"],
                    ids=ex_cfg_app["ids"],
                    max_per_participant=ex_cfg_app.get("max_per_participant", 0),
                    participant_key="inscripcio_id",
                )
                picked_by_app[app_id] = [
                    _copy_ex_row_with_value(row, row.get("value"))
                    for row in picked
                ]

        selected_rows_agg_cache[ins_id] = dict(picked_by_app)
        return selected_rows_agg_cache[ins_id]

    def _get_selected_rows_agg_for_team(equip_id: int):
        if equip_id in selected_team_rows_agg_cache:
            return selected_team_rows_agg_cache[equip_id]

        picked_by_app = defaultdict(list)
        if mode_seleccio_exercicis == "global_pool":
            pool_rows = []
            for ca in aparells:
                app_id = ca.id
                if not is_team_context_app(ca):
                    continue
                for row in team_app_ex_rows_by_equip.get(app_id, {}).get(equip_id, []):
                    item = _copy_ex_row_with_value(row, row.get("value"))
                    item["idx"] = 0
                    pool_rows.append(item)

            if pool_rows:
                pool_rows = sorted(
                    pool_rows,
                    key=lambda r: (r.get("app_order", 0), r.get("exercici", 0), r.get("app_id", 0)),
                )
                for idx, row in enumerate(pool_rows, start=1):
                    row["idx"] = idx
                picked_rows = _pick_exercicis_rows(
                    pool_rows,
                    exerc_mode,
                    ex_best_n,
                    index=ex_index,
                    ids=ex_ids,
                    max_per_participant=base_ex_cfg.get("max_per_participant", 0),
                    participant_key="equip_id",
                )
                for row in picked_rows:
                    try:
                        app_id = int(row.get("app_id"))
                    except Exception:
                        continue
                    picked_by_app[app_id].append(_copy_ex_row_with_value(row, row.get("value")))
        else:
            for ca in aparells:
                app_id = ca.id
                if not is_team_context_app(ca):
                    continue
                rows_ex = team_app_ex_rows_by_equip.get(app_id, {}).get(equip_id, [])
                ex_cfg_app = _resolve_ex_cfg_for_app(app_id)
                picked = _pick_exercicis_rows(
                    rows_ex,
                    ex_cfg_app["mode"],
                    ex_cfg_app["best_n"],
                    index=ex_cfg_app["index"],
                    ids=ex_cfg_app["ids"],
                    max_per_participant=ex_cfg_app.get("max_per_participant", 0),
                    participant_key="equip_id",
                )
                picked_by_app[app_id] = [
                    _copy_ex_row_with_value(row, row.get("value"))
                    for row in picked
                ]

        selected_team_rows_agg_cache[equip_id] = dict(picked_by_app)
        return selected_team_rows_agg_cache[equip_id]

    def _get_selected_rows_for_field(ins_id: int, field_code: str):
        cache_key = (ins_id, str(field_code or ""))
        if cache_key in selected_rows_field_cache:
            return selected_rows_field_cache[cache_key]

        picked_by_app = defaultdict(list)
        if mode_seleccio_exercicis == "global_pool":
            pool_rows = []
            for ca in aparells:
                app_id = ca.id
                raw_rows = app_ex_rows_by_ins.get(app_id, {}).get(ins_id, [])
                field_rows = [
                    _copy_ex_row_with_value(row, ((row.get("by_camp") or {}).get(field_code)))
                    for row in raw_rows
                ]
                for row in _build_candidate_rows_from_source_rows(field_rows, app_id, participant_key="inscripcio_id"):
                    item = _copy_ex_row_with_value(
                        row,
                        row.get("value"),
                    )
                    item["idx"] = 0
                    pool_rows.append(item)
            if pool_rows:
                pool_rows = sorted(
                    pool_rows,
                    key=lambda r: (r.get("app_order", 0), r.get("exercici", 0), r.get("app_id", 0)),
                )
                for idx, row in enumerate(pool_rows, start=1):
                    row["idx"] = idx
                picked_rows = _pick_exercicis_rows(
                    pool_rows,
                    exerc_mode,
                    ex_best_n,
                    index=ex_index,
                    ids=ex_ids,
                    max_per_participant=base_ex_cfg.get("max_per_participant", 0),
                    participant_key="inscripcio_id",
                )
                for row in picked_rows:
                    try:
                        app_id = int(row.get("app_id"))
                    except Exception:
                        continue
                    picked_by_app[app_id].append(
                        _copy_ex_row_with_value(row, row.get("value"))
                    )
        else:
            for ca in aparells:
                app_id = ca.id
                rows_ex = [
                    _copy_ex_row_with_value(row, ((row.get("by_camp") or {}).get(field_code)))
                    for row in app_ex_rows_by_ins.get(app_id, {}).get(ins_id, [])
                ]
                rows_ex = _build_candidate_rows_from_source_rows(rows_ex, app_id, participant_key="inscripcio_id")
                ex_cfg_app = _resolve_ex_cfg_for_app(app_id)
                picked = _pick_exercicis_rows(
                    rows_ex,
                    ex_cfg_app["mode"],
                    ex_cfg_app["best_n"],
                    index=ex_cfg_app["index"],
                    ids=ex_cfg_app["ids"],
                    max_per_participant=ex_cfg_app.get("max_per_participant", 0),
                    participant_key="inscripcio_id",
                )
                picked_by_app[app_id] = [
                    _copy_ex_row_with_value(row, row.get("value"))
                    for row in picked
                ]

        selected_rows_field_cache[cache_key] = dict(picked_by_app)
        return selected_rows_field_cache[cache_key]

    def _get_selected_team_rows_for_field(equip_id: int, field_code: str):
        cache_key = (equip_id, str(field_code or ""))
        if cache_key in selected_team_rows_field_cache:
            return selected_team_rows_field_cache[cache_key]

        picked_by_app = defaultdict(list)
        if mode_seleccio_exercicis == "global_pool":
            pool_rows = []
            for ca in aparells:
                app_id = ca.id
                if not is_team_context_app(ca):
                    continue
                n_ex = int(getattr(ca, "nombre_exercicis", 1) or 1)
                n_ex = max(1, min(50, n_ex))
                by_team_ex = defaultdict(dict)
                for nt in team_notes_by_app.get(app_id, []):
                    ex_idx = int(getattr(nt, "exercici", 1) or 1)
                    if 1 <= ex_idx <= n_ex:
                        by_team_ex[nt.equip_id][ex_idx] = nt
                for ex_idx in range(1, n_ex + 1):
                    nt = by_team_ex.get(equip_id, {}).get(ex_idx)
                    if not nt:
                        continue
                    item = {
                        "idx": 0,
                        "value": _to_float(_get_score_field(nt, field_code)),
                        "app_id": app_id,
                        "app_order": app_order.get(app_id, 0),
                        "exercici": int(ex_idx),
                        "equip_id": equip_id,
                        "by_camp": {field_code: _get_score_field(nt, field_code)},
                    }
                    item["idx"] = 0
                    pool_rows.append(item)
            if pool_rows:
                pool_rows = sorted(
                    pool_rows,
                    key=lambda r: (r.get("app_order", 0), r.get("exercici", 0), r.get("app_id", 0)),
                )
                for idx, row in enumerate(pool_rows, start=1):
                    row["idx"] = idx
                picked_rows = _pick_exercicis_rows(
                    pool_rows,
                    exerc_mode,
                    ex_best_n,
                    index=ex_index,
                    ids=ex_ids,
                    max_per_participant=base_ex_cfg.get("max_per_participant", 0),
                    participant_key="equip_id",
                )
                for row in picked_rows:
                    try:
                        app_id = int(row.get("app_id"))
                    except Exception:
                        continue
                    picked_by_app[app_id].append(
                        _copy_ex_row_with_value(row, row.get("value"))
                    )
        else:
            for ca in aparells:
                app_id = ca.id
                if not is_team_context_app(ca):
                    continue
                n_ex = int(getattr(ca, "nombre_exercicis", 1) or 1)
                n_ex = max(1, min(50, n_ex))
                by_team_ex = defaultdict(dict)
                for nt in team_notes_by_app.get(app_id, []):
                    ex_idx = int(getattr(nt, "exercici", 1) or 1)
                    if 1 <= ex_idx <= n_ex:
                        by_team_ex[nt.equip_id][ex_idx] = nt
                rows_ex = []
                for ex_idx in range(1, n_ex + 1):
                    nt = by_team_ex.get(equip_id, {}).get(ex_idx)
                    if not nt:
                        continue
                    rows_ex.append(
                        {
                            "idx": int(ex_idx),
                            "value": _to_float(_get_score_field(nt, field_code)),
                            "app_id": app_id,
                            "app_order": app_order.get(app_id, 0),
                            "exercici": int(ex_idx),
                            "equip_id": equip_id,
                            "by_camp": {field_code: _get_score_field(nt, field_code)},
                        }
                    )
                ex_cfg_app = _resolve_ex_cfg_for_app(app_id)
                picked = _pick_exercicis_rows(
                    rows_ex,
                    ex_cfg_app["mode"],
                    ex_cfg_app["best_n"],
                    index=ex_cfg_app["index"],
                    ids=ex_cfg_app["ids"],
                    max_per_participant=ex_cfg_app.get("max_per_participant", 0),
                    participant_key="equip_id",
                )
                picked_by_app[app_id] = [
                    _copy_ex_row_with_value(row, row.get("value"))
                    for row in picked
                ]

        selected_team_rows_field_cache[cache_key] = dict(picked_by_app)
        return selected_team_rows_field_cache[cache_key]

    def _build_team_field_rows_for_app(equip_id: int, app_id: int, field_code: str):
        rows_ex = []
        ca = next((item for item in aparells if int(item.id) == int(app_id)), None)
        if ca is None or not is_team_context_app(ca):
            return rows_ex
        n_ex = int(getattr(ca, "nombre_exercicis", 1) or 1)
        n_ex = max(1, min(50, n_ex))
        by_team_ex = defaultdict(dict)
        for nt in team_notes_by_app.get(app_id, []):
            ex_idx = int(getattr(nt, "exercici", 1) or 1)
            if 1 <= ex_idx <= n_ex:
                by_team_ex[nt.equip_id][ex_idx] = nt
        for ex_idx in range(1, n_ex + 1):
            nt = by_team_ex.get(equip_id, {}).get(ex_idx)
            if not nt:
                continue
            rows_ex.append(
                {
                    "idx": int(ex_idx),
                    "value": _to_float(_get_score_field(nt, field_code)),
                    "app_id": int(app_id),
                    "app_order": app_order.get(int(app_id), 0),
                    "exercici": int(ex_idx),
                    "equip_id": int(equip_id),
                    "by_camp": {field_code: _get_score_field(nt, field_code)},
                }
            )
        return rows_ex

    main_selected_team_rows_agg_cache = {}
    main_selected_team_rows_field_cache = {}
    main_selected_rows_for_group_cache = {}
    main_selected_rows_for_group_field_cache = {}
    derived_team_selected_rows_agg_cache = {}
    derived_team_selected_rows_field_cache = {}

    def _get_main_selected_rows_agg_for_team(equip_id: int):
        if equip_id in main_selected_team_rows_agg_cache:
            return main_selected_team_rows_agg_cache[equip_id]

        picked_by_app = defaultdict(list)
        if mode_seleccio_exercicis == "global_pool":
            pool_rows = []
            for ca in aparells:
                app_id = ca.id
                if not is_team_context_app(ca):
                    continue
                source_rows = _build_candidate_rows_from_source_rows(
                    team_app_ex_rows_by_equip.get(app_id, {}).get(equip_id, []),
                    app_id,
                    participant_key="equip_id",
                )
                for row in source_rows:
                    item = _copy_ex_row_with_value(row, row.get("value"))
                    item["idx"] = 0
                    pool_rows.append(item)

            if pool_rows:
                pool_rows = sorted(
                    pool_rows,
                    key=lambda r: (r.get("app_order", 0), r.get("exercici", 0), r.get("app_id", 0)),
                )
                for idx, row in enumerate(pool_rows, start=1):
                    row["idx"] = idx
                picked_rows = _pick_exercicis_rows(
                    pool_rows,
                    exerc_mode,
                    ex_best_n,
                    index=ex_index,
                    ids=ex_ids,
                    max_per_participant=base_ex_cfg.get("max_per_participant", 0),
                    participant_key="equip_id",
                )
                for row in picked_rows:
                    try:
                        app_id = int(row.get("app_id"))
                    except Exception:
                        continue
                    picked_by_app[app_id].append(_copy_ex_row_with_value(row, row.get("value")))
        else:
            for ca in aparells:
                app_id = ca.id
                if not is_team_context_app(ca):
                    continue
                rows_ex = _build_candidate_rows_from_source_rows(
                    team_app_ex_rows_by_equip.get(app_id, {}).get(equip_id, []),
                    app_id,
                    participant_key="equip_id",
                )
                ex_cfg_app = _resolve_ex_cfg_for_app(app_id)
                picked = _pick_exercicis_rows(
                    rows_ex,
                    ex_cfg_app["mode"],
                    ex_cfg_app["best_n"],
                    index=ex_cfg_app["index"],
                    ids=ex_cfg_app["ids"],
                    max_per_participant=ex_cfg_app.get("max_per_participant", 0),
                    participant_key="equip_id",
                )
                picked_by_app[app_id] = [
                    _copy_ex_row_with_value(row, row.get("value"))
                    for row in picked
                ]

        main_selected_team_rows_agg_cache[equip_id] = dict(picked_by_app)
        return main_selected_team_rows_agg_cache[equip_id]

    def _get_main_selected_team_rows_for_field(equip_id: int, field_code: str):
        cache_key = (equip_id, str(field_code or ""))
        if cache_key in main_selected_team_rows_field_cache:
            return main_selected_team_rows_field_cache[cache_key]

        picked_by_app = defaultdict(list)
        if mode_seleccio_exercicis == "global_pool":
            pool_rows = []
            for ca in aparells:
                app_id = ca.id
                if not is_team_context_app(ca):
                    continue
                rows_ex = _build_candidate_rows_from_source_rows(
                    _build_team_field_rows_for_app(equip_id, app_id, field_code),
                    app_id,
                    participant_key="equip_id",
                )
                for row in rows_ex:
                    item = _copy_ex_row_with_value(row, row.get("value"))
                    item["idx"] = 0
                    pool_rows.append(item)
            if pool_rows:
                pool_rows = sorted(
                    pool_rows,
                    key=lambda r: (r.get("app_order", 0), r.get("exercici", 0), r.get("app_id", 0)),
                )
                for idx, row in enumerate(pool_rows, start=1):
                    row["idx"] = idx
                picked_rows = _pick_exercicis_rows(
                    pool_rows,
                    exerc_mode,
                    ex_best_n,
                    index=ex_index,
                    ids=ex_ids,
                    max_per_participant=base_ex_cfg.get("max_per_participant", 0),
                    participant_key="equip_id",
                )
                for row in picked_rows:
                    try:
                        app_id = int(row.get("app_id"))
                    except Exception:
                        continue
                    picked_by_app[app_id].append(
                        _copy_ex_row_with_value(row, row.get("value"))
                    )
        else:
            for ca in aparells:
                app_id = ca.id
                if not is_team_context_app(ca):
                    continue
                rows_ex = _build_candidate_rows_from_source_rows(
                    _build_team_field_rows_for_app(equip_id, app_id, field_code),
                    app_id,
                    participant_key="equip_id",
                )
                ex_cfg_app = _resolve_ex_cfg_for_app(app_id)
                picked = _pick_exercicis_rows(
                    rows_ex,
                    ex_cfg_app["mode"],
                    ex_cfg_app["best_n"],
                    index=ex_cfg_app["index"],
                    ids=ex_cfg_app["ids"],
                    max_per_participant=ex_cfg_app.get("max_per_participant", 0),
                    participant_key="equip_id",
                )
                picked_by_app[app_id] = [
                    _copy_ex_row_with_value(row, row.get("value"))
                    for row in picked
                ]

        main_selected_team_rows_field_cache[cache_key] = dict(picked_by_app)
        return main_selected_team_rows_field_cache[cache_key]

    def _derived_team_cache_key(equip_id, member_ids):
        if equip_id not in (None, "", "__sense_equip__"):
            try:
                return f"equip:{int(equip_id)}"
            except Exception:
                pass
        mids = []
        for raw_member_id in (member_ids or []):
            try:
                mids.append(int(raw_member_id))
            except Exception:
                continue
        mids = sorted(set(mids))
        return f"members:{','.join(str(mid) for mid in mids)}"

    def _build_derived_team_rows_for_app(member_ids, app_id: int, *, field_code=None):
        rows = []
        seen_members = set()
        for raw_member_id in (member_ids or []):
            try:
                member_id = int(raw_member_id)
            except Exception:
                continue
            if member_id in seen_members:
                continue
            seen_members.add(member_id)
            member_rows = app_ex_rows_by_ins.get(app_id, {}).get(member_id, [])
            source_rows = []
            for base_row in member_rows:
                value = (
                    ((base_row.get("by_camp") or {}).get(field_code))
                    if field_code is not None
                    else base_row.get("value")
                )
                source_rows.append(_copy_ex_row_with_value(base_row, value))
            for item in _build_candidate_rows_from_source_rows(source_rows, app_id, participant_key="inscripcio_id"):
                item["inscripcio_id"] = member_id
                rows.append(item)
        return rows

    def _get_selected_rows_agg_for_derived_team(team_cache_key: str, member_ids):
        if team_cache_key in derived_team_selected_rows_agg_cache:
            return derived_team_selected_rows_agg_cache[team_cache_key]

        picked_by_app = defaultdict(list)
        if mode_seleccio_exercicis == "global_pool":
            pool_rows = []
            for ca in aparells:
                app_id = ca.id
                if is_team_context_app(ca):
                    continue
                for row in _build_derived_team_rows_for_app(member_ids, app_id):
                    item = _copy_ex_row_with_value(row, row.get("value"))
                    item["idx"] = 0
                    pool_rows.append(item)

            if pool_rows:
                pool_rows = sorted(
                    pool_rows,
                    key=lambda r: (r.get("app_order", 0), r.get("exercici", 0), r.get("app_id", 0)),
                )
                for idx, row in enumerate(pool_rows, start=1):
                    row["idx"] = idx
                picked_rows = _pick_exercicis_rows(
                    pool_rows,
                    exerc_mode,
                    ex_best_n,
                    index=ex_index,
                    ids=ex_ids,
                    max_per_participant=base_ex_cfg.get("max_per_participant", 0),
                    participant_key="inscripcio_id",
                )
                for row in picked_rows:
                    try:
                        app_id = int(row.get("app_id"))
                    except Exception:
                        continue
                    picked_by_app[app_id].append(_copy_ex_row_with_value(row, row.get("value")))
        else:
            for ca in aparells:
                app_id = ca.id
                if is_team_context_app(ca):
                    continue
                rows_ex = _build_derived_team_rows_for_app(member_ids, app_id)
                ex_cfg_app = _resolve_ex_cfg_for_app(app_id)
                picked = _pick_exercicis_rows(
                    rows_ex,
                    ex_cfg_app["mode"],
                    ex_cfg_app["best_n"],
                    index=ex_cfg_app["index"],
                    ids=ex_cfg_app["ids"],
                    max_per_participant=ex_cfg_app.get("max_per_participant", 0),
                    participant_key="inscripcio_id",
                )
                picked_by_app[app_id] = [
                    _copy_ex_row_with_value(row, row.get("value"))
                    for row in picked
                ]

        derived_team_selected_rows_agg_cache[team_cache_key] = dict(picked_by_app)
        return derived_team_selected_rows_agg_cache[team_cache_key]

    def _get_main_selected_rows_for_group(team_cache_key: str, member_ids):
        if team_cache_key in main_selected_rows_for_group_cache:
            return main_selected_rows_for_group_cache[team_cache_key]

        if exercise_selection_scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL:
            rows = _get_selected_rows_agg_for_derived_team(team_cache_key, member_ids)
            main_selected_rows_for_group_cache[team_cache_key] = rows
            return rows

        picked_by_app = defaultdict(list)
        seen_members = set()
        for raw_member_id in (member_ids or []):
            try:
                member_id = int(raw_member_id)
            except Exception:
                continue
            if member_id in seen_members:
                continue
            seen_members.add(member_id)
            for app_id, rows in (_get_selected_rows_agg_for_ins(member_id) or {}).items():
                try:
                    app_id_int = int(app_id)
                except Exception:
                    continue
                for row in (rows or []):
                    item = _copy_ex_row_with_value(row, row.get("value"))
                    item["inscripcio_id"] = member_id
                    picked_by_app[app_id_int].append(item)

        for app_id, rows in list(picked_by_app.items()):
            picked_by_app[app_id] = sorted(
                rows,
                key=lambda r: (
                    r.get("app_order", 0),
                    r.get("exercici", 0),
                    r.get("app_id", 0),
                    r.get("inscripcio_id", 0),
                ),
            )

        main_selected_rows_for_group_cache[team_cache_key] = dict(picked_by_app)
        return main_selected_rows_for_group_cache[team_cache_key]

    def _get_selected_rows_for_derived_team_field(team_cache_key: str, member_ids, field_code: str):
        cache_key = (team_cache_key, str(field_code or ""))
        if cache_key in derived_team_selected_rows_field_cache:
            return derived_team_selected_rows_field_cache[cache_key]

        picked_by_app = defaultdict(list)
        if mode_seleccio_exercicis == "global_pool":
            pool_rows = []
            for ca in aparells:
                app_id = ca.id
                if is_team_context_app(ca):
                    continue
                for row in _build_derived_team_rows_for_app(member_ids, app_id, field_code=field_code):
                    item = _copy_ex_row_with_value(row, row.get("value"))
                    item["idx"] = 0
                    pool_rows.append(item)
            if pool_rows:
                pool_rows = sorted(
                    pool_rows,
                    key=lambda r: (r.get("app_order", 0), r.get("exercici", 0), r.get("app_id", 0)),
                )
                for idx, row in enumerate(pool_rows, start=1):
                    row["idx"] = idx
                picked_rows = _pick_exercicis_rows(
                    pool_rows,
                    exerc_mode,
                    ex_best_n,
                    index=ex_index,
                    ids=ex_ids,
                    max_per_participant=base_ex_cfg.get("max_per_participant", 0),
                    participant_key="inscripcio_id",
                )
                for row in picked_rows:
                    try:
                        app_id = int(row.get("app_id"))
                    except Exception:
                        continue
                    picked_by_app[app_id].append(_copy_ex_row_with_value(row, row.get("value")))
        else:
            for ca in aparells:
                app_id = ca.id
                if is_team_context_app(ca):
                    continue
                rows_ex = _build_derived_team_rows_for_app(member_ids, app_id, field_code=field_code)
                ex_cfg_app = _resolve_ex_cfg_for_app(app_id)
                picked = _pick_exercicis_rows(
                    rows_ex,
                    ex_cfg_app["mode"],
                    ex_cfg_app["best_n"],
                    index=ex_cfg_app["index"],
                    ids=ex_cfg_app["ids"],
                    max_per_participant=ex_cfg_app.get("max_per_participant", 0),
                    participant_key="inscripcio_id",
                )
                picked_by_app[app_id] = [
                    _copy_ex_row_with_value(row, row.get("value"))
                    for row in picked
                ]

        derived_team_selected_rows_field_cache[cache_key] = dict(picked_by_app)
        return derived_team_selected_rows_field_cache[cache_key]

    def _get_main_selected_rows_for_group_field(team_cache_key: str, member_ids, field_code: str):
        cache_key = (team_cache_key, str(field_code or ""))
        if cache_key in main_selected_rows_for_group_field_cache:
            return main_selected_rows_for_group_field_cache[cache_key]

        if exercise_selection_scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL:
            rows = _get_selected_rows_for_derived_team_field(team_cache_key, member_ids, field_code)
            main_selected_rows_for_group_field_cache[cache_key] = rows
            return rows

        picked_by_app = defaultdict(list)
        seen_members = set()
        for raw_member_id in (member_ids or []):
            try:
                member_id = int(raw_member_id)
            except Exception:
                continue
            if member_id in seen_members:
                continue
            seen_members.add(member_id)
            for app_id, rows in (_get_selected_rows_for_field(member_id, field_code) or {}).items():
                try:
                    app_id_int = int(app_id)
                except Exception:
                    continue
                for row in (rows or []):
                    item = _copy_ex_row_with_value(row, row.get("value"))
                    item["inscripcio_id"] = member_id
                    picked_by_app[app_id_int].append(item)

        for app_id, rows in list(picked_by_app.items()):
            picked_by_app[app_id] = sorted(
                rows,
                key=lambda r: (
                    r.get("app_order", 0),
                    r.get("exercici", 0),
                    r.get("app_id", 0),
                    r.get("inscripcio_id", 0),
                ),
            )

        main_selected_rows_for_group_field_cache[cache_key] = dict(picked_by_app)
        return main_selected_rows_for_group_field_cache[cache_key]

    for ins_id, obj in per_ins.items():
        selected_rows_by_app = _get_selected_rows_agg_for_ins(ins_id)
        for ca in aparells:
            app_id = ca.id
            if ins_id not in ins_ids_by_app.get(app_id, set()):
                continue
            score_app = _apply_simple_agg(
                [_to_float(row.get("value")) for row in selected_rows_by_app.get(app_id, [])],
                agg_exercicis,
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
    #  - nou: {"aparell_id": X, "camp": "E_total", "ordre":"desc"} -> recalcula com "score d'aquell aparell però només amb aquell camp"
    #
    # IMPORTANT: per no duplicar molt codi, fem una funció que calcula "valor criteri" reutilitzant el mateix pipeline,
    # però substituint camps per la llista [camp].
    def calc_criterion_value(
        ins_id: int,
        crit: dict,
        forced_app_ids=None,
        forced_exercici_ids=None,
        forced_camps=None,
    ) -> float:
        """
        Calcula el valor d'un criteri de desempat per una inscripció concreta.

        Suporta:
        - compat antic:
            {"camp":"E_total","ordre":"desc"}  -> tots els aparells, exercicis heretats
            {"aparell_id": 12, "camp":"E_total","ordre":"desc"} -> un aparell, exercicis heretats
        - nou (overrides):
            {
                "camp":"E_total",
                "camps":["E_total","D_total"],
                "ordre":"desc",
                "scope":{
                "aparells":{"mode":"tots"|"seleccionar","ids":[12,13]},
                "exercicis":{"mode":"hereta"|"tots"|"millor_1"|"millor_n"|"pitjor_1"|"pitjor_n"|"primer"|"ultim"|"index"|"llista",
                            "best_n":2, "index":1, "ids":[1,3]}
                },
                "agregacio_camps":"hereta"|"sum"|"avg"|"median"|"max"|"min",
                "agregacio_exercicis":"hereta"|"sum"|"avg"|"median"|"max"|"min",
                "agregacio_aparells":"hereta"|"sum"|"avg"|"median"|"max"|"min"
            }
        """

        if forced_camps is not None:
            camps = [str(x).strip() for x in (forced_camps or []) if str(x).strip()]
        else:
            camps = _normalize_tie_camps(crit)
        if not camps:
            return 0.0

        # -----------------------------
        # Overrides (scope + agregacions)
        # -----------------------------
        scope = crit.get("scope") or {}
        crit_apps = scope.get("aparells") or {}
        crit_ex = scope.get("exercicis") or {}

        def _inherit(v, fallback):
            v = (v or "hereta")
            return fallback if str(v).lower().strip() == "hereta" else str(v).lower().strip()

        crit_agg_camps = _inherit(crit.get("agregacio_camps"), agg_camps)
        crit_agg_exercicis = _inherit(crit.get("agregacio_exercicis"), agg_exercicis)
        crit_agg_aparells = _inherit(crit.get("agregacio_aparells"), agg_aparells)

        # exercicis: hereta o override
        crit_ex_mode = (crit_ex.get("mode") or "hereta").lower().strip()
        if crit_ex_mode == "hereta":
            crit_ex_mode = exerc_mode

        try:
            crit_best_n = int(crit_ex.get("best_n") or ex_best_n)
        except Exception:
            crit_best_n = ex_best_n
        crit_ex_index = crit_ex.get("index", ex_index)
        crit_ex_ids = crit_ex.get("ids", ex_ids)
        try:
            crit_ex_max_per_participant = int(
                crit_ex.get("max_per_participant", base_ex_cfg.get("max_per_participant", 0))
            )
        except Exception:
            crit_ex_max_per_participant = int(base_ex_cfg.get("max_per_participant", 0) or 0)
        crit_ex_max_per_participant = max(0, crit_ex_max_per_participant)

        crit_ex_cfg_global = _normalize_exercicis_cfg(
            {
                "mode": crit_ex_mode,
                "best_n": crit_best_n,
                "index": crit_ex_index,
                "ids": crit_ex_ids,
                "max_per_participant": crit_ex_max_per_participant,
            },
            fallback=base_ex_cfg,
        )

        crit_mode_sel = (
            crit.get("mode_seleccio_exercicis")
            or crit_ex.get("mode_seleccio_exercicis")
            or "hereta"
        )
        crit_mode_sel = _inherit(crit_mode_sel, mode_seleccio_exercicis)
        if crit_mode_sel not in ("per_aparell_global", "per_aparell_override", "global_pool"):
            crit_mode_sel = mode_seleccio_exercicis

        crit_ex_per_app_raw = (
            crit.get("exercicis_per_aparell")
            or crit_ex.get("exercicis_per_aparell")
            or {}
        )
        if not isinstance(crit_ex_per_app_raw, dict):
            crit_ex_per_app_raw = {}

        # -----------------------------
        # Aparells objectiu del criteri
        # -----------------------------
        target_apps = []
        if forced_app_ids is not None:
            for raw_app_id in (forced_app_ids or []):
                try:
                    app_id = int(raw_app_id)
                except Exception:
                    continue
                target_apps.append(app_id)
        else:
            mode = (crit_apps.get("mode") or "").lower().strip()
            ids = crit_apps.get("ids") or []

            if mode == "seleccionar" and ids:
                try:
                    target_apps = [int(x) for x in ids]
                except Exception:
                    target_apps = []
            elif mode == "tots":
                target_apps = [ca.id for ca in aparells]
            else:
                # compat: aparell_id antic
                app_id = crit.get("aparell_id", None)
                if app_id in (None, "", 0, "0"):
                    target_apps = [ca.id for ca in aparells]
                else:
                    try:
                        target_apps = [int(app_id)]
                    except Exception:
                        target_apps = [ca.id for ca in aparells]

        # -----------------------------
        # Càlcul per aparell -> exercicis
        # -----------------------------
        vals_apps = []
        app_vals_ex = {}
        forced_exercicis_set = None
        if forced_exercici_ids is not None:
            forced_exercicis_set = set()
            for raw_ex in (forced_exercici_ids or []):
                try:
                    forced_exercicis_set.add(int(raw_ex))
                except Exception:
                    continue

        for ta in target_apps:
            ca = next((x for x in aparells if x.id == ta), None)
            if not ca:
                continue

            n_ex = int(getattr(ca, "nombre_exercicis", 1) or 1)
            n_ex = max(1, min(50, n_ex))

            app_scores = notes_by_app.get(ta, [])
            by_ins_ex = defaultdict(dict)
            for se in app_scores:
                ex_idx = int(getattr(se, "exercici", 1) or 1)
                if 1 <= ex_idx <= n_ex:
                    by_ins_ex[se.inscripcio_id][ex_idx] = se

            vals_ex = []
            for ex_idx in range(1, n_ex + 1):
                if forced_exercicis_set is not None and ex_idx not in forced_exercicis_set:
                    continue
                se = by_ins_ex.get(ins_id, {}).get(ex_idx)
                if not se:
                    continue
                vals_fields = [_get_score_field(se, c) for c in camps]
                v_ex = _apply_simple_agg(vals_fields, crit_agg_camps)
                vals_ex.append((ex_idx, v_ex))

            app_vals_ex[ta] = vals_ex

        def _resolve_tie_ex_cfg_for_app(app_id: int):
            if crit_mode_sel != "per_aparell_override":
                return crit_ex_cfg_global
            raw = crit_ex_per_app_raw.get(str(app_id))
            if raw is None:
                raw = crit_ex_per_app_raw.get(app_id)
            return _normalize_exercicis_cfg(raw, fallback=crit_ex_cfg_global)

        if forced_exercicis_set is not None:
            for ta in target_apps:
                vals_ex = app_vals_ex.get(ta, [])
                val_app = _apply_simple_agg([_to_float(v_ex) for _, v_ex in vals_ex], crit_agg_exercicis)
                vals_apps.append(val_app)
        elif crit_mode_sel == "global_pool":
            pool_rows = []
            for ta in target_apps:
                vals_ex = app_vals_ex.get(ta, [])
                for ex_idx, v_ex in vals_ex:
                    pool_rows.append(
                        {
                            "idx": 0,
                            "value": _to_float(v_ex),
                            "app_id": ta,
                            "app_order": app_order.get(ta, 0),
                            "exercici": int(ex_idx),
                            "inscripcio_id": ins_id,
                        }
                    )

            pool_rows = sorted(
                pool_rows,
                key=lambda r: (r.get("app_order", 0), r.get("exercici", 0), r.get("app_id", 0)),
            )
            for idx, row in enumerate(pool_rows, start=1):
                row["idx"] = idx

            picked_rows = _pick_exercicis_rows(
                pool_rows,
                crit_ex_cfg_global["mode"],
                crit_ex_cfg_global["best_n"],
                index=crit_ex_cfg_global["index"],
                ids=crit_ex_cfg_global["ids"],
                max_per_participant=crit_ex_cfg_global.get("max_per_participant", 0),
                participant_key="inscripcio_id",
            )
            picked_by_app = defaultdict(list)
            for row in picked_rows:
                try:
                    app_id = int(row.get("app_id"))
                except Exception:
                    continue
                picked_by_app[app_id].append(_to_float(row.get("value")))

            for ta in target_apps:
                val_app = _apply_simple_agg(picked_by_app.get(ta, []), crit_agg_exercicis)
                vals_apps.append(val_app)
        else:
            for ta in target_apps:
                vals_ex = app_vals_ex.get(ta, [])
                ex_cfg_app = _resolve_tie_ex_cfg_for_app(ta)
                picked = _pick_exercicis_tuples(
                    vals_ex,
                    ex_cfg_app["mode"],
                    ex_cfg_app["best_n"],
                    index=ex_cfg_app["index"],
                    ids=ex_cfg_app["ids"],
                    max_per_participant=ex_cfg_app.get("max_per_participant", 0),
                    participant_key="inscripcio_id",
                )
                val_app = _apply_simple_agg(picked, crit_agg_exercicis)
                vals_apps.append(val_app)

        return float(_apply_simple_agg(vals_apps, crit_agg_aparells))
    
    # capa reutilitzable: desempat + columnes mètriques
    metric_cache = {}

    def _metric_signature(crit: dict, forced_app_ids=None, forced_exercici_ids=None, forced_camps=None) -> str:
        try:
            payload = {"crit": crit or {}}
            if forced_app_ids is not None:
                payload["forced_app_ids"] = [int(x) for x in (forced_app_ids or [])]
            if forced_exercici_ids is not None:
                payload["forced_exercici_ids"] = [int(x) for x in (forced_exercici_ids or [])]
            if forced_camps is not None:
                payload["forced_camps"] = [str(x).strip() for x in (forced_camps or []) if str(x).strip()]
            return json.dumps(payload, sort_keys=True, ensure_ascii=False)
        except Exception:
            return str(_tie_key(crit) or crit or "")

    def calc_metric_value_for_ins(
        ins_id: int,
        crit: dict,
        forced_app_ids=None,
        forced_exercici_ids=None,
        forced_camps=None,
    ) -> float:
        try:
            iid = int(ins_id)
        except Exception:
            return 0.0
        sig = _metric_signature(
            crit,
            forced_app_ids=forced_app_ids,
            forced_exercici_ids=forced_exercici_ids,
            forced_camps=forced_camps,
        )
        ck = (iid, sig)
        if ck in metric_cache:
            return metric_cache[ck]
        val = float(
            calc_criterion_value(
                iid,
                crit or {},
                forced_app_ids=forced_app_ids,
                forced_exercici_ids=forced_exercici_ids,
                forced_camps=forced_camps,
            )
        )
        metric_cache[ck] = val
        return val

    def calc_metric_value_for_group(member_ids, crit: dict) -> float:
        mids = []
        for x in (member_ids or []):
            try:
                mids.append(int(x))
            except Exception:
                continue
        if not mids:
            return 0.0

        crit_selection_scope = _normalize_exercise_selection_scope(
            (crit or {}).get("exercise_selection_scope"),
            allow_inherit=True,
        )
        if crit_selection_scope == EXERCISE_SELECTION_SCOPE_INHERIT:
            crit_selection_scope = exercise_selection_scope

        def _inherit(v, fallback):
            v = (v or "hereta")
            return fallback if str(v).lower().strip() == "hereta" else str(v).lower().strip()

        def _resolve_target_apps(crit_apps, forced_app_ids=None):
            if forced_app_ids is not None:
                out = []
                for raw_app_id in (forced_app_ids or []):
                    try:
                        out.append(int(raw_app_id))
                    except Exception:
                        continue
                return out

            mode = str(crit_apps.get("mode") or "").lower().strip()
            ids = crit_apps.get("ids") or []
            if mode == "seleccionar" and ids:
                out = []
                for raw_app_id in ids:
                    try:
                        out.append(int(raw_app_id))
                    except Exception:
                        continue
                return out
            if mode == "tots":
                return [int(ca.id) for ca in aparells]
            if crit.get("aparell_id") not in (None, "", 0, "0"):
                try:
                    return [int(crit.get("aparell_id"))]
                except Exception:
                    return [int(ca.id) for ca in aparells]
            return [int(ca.id) for ca in aparells]

        def _calc_metric_value_for_team_pool(
            mids_local,
            crit_local,
            *,
            forced_app_ids=None,
            forced_exercici_ids=None,
            forced_camps=None,
        ):
            if forced_camps is not None:
                camps = [str(x).strip() for x in (forced_camps or []) if str(x).strip()]
            else:
                camps = _normalize_tie_camps(crit_local)
            if not camps:
                return 0.0

            scope = crit_local.get("scope") or {}
            crit_apps = scope.get("aparells") or {}

            crit_agg_camps = _inherit(crit_local.get("agregacio_camps"), agg_camps)
            crit_agg_exercicis = _inherit(crit_local.get("agregacio_exercicis"), agg_exercicis)
            crit_agg_aparells = _inherit(crit_local.get("agregacio_aparells"), agg_aparells)

            target_apps = _resolve_target_apps(crit_apps, forced_app_ids=forced_app_ids)
            forced_exercicis_set = None
            if forced_exercici_ids is not None:
                forced_exercicis_set = set()
                for raw_ex in (forced_exercici_ids or []):
                    try:
                        forced_exercicis_set.add(int(raw_ex))
                    except Exception:
                        continue

            team_cache_key = _derived_team_cache_key(None, mids_local)
            selected_rows_by_app = _get_main_selected_rows_for_group(
                team_cache_key,
                mids_local,
            )
            vals_apps = []
            for app_id in target_apps:
                ca = next((x for x in aparells if x.id == app_id), None)
                if not ca or is_team_context_app(ca):
                    continue

                selected_rows = list(selected_rows_by_app.get(app_id, []))
                if forced_exercicis_set is not None:
                    selected_rows = [
                        row for row in selected_rows
                        if int(row.get("exercici", 0) or 0) in forced_exercicis_set
                    ]

                row_values = []
                for row in selected_rows:
                    by_camp = dict((row or {}).get("by_camp") or {})
                    row_values.append(
                        _apply_simple_agg(
                            [_to_float(by_camp.get(code)) for code in camps],
                            crit_agg_camps,
                        )
                    )

                vals_apps.append(_apply_simple_agg(row_values, crit_agg_exercicis))

            return float(_apply_simple_agg(vals_apps, crit_agg_aparells))

        if crit_selection_scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL:
            return _calc_metric_value_for_team_pool(mids, crit or {})

        part_scope = ((crit.get("scope") or {}).get("participants") or {})
        part_mode = (part_scope.get("mode") or "tots").lower().strip()
        if part_mode == "hereta":
            part_mode = "tots"
        try:
            part_n = int(part_scope.get("n") or 1)
        except Exception:
            part_n = 1

        agg_parts = (crit.get("agregacio_participants") or "sum").lower().strip()
        team_context_app_ids = {int(ca.id) for ca in aparells if is_team_context_app(ca)}
        if not team_context_app_ids:
            vals = [calc_metric_value_for_ins(mid, crit) for mid in mids]
            selected_vals = _pick_participants(vals, part_mode, part_n)
            return float(_apply_simple_agg(selected_vals, agg_parts))

        equip_id = None
        for team_id_key, members in teams.items():
            if team_id_key == "__sense_equip__":
                continue
            current_member_ids = [m.id for m, _resolved_equip in members]
            if any(mid in current_member_ids for mid in mids):
                try:
                    equip_id = int(team_id_key)
                except Exception:
                    equip_id = None
                break

        scope = crit.get("scope") or {}
        app_scope = scope.get("aparells") or {}
        forced_app_ids = None
        app_scope_mode = str(app_scope.get("mode") or "").lower().strip()
        if app_scope_mode == "seleccionar":
            forced_app_ids = []
            for raw_app_id in (app_scope.get("ids") or []):
                try:
                    forced_app_ids.append(int(raw_app_id))
                except Exception:
                    continue
        elif crit.get("aparell_id") not in (None, "", 0, "0"):
            try:
                forced_app_ids = [int(crit.get("aparell_id"))]
            except Exception:
                forced_app_ids = None

        candidate_app_ids = forced_app_ids or [int(ca.id) for ca in aparells]
        tie_camps = _normalize_tie_camps(crit)
        team_vals = []
        member_vals = []

        for app_id in candidate_app_ids:
            if app_id in team_context_app_ids and equip_id is not None:
                if tie_camps:
                    selected_rows = _get_selected_team_rows_for_field(equip_id, tie_camps[0]).get(app_id, [])
                else:
                    selected_rows = _get_selected_rows_agg_for_team(equip_id).get(app_id, [])
                if selected_rows:
                    team_vals.append(
                        _apply_simple_agg([_to_float(row.get("value")) for row in selected_rows], agg_exercicis)
                    )
                continue

            if app_id in team_context_app_ids:
                continue

            for mid in mids:
                member_vals.append(
                    calc_metric_value_for_ins(
                        mid,
                        crit,
                        forced_app_ids=[app_id],
                    )
                )

        if team_vals:
            team_score = float(_apply_simple_agg(team_vals, agg_aparells))
            if not member_vals:
                return team_score
            selected_vals = _pick_participants(member_vals, part_mode, part_n)
            member_score = float(_apply_simple_agg(selected_vals, agg_parts))
            return float(_apply_simple_agg([team_score, member_score], agg_aparells))

        vals = member_vals or [calc_metric_value_for_ins(mid, crit) for mid in mids]
        selected_vals = _pick_participants(vals, part_mode, part_n)
        return float(_apply_simple_agg(selected_vals, agg_parts))

    def calc_metric_value_for_native_team(equip_id: int, crit: dict) -> float:
        try:
            equip_id = int(equip_id)
        except Exception:
            return 0.0
        if equip_id <= 0:
            return 0.0

        camps = _normalize_tie_camps(crit)
        if not camps:
            return 0.0

        scope = crit.get("scope") or {}
        if not isinstance(scope, dict):
            scope = {}
        crit_apps = scope.get("aparells") or {}
        if not isinstance(crit_apps, dict):
            crit_apps = {}
        crit_ex = scope.get("exercicis") or {}
        if not isinstance(crit_ex, dict):
            crit_ex = {}

        def _inherit(v, fallback):
            v = (v or "hereta")
            return fallback if str(v).lower().strip() == "hereta" else str(v).lower().strip()

        crit_agg_camps = _inherit(crit.get("agregacio_camps"), agg_camps)
        crit_agg_exercicis = _inherit(crit.get("agregacio_exercicis"), agg_exercicis)
        crit_agg_aparells = _inherit(crit.get("agregacio_aparells"), agg_aparells)

        crit_ex_mode = (crit_ex.get("mode") or "hereta").lower().strip()
        if crit_ex_mode == "hereta":
            crit_ex_mode = exerc_mode

        try:
            crit_best_n = int(crit_ex.get("best_n") or ex_best_n)
        except Exception:
            crit_best_n = ex_best_n
        crit_ex_index = crit_ex.get("index", ex_index)
        crit_ex_ids = crit_ex.get("ids", ex_ids)
        try:
            crit_ex_max_per_participant = int(
                crit_ex.get("max_per_participant", base_ex_cfg.get("max_per_participant", 0))
            )
        except Exception:
            crit_ex_max_per_participant = int(base_ex_cfg.get("max_per_participant", 0) or 0)
        crit_ex_max_per_participant = max(0, crit_ex_max_per_participant)

        crit_ex_cfg_global = _normalize_exercicis_cfg(
            {
                "mode": crit_ex_mode,
                "best_n": crit_best_n,
                "index": crit_ex_index,
                "ids": crit_ex_ids,
                "max_per_participant": crit_ex_max_per_participant,
            },
            fallback=base_ex_cfg,
        )

        crit_mode_sel = (
            crit.get("mode_seleccio_exercicis")
            or crit_ex.get("mode_seleccio_exercicis")
            or "hereta"
        )
        crit_mode_sel = _inherit(crit_mode_sel, mode_seleccio_exercicis)
        if crit_mode_sel not in ("per_aparell_global", "per_aparell_override", "global_pool"):
            crit_mode_sel = mode_seleccio_exercicis

        crit_ex_per_app_raw = (
            crit.get("exercicis_per_aparell")
            or crit_ex.get("exercicis_per_aparell")
            or {}
        )
        if not isinstance(crit_ex_per_app_raw, dict):
            crit_ex_per_app_raw = {}

        team_apps = [ca for ca in aparells if is_team_context_app(ca)]
        team_app_ids = [int(ca.id) for ca in team_apps]
        target_apps = []
        mode = str(crit_apps.get("mode") or "").lower().strip()
        ids = crit_apps.get("ids") or []
        if mode == "seleccionar" and ids:
            for raw_app_id in ids:
                try:
                    app_id = int(raw_app_id)
                except Exception:
                    continue
                if app_id in team_app_ids:
                    target_apps.append(app_id)
        else:
            raw_app_id = crit.get("aparell_id", None)
            if raw_app_id in (None, "", 0, "0"):
                target_apps = list(team_app_ids)
            else:
                try:
                    app_id = int(raw_app_id)
                except Exception:
                    app_id = None
                if app_id in team_app_ids:
                    target_apps = [app_id]
        if not target_apps:
            return 0.0

        def _resolve_tie_ex_cfg_for_app(app_id: int):
            if crit_mode_sel != "per_aparell_override":
                return crit_ex_cfg_global
            raw = crit_ex_per_app_raw.get(str(app_id))
            if raw is None:
                raw = crit_ex_per_app_raw.get(app_id)
            return _normalize_exercicis_cfg(raw, fallback=crit_ex_cfg_global)

        vals_apps = []
        app_vals_ex = {}
        for app_id in target_apps:
            vals_ex = []
            for nt in team_notes_by_app.get(app_id, []):
                if int(getattr(nt, "equip_id", 0) or 0) != equip_id:
                    continue
                ex_idx = int(getattr(nt, "exercici", 1) or 1)
                vals_fields = [_get_score_field(nt, c) for c in camps]
                vals_ex.append((ex_idx, _apply_simple_agg(vals_fields, crit_agg_camps)))
            app_vals_ex[app_id] = vals_ex

        if crit_mode_sel == "global_pool":
            pool_rows = []
            for app_id in target_apps:
                vals_ex = app_vals_ex.get(app_id, [])
                for ex_idx, v_ex in vals_ex:
                    pool_rows.append(
                        {
                            "idx": 0,
                            "value": _to_float(v_ex),
                            "app_id": app_id,
                            "app_order": app_order.get(app_id, 0),
                            "exercici": int(ex_idx),
                            "equip_id": equip_id,
                        }
                    )
            pool_rows = sorted(
                pool_rows,
                key=lambda r: (r.get("app_order", 0), r.get("exercici", 0), r.get("app_id", 0)),
            )
            for idx, row in enumerate(pool_rows, start=1):
                row["idx"] = idx
            picked_rows = _pick_exercicis_rows(
                pool_rows,
                crit_ex_cfg_global["mode"],
                crit_ex_cfg_global["best_n"],
                index=crit_ex_cfg_global["index"],
                ids=crit_ex_cfg_global["ids"],
                max_per_participant=crit_ex_cfg_global.get("max_per_participant", 0),
                participant_key="equip_id",
            )
            picked_by_app = defaultdict(list)
            for row in picked_rows:
                try:
                    app_id = int(row.get("app_id"))
                except Exception:
                    continue
                picked_by_app[app_id].append(_to_float(row.get("value")))

            for app_id in target_apps:
                vals_apps.append(
                    _apply_simple_agg(picked_by_app.get(app_id, []), crit_agg_exercicis)
                )
        else:
            for app_id in target_apps:
                vals_ex = app_vals_ex.get(app_id, [])
                ex_cfg_app = _resolve_tie_ex_cfg_for_app(app_id)
                picked = _pick_exercicis_tuples(
                    vals_ex,
                    ex_cfg_app["mode"],
                    ex_cfg_app["best_n"],
                    index=ex_cfg_app["index"],
                    ids=ex_cfg_app["ids"],
                    max_per_participant=ex_cfg_app.get("max_per_participant", 0),
                    participant_key="equip_id",
                )
                vals_apps.append(_apply_simple_agg(picked, crit_agg_exercicis))

        return float(_apply_simple_agg(vals_apps, crit_agg_aparells))

    def _apply_decimals_if_numeric(v, decimals):
        if decimals is None:
            return v
        try:
            dv = int(decimals)
        except Exception:
            return v
        if isinstance(v, (int, float, Decimal)):
            return round(_to_float(v), max(0, min(6, dv)))
        return v

    def _value_from_entry(entry: ScoreEntry, camp: str):
        raw = _field_value_from_entry(entry, camp)
        if raw is None:
            return ""
        num = _numeric_scalar_or_1x1(raw)
        if num is not None:
            return num
        return raw

    def _normalize_judge_item(v):
        if isinstance(v, Decimal):
            return _to_float(v)
        if isinstance(v, list):
            out = []
            for x in v:
                if isinstance(x, Decimal):
                    out.append(_to_float(x))
                else:
                    out.append(x)
            return out
        return v

    def _apply_judge_selection(raw_value, judge_ids):
        ids = []
        for x in (judge_ids or []):
            try:
                j = int(x)
            except Exception:
                continue
            if j > 0 and j not in ids:
                ids.append(j)
        if not isinstance(raw_value, list):
            return raw_value
        # Si no es selecciona jutge, mostrem totes les files de jutges.
        if not ids:
            ids = list(range(1, len(raw_value) + 1))

        picked = []
        for j in ids:
            idx = j - 1
            if 0 <= idx < len(raw_value):
                picked.append((j, raw_value[idx]))

        if not picked:
            return ""
        rows = []
        for j, v in picked:
            vv = _normalize_judge_item(v)
            if isinstance(vv, list):
                items = vv
            else:
                items = [vv]
            rows.append({"judge": j, "items": items})

        return {"_kind": "judge_rows", "rows": rows}

    def _raw_col_value_for_ins(ins_id, col):
        src = col.get("source") or {}
        app_id = src.get("aparell_id")
        ex_idx = src.get("exercici", 1)
        camp = str(src.get("camp") or "total").strip() or "total"
        try:
            app_id = int(app_id)
        except Exception:
            return ""
        try:
            ex_idx = max(1, int(ex_idx))
        except Exception:
            ex_idx = 1

        entry = notes_by_key.get((ins_id, app_id, ex_idx))
        if not entry:
            return ""
        raw = _value_from_entry(entry, camp)
        jcfg = src.get("jutges") if isinstance(src.get("jutges"), dict) else {}
        jids = jcfg.get("ids") if isinstance(jcfg.get("ids"), list) else []
        return _apply_judge_selection(raw, jids)

    def _is_scalar_team_raw_value(value):
        if value in (None, ""):
            return False
        if isinstance(value, bool):
            return True
        if isinstance(value, (int, float, Decimal)):
            return True
        return isinstance(value, str)

    def _build_team_raw_detail(rows):
        detail_rows = []
        numeric_values = []

        for item in rows or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            value = item.get("value")
            judge_rows = item.get("judge_rows")
            if not label:
                continue
            row_out = {"label": label}
            if judge_rows and isinstance(judge_rows, dict) and judge_rows.get("_kind") == "judge_rows":
                row_out["judge_rows"] = judge_rows
            else:
                row_out["value"] = value
                if _is_scalar_team_raw_value(value):
                    if not isinstance(value, bool):
                        num = _numeric_scalar_or_1x1(value)
                        if num is not None:
                            numeric_values.append(num)
            detail_rows.append(row_out)

        if not detail_rows:
            return ""

        summary = ""
        if len(detail_rows) == 1:
            only = detail_rows[0]
            if "judge_rows" not in only:
                summary = only.get("value", "")
        elif numeric_values and len(numeric_values) == len(detail_rows):
            summary = float(sum(numeric_values))

        return {"_kind": "team_raw_detail", "summary": summary, "rows": detail_rows}

    def _merge_judge_rows_payloads(payloads):
        merged = {}
        order = []
        for payload in payloads or []:
            if not isinstance(payload, dict) or payload.get("_kind") != "judge_rows":
                continue
            for row in payload.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                judge = row.get("judge")
                key = str(judge)
                if key not in merged:
                    merged[key] = {"judge": judge, "items": []}
                    order.append(key)
                items = row.get("items") or []
                if not isinstance(items, list):
                    items = [items]
                merged[key]["items"].extend(items)
        out_rows = [merged[key] for key in order if merged[key]["items"]]
        if not out_rows:
            return ""
        return {"_kind": "judge_rows", "rows": out_rows}

    def _aggregate_selected_raw_values(raw_values):
        values = [v for v in (raw_values or []) if v not in (None, "")]
        if not values:
            return ""

        judge_payloads = [
            v for v in values
            if isinstance(v, dict) and v.get("_kind") == "judge_rows"
        ]
        if judge_payloads:
            if len(judge_payloads) != len(values):
                return ""
            return _merge_judge_rows_payloads(judge_payloads)

        if len(values) == 1:
            return values[0]

        numeric_values = []
        for value in values:
            if isinstance(value, bool):
                return ""
            num = _numeric_scalar_or_1x1(value)
            if num is None:
                return ""
            numeric_values.append(num)
        return float(sum(numeric_values))

    def _raw_value_for_selected_member_row(row, field_code: str, judge_ids):
        try:
            member_id = int(row.get("inscripcio_id"))
            app_id = int(row.get("app_id"))
            ex_idx = int(row.get("exercici"))
        except Exception:
            return ""
        entry = notes_by_key.get((member_id, app_id, ex_idx))
        if not entry:
            return ""
        raw = _value_from_entry(entry, field_code)
        return _apply_judge_selection(raw, judge_ids)

    def _raw_value_for_selected_team_row(row, field_code: str, judge_ids):
        try:
            equip_id = int(row.get("equip_id"))
            app_id = int(row.get("app_id"))
            ex_idx = int(row.get("exercici"))
        except Exception:
            return ""
        entry = team_notes_by_key.get((equip_id, app_id, ex_idx))
        if not entry:
            return ""
        raw = _value_from_entry(entry, field_code)
        return _apply_judge_selection(raw, judge_ids)

    def _team_member_raw_value(raw_value, member_id):
        if not isinstance(raw_value, dict):
            return ""
        return raw_value.get(str(int(member_id)), "")

    def _ordered_member_ids_for_team_entry(entry, fallback_member_ids):
        fallback_ids = _dedupe_int_ids_preserve_order(fallback_member_ids or [])
        subject = getattr(entry, "team_subject", None)
        subject_ids = _dedupe_int_ids_preserve_order(getattr(subject, "member_ids", []) or [])
        raw_subject_ids = [
            _normalize_positive_int(raw_id)
            for raw_id in (getattr(subject, "member_ids", []) or [])
        ] if subject is not None else []
        subject_ids_consistent = bool(subject_ids) and len(subject_ids) == len([value for value in raw_subject_ids if value is not None])
        if fallback_ids and (not subject_ids_consistent or any(member_id not in subject_ids for member_id in fallback_ids)):
            return fallback_ids
        if subject_ids_consistent:
            return subject_ids
        return fallback_ids

    def _team_member_slot_for_entry(entry, member_id, fallback_member_ids):
        member_pk = _normalize_positive_int(member_id)
        if member_pk is None:
            return None
        ordered_member_ids = _ordered_member_ids_for_team_entry(entry, fallback_member_ids)
        try:
            return ordered_member_ids.index(member_pk) + 1
        except ValueError:
            return None

    def _member_raw_value_from_container(container, field_code, member_id):
        if not isinstance(container, dict):
            return None
        member_raw = _team_member_raw_value(container.get(str(field_code or "").strip()), member_id)
        if member_raw in (None, ""):
            return None
        return member_raw

    def _raw_value_for_team_member_entry(entry, field_code: str, judge_ids, member_id, fallback_member_ids):
        member_pk = _normalize_positive_int(member_id)
        if entry is None or member_pk is None:
            return ""

        field_code = str(field_code or "").strip()
        inputs = entry.inputs if isinstance(entry.inputs, dict) else {}
        outputs = entry.outputs if isinstance(entry.outputs, dict) else {}

        member_raw = _member_raw_value_from_container(inputs, field_code, member_pk)
        if member_raw is None:
            member_raw = _member_raw_value_from_container(outputs, field_code, member_pk)

        slot = _team_member_slot_for_entry(entry, member_pk, fallback_member_ids)
        if member_raw is None and slot is not None:
            runtime_code = member_runtime_code(field_code, slot)
            if runtime_code in outputs and outputs.get(runtime_code) not in (None, ""):
                member_raw = outputs.get(runtime_code)
            elif runtime_code in inputs and inputs.get(runtime_code) not in (None, ""):
                member_raw = inputs.get(runtime_code)

        if member_raw in (None, ""):
            return ""
        return _apply_judge_selection(member_raw, judge_ids)

    def _raw_col_value_for_team_row(row, col):
        team_mode_value = str(row.get("_team_mode") or "").strip().lower()
        equip_id = row.get("equip_id")
        member_ids = row.get("_member_ids") or []
        src = col.get("source") or {}
        camp = str(src.get("camp") or "total").strip() or "total"
        jcfg = src.get("jutges") if isinstance(src.get("jutges"), dict) else {}
        jids = jcfg.get("ids") if isinstance(jcfg.get("ids"), list) else []
        try:
            app_id = int(src.get("aparell_id"))
        except Exception:
            return ""
        if team_mode_value == "native_team":
            if equip_id in (None, "", "__sense_equip__"):
                return ""
            ca = next((item for item in aparells if int(item.id) == app_id), None)
            if not ca or not is_team_context_app(ca):
                return ""
            selected_rows = _get_main_selected_team_rows_for_field(int(equip_id), camp).get(app_id, [])
            raw_value = _aggregate_selected_raw_values([
                _raw_value_for_selected_team_row(selected_row, camp, jids)
                for selected_row in selected_rows
            ])
            if raw_value in (None, ""):
                return ""
            if isinstance(raw_value, dict) and raw_value.get("_kind") == "judge_rows":
                return _build_team_raw_detail([
                    {"label": row.get("participant") or row.get("nom") or "Equip", "judge_rows": raw_value}
                ])
            return _build_team_raw_detail([
                {"label": row.get("participant") or row.get("nom") or "Equip", "value": raw_value}
            ])

        team_cache_key = _derived_team_cache_key(equip_id, member_ids)
        selected_rows_by_app = _get_main_selected_rows_for_group_field(team_cache_key, member_ids, camp)
        selected_rows = selected_rows_by_app.get(app_id, [])
        rows_by_member = defaultdict(list)
        for selected_row in selected_rows:
            try:
                member_id = int(selected_row.get("inscripcio_id"))
            except Exception:
                continue
            rows_by_member[member_id].append(selected_row)

        detail_rows = []
        for member_id in member_ids:
            member = all_ins_by_id.get(member_id)
            if member is None:
                continue
            label = (
                getattr(member, "nom_complet", None)
                or getattr(member, "nom_i_cognoms", None)
                or getattr(member, "nom", None)
                or str(member)
            )
            raw_value = _aggregate_selected_raw_values([
                _raw_value_for_selected_member_row(selected_row, camp, jids)
                for selected_row in rows_by_member.get(member_id, [])
            ])
            if raw_value in (None, ""):
                continue
            if isinstance(raw_value, dict) and raw_value.get("_kind") == "judge_rows":
                detail_rows.append({"label": label, "judge_rows": raw_value})
            else:
                detail_rows.append({"label": label, "value": raw_value})
        return _build_team_raw_detail(detail_rows)

    def _builtin_col_value(row: dict, key: str):
        if key == "nom":
            key = "participant"
        if key == "participant":
            return row.get("participant") or row.get("nom") or row.get("entitat_nom") or ""
        if key == "punts":
            return row.get("punts", 0.0)
        if key == "posicio":
            return row.get("posicio")
        if key == "entitat_nom":
            return row.get("entitat_nom") or ""
        if key == "participants":
            return row.get("participants", 0)
        return row.get(key)

    def _detail_builtin_value_for_member(member, key: str):
        if key == "participant":
            return (
                getattr(member, "nom_complet", None)
                or getattr(member, "nom_i_cognoms", None)
                or getattr(member, "nom", None)
                or str(member)
            )
        if key == "entitat_nom":
            return _display_value(member, "entitat")
        return ""

    def _detail_builtin_value_for_row(row, key: str):
        if key == "participant":
            return row.get("participant") or row.get("nom") or row.get("entitat_nom") or ""
        if key == "entitat_nom":
            return row.get("entitat_nom") or ""
        return row.get(key) or ""

    def _detail_builtin_value_for_exercise_row(row, key: str):
        if key == "exercise_index":
            return row.get("exercise_index")
        if key == "aparell_nom":
            return row.get("aparell_nom") or ""
        if key == "participant":
            return row.get("participant") or ""
        if key == "entitat_nom":
            return row.get("entitat_nom") or ""
        return row.get(key) or ""

    def _detail_type_for_row(row: dict):
        team_mode_row = str(row.get("_team_mode") or "").strip().lower()
        if team_mode_row == "derived_from_individual":
            return "derived_team"
        if team_mode_row == "native_team":
            return "native_team"
        if _normalize_positive_int(row.get("inscripcio_id")) is not None:
            return "individual"
        if "entitat_nom" in row and (row.get("_member_ids") or []):
            return "entity"
        return ""

    def _comp_aparell_label(app_id):
        try:
            app_id = int(app_id)
        except Exception:
            return ""
        ca = next((item for item in aparells if int(getattr(item, "id", 0) or 0) == app_id), None)
        if ca is None:
            return ""
        return getattr(getattr(ca, "aparell", None), "nom", None) or str(ca)

    def _comp_aparell_exercise_count(app_id):
        try:
            app_id = int(app_id)
        except Exception:
            return 1
        ca = next((item for item in aparells if int(getattr(item, "id", 0) or 0) == app_id), None)
        if ca is None:
            return 1
        try:
            return max(1, int(getattr(ca, "nombre_exercicis", 1) or 1))
        except Exception:
            return 1

    def _detail_row_id(row: dict):
        if row.get("_team_mode"):
            equip_marker = row.get("equip_id")
            if equip_marker in (None, ""):
                equip_marker = "none"
            member_part = "-".join(str(int(x)) for x in (row.get("_member_ids") or []) if _normalize_positive_int(x))
            return f"team:{equip_marker}:{member_part}"
        if "entitat_nom" in row and (row.get("_member_ids") or []):
            member_part = "-".join(str(int(x)) for x in (row.get("_member_ids") or []) if _normalize_positive_int(x))
            ent_part = _normalized_text_token(row.get("entitat_nom") or "sense-entitat") or "sense-entitat"
            return f"entity:{ent_part}:{member_part}"
        ins_id = _normalize_positive_int(row.get("inscripcio_id"))
        return f"row:{ins_id}" if ins_id is not None else ""

    def _build_members_list_section(row: dict, section: dict):
        items = []
        seen = set()
        ordered_member_ids = sorted(
            (row.get("_member_ids") or []),
            key=lambda raw_member_id: (
                getattr(all_ins_by_id.get(_normalize_positive_int(raw_member_id) or -1), "ordre_competicio", None)
                or getattr(all_ins_by_id.get(_normalize_positive_int(raw_member_id) or -1), "ordre_sortida", None)
                or 10**9,
                _normalize_positive_int(raw_member_id) or 10**9,
            ),
        )
        for member_id in ordered_member_ids:
            member_pk = _normalize_positive_int(member_id)
            if member_pk is None or member_pk in seen:
                continue
            seen.add(member_pk)
            member = all_ins_by_id.get(member_pk)
            if member is None:
                continue
            items.append(
                {
                    "member_id": member_pk,
                    "participant": _detail_builtin_value_for_member(member, "participant"),
                    "entitat_nom": _detail_builtin_value_for_member(member, "entitat_nom"),
                }
            )
        if not items:
            return None
        return {
            "type": "members_list",
            "label": str(section.get("label") or "Participants"),
            "items": items,
        }

    def _build_members_table_section(row: dict, section: dict):
        detail_rows = []
        detail_columns = section.get("columns") or []
        ordered_member_ids = sorted(
            (row.get("_member_ids") or []),
            key=lambda raw_member_id: (
                getattr(all_ins_by_id.get(_normalize_positive_int(raw_member_id) or -1), "ordre_competicio", None)
                or getattr(all_ins_by_id.get(_normalize_positive_int(raw_member_id) or -1), "ordre_sortida", None)
                or 10**9,
                _normalize_positive_int(raw_member_id) or 10**9,
            ),
        )
        for member_id in ordered_member_ids:
            member_pk = _normalize_positive_int(member_id)
            if member_pk is None:
                continue
            member = all_ins_by_id.get(member_pk)
            if member is None:
                continue

            cells = {}
            for col in detail_columns:
                ctype = str(col.get("type") or "builtin").strip().lower()
                ckey = str(col.get("key") or "").strip()
                if not ckey:
                    continue
                if ctype == "raw":
                    val = _raw_col_value_for_ins(member_pk, col)
                    if not (isinstance(val, dict) and val.get("_kind") == "judge_rows"):
                        val = _apply_decimals_if_numeric(val, col.get("decimals"))
                else:
                    val = _detail_builtin_value_for_member(member, ckey)
                    val = _apply_decimals_if_numeric(val, col.get("decimals"))
                cells[ckey] = val

            detail_rows.append(
                {
                    "member_id": member_pk,
                    "participant": _detail_builtin_value_for_member(member, "participant"),
                    "entitat_nom": _detail_builtin_value_for_member(member, "entitat_nom"),
                    "cells": cells,
                    "display": cells,
                }
            )

        if not detail_rows:
            return None
        return {
            "type": str(section.get("type") or "members_table"),
            "label": str(section.get("label") or "Detall"),
            "aparell_id": _normalize_positive_int(section.get("aparell_id")),
            "columns": _json_clone_value(detail_columns),
            "rows": detail_rows,
        }

    def _build_team_metrics_section(row: dict, section: dict):
        detail_columns = section.get("columns") or []
        cells = {}
        for col in detail_columns:
            ctype = str(col.get("type") or "builtin").strip().lower()
            ckey = str(col.get("key") or "").strip()
            if not ckey:
                continue
            if ctype == "raw":
                val = _raw_col_value_for_team_row(row, col)
                if not (isinstance(val, dict) and val.get("_kind") == "team_raw_detail"):
                    val = _apply_decimals_if_numeric(val, col.get("decimals"))
            else:
                val = _detail_builtin_value_for_row(row, ckey)
                val = _apply_decimals_if_numeric(val, col.get("decimals"))
            cells[ckey] = val
        if not cells:
            return None
        return {
            "type": "team_metrics",
            "label": str(section.get("label") or "Notes equip"),
            "aparell_id": _normalize_positive_int(section.get("aparell_id")),
            "columns": _json_clone_value(detail_columns),
            "rows": [
                {
                    "participant": _detail_builtin_value_for_row(row, "participant"),
                    "entitat_nom": _detail_builtin_value_for_row(row, "entitat_nom"),
                    "cells": cells,
                    "display": cells,
                }
            ],
        }

    def _build_native_team_members_table_section(row: dict, section: dict):
        equip_id = _normalize_positive_int(row.get("equip_id"))
        member_ids = row.get("_member_ids") or []
        if equip_id is None or not member_ids:
            return None

        detail_columns = section.get("columns") or []
        detail_rows = []
        team_entries_cache = {}

        def team_entries_for(app_id, exercici):
            cache_key = (int(app_id), _normalize_positive_int(exercici) or 0)
            if cache_key in team_entries_cache:
                return team_entries_cache[cache_key]

            if _normalize_positive_int(exercici) is not None:
                entry = team_notes_by_key.get((equip_id, int(app_id), int(exercici)))
                team_entries_cache[cache_key] = [entry] if entry is not None else []
                return team_entries_cache[cache_key]

            entries = []
            seen = set()
            for selected_row in _get_main_selected_rows_agg_for_team(equip_id).get(int(app_id), []):
                try:
                    selected_equip_id = int(selected_row.get("equip_id"))
                    selected_app_id = int(selected_row.get("app_id"))
                    selected_ex_idx = int(selected_row.get("exercici"))
                except Exception:
                    continue
                entry_key = (selected_equip_id, selected_app_id, selected_ex_idx)
                if entry_key in seen:
                    continue
                seen.add(entry_key)
                entry = team_notes_by_key.get(entry_key)
                if entry is not None:
                    entries.append(entry)
            team_entries_cache[cache_key] = entries
            return team_entries_cache[cache_key]

        for member_id in member_ids:
            member_pk = _normalize_positive_int(member_id)
            if member_pk is None:
                continue
            member = all_ins_by_id.get(member_pk)
            if member is None:
                continue

            cells = {}
            for col in detail_columns:
                ctype = str(col.get("type") or "builtin").strip().lower()
                ckey = str(col.get("key") or "").strip()
                if not ckey:
                    continue
                if ctype == "raw":
                    src = col.get("source") if isinstance(col.get("source"), dict) else {}
                    app_id = _normalize_positive_int(src.get("aparell_id"))
                    exercise_mode = str(src.get("exercise_mode") or "").strip().lower()
                    exercici = _normalize_positive_int(src.get("exercici")) if exercise_mode == "fixed" else None
                    camp = str(src.get("camp") or "").strip()
                    jcfg = src.get("jutges") if isinstance(src.get("jutges"), dict) else {}
                    jids = jcfg.get("ids") if isinstance(jcfg.get("ids"), list) else []
                    if app_id is None or not camp:
                        val = ""
                    else:
                        val = _aggregate_selected_raw_values([
                            _raw_value_for_team_member_entry(entry, camp, jids, member_pk, member_ids)
                            for entry in team_entries_for(app_id, exercici)
                        ])
                    if not (isinstance(val, dict) and val.get("_kind") == "judge_rows"):
                        val = _apply_decimals_if_numeric(val, col.get("decimals"))
                else:
                    val = _detail_builtin_value_for_member(member, ckey)
                    val = _apply_decimals_if_numeric(val, col.get("decimals"))
                cells[ckey] = val

            detail_rows.append(
                {
                    "member_id": member_pk,
                    "participant": _detail_builtin_value_for_member(member, "participant"),
                    "entitat_nom": _detail_builtin_value_for_member(member, "entitat_nom"),
                    "cells": cells,
                    "display": cells,
                }
            )

        if not detail_rows:
            return None
        return {
            "type": "team_members_table",
            "label": str(section.get("label") or "Notes per membre"),
            "aparell_id": _normalize_positive_int(section.get("aparell_id")),
            "columns": _json_clone_value(detail_columns),
            "rows": detail_rows,
        }

    def _build_exercise_table_section(row: dict, section: dict):
        ins_id = _normalize_positive_int(row.get("inscripcio_id"))
        if ins_id is None:
            return None
        detail_columns = section.get("columns") or []
        section_app_id = _normalize_positive_int(section.get("aparell_id"))
        row_defs = []
        seen_defs = set()
        for col in detail_columns:
            if str(col.get("type") or "").strip().lower() != "raw":
                continue
            src = col.get("source") if isinstance(col.get("source"), dict) else {}
            app_id = _normalize_positive_int(src.get("aparell_id"))
            ex_idx = _normalize_positive_int(src.get("exercici")) or 1
            if app_id is None:
                continue
            key = (app_id, ex_idx)
            if key in seen_defs:
                continue
            seen_defs.add(key)
            row_defs.append(key)
        if not row_defs and section_app_id is not None:
            for ex_idx in range(1, _comp_aparell_exercise_count(section_app_id) + 1):
                row_defs.append((section_app_id, ex_idx))
        if not row_defs:
            return None

        rows_out = []
        for app_id, ex_idx in row_defs:
            cells = {}
            for col in detail_columns:
                ctype = str(col.get("type") or "builtin").strip().lower()
                ckey = str(col.get("key") or "").strip()
                if not ckey:
                    continue
                if ctype == "raw":
                    src = col.get("source") if isinstance(col.get("source"), dict) else {}
                    if _normalize_positive_int(src.get("aparell_id")) != app_id:
                        cells[ckey] = ""
                        continue
                    if (_normalize_positive_int(src.get("exercici")) or 1) != ex_idx:
                        cells[ckey] = ""
                        continue
                    val = _raw_col_value_for_ins(ins_id, col)
                    if not (isinstance(val, dict) and val.get("_kind") == "judge_rows"):
                        val = _apply_decimals_if_numeric(val, col.get("decimals"))
                else:
                    val = _detail_builtin_value_for_exercise_row(
                        {
                            "exercise_index": ex_idx,
                            "aparell_nom": _comp_aparell_label(app_id),
                            "participant": _detail_builtin_value_for_row(row, "participant"),
                            "entitat_nom": _detail_builtin_value_for_row(row, "entitat_nom"),
                        },
                        ckey,
                    )
                    val = _apply_decimals_if_numeric(val, col.get("decimals"))
                cells[ckey] = val
            rows_out.append(
                {
                    "app_id": app_id,
                    "exercise_index": ex_idx,
                    "aparell_nom": _comp_aparell_label(app_id),
                    "participant": _detail_builtin_value_for_row(row, "participant"),
                    "entitat_nom": _detail_builtin_value_for_row(row, "entitat_nom"),
                    "cells": cells,
                    "display": cells,
                }
            )
        if not rows_out:
            return None
        return {
            "type": "exercise_table",
            "label": str(section.get("label") or "Exercicis"),
            "aparell_id": section_app_id,
            "columns": _json_clone_value(detail_columns),
            "rows": rows_out,
        }

    def _build_detail_payload(row: dict):
        if not detail_enabled:
            return None
        sections = []
        detail_type = _detail_type_for_row(row)
        for section in detail_config.get("sections") or []:
            stype = str(section.get("type") or "").strip().lower()
            section_payload = None
            if stype == "members_list" and detail_type in ("derived_team", "native_team"):
                section_payload = _build_members_list_section(row, section)
            elif stype == "members_table" and detail_type == "derived_team":
                section_payload = _build_members_table_section(row, section)
            elif stype == "team_members_table" and detail_type == "native_team":
                section_payload = _build_native_team_members_table_section(row, section)
            elif stype == "entity_members_table" and detail_type == "entity":
                section_payload = _build_members_table_section(row, section)
            elif stype == "team_metrics" and detail_type == "native_team":
                section_payload = _build_team_metrics_section(row, section)
            elif stype == "exercise_table" and detail_type == "individual":
                section_payload = _build_exercise_table_section(row, section)
            if section_payload is not None:
                sections.append(section_payload)
        if not sections:
            return None
        return {
            "default_open": bool(detail_config.get("default_open", False)),
            "sections": sections,
        }

    def _attach_display_cells(rows, entity_mode=False):
        for row in rows:
            cells = {}
            member_ids = row.get("_member_ids") or []
            for col in display_columns:
                ctype = col.get("type")
                ckey = col.get("key")
                if not ckey:
                    continue

                if ctype == "raw":
                    if entity_mode:
                        if row.get("_team_mode"):
                            val = _raw_col_value_for_team_row(row, col)
                        elif len(member_ids) == 1:
                            val = _raw_col_value_for_ins(member_ids[0], col)
                        else:
                            val = ""
                    else:
                        val = _raw_col_value_for_ins(row.get("inscripcio_id"), col)
                    if not (isinstance(val, dict) and val.get("_kind") == "team_raw_detail"):
                        val = _apply_decimals_if_numeric(val, col.get("decimals"))
                else:
                    val = _builtin_col_value(row, ckey)
                    val = _apply_decimals_if_numeric(val, col.get("decimals"))

                cells[ckey] = val

            row["cells"] = cells
            row["display"] = cells
            row["row_id"] = _detail_row_id(row)
            detail_payload = _build_detail_payload(row)
            if detail_payload is not None:
                row["detail"] = detail_payload
            else:
                row.pop("detail", None)
            row.pop("_member_ids", None)
            row.pop("_team_mode", None)
        return rows

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
            # extra útil pel front (si vols mostrar detalls)
            "by_app": dict(per_ins[ins.id]["by_app"]),
            "by_app_base": dict(per_ins[ins.id]["by_app_base"]),
        }
        per_particio[pkey].append(row)

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
                    metric_value_getter=calc_metric_value_for_ins,
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
                            base_val = _apply_simple_agg(
                                [_to_float(item.get("value")) for item in selected_rows],
                                agg_exercicis,
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

    resolved_team_by_ins_id = {}
    if tipus == "equips" and team_mode != "native_team":
        for ins in ins_list:
            resolved_team_by_ins_id[int(ins.id)] = _resolve_inscripcio_equip_for_classificacio(
                ins,
                context_code=team_context_code,
                fallback=assignment_source.get("fallback"),
                assignment_map=team_assignment_map,
            )

    if tipus == "equips":
        use_native_team_mode = team_mode == "native_team"
        include_sense_equip = bool(equips_cfg.get("incloure_sense_equip", False)) if not use_native_team_mode else False
        manual_defs = (equips_cfg.get("particions_manuals") or []) if not use_native_team_mode else []
        age_cfg = (equips_cfg.get("particio_edat") or {}) if not use_native_team_mode else {}
        age_active = bool(age_cfg.get("activa", False)) if not use_native_team_mode else False
        age_label_empty = (age_cfg.get("sense_data_label") or "Sense edat").strip() or "Sense edat"
        combine_manual_age = bool(equips_cfg.get("combinar_manual_i_edat", False)) if not use_native_team_mode else False

        llindars = []
        for x in (age_cfg.get("llindars") or []):
            try:
                llindars.append(int(x))
            except Exception:
                continue

        manual_map = {}
        for idx, it in enumerate(manual_defs):
            if not isinstance(it, dict):
                continue
            label = (
                str(it.get("label") or it.get("key") or f"Particio {idx + 1}").strip()
                or f"Particio {idx + 1}"
            )
            team_key = f"manual:{label}"
            for raw_id in (it.get("equip_ids") or []):
                try:
                    eid = int(raw_id)
                except Exception:
                    continue
                # primera assignacio guanya (evitem comportament no determinista)
                if eid not in manual_map:
                    manual_map[eid] = team_key

        has_team_birth_partition = any(
            str((entry or {}).get("code") or "").strip() == BIRTH_YEAR_RANGE_PARTITION_CODE
            for entry in (part_entries or [])
        )
        grouped = defaultdict(lambda: defaultdict(list))  # base_pkey -> equip_id_key -> [ins]
        if use_native_team_mode:
            for app_id, rows in team_notes_by_app.items():
                if app_id not in {int(ca.id) for ca in aparells if is_team_context_app(ca)}:
                    continue
                for row in rows:
                    subject = getattr(row, "team_subject", None)
                    equip = getattr(subject, "equip", None)
                    if subject is None or equip is None:
                        continue
                    member_rows = []
                    missing_members = False
                    for member_id in _dedupe_int_ids_preserve_order(
                        getattr(subject, "member_ids", []) or []
                    ):
                        member = all_ins_by_id.get(member_id)
                        if member is None:
                            missing_members = True
                            break
                        member_rows.append((member, equip))
                    if missing_members or not _native_team_members_match_classificacio_filters(member_rows, filtres):
                        continue
                    base_bucket = "__team_partition__" if has_team_birth_partition else "global"
                    grouped[base_bucket].setdefault(int(equip.id), member_rows)
        else:
            for ins in ins_list:
                resolved_equip = resolved_team_by_ins_id.get(int(ins.id))
                if resolved_equip is None and not include_sense_equip:
                    continue
                if has_team_birth_partition:
                    base_pkey = "__team_partition__"
                else:
                    base_pkey = _partition_key_from_entries(
                        ins,
                        part_entries,
                        part_custom_idx,
                        particions_config=particions_config,
                    )
                team_id_key = resolved_equip.id if resolved_equip is not None else "__sense_equip__"
                grouped[base_pkey][team_id_key].append((ins, resolved_equip))

        for base_pkey, teams in grouped.items():
            for team_id_key, members in teams.items():
                if not members:
                    continue
                members = sorted(
                    members,
                    key=lambda item: (
                        int(getattr(item[0], "ordre_competicio", 10**9) or 10**9),
                        int(getattr(item[0], "id", 10**9) or 10**9),
                    ),
                )

                # nom equip
                if team_id_key == "__sense_equip__":
                    equip_id = None
                    equip_nom = "Sense equip"
                else:
                    equip_id = int(team_id_key)
                    eq_obj = members[0][1]
                    equip_nom = (getattr(eq_obj, "nom", None) or f"Equip {equip_id}").strip()

                if has_team_birth_partition:
                    base_partition_key = _partition_key_from_entries_for_team(
                        members,
                        part_entries,
                        part_custom_idx,
                        particions_config=particions_config,
                    )
                else:
                    base_partition_key = base_pkey

                # particio manual / compat legacy
                if use_native_team_mode:
                    final_pkey = base_partition_key
                else:
                    manual_part = manual_map.get(equip_id) if equip_id is not None else None
                    age_part = None
                    if age_active and not has_team_birth_partition:
                        ref_date = getattr(competicio, "data", None) or timezone.localdate()
                        ages = []
                        for m, _resolved_equip in members:
                            age = _years_old(getattr(m, "data_naixement", None), ref_date)
                            if age is not None:
                                ages.append(age)
                        age_max = max(ages) if ages else None
                        age_part = _bucket_edat(age_max, llindars, age_label_empty)

                    team_part = _resolve_particio_equip(manual_part, age_part, combine_manual_age)
                    if base_partition_key != "global" and team_part != "global":
                        final_pkey = f"{base_partition_key}|{team_part}"
                    elif team_part != "global":
                        final_pkey = team_part
                    else:
                        final_pkey = base_partition_key

                member_ids = [m.id for m, _resolved_equip in members]
                derived_team_cache_key = _derived_team_cache_key(equip_id, member_ids)
                team_by_app = {}
                for ca in aparells:
                    app_id = ca.id
                    if is_team_context_app(ca):
                        if equip_id is None:
                            continue
                        selected_rows = _get_main_selected_rows_agg_for_team(int(equip_id)).get(app_id, [])
                        if not selected_rows:
                            continue
                        team_by_app[app_id] = float(
                            _apply_simple_agg(
                                [_to_float(row.get("value")) for row in selected_rows],
                                agg_exercicis,
                            )
                        )
                        continue

                    if use_native_team_mode:
                        continue

                    if exercise_selection_scope == EXERCISE_SELECTION_SCOPE_TEAM_POOL:
                        selected_rows = _get_selected_rows_agg_for_derived_team(
                            derived_team_cache_key,
                            member_ids,
                        ).get(app_id, [])
                        if selected_rows:
                            team_by_app[app_id] = float(
                                _apply_simple_agg(
                                    [_to_float(row.get("value")) for row in selected_rows],
                                    agg_exercicis,
                                )
                            )
                        continue

                    app_total = 0.0
                    found_any = False
                    for m, _resolved_equip in members:
                        by_app_base = per_ins.get(m.id, {}).get("by_app_base") or {}
                        if app_id not in by_app_base:
                            continue
                        found_any = True
                        app_total += _to_float(by_app_base.get(app_id))
                    if found_any:
                        team_by_app[app_id] = float(app_total)

                team_score = float(_apply_simple_agg(list(team_by_app.values()), agg_aparells))

                team_tie = {}
                for t in desempat or []:
                    tkey = _tie_key(t)
                    if not tkey:
                        continue
                    if use_native_team_mode and equip_id is not None:
                        team_tie[tkey] = calc_metric_value_for_native_team(int(equip_id), t)
                    else:
                        team_tie[tkey] = calc_metric_value_for_group(member_ids, t)

                out.setdefault(final_pkey, []).append({
                    "equip_id": equip_id,
                    "nom": equip_nom,
                    "participant": equip_nom,
                    "score": float(team_score),
                    "tie": team_tie,
                    "participants": len(members),
                    "_member_ids": member_ids,
                    "_team_mode": team_mode,
                })

        for pkey, rows in out.items():
            ranked = _rank_v2(rows, desempat, presentacio, ordre_principal=ordre_principal, entity_mode=True)
            out[pkey] = _attach_display_cells(ranked, entity_mode=True)
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
                    ent_tie[tkey] = sum([_to_float((x.get("tie") or {}).get(tkey, 0.0)) for x in items])

                ent_rows.append({
                    "entitat_nom": ent_nom,
                    "score": float(ent_score),
                    "tie": ent_tie,
                    "participants": len(items),
                    "_member_ids": [x.get("inscripcio_id") for x in items if x.get("inscripcio_id") is not None],
                })

            ranked = _rank_v2(ent_rows, desempat, presentacio, ordre_principal=ordre_principal, entity_mode=True)
            out[pkey] = _attach_display_cells(ranked, entity_mode=True)
        return out

    for pkey, rows in per_particio.items():
        ranked = _rank_v2(rows, desempat, presentacio, ordre_principal=ordre_principal, entity_mode=False)
        out[pkey] = _attach_display_cells(ranked, entity_mode=False)
    return out



def _get_score_field(entry: ScoreEntry, code: str) -> float:
    raw = _field_value_from_entry(entry, code)
    if raw is None:
        return 0.0

    num = _numeric_scalar_or_1x1(raw)
    if num is not None:
        return num

    logger.warning(
        "Classificacio: camp no puntuable (escalar o 1x1). "
        "entry_id=%s inscripcio_id=%s comp_aparell_id=%s camp=%s tipus=%s",
        getattr(entry, "id", None),
        getattr(entry, "inscripcio_id", None),
        getattr(entry, "comp_aparell_id", None),
        (code or "").strip(),
        type(raw).__name__,
    )
    return 0.0


def _rank_v2(rows, desempat, presentacio, ordre_principal="desc", entity_mode=False):
    """
    Igual que el teu _rank actual, però:
      - ordre principal configurable (asc/desc)
      - claus tie poden ser "camp" (legacy) o "camp@app_id"
    """
    # ordenació principal: score (asc/desc)
    sort_keys = [("score", ordre_principal)]

    for t in desempat or []:
        key = _tie_key(t)
        if not key:
            continue
        ordre = (t.get("ordre") or "desc").lower().strip()
        sort_keys.append((key, ordre))
        
    def keyfunc(r):
        k = []
        for field, ordre in sort_keys:
            if field == "score":
                val = _to_float(r.get("score", 0.0))
            else:
                val = _to_float((r.get("tie") or {}).get(field, 0.0))
            # sorted asc: invertim si volem desc
            k.append(-val if ordre == "desc" else val)
        return tuple(k)

    rows_sorted = sorted(rows, key=keyfunc)

    mostrar_empats = bool((presentacio or {}).get("mostrar_empats", True))
    top_n = int((presentacio or {}).get("top_n") or 0)

    ranked = []
    last_key = None
    pos = 0
    shown = 0

    for idx, r in enumerate(rows_sorted, start=1):
        cur_key = keyfunc(r)
        if last_key is None or cur_key != last_key:
            pos = idx
        last_key = cur_key

        row_out = dict(r)
        row_out["posicio"] = pos
        row_out["punts"] = round(_to_float(r.get("score", 0.0)), 3)

        ranked.append(row_out)
        shown += 1

        if top_n and shown >= top_n:
            if mostrar_empats and idx < len(rows_sorted):
                if keyfunc(rows_sorted[idx]) == cur_key:
                    continue
            break

    return ranked



