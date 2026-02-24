# services_classificacions.py
from collections import defaultdict
from datetime import date
from decimal import Decimal
from django.db import models
from django.utils import timezone
from ..models import Inscripcio
from ..models_trampoli import CompeticioAparell
from ..models_scoring import ScoreEntry


# -----------------------------
# DEFAULTS (nova proposta)
# -----------------------------
DEFAULT_SCHEMA = {
    "particions": [],
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
        "exercicis": {"mode": "tots", "index": 1, "ids": []},
        "exercicis_best_n": 1,

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

        # ordre principal del ranking
        "ordre": "desc",  # desc = més punts millor
    },

    # desempats: admet format legacy i nou
    # legacy: {"camp":"execucio_total","ordre":"desc"}
    # nou: {"aparell_id": 12, "camp":"E_total", "ordre":"desc"}
    "desempat": [],

    "presentacio": {"top_n": 0, "mostrar_empats": True},

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
    out["particions"] = schema.get("particions", DEFAULT_SCHEMA["particions"]) or []
    out["filtres"] = {**DEFAULT_SCHEMA["filtres"], **(schema.get("filtres") or {})}
    out["puntuacio"] = {**DEFAULT_SCHEMA["puntuacio"], **(schema.get("puntuacio") or {})}
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


def _partition_key(ins: Inscripcio, fields: list):
    parts = []
    for f in fields or []:
        f = (f or "").strip()
        if not f:
            continue
        if f in ("categoria", "subcategoria", "entitat", "grup"):
            parts.append(f"{f}:{_display_value(ins, f)}")
        else:
            parts.append(f"{f}:{getattr(ins, f, '')}")
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

    # fallback
    return xs

def _pick_exercicis_tuples(ex_vals, mode: str, best_n: int, index=None, ids=None):
    """
    ex_vals: [(ex_idx, value), ...]
    retorna: [values...]
    """
    xs = [(int(i), _to_float(v)) for (i, v) in (ex_vals or [])]
    if not xs:
        return []

    m = (mode or "tots").lower().strip()

    if m == "tots":
        return [v for _, v in xs]

    if m == "millor_1":
        return [max([v for _, v in xs])]

    if m == "millor_n":
        n = max(1, int(best_n or 1))
        return sorted([v for _, v in xs], reverse=True)[:n]

    if m == "primer":
        first_idx = min(i for i, _ in xs)
        for i, v in xs:
            if i == first_idx:
                return [v]
        return []

    if m == "ultim":
        last_idx = max(i for i, _ in xs)
        for i, v in xs:
            if i == last_idx:
                return [v]
        return []

    if m == "index":
        try:
            idx = int(index or 1)
        except Exception:
            idx = 1
        for i, v in xs:
            if i == idx:
                return [v]
        return []

    if m == "llista":
        wanted = set(int(x) for x in (ids or []) if str(x).strip())
        return [v for i, v in xs if i in wanted]

    return [v for _, v in xs]


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
    if ex_mode == "millor_n":
        ex_sig += f":{ex.get('best_n') or ''}"
    elif ex_mode == "index":
        ex_sig += f":{ex.get('index') or 1}"
    elif ex_mode == "llista":
        ex_ids = ex.get("ids") or []
        ex_sig += ":" + ",".join(str(int(x)) for x in ex_ids)

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


def compute_classificacio(competicio, cfg_obj):
    """
    Retorna:
      { "particio_key": [ {row}, ... ] }

    row (individual) mínim:
      - inscripcio_id, nom, entitat_nom, score, tie{...}
      - posicio/punts els posa _rank()
    """
    schema = _merge_schema(getattr(cfg_obj, "schema", {}) or {})
    part_fields = schema["particions"]
    filtres = schema["filtres"] or {}
    punt = schema["puntuacio"] or {}
    desempat = schema["desempat"] or []
    presentacio = schema["presentacio"] or {}
    equips_cfg = schema.get("equips") or {}
    tipus = (getattr(cfg_obj, "tipus", "individual") or "individual").lower().strip()
    desempat = _sanitize_desempat_for_tipus(desempat, tipus)

    # 1) PRETRACTAMENT
    ordre_principal = (punt.get("ordre") or "desc").lower().strip()
    if ordre_principal not in ("asc", "desc"):
        ordre_principal = "desc"

    ex_cfg = punt.get("exercicis") or {}
    exerc_mode = (ex_cfg.get("mode") or "tots").lower().strip()
    if exerc_mode not in ("tots", "millor_1", "millor_n", "primer", "ultim", "index", "llista"):
        exerc_mode = "tots"

    try:
        ex_best_n = int(punt.get("exercicis_best_n") or ex_cfg.get("best_n") or 1)
    except Exception:
        ex_best_n = 1
    ex_best_n = max(1, ex_best_n)

    try:
        ex_index = int(ex_cfg.get("index") or 1)
    except Exception:
        ex_index = 1
    ex_index = max(1, ex_index)

    ex_ids_raw = ex_cfg.get("ids", [])
    ex_ids = []
    if isinstance(ex_ids_raw, str):
        parts = [x.strip() for x in ex_ids_raw.split(",") if x.strip()]
        for p in parts:
            try:
                iv = int(p)
            except Exception:
                continue
            if iv > 0:
                ex_ids.append(iv)
    elif isinstance(ex_ids_raw, (list, tuple)):
        for x in ex_ids_raw:
            try:
                iv = int(x)
            except Exception:
                continue
            if iv > 0:
                ex_ids.append(iv)

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
    for n in notes:
        notes_by_app[n.comp_aparell_id].append(n)

    # inscripcions que realment �?ocompeteixen�?� a cada aparell (tenen notes)
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
    #    i selecció d'exercicis (mode: tots/millor_1/millor_n)
    # 6) AGREGACIONS + construcció de score final per inscripció
    per_ins = {}  # ins_id -> {"score":float, "by_app":{app_id:score_app}, "tie":{...}}
    for ins in ins_list:
        per_ins[ins.id] = {"score": 0.0, "by_app": {}, "tie": {}}

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
                # si hi ha notes �?oextra�?�, les ignores per coherència amb configuració d'aparell
                continue
            by_ins_ex[nt.inscripcio_id][ex_idx] = nt

        fields = camps_for_app(app_id)

        # calculem valor per exercici (agregant camps)
        for ins_id in list(ins_by_id.keys()):
            if ins_id not in ins_ids_by_app.get(app_id, set()):
                # no competeix en aquest aparell
                continue

            vals_ex = []
            for ex_idx in range(1, n_ex + 1):
                nt = by_ins_ex.get(ins_id, {}).get(ex_idx)
                if not nt:
                    continue
                v_fields = [_get_score_field(nt, f) for f in fields]

                v_ex = _apply_simple_agg(v_fields, agg_camps)  # agregació camps dins exercici
                vals_ex.append((ex_idx, v_ex))

            # selecció d'exercicis (tots/millor_1/millor_n)
            picked = _pick_exercicis_tuples(
                vals_ex,
                exerc_mode,
                ex_best_n,
                index=ex_index,
                ids=ex_ids,
            )

            # agregació d'exercicis dins aparell
            score_app = _apply_simple_agg(picked, agg_exercicis)

            per_ins[ins_id]["by_app"][app_id] = float(score_app)

    # agregació final entre aparells
    for ins_id, obj in per_ins.items():
        app_vals = list((obj.get("by_app") or {}).values())
        obj["score"] = float(_apply_simple_agg(app_vals, agg_aparells))

    # 7) TIE-BREAKS segons ordre del front
    # suport:
    #  - legacy: {"camp":"execucio_total","ordre":"desc"} -> suma (o avg) sobre aparells/exercicis segons el pipeline
    #  - nou: {"aparell_id": X, "camp": "E_total", "ordre":"desc"} -> recalcula com �?oscore d'aquell aparell però només amb aquell camp�?�
    #
    # IMPORTANT: per no duplicar molt codi, fem una funció que calcula "valor criteri" reutilitzant el mateix pipeline,
    # però substituint camps per la llista [camp].
    def calc_criterion_value(ins_id: int, crit: dict) -> float:
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
                "exercicis":{"mode":"hereta"|"tots"|"millor_1"|"millor_n"|"primer"|"ultim"|"index"|"llista",
                            "best_n":2, "index":1, "ids":[1,3]}
                },
                "agregacio_camps":"hereta"|"sum"|"avg"|"median"|"max"|"min",
                "agregacio_exercicis":"hereta"|"sum"|"avg"|"median"|"max"|"min",
                "agregacio_aparells":"hereta"|"sum"|"avg"|"median"|"max"|"min"
            }
        """

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
        crit_best_n = int(crit_ex.get("best_n") or ex_best_n)
        crit_ex_index = crit_ex.get("index", None)
        crit_ex_ids = crit_ex.get("ids", None)

        # -----------------------------
        # Aparells objectiu del criteri
        # -----------------------------
        target_apps = []
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

        for ta in target_apps:
            ca = next((x for x in aparells if x.id == ta), None)
            if not ca:
                continue

            n_ex = int(getattr(ca, "nombre_exercicis", 1) or 1)
            n_ex = max(1, min(50, n_ex))

            # ScoreEntries d'aquest aparell
            app_scores = notes_by_app.get(ta, [])  # IMPORTANT: al teu codi és scores_by_app (no notes_by_app)
            by_ins_ex = defaultdict(dict)
            for se in app_scores:
                ex_idx = int(getattr(se, "exercici", 1) or 1)
                if 1 <= ex_idx <= n_ex:
                    by_ins_ex[se.inscripcio_id][ex_idx] = se

            # (ex_idx, value) per poder seleccionar "index" o "llista"
            vals_ex = []
            for ex_idx in range(1, n_ex + 1):
                se = by_ins_ex.get(ins_id, {}).get(ex_idx)
                if not se:
                    continue

                # IMPORTANT: desempat llegeix ScoreEntry via _get_score_field
                vals_fields = [_get_score_field(se, c) for c in camps]
                v_ex = _apply_simple_agg(vals_fields, crit_agg_camps)
                vals_ex.append((ex_idx, v_ex))

            picked = _pick_exercicis_tuples(
                vals_ex,
                crit_ex_mode,
                crit_best_n,
                index=crit_ex_index,
                ids=crit_ex_ids
            )

            val_app = _apply_simple_agg(picked, crit_agg_exercicis)
            vals_apps.append(val_app)

        return float(_apply_simple_agg(vals_apps, crit_agg_aparells))
    
    # guardem tie values (amb clau estable per UI)
    for crit in desempat:
        key = _tie_key(crit)
        if not key:
            continue
        for ins_id in per_ins.keys():
            per_ins[ins_id]["tie"][key] = calc_criterion_value(ins_id, crit)

    # 8) PARTICIONS + output rows
    per_particio = defaultdict(list)

    for ins in ins_list:
        pkey = _partition_key(ins, part_fields)
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
            "by_app": per_ins[ins.id]["by_app"],
        }
        per_particio[pkey].append(row)

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
            base_pkey = _partition_key(ins, part_fields)
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

                team_tie = {}
                for t in desempat or []:
                    tkey = _tie_key(t)
                    if not tkey:
                        continue

                    part_scope = ((t.get("scope") or {}).get("participants") or {})
                    part_mode = (part_scope.get("mode") or "hereta").lower().strip()
                    if part_mode == "hereta":
                        part_mode = "tots"
                    try:
                        part_n = int(part_scope.get("n") or 1)
                    except Exception:
                        part_n = 1

                    part_vals = [_to_float((per_ins[m.id].get("tie") or {}).get(tkey, 0.0)) for m in members]
                    selected_vals = _pick_participants(part_vals, part_mode, part_n)
                    agg_parts = (t.get("agregacio_participants") or "sum").lower().strip()
                    team_tie[tkey] = float(_apply_simple_agg(selected_vals, agg_parts))

                out.setdefault(final_pkey, []).append({
                    "equip_id": equip_id,
                    "nom": equip_nom,
                    "participant": equip_nom,
                    "score": float(team_score),
                    "tie": team_tie,
                    "participants": len(members),
                })

        for pkey, rows in out.items():
            out[pkey] = _rank_v2(rows, desempat, presentacio, ordre_principal=ordre_principal, entity_mode=True)
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
                })

            out[pkey] = _rank_v2(ent_rows, desempat, presentacio, ordre_principal=ordre_principal, entity_mode=True)
        return out

    for pkey, rows in per_particio.items():
        out[pkey] = _rank_v2(rows, desempat, presentacio, ordre_principal=ordre_principal, entity_mode=False)
    return out



def _get_score_field(entry: ScoreEntry, code: str) -> float:
    code = (code or "").strip()
    if not code:
        return 0.0

    # "total" especial: columna total del model :contentReference[oaicite:11]{index=11}
    if code.lower() == "total":
        return _to_float(entry.total)

    out = entry.outputs or {}
    if isinstance(out, dict) and code in out:
        return _to_float(out.get(code))

    # fallback comú si el total també s�?Tha escrit a outputs
    if isinstance(out, dict):
        if code == "TOTAL" and "TOTAL" in out:
            return _to_float(out["TOTAL"])
        if code == "total" and "total" in out:
            return _to_float(out["total"])

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
