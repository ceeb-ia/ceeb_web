from datetime import date

from ..birth_year_ranges import BIRTH_YEAR_RANGE_PARTITION_CODE
from ..equip_contexts import NATIVE_EQUIP_CONTEXT_CODE, normalize_equip_context_code
from ..team_scoring import is_team_context_app


EXERCISE_SELECTION_SCOPE_PER_MEMBER = "per_member"
EXERCISE_SELECTION_SCOPE_TEAM_POOL = "team_pool"
EXERCISE_SELECTION_SCOPE_INHERIT = "hereta"
CLASSIFICACIO_FILTER_KEYS = (
    "entitats_in",
    "categories_in",
    "subcategories_in",
    "grups_in",
)

DEFAULT_EQUIPS_CFG = {
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
    "particions_manuals": [],
    "particio_edat": {
        "activa": False,
        "llindars": [],
        "sense_data_label": "Sense edat",
    },
    "combinar_manual_i_edat": False,
}


def normalize_positive_int(value):
    try:
        num = int(value)
    except Exception:
        return None
    return num if num > 0 else None


def normalized_text_token(value) -> str:
    txt = str(value or "")
    txt = " ".join(txt.split()).strip()
    return txt.casefold()


def normalize_classificacio_filter_values(raw_values, *, groups=False):
    items = raw_values if isinstance(raw_values, list) else ([] if raw_values in (None, "") else [raw_values])
    out = []
    seen = set()
    for raw in items:
        if raw is None or isinstance(raw, bool):
            continue

        as_int = None
        if isinstance(raw, int):
            as_int = normalize_positive_int(raw)
        elif isinstance(raw, float):
            if raw.is_integer():
                as_int = normalize_positive_int(int(raw))
        else:
            try:
                from decimal import Decimal
            except Exception:  # pragma: no cover
                Decimal = None
            if Decimal is not None and isinstance(raw, Decimal):
                try:
                    if raw == raw.to_integral_value():
                        as_int = normalize_positive_int(int(raw))
                except Exception:
                    as_int = None

        txt = ""
        if as_int is None:
            txt = str(raw).strip()
            if not txt:
                continue
            parsed = normalize_positive_int(txt)
            if parsed is not None:
                as_int = parsed

        if groups:
            stored = str(as_int) if as_int is not None else txt
            token = ("group", normalized_text_token(stored))
        elif as_int is not None:
            stored = int(as_int)
            token = ("id", int(as_int))
        else:
            stored = txt
            token = ("txt", normalized_text_token(txt))

        if not stored or token in seen:
            continue
        seen.add(token)
        out.append(stored)
    return out


def normalize_classificacio_filters(raw_filters):
    filters = raw_filters if isinstance(raw_filters, dict) else {}
    out = {}
    for key in CLASSIFICACIO_FILTER_KEYS:
        values = normalize_classificacio_filter_values(
            filters.get(key),
            groups=(key == "grups_in"),
        )
        if values:
            out[key] = values
    return out


def normalize_equip_assignment_source(raw_cfg):
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


def resolve_classificacio_equips_context_code(raw_context_code=None, raw_assignment_source=None, normalized_assignment_source=None):
    assignment_source = (
        normalized_assignment_source
        if isinstance(normalized_assignment_source, dict)
        else normalize_equip_assignment_source(raw_assignment_source)
    )
    assignment_source_provided = isinstance(raw_assignment_source, dict) and bool(raw_assignment_source)
    if assignment_source_provided:
        return normalize_equip_context_code(assignment_source.get("context_code"))
    if str(raw_context_code or "").strip():
        return normalize_equip_context_code(raw_context_code)
    return normalize_equip_context_code(assignment_source.get("context_code"))


def get_effective_team_context_code(equips_cfg):
    cfg = equips_cfg if isinstance(equips_cfg, dict) else {}
    assignment_source = cfg.get("assignment_source")
    if isinstance(assignment_source, dict) and assignment_source:
        return normalize_equip_context_code(assignment_source.get("context_code"))
    return normalize_equip_context_code(cfg.get("context_code"))


def normalize_team_mode(raw_mode) -> str:
    mode = str(raw_mode or "").strip().lower()
    if mode in {"derived_from_individual", "native_team"}:
        return mode
    return ""


def normalize_exercise_selection_scope(raw_scope, *, allow_inherit=False):
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


def normalize_mode_resolution(raw_cfg):
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


def normalize_classificacio_equips_cfg(raw_cfg):
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    raw_assignment_source = cfg.get("assignment_source")
    assignment_source = normalize_equip_assignment_source(raw_assignment_source)
    context_code = resolve_classificacio_equips_context_code(
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
        **DEFAULT_EQUIPS_CFG,
        **cfg,
        "context_code": context_code,
        "team_mode": normalize_team_mode(cfg.get("team_mode")),
        "mode_resolution": normalize_mode_resolution(cfg.get("mode_resolution")),
        "assignment_source": assignment_source,
        "particio_edat": {
            **DEFAULT_EQUIPS_CFG["particio_edat"],
            **(cfg.get("particio_edat") or {}),
        },
    }


def competition_reference_date(competicio):
    ref_date = getattr(competicio, "data", None)
    return ref_date if isinstance(ref_date, date) else None


def infer_team_mode_from_comp_aparells(comp_aparells) -> str:
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


__all__ = [
    "CLASSIFICACIO_FILTER_KEYS",
    "DEFAULT_EQUIPS_CFG",
    "EXERCISE_SELECTION_SCOPE_INHERIT",
    "EXERCISE_SELECTION_SCOPE_PER_MEMBER",
    "EXERCISE_SELECTION_SCOPE_TEAM_POOL",
    "competition_reference_date",
    "get_effective_team_context_code",
    "infer_team_mode_from_comp_aparells",
    "normalize_classificacio_equips_cfg",
    "normalize_classificacio_filters",
    "normalize_equip_assignment_source",
    "normalize_exercise_selection_scope",
    "normalize_team_mode",
    "resolve_classificacio_equips_context_code",
]
