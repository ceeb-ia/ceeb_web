import json

from ..shared.birth_year_ranges import (
    BIRTH_YEAR_RANGE_PARTITION_CODE,
    DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG,
    legacy_team_age_partition_to_birth_year_range_config,
    normalize_birth_year_range_partition_config,
)
from ._filters_impl import (
    DEFAULT_EQUIPS_CFG,
    competition_reference_date,
    normalize_classificacio_equips_cfg,
    normalize_classificacio_filters,
)


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
    "puntuacio": {
        "camp": "total",
        "agregacio": "sum",
        "best_n": 1,
        "exercicis": {"mode": "tots", "index": 1, "ids": [], "max_per_participant": 0},
        "exercicis_best_n": 1,
        "mode_seleccio_exercicis": "per_aparell_global",
        "exercicis_per_aparell": {},
        "aparells": {"mode": "tots", "ids": []},
        "camps_per_aparell": {},
        "agregacio_camps_per_aparell": {},
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
        "agregacio_exercicis": "sum",
        "agregacio_aparells": "sum",
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
        "ordre": "desc",
    },
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
    "equips": DEFAULT_EQUIPS_CFG,
}


def _json_clone_value(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except Exception:
        return value


def normalize_particions_config(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    return {
        BIRTH_YEAR_RANGE_PARTITION_CODE: normalize_birth_year_range_partition_config(
            cfg.get(BIRTH_YEAR_RANGE_PARTITION_CODE)
        ),
    }


def _normalize_partition_token(value: str) -> str:
    txt = str(value or "")
    txt = " ".join(txt.split()).strip()
    return txt.casefold()


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


def _merge_schema(schema: dict) -> dict:
    raw = schema if isinstance(schema, dict) else {}
    out = {**DEFAULT_SCHEMA}
    raw_parts = raw.get("particions", DEFAULT_SCHEMA["particions"]) or []
    raw_parts_v2 = raw.get("particions_v2", DEFAULT_SCHEMA["particions_v2"]) or []
    part_entries = normalize_particions_v2_entries(raw_parts_v2, fallback_codes=raw_parts)
    out["particions_v2"] = part_entries
    out["particions"] = particio_codes_from_entries(part_entries)
    raw_custom = raw.get("particions_custom", DEFAULT_SCHEMA["particions_custom"]) or {}
    out["particions_custom"] = raw_custom if isinstance(raw_custom, dict) else {}
    out["particions_config"] = normalize_particions_config(
        raw.get("particions_config", DEFAULT_SCHEMA["particions_config"]) or {}
    )
    out["filtres"] = normalize_classificacio_filters(raw.get("filtres") or {})
    out["puntuacio"] = {**DEFAULT_SCHEMA["puntuacio"], **(raw.get("puntuacio") or {})}
    out["puntuacio"]["candidate_source_cfg"] = {
        **DEFAULT_SCHEMA["puntuacio"]["candidate_source_cfg"],
        **((((raw.get("puntuacio") or {}).get("candidate_source_cfg")) or {}) if isinstance(raw.get("puntuacio"), dict) else {}),
    }
    raw_punt = (raw.get("puntuacio") or {}) if isinstance(raw.get("puntuacio"), dict) else {}
    raw_agg_map = raw_punt.get("agregacio_camps_per_aparell")
    out["puntuacio"]["agregacio_camps_per_aparell"] = raw_agg_map if isinstance(raw_agg_map, dict) else {}
    raw_candidate_map = raw_punt.get("candidate_source_per_aparell")
    out["puntuacio"]["candidate_source_per_aparell"] = raw_candidate_map if isinstance(raw_candidate_map, dict) else {}
    out["puntuacio"]["victories"] = {
        **DEFAULT_SCHEMA["puntuacio"]["victories"],
        **((((raw.get("puntuacio") or {}).get("victories")) or {}) if isinstance(raw.get("puntuacio"), dict) else {}),
    }
    out["presentacio"] = {**DEFAULT_SCHEMA["presentacio"], **(raw.get("presentacio") or {})}
    out["presentacio"]["detall"] = {
        **DEFAULT_SCHEMA["presentacio"]["detall"],
        **(((raw.get("presentacio") or {}).get("detall")) or {}),
    }
    raw_detail = ((raw.get("presentacio") or {}).get("detall")) or {}
    if isinstance(raw_detail, dict) and "columnes" in raw_detail:
        out["presentacio"]["detall"]["columnes"] = _json_clone_value(raw_detail.get("columnes"))
    if not isinstance(out["presentacio"]["detall"].get("sections"), list):
        out["presentacio"]["detall"]["sections"] = []
    out["desempat"] = raw.get("desempat", DEFAULT_SCHEMA["desempat"]) or []
    out["equips"] = normalize_classificacio_equips_cfg(raw.get("equips") or {})
    return out


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

    equips_cfg = normalize_classificacio_equips_cfg(out.get("equips") or {})
    age_cfg = equips_cfg.get("particio_edat") or {}
    age_active = bool(age_cfg.get("activa", False))
    if not age_active:
        if persist:
            equips_cfg["particio_edat"] = dict(DEFAULT_EQUIPS_CFG["particio_edat"])
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
            ref_date = competition_reference_date(competicio)
            if ref_date is None:
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
        equips_cfg["particio_edat"] = dict(DEFAULT_EQUIPS_CFG["particio_edat"])
        equips_cfg["combinar_manual_i_edat"] = False
    out["equips"] = equips_cfg
    return out, info


__all__ = [
    "BIRTH_YEAR_RANGE_PARTITION_CODE",
    "normalize_birth_year_range_partition_config",
    "normalize_particions_config",
    "normalize_particions_v2_entries",
    "normalize_schema_legacy_team_birth_partition",
    "particio_codes_from_entries",
]
