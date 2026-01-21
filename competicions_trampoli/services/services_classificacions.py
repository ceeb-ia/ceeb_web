# services_classificacions.py
from collections import defaultdict
from decimal import Decimal
from django.db import models
from ..models import Inscripcio
from ..models_trampoli import TrampoliNota, CompeticioAparell
ALLOWED_SCORE_FIELDS = {
    "total": {"label": "Total", "sign": +1},
    "execucio_total": {"label": "Execució", "sign": +1},
    "dificultat": {"label": "Dificultat", "sign": +1},
    "tof": {"label": "TOF", "sign": +1},
    "hdc": {"label": "HD", "sign": +1},
    "penalitzacio": {"label": "Penalització", "sign": -1},  # en un ranking normal, resta
}

DEFAULT_SCHEMA = {
    "particions": [],  # ex: ["categoria"] / ["categoria","subcategoria"] / ["entitat"] ...
    "filtres": {
        "entitats_in": [],
        "categories_in": [],
        "subcategories_in": [],
        "grups_in": [],
    },
    "puntuacio": {
        "camp": "total",            # total / execucio_total / dificultat / tof / hdc / penalitzacio
        "agregacio": "sum",         # sum / best_n / avg / max
        "best_n": 1,                # si best_n
        "exercicis": {"mode": "tots"},   # tots / millor_1 / millor_n
        "exercicis_best_n": 1,
        "aparells": {"mode": "tots", "ids": []},  # tots / seleccionar
    },
    "desempat": [  # llista de criteris addicionals
        # {"camp":"execucio_total", "ordre":"desc"},
    ],
    "presentacio": {"top_n": 0, "mostrar_empats": True},  # top_n=0 => tots
} 

def _is_relational_field(model_cls, field_name: str) -> bool:
    try:
        f = model_cls._meta.get_field(field_name)
        return isinstance(f, (models.ForeignKey, models.OneToOneField))
    except Exception:
        return False

def _filter_in(qs, model_cls, field_name: str, ids: list):
    """
    Si el camp és FK, filtre per <field>_id__in.
    Si no és FK, filtre per <field>__in.
    """
    if not ids:
        return qs
    if _is_relational_field(model_cls, field_name):
        return qs.filter(**{f"{field_name}_id__in": ids})
    return qs.filter(**{f"{field_name}__in": ids})

def _display_value(ins, field_name: str) -> str:
    """
    Retorna un valor “humà” del camp:
    - si és relació: prova .nom, si no str(obj)
    - si no: valor directe
    """
    val = getattr(ins, field_name, None)
    if val is None:
        return ""
    # si és objecte relacionat (té ._meta), intentem nom
    if hasattr(val, "_meta"):
        return getattr(val, "nom", None) or str(val)
    return str(val)


def _merge_schema(schema: dict) -> dict:
    # merge simple i segur amb DEFAULT_SCHEMA
    out = {**DEFAULT_SCHEMA}
    schema = schema or {}
    out["particions"] = schema.get("particions", DEFAULT_SCHEMA["particions"])
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

def _pick_best(vals, n: int):
    vals = sorted([_to_float(x) for x in vals], reverse=True)
    n = max(1, min(int(n or 1), len(vals)))
    return vals[:n]

def _apply_aggregation(vals, mode: str, best_n: int):
    vals = [_to_float(x) for x in (vals or [])]
    if not vals:
        return 0.0

    mode = (mode or "sum").lower()
    if mode == "sum":
        return sum(vals)
    if mode == "avg":
        return sum(vals) / len(vals)
    if mode == "max":
        return max(vals)
    if mode == "best_n":
        return sum(_pick_best(vals, best_n))
    # fallback
    return sum(vals)

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

def compute_classificacio(competicio, cfg_obj):
    """
    Retorna dict:
      {
        "particio_key": [ {row}, {row}, ... ],
        ...
      }
    row conté:
      - posicio, punts, nom/entitat, i camps per desempats.
    """
    schema = _merge_schema(getattr(cfg_obj, "schema", {}) or {})
    part_fields = schema["particions"]
    filtres = schema["filtres"]
    punt = schema["puntuacio"]
    desempat = schema["desempat"]
    presentacio = schema["presentacio"]

    camp = (punt.get("camp") or "total").strip()
    if camp not in ALLOWED_SCORE_FIELDS:
        camp = "total"

    sign = ALLOWED_SCORE_FIELDS[camp]["sign"]

    # exercicis a tenir en compte:
    # - tots (default): tots els exercicis existents de la competició
    # - millor_1 / millor_n: primer agreguem per exercici i després triem els millors exercicis
    exerc_mode = (punt.get("exercicis") or {}).get("mode", "tots")
    ex_best_n = int(punt.get("exercicis_best_n") or 1)

    # aparells:
    app_mode = (punt.get("aparells") or {}).get("mode", "tots")
    app_ids = (punt.get("aparells") or {}).get("ids", []) or []

    aparells_qs = CompeticioAparell.objects.filter(competicio=competicio, actiu=True)
    if app_mode == "seleccionar" and app_ids:
        aparells_qs = aparells_qs.filter(id__in=app_ids)

    aparell_ids = list(aparells_qs.values_list("id", flat=True))

    # Base: inscripcions de competició
    ins_qs = Inscripcio.objects.filter(competicio=competicio)

    # filtres “compatibles” tant si són FK com si són camps simples
    ins_qs = _filter_in(ins_qs, Inscripcio, "entitat", filtres.get("entitats_in") or [])
    ins_qs = _filter_in(ins_qs, Inscripcio, "categoria", filtres.get("categories_in") or [])
    ins_qs = _filter_in(ins_qs, Inscripcio, "subcategoria", filtres.get("subcategories_in") or [])

    if filtres.get("grups_in"):
        ins_qs = ins_qs.filter(grup__in=filtres["grups_in"])

    # select_related només dels camps realment relacionals
    sr = []
    for f in ("entitat", "categoria", "subcategoria"):
        if _is_relational_field(Inscripcio, f):
            sr.append(f)
    if sr:
        ins_qs = ins_qs.select_related(*sr)


    ins_list = list(ins_qs)

    # Notes
    notes_qs = TrampoliNota.objects.filter(
        competicio=competicio,
        inscripcio__in=ins_list,
        comp_aparell_id__in=aparell_ids if aparell_ids else [],
    )
    # Si no hi ha aparells, no hi ha notes:
    if not aparell_ids:
        return {"global": []}

    # index per inscripcio
    notes_by_ins = defaultdict(list)
    for n in notes_qs:
        notes_by_ins[n.inscripcio_id].append(n)

    # calcula punts base per inscripcio
    per_particio = defaultdict(list)

    for ins in ins_list:
        notes = notes_by_ins.get(ins.id, [])
        if not notes:
            continue

        # Agrupació per exercici (si cal fer millor_1/millor_n)
        if exerc_mode in ("millor_1", "millor_n"):
            by_ex = defaultdict(list)
            for n in notes:
                by_ex[n.exercici].append(n)

            ex_scores = []
            for ex, ex_notes in by_ex.items():
                vals = [_to_float(getattr(x, camp, 0.0)) * sign for x in ex_notes]
                # agregació dins l'exercici (suma per aparells seleccionats)
                ex_score = _apply_aggregation(vals, "sum", 1)
                ex_scores.append(ex_score)

            if exerc_mode == "millor_1":
                base_vals = _pick_best(ex_scores, 1)
            else:
                base_vals = _pick_best(ex_scores, ex_best_n)
            score = sum(base_vals)

        else:
            vals = [_to_float(getattr(x, camp, 0.0)) * sign for x in notes]
            score = _apply_aggregation(vals, punt.get("agregacio"), punt.get("best_n"))

        # valors per desempats (calculats igual: suma per totes les notes disponibles)
        tie_vals = {}
        for t in desempat or []:
            tcamp = (t.get("camp") or "").strip()
            if tcamp in ALLOWED_SCORE_FIELDS:
                tsign = ALLOWED_SCORE_FIELDS[tcamp]["sign"]
                tie_vals[tcamp] = sum([_to_float(getattr(x, tcamp, 0.0)) * tsign for x in notes])
            else:
                tie_vals[tcamp] = 0.0

        pkey = _partition_key(ins, part_fields)

        if cfg_obj.tipus == "entitat":
            ent = getattr(ins, "entitat", None)
            ent_id = getattr(ent, "id", None)
            ent_nom = getattr(ent, "nom", None) or str(ent) if ent else "Sense entitat"

            per_particio[pkey].append({
                "entitat_id": ent_id,
                "entitat_nom": ent_nom,
                "inscripcio_id": ins.id,
                "participant": getattr(ins, "nom_complet", None) or getattr(ins, "nom", None) or str(ins),
                "score": score,
                "tie": tie_vals,
            })
        else:
            per_particio[pkey].append({
                "inscripcio_id": ins.id,
                "participant": getattr(ins, "nom_complet", None) or getattr(ins, "nom", None) or str(ins),
                "entitat_nom": getattr(getattr(ins, "entitat", None), "nom", None) or "",
                "score": score,
                "tie": tie_vals,
            })

    # Si és "entitat": agreguem per entitat
    out = {}

    if cfg_obj.tipus == "entitat":
        for pkey, rows in per_particio.items():
            by_ent = defaultdict(list)
            for r in rows:
                by_ent[r["entitat_nom"]].append(r)

            ent_rows = []
            for ent_nom, items in by_ent.items():
                ent_score = sum([_to_float(x["score"]) for x in items])
                # desempats a nivell d'entitat: suma també
                ent_tie = {}
                for t in desempat or []:
                    tcamp = (t.get("camp") or "").strip()
                    ent_tie[tcamp] = sum([_to_float(x["tie"].get(tcamp, 0.0)) for x in items])

                ent_rows.append({
                    "entitat_nom": ent_nom,
                    "score": ent_score,
                    "tie": ent_tie,
                    "participants": len(items),
                })

            out[pkey] = _rank(ent_rows, desempat, presentacio, entity_mode=True)

        return out

    # individual:
    for pkey, rows in per_particio.items():
        out[pkey] = _rank(rows, desempat, presentacio, entity_mode=False)
    return out


def _rank(rows, desempat, presentacio, entity_mode=False):
    # ordenació principal: score desc
    sort_keys = [("score", "desc")]

    # desempats
    for t in desempat or []:
        camp = (t.get("camp") or "").strip()
        ordre = (t.get("ordre") or "desc").lower()
        sort_keys.append((camp, ordre))

    def keyfunc(r):
        k = []
        for field, ordre in sort_keys:
            if field == "score":
                val = _to_float(r.get("score", 0.0))
            else:
                val = _to_float((r.get("tie") or {}).get(field, 0.0))
            # desc: invertim per ordenar amb sorted asc
            k.append(-val if ordre == "desc" else val)
        return tuple(k)

    rows_sorted = sorted(rows, key=keyfunc)

    # posicions amb empats segons score (i si vols, segons tota la clau)
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
            if mostrar_empats:
                # si hi ha empat amb el següent, seguim
                if idx < len(rows_sorted):
                    if keyfunc(rows_sorted[idx]) == cur_key:
                        continue
            break

    return ranked
