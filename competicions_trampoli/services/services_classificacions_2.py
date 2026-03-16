# services_classificacions.py
import json
import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal
from django.db import models
from django.utils import timezone
from ..models import Inscripcio
from ..models_trampoli import CompeticioAparell
from ..models_scoring import ScoreEntry

logger = logging.getLogger(__name__)


# -----------------------------
# DEFAULTS (nova proposta)
# -----------------------------
DEFAULT_SCHEMA = {
    "particions": [],
    "particions_v2": [],
    "particions_custom": {},
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

        # agregació dels camps seleccionats DINS d'un exercici (nota)
        # sum/avg/median/max/min
        "agregacio_camps": "sum",

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
    },

    # Config additiva per tipus="equips"
    "equips": {
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
    out["filtres"] = {**DEFAULT_SCHEMA["filtres"], **(schema.get("filtres") or {})}
    out["puntuacio"] = {**DEFAULT_SCHEMA["puntuacio"], **(schema.get("puntuacio") or {})}
    out["puntuacio"]["victories"] = {
        **DEFAULT_SCHEMA["puntuacio"]["victories"],
        **((((schema.get("puntuacio") or {}).get("victories")) or {}) if isinstance(schema.get("puntuacio"), dict) else {}),
    }
    out["presentacio"] = {**DEFAULT_SCHEMA["presentacio"], **(schema.get("presentacio") or {})}
    out["desempat"] = schema.get("desempat", DEFAULT_SCHEMA["desempat"]) or []
    out["equips"] = {**DEFAULT_SCHEMA["equips"], **(schema.get("equips") or {})}
    out["equips"]["particio_edat"] = {
        **DEFAULT_SCHEMA["equips"]["particio_edat"],
        **(((schema.get("equips") or {}).get("particio_edat")) or {}),
    }
    return out


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


def _partition_key(ins: Inscripcio, fields: list, particions_custom_index=None):
    parts = []
    for f in fields or []:
        f = (f or "").strip()
        if not f:
            continue
        raw_value = _inscripcio_value_for_partition(ins, f)
        display_value = _partition_value_display(raw_value)
        resolved = _resolve_partition_display(f, display_value, particions_custom_index or {})
        parts.append(f"{f}:{resolved}")
    return "|".join(parts) if parts else "global"


def _partition_key_from_entries(ins: Inscripcio, entries: list, particions_custom_index=None):
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

        raw_value = _inscripcio_value_for_partition(ins, code)
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
        f"|ex_sel[{ex_sel_mode}]|ex_app[{ex_per_app_sig}]"
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

    raw_cols = presentacio.get("columnes")
    cols = raw_cols if isinstance(raw_cols, list) else []

    def _default():
        return [
            {"type": "builtin", "key": "posicio", "label": "#", "align": "left"},
            {"type": "builtin", "key": "participant", "label": "Nom", "align": "left"},
            {"type": "builtin", "key": "punts", "label": "Punts", "align": "right", "decimals": 3},
        ]

    if not cols:
        return _default()

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
            exercici = source.get("exercici", 1)
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
                    "jutges": {"ids": jutges_ids},
                },
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
            if key not in ("posicio", "participant", "nom", "entitat_nom", "participants", "punts"):
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

    return out or _default()


def compute_classificacio(competicio, cfg_obj):
    """
    Retorna:
      { "particio_key": [ {row}, ... ] }

    row (individual) mínim:
      - inscripcio_id, nom, entitat_nom, score, tie{...}
      - posicio/punts els posa _rank()
    """
    schema = _merge_schema(getattr(cfg_obj, "schema", {}) or {})
    part_entries = schema.get("particions_v2") or normalize_particions_v2_entries(
        schema.get("particions") or []
    )
    part_custom_idx = _build_particions_custom_index(schema.get("particions_custom") or {})
    filtres = schema["filtres"] or {}
    punt = schema["puntuacio"] or {}
    desempat = schema["desempat"] or []
    presentacio = schema["presentacio"] or {}
    display_columns = get_display_columns(schema)
    equips_cfg = schema.get("equips") or {}
    tipus = (getattr(cfg_obj, "tipus", "individual") or "individual").lower().strip()
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
            "best_n": (punt.get("exercicis_best_n") or (ex_cfg.get("best_n") if isinstance(ex_cfg, dict) else 1) or 1),
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

    agg_camps = (punt.get("agregacio_camps") or "sum").lower().strip()
    agg_exercicis = (punt.get("agregacio_exercicis") or "sum").lower().strip()
    agg_aparells = (punt.get("agregacio_aparells") or "sum").lower().strip()

    # 2) APARELLS sobre els quals es computa
    app_mode = ((punt.get("aparells") or {}).get("mode") or "tots").lower().strip()
    app_ids = (punt.get("aparells") or {}).get("ids") or []

    aparells_qs = CompeticioAparell.objects.filter(competicio=competicio, actiu=True).select_related("aparell")
    if app_mode == "seleccionar" and app_ids:
        aparells_qs = aparells_qs.filter(id__in=app_ids)
    aparells = list(aparells_qs.order_by("ordre", "id"))

    # si no hi ha aparells seleccionats -> retorn buit
    if not aparells:
        return {"global": []}

    # 3) INSCRIPCIONS per competició, agrupades per aparell
    ins_qs = Inscripcio.objects.filter(competicio=competicio)
    ins_qs = _filter_in(ins_qs, Inscripcio, "entitat", filtres.get("entitats_in") or [])
    ins_qs = _filter_in(ins_qs, Inscripcio, "categoria", filtres.get("categories_in") or [])
    ins_qs = _filter_in(ins_qs, Inscripcio, "subcategoria", filtres.get("subcategories_in") or [])
    if filtres.get("grups_in"):
        ins_qs = ins_qs.filter(grup__in=filtres["grups_in"])

    sr = []
    for f in ("entitat", "categoria", "subcategoria", "equip"):
        if _is_relational_field(Inscripcio, f):
            sr.append(f)
    if sr:
        ins_qs = ins_qs.select_related(*sr)

    ins_list = list(ins_qs)
    ins_by_id = {i.id: i for i in ins_list}

    # notes per tots els aparells seleccionats (una query)
    notes_qs = (
        ScoreEntry.objects
      .filter(competicio=competicio, inscripcio__in=ins_list, comp_aparell__in=aparells)
      .select_related("inscripcio", "comp_aparell")
    )
    notes = list(notes_qs)

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

    # 4) CAMPS per aparell (lliures)
    camps_per_aparell = punt.get("camps_per_aparell") or {}
    # fallback legacy: si no hi ha camps_per_aparell, usem camp legacy per tots els aparells
    legacy_camp = (punt.get("camp") or "total").strip()

    def camps_for_app(app_id: int):
        raw = camps_per_aparell.get(str(app_id)) or camps_per_aparell.get(app_id)
        if isinstance(raw, list) and raw:
            return [str(x).strip() for x in raw if str(x).strip()]
        if isinstance(raw, str) and raw.strip():
            # permet "total,execucio_total"
            return [x.strip() for x in raw.split(",") if x.strip()]
        # legacy
        return [legacy_camp] if legacy_camp else ["total"]

    # 5) EXERCICIS per aparell segons CompeticioAparell.nombre_exercicis
    # 6) AGREGACIONS + construccio de score final per inscripcio
    per_ins = {}  # ins_id -> {"score":float, "by_app_base":{}, "by_app":{}, "tie":{...}}
    for ins in ins_list:
        per_ins[ins.id] = {"score": 0.0, "by_app_base": {}, "by_app": {}, "tie": {}}

    app_order = {ca.id: idx for idx, ca in enumerate(aparells, start=1)}
    app_fields_by_app = {}
    app_ex_rows_by_ins = defaultdict(dict)  # app_id -> ins_id -> [row]

    for ca in aparells:
        app_id = ca.id
        n_ex = int(getattr(ca, "nombre_exercicis", 1) or 1)
        n_ex = max(1, min(50, n_ex))

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

        fields = camps_for_app(app_id)
        app_fields_by_app[app_id] = list(fields)

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
                v_fields = [fields_map.get(f, 0.0) for f in fields]

                v_ex = _apply_simple_agg(v_fields, agg_camps)  # agregacio camps dins exercici
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

    selected_rows_agg_cache = {}
    selected_rows_field_cache = {}

    def _get_selected_rows_agg_for_ins(ins_id: int):
        if ins_id in selected_rows_agg_cache:
            return selected_rows_agg_cache[ins_id]

        picked_by_app = defaultdict(list)
        if mode_seleccio_exercicis == "global_pool":
            pool_rows = []
            for ca in aparells:
                app_id = ca.id
                for row in app_ex_rows_by_ins.get(app_id, {}).get(ins_id, []):
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
                rows_ex = app_ex_rows_by_ins.get(app_id, {}).get(ins_id, [])
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

    def _get_selected_rows_for_field(ins_id: int, field_code: str):
        cache_key = (ins_id, str(field_code or ""))
        if cache_key in selected_rows_field_cache:
            return selected_rows_field_cache[cache_key]

        picked_by_app = defaultdict(list)
        if mode_seleccio_exercicis == "global_pool":
            pool_rows = []
            for ca in aparells:
                app_id = ca.id
                for row in app_ex_rows_by_ins.get(app_id, {}).get(ins_id, []):
                    item = _copy_ex_row_with_value(
                        row,
                        ((row.get("by_camp") or {}).get(field_code)),
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

        part_scope = ((crit.get("scope") or {}).get("participants") or {})
        part_mode = (part_scope.get("mode") or "tots").lower().strip()
        if part_mode == "hereta":
            part_mode = "tots"
        try:
            part_n = int(part_scope.get("n") or 1)
        except Exception:
            part_n = 1

        vals = [calc_metric_value_for_ins(mid, crit) for mid in mids]
        selected_vals = _pick_participants(vals, part_mode, part_n)
        agg_parts = (crit.get("agregacio_participants") or "sum").lower().strip()
        return float(_apply_simple_agg(selected_vals, agg_parts))

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
                        if len(member_ids) == 1:
                            val = _raw_col_value_for_ins(member_ids[0], col)
                        else:
                            val = ""
                    else:
                        val = _raw_col_value_for_ins(row.get("inscripcio_id"), col)
                    val = _apply_decimals_if_numeric(val, col.get("decimals"))
                else:
                    val = _builtin_col_value(row, ckey)
                    val = _apply_decimals_if_numeric(val, col.get("decimals"))

                cells[ckey] = val

            row["cells"] = cells
            row["display"] = cells
            row.pop("_member_ids", None)
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
        pkey = _partition_key_from_entries(ins, part_entries, part_custom_idx)
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

    if tipus == "equips":
        include_sense_equip = bool(equips_cfg.get("incloure_sense_equip", False))
        manual_defs = equips_cfg.get("particions_manuals") or []
        age_cfg = equips_cfg.get("particio_edat") or {}
        age_active = bool(age_cfg.get("activa", False))
        age_label_empty = (age_cfg.get("sense_data_label") or "Sense edat").strip() or "Sense edat"
        combine_manual_age = bool(equips_cfg.get("combinar_manual_i_edat", False))

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

        # agrupem participants per equip dins cada particio "base" existent
        grouped = defaultdict(lambda: defaultdict(list))  # base_pkey -> equip_id_key -> [ins]
        for ins in ins_list:
            if ins.equip_id is None and not include_sense_equip:
                continue
            base_pkey = _partition_key_from_entries(ins, part_entries, part_custom_idx)
            team_id_key = ins.equip_id if ins.equip_id is not None else "__sense_equip__"
            grouped[base_pkey][team_id_key].append(ins)

        for base_pkey, teams in grouped.items():
            for team_id_key, members in teams.items():
                if not members:
                    continue

                # nom equip
                if team_id_key == "__sense_equip__":
                    equip_id = None
                    equip_nom = "Sense equip"
                else:
                    equip_id = int(team_id_key)
                    eq_obj = getattr(members[0], "equip", None)
                    equip_nom = (getattr(eq_obj, "nom", None) or f"Equip {equip_id}").strip()

                # particio manual / edat
                manual_part = manual_map.get(equip_id) if equip_id is not None else None
                age_part = None
                if age_active:
                    ref_date = getattr(competicio, "data", None) or timezone.localdate()
                    ages = []
                    for m in members:
                        age = _years_old(getattr(m, "data_naixement", None), ref_date)
                        if age is not None:
                            ages.append(age)
                    age_max = max(ages) if ages else None
                    age_part = _bucket_edat(age_max, llindars, age_label_empty)

                team_part = _resolve_particio_equip(manual_part, age_part, combine_manual_age)
                if base_pkey != "global" and team_part != "global":
                    final_pkey = f"{base_pkey}|{team_part}"
                elif team_part != "global":
                    final_pkey = team_part
                else:
                    final_pkey = base_pkey

                team_score = sum([_to_float(per_ins[m.id]["score"]) for m in members])
                member_ids = [m.id for m in members]

                team_tie = {}
                for t in desempat or []:
                    tkey = _tie_key(t)
                    if not tkey:
                        continue
                    team_tie[tkey] = calc_metric_value_for_group(member_ids, t)

                out.setdefault(final_pkey, []).append({
                    "equip_id": equip_id,
                    "nom": equip_nom,
                    "participant": equip_nom,
                    "score": float(team_score),
                    "tie": team_tie,
                    "participants": len(members),
                    "_member_ids": member_ids,
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



