# services_classificacions.py
from collections import defaultdict
from decimal import Decimal
from django.db import models
from .models import Inscripcio
from .models_trampoli import TrampoliNota, CompeticioAparell
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
        "exercicis": {"mode": "tots"},
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


def _get_note_field(note: TrampoliNota, field_code: str) -> float:
    """
    Lector tolerant:
      - primer prova atribut (TrampoliNota.total, dificultat, execucio_total, etc.)
      - després prova dicts típics (outputs / data), pensant en migració a ScoreEntry
    """
    code = (field_code or "").strip()
    if not code:
        return 0.0

    if hasattr(note, code):
        return _to_float(getattr(note, code, 0.0))

    # futur: ScoreEntry / notes amb JSON
    for attr in ("outputs", "data", "result", "valors"):
        d = getattr(note, attr, None)
        if isinstance(d, dict) and code in d:
            return _to_float(d.get(code))

    return 0.0


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


# -----------------------------
# CORE NOU
# -----------------------------
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
    tipus = getattr(cfg_obj, "tipus", "individual") or "individual"

    # 1) PRETRACTAMENT
    ordre_principal = (punt.get("ordre") or "desc").lower().strip()
    if ordre_principal not in ("asc", "desc"):
        ordre_principal = "desc"

    exerc_mode = ((punt.get("exercicis") or {}).get("mode") or "tots").lower().strip()
    ex_best_n = int(punt.get("exercicis_best_n") or 1)

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
    for f in ("entitat", "categoria", "subcategoria"):
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

    # inscripcions que realment “competeixen” a cada aparell (tenen notes)
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
                # si hi ha notes “extra”, les ignores per coherència amb configuració d'aparell
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
                vals_ex.append(v_ex)

            # selecció d'exercicis (tots/millor_1/millor_n)
            picked = _pick_exercicis(vals_ex, exerc_mode, ex_best_n)

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
    #  - nou: {"aparell_id": X, "camp": "E_total", "ordre":"desc"} -> recalcula com “score d'aquell aparell però només amb aquell camp”
    #
    # IMPORTANT: per no duplicar molt codi, fem una funció que calcula "valor criteri" reutilitzant el mateix pipeline,
    # però substituint camps per la llista [camp].
    def calc_criterion_value(ins_id: int, crit: dict) -> float:
        camp = (crit.get("camp") or "").strip()
        if not camp:
            return 0.0

        app_id = crit.get("aparell_id", None)
        # legacy: si no hi ha aparell_id, fem el mateix criteri “sumant” sobre aparells disponibles,
        # igual que el score global però substituint camps.
        target_apps = []
        if app_id in (None, "", 0, "0"):
            target_apps = [ca.id for ca in aparells]
        else:
            try:
                target_apps = [int(app_id)]
            except Exception:
                target_apps = [ca.id for ca in aparells]

        vals_apps = []
        for ta in target_apps:
            ca = next((x for x in aparells if x.id == ta), None)
            if not ca:
                continue

            n_ex = int(getattr(ca, "nombre_exercicis", 1) or 1)
            n_ex = max(1, min(50, n_ex))

            # notes d'aquest aparell
            app_notes = notes_by_app.get(ta, [])
            by_ins_ex = defaultdict(dict)
            for nt in app_notes:
                ex_idx = int(getattr(nt, "exercici", 1) or 1)
                if 1 <= ex_idx <= n_ex:
                    by_ins_ex[nt.inscripcio_id][ex_idx] = nt

            vals_ex = []
            for ex_idx in range(1, n_ex + 1):
                nt = by_ins_ex.get(ins_id, {}).get(ex_idx)
                if not nt:
                    continue
                v_ex = _apply_simple_agg([_get_score_field(nt, camp)], agg_camps)
                vals_ex.append(v_ex)

            picked = _pick_exercicis(vals_ex, exerc_mode, ex_best_n)
            val_app = _apply_simple_agg(picked, agg_exercicis)
            vals_apps.append(val_app)

        # si el criteri és “per aparell” (app_id fix) retorna directament aquest valor;
        # si és “global” (sense app) el combinem com el score final
        return float(_apply_simple_agg(vals_apps, agg_aparells))

    # guardem tie values (amb clau estable per UI)
    for crit in desempat:
        camp = (crit.get("camp") or "").strip()
        if not camp:
            continue
        app_id = crit.get("aparell_id", None)
        key = f"{camp}@{app_id}" if app_id not in (None, "", 0, "0") else camp
        for ins_id in per_ins.keys():
            per_ins[ins_id]["tie"][key] = calc_criterion_value(ins_id, crit)

    # 8) PARTICIONS + output rows
    per_particio = defaultdict(list)

    for ins in ins_list:
        pkey = _partition_key(ins, part_fields)

        row = {
            "inscripcio_id": ins.id,
            "nom": getattr(ins, "nom", None) or str(ins),
            "entitat_nom": _display_value(ins, "entitat"),
            "score": float(per_ins[ins.id]["score"]),
            "tie": per_ins[ins.id]["tie"],
            # extra útil pel front (si vols mostrar detalls)
            "by_app": per_ins[ins.id]["by_app"],
        }
        per_particio[pkey].append(row)

    # mode "entitat": mantenim comportament antic (suma per entitat)
    out = {}
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
                    camp = (t.get("camp") or "").strip()
                    app_id = t.get("aparell_id", None)
                    k = f"{camp}@{app_id}" if app_id not in (None, "", 0, "0") else camp
                    ent_tie[k] = sum([_to_float((x.get("tie") or {}).get(k, 0.0)) for x in items])

                ent_rows.append({
                    "entitat_nom": ent_nom,
                    "score": float(ent_score),
                    "tie": ent_tie,
                    "participants": len(items),
                })

            out[pkey] = _rank_v2(ent_rows, desempat, presentacio, ordre_principal=ordre_principal, entity_mode=True)

        return out

    # individual
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

    # fallback comú si el total també s’ha escrit a outputs
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
        camp = (t.get("camp") or "").strip()
        if not camp:
            continue
        ordre = (t.get("ordre") or "desc").lower().strip()
        app_id = t.get("aparell_id", None)
        key = f"{camp}@{app_id}" if app_id not in (None, "", 0, "0") else camp
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
