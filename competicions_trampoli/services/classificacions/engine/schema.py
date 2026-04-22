"""Canonical compute schema owner for classificacions.

This module centralizes the compute schema defaults plus the final schema
merge/normalization currently split across legacy and partition helpers.
The public compute bridge is intentionally unchanged for now.
"""

from ...shared.birth_year_ranges import (
    BIRTH_YEAR_RANGE_PARTITION_CODE,
    DEFAULT_BIRTH_YEAR_RANGE_PARTITION_CONFIG,
    legacy_team_age_partition_to_birth_year_range_config,
    normalize_birth_year_range_partition_config,
)
from ..filters import normalize_classificacio_equips_cfg, normalize_classificacio_filters
from ..partitions import (
    normalize_particions_config,
    normalize_particions_v2_entries,
    particio_codes_from_entries,
)
from .common import DEFAULT_EQUIPS_CFG, competition_reference_date, json_clone_value


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
        "camps_mode_per_aparell": {},
        "camps_per_aparell": {},
        "camps_per_exercici_per_aparell": {},
        "agregacio_camps_per_aparell": {},
        "agregacio_camps_per_exercici_per_aparell": {},
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
        "participants_per_aparell": {},
        "agregacio_participants_per_aparell": {},
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


def _dict_or_empty(value):
    return value if isinstance(value, dict) else {}


def _merge_puntuacio(raw_puntuacio):
    raw = _dict_or_empty(raw_puntuacio)
    out = {**DEFAULT_SCHEMA["puntuacio"], **raw}
    out["exercicis"] = {
        **DEFAULT_SCHEMA["puntuacio"]["exercicis"],
        **_dict_or_empty(raw.get("exercicis")),
    }
    out["aparells"] = {
        **DEFAULT_SCHEMA["puntuacio"]["aparells"],
        **_dict_or_empty(raw.get("aparells")),
    }
    out["candidate_source_cfg"] = {
        **DEFAULT_SCHEMA["puntuacio"]["candidate_source_cfg"],
        **_dict_or_empty(raw.get("candidate_source_cfg")),
    }
    out["victories"] = {
        **DEFAULT_SCHEMA["puntuacio"]["victories"],
        **_dict_or_empty(raw.get("victories")),
    }
    for key in (
        "exercicis_per_aparell",
        "camps_mode_per_aparell",
        "camps_per_aparell",
        "camps_per_exercici_per_aparell",
        "agregacio_camps_per_aparell",
        "agregacio_camps_per_exercici_per_aparell",
        "candidate_source_per_aparell",
        "participants_per_aparell",
        "agregacio_participants_per_aparell",
    ):
        out[key] = _dict_or_empty(raw.get(key))
    return out


def _merge_presentacio(raw_presentacio):
    raw = _dict_or_empty(raw_presentacio)
    out = {**DEFAULT_SCHEMA["presentacio"], **raw}
    out["detall"] = {
        **DEFAULT_SCHEMA["presentacio"]["detall"],
        **_dict_or_empty(raw.get("detall")),
    }
    raw_detail = raw.get("detall")
    if isinstance(raw_detail, dict) and "columnes" in raw_detail:
        out["detall"]["columnes"] = json_clone_value(raw_detail.get("columnes"))
    if not isinstance(out["detall"].get("sections"), list):
        out["detall"]["sections"] = []
    return out


def merge_schema(schema):
    raw = schema if isinstance(schema, dict) else {}
    out = {**DEFAULT_SCHEMA}
    part_entries = normalize_particions_v2_entries(
        raw.get("particions_v2") or [],
        fallback_codes=raw.get("particions") or [],
    )
    out["particions_v2"] = part_entries
    out["particions"] = particio_codes_from_entries(part_entries)
    raw_custom = raw.get("particions_custom") or {}
    out["particions_custom"] = raw_custom if isinstance(raw_custom, dict) else {}
    out["particions_config"] = normalize_particions_config(raw.get("particions_config") or {})
    out["filtres"] = normalize_classificacio_filters(raw.get("filtres") or {})
    out["puntuacio"] = _merge_puntuacio(raw.get("puntuacio"))
    out["desempat"] = raw.get("desempat", DEFAULT_SCHEMA["desempat"]) or []
    out["presentacio"] = _merge_presentacio(raw.get("presentacio"))
    out["equips"] = normalize_classificacio_equips_cfg(raw.get("equips") or {})
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


def normalize_schema(competicio, schema, *, tipus="individual", persist=False):
    raw_schema = schema if isinstance(schema, dict) else {}
    out = merge_schema(raw_schema)
    info = {
        "legacy_inferred": False,
        "legacy_pending_review": False,
        "compatibility_errors": [],
    }

    if str(tipus or "").strip().lower() != "equips":
        return out, info

    equips_cfg = normalize_classificacio_equips_cfg(out.get("equips") or {})
    age_cfg = equips_cfg.get("particio_edat") or {}
    if not bool(age_cfg.get("activa", False)):
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
        if not any(
            str((entry or {}).get("code") or "").strip() == BIRTH_YEAR_RANGE_PARTITION_CODE
            for entry in part_entries
        ):
            part_entries.append(
                {"code": BIRTH_YEAR_RANGE_PARTITION_CODE, "apply_mode": "all", "parent_values": []}
            )
        out["particions_v2"] = part_entries
        out["particions"] = particio_codes_from_entries(part_entries)

        current_cfg = dict(
            (((raw_schema.get("particions_config") or {}).get(BIRTH_YEAR_RANGE_PARTITION_CODE)) or {})
        )
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


normalize_schema_for_compute = normalize_schema


__all__ = [
    "DEFAULT_SCHEMA",
    "merge_schema",
    "normalize_schema",
    "normalize_schema_for_compute",
]
