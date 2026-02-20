# competicio/services/import_excel.py
import unicodedata
from datetime import datetime, date
from typing import Optional, Dict, Any, Set, Tuple, List

from openpyxl import load_workbook

from ..models import Inscripcio, Competicio


def _norm_header(s: str) -> str:
    """
    Normalitza capçaleres: minúscules, sense accents, separadors -> underscore.
    Ex: 'Data de naixement' -> 'data_de_naixement'
    """
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    for ch in (" ", "-", "/", ".", ":", ";", ","):
        s = s.replace(ch, "_")
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_")


def _to_none(v):
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return v


def _parse_date(value) -> Optional[date]:
    """
    Accepta:
    - datetime/date d'Excel
    - string amb formats típics: dd/mm/yyyy o yyyy-mm-dd o dd-mm-yyyy
    """
    value = _to_none(value)
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    if isinstance(value, str):
        txt = value.strip()
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(txt, fmt).date()
            except ValueError:
                pass
    return None


# Camps coneguts (built-in) i sinònims habituals (normalitzats amb _norm_header)
# "code" = codi que farem servir a group_by i schema
BUILTIN = {
    "document": {
        "label": "Document (DNI/NIF/Passaport)",
        "syn": ["dni", "nif", "document", "document_identitat", "num_document", "numero_document", "id", "identificador"],
        "setter": lambda defaults, v: defaults.__setitem__("document", str(v).strip() if _to_none(v) is not None else None),
    },
    "nom_i_cognoms": {
        "label": "Nom i cognoms",
        "syn": ["nom_i_cognoms", "nom_cognoms", "participant", "nom_complet", "nomcomplert", "nom_i_llinatges"],
        "setter": lambda defaults, v: defaults.__setitem__("nom_i_cognoms", str(v).strip() if _to_none(v) is not None else None),
    },
    # per si ve separat:
    "nom": {
        "label": "Nom",
        "syn": ["nom", "name"],
        "setter": None,  # es tracta a banda
    },
    "cognoms": {
        "label": "Cognoms",
        "syn": ["cognoms", "apellidos", "surname", "llinatges"],
        "setter": None,  # es tracta a banda
    },
    "entitat": {
        "label": "Entitat/Club",
        "syn": ["entitat", "club", "equip", "team", "organitzacio", "organizacion"],
        "setter": lambda defaults, v: defaults.__setitem__("entitat", str(v).strip() if _to_none(v) is not None else None),
    },
    "categoria": {
        "label": "Categoria",
        "syn": ["categoria", "category", "cat"],
        "setter": lambda defaults, v: defaults.__setitem__("categoria", str(v).strip() if _to_none(v) is not None else None),
    },
    "subcategoria": {
        "label": "Subcategoria",
        "syn": ["subcategoria", "sub_categoria", "subcat", "subcategory", "nivell", "nivel"],
        "setter": lambda defaults, v: defaults.__setitem__("subcategoria", str(v).strip() if _to_none(v) is not None else None),
    },
    "sexe": {
        "label": "Sexe",
        "syn": ["sexe", "sexo", "sex", "genere", "genero", "g"],
        "setter": lambda defaults, v: defaults.__setitem__("sexe", str(v).strip() if _to_none(v) is not None else None),
    },
    "data_naixement": {
        "label": "Data naixement",
        "syn": ["data_naixement", "data_de_naixement", "naixement", "fecha_nacimiento", "birthdate", "data_nasc"],
        "setter": lambda defaults, v: defaults.__setitem__("data_naixement", _parse_date(v)),
    },
}


def _build_syn_map(competicio: Competicio) -> Dict[str, List[str]]:
    """
    Combina sinònims per defecte + configuració guardada a competicio.inscripcions_schema["synonyms"].
    Els sinònims es normalitzen a _norm_header.
    """
    syn_map = {}
    for code, cfg in BUILTIN.items():
        syn_map[code] = [_norm_header(s) for s in cfg.get("syn", [])]

    schema = competicio.inscripcions_schema or {}
    extra_syn = schema.get("synonyms") or {}
    for code, syns in extra_syn.items():
        if not isinstance(syns, list):
            continue
        syn_map.setdefault(code, [])
        syn_map[code].extend(_norm_header(s) for s in syns)

    # dedup preservant ordre
    for code, syns in syn_map.items():
        seen = set()
        out = []
        for s in syns:
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        syn_map[code] = out

    return syn_map


def importar_inscripcions_excel(fitxer, competicio: Competicio, sheet: str = "") -> Dict[str, Any]:
    """
    Importa inscripcions des d'Excel de forma adaptable:
    - Detecta headers (fila 1)
    - Mapeja camps built-in amb sinònims (configurable)
    - Qualsevol columna no mapejada -> Inscripcio.extra[code_columna]

    Duplicats:
    - Si hi ha document: update_or_create(competicio, document)
    - Si no: crea nou registre (no deduplicable fiable)
    """
    wb = load_workbook(fitxer, data_only=True)
    ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.active

    # 1) headers: norm -> (label_original, col_idx)
    headers: Dict[str, Tuple[str, int]] = {}
    for col_idx, cell in enumerate(ws[1], start=1):
        if cell.value is None:
            continue
        raw = str(cell.value).strip()
        if not raw:
            continue
        headers[_norm_header(raw)] = (raw, col_idx)

    # 2) sinònims combinats
    syn_map = _build_syn_map(competicio)

    # 3) detecta quina columna correspon a cada builtin code
    detected_builtin_col: Dict[str, str] = {}  # code -> header_norm
    header_norms = set(headers.keys())

    # primer: si hi ha match exacte pel mateix "code"
    for code in BUILTIN.keys():
        if code in header_norms:
            detected_builtin_col[code] = code

    # després: sinònims
    for code, syns in syn_map.items():
        if code in detected_builtin_col:
            continue
        for s in syns:
            if s in header_norms:
                detected_builtin_col[code] = s
                break

    def cell_value(row: int, header_norm: str):
        meta = headers.get(header_norm)
        if not meta:
            return None
        return ws.cell(row=row, column=meta[1]).value

    # 4) construcció de schema columns (builtins + extras)
    # - builtins "útils" (els que existeixen realment al model Inscripcio)
    builtin_model_fields = {"nom_i_cognoms", "categoria", "subcategoria", "entitat", "document", "sexe", "data_naixement"}
    columns_schema: List[Dict[str, Any]] = []

    def add_col(code: str, label: str, kind: str):
        columns_schema.append({"code": code, "label": label, "kind": kind})

    # builtins detectats
    for code, header_norm in detected_builtin_col.items():
        if code not in builtin_model_fields:
            continue
        label = BUILTIN.get(code, {}).get("label") or headers.get(header_norm, (code, 0))[0]
        add_col(code, label, "builtin")

    # extras (tota columna que no sigui builtin detectada)
    used_header_norms = set(detected_builtin_col.values())
    for h_norm, (raw_label, _col) in headers.items():
        if h_norm in used_header_norms:
            continue
        # evita coses típiques que no vols guardar com extra (si vols, pots ampliar)
        if h_norm in ("nom_competicio", "nom_competició", "nom_competicio_"):
            continue
        add_col(h_norm, raw_label, "extra")

    # 5) merge schema a competicio (preservant el que ja hi havia)
    existing_schema = competicio.inscripcions_schema or {}
    existing_cols = existing_schema.get("columns") or []
    if not isinstance(existing_cols, list):
        existing_cols = []

    # index per code
    existing_by_code = {c.get("code"): c for c in existing_cols if isinstance(c, dict) and c.get("code")}
    for c in columns_schema:
        code = c["code"]
        if code in existing_by_code:
            # conserva label existent si existia (per no “ballar”)
            if existing_by_code[code].get("label"):
                c["label"] = existing_by_code[code]["label"]
        existing_by_code[code] = {**existing_by_code.get(code, {}), **c}

    merged_cols = list(existing_by_code.values())
    competicio.inscripcions_schema = {
        **existing_schema,
        "columns": merged_cols,
        "synonyms": existing_schema.get("synonyms", {}),
    }
    competicio.save(update_fields=["inscripcions_schema"])

    # 6) import rows
    creats = 0
    actualitzats = 0
    ignorats = 0
    errors = 0
    noms_competicio_excel: Set[str] = set()

    for r in range(2, ws.max_row + 1):
        try:
            # captura possible nom de competició en excel (si existeix)
            for possible in ("nom_competició", "nom_competicio", "nom competicio", "nom competició"):
                h = _norm_header(possible)
                if h in headers:
                    v = _to_none(cell_value(r, h))
                    if v:
                        noms_competicio_excel.add(str(v).strip())
                    break

            defaults: Dict[str, Any] = {
                "nom_i_cognoms": None,
                "entitat": None,
                "categoria": None,
                "subcategoria": None,
                "sexe": None,
                "data_naixement": None,
            }

            # 6.1 omple builtins (excepte nom/cognoms separats)
            for code, header_norm in detected_builtin_col.items():
                if code in ("nom", "cognoms"):
                    continue
                if code not in BUILTIN:
                    continue
                setter = BUILTIN[code].get("setter")
                if setter is None:
                    continue
                setter(defaults, cell_value(r, header_norm))

            # 6.2 si no hi ha nom_i_cognoms, intenta construir-ho amb nom + cognoms
            if not defaults.get("nom_i_cognoms"):
                nom = None
                cognoms = None
                if "nom" in detected_builtin_col:
                    nom = _to_none(cell_value(r, detected_builtin_col["nom"]))
                if "cognoms" in detected_builtin_col:
                    cognoms = _to_none(cell_value(r, detected_builtin_col["cognoms"]))

                if nom or cognoms:
                    full = f"{str(nom).strip() if nom else ''} {str(cognoms).strip() if cognoms else ''}".strip()
                    defaults["nom_i_cognoms"] = full if full else None

            # sense nom no importem
            if not defaults.get("nom_i_cognoms"):
                ignorats += 1
                continue

            # 6.3 extras
            extra: Dict[str, Any] = {}
            for h_norm in headers.keys():
                if h_norm in used_header_norms:
                    continue
                v = ws.cell(row=r, column=headers[h_norm][1]).value
                v = _to_none(v)
                if v is None:
                    continue
                # guarda strings netes
                if isinstance(v, str):
                    v = v.strip()
                extra[h_norm] = v

            # 6.4 document (si existeix)
            document = None
            if "document" in detected_builtin_col:
                dv = _to_none(cell_value(r, detected_builtin_col["document"]))
                document = str(dv).strip() if dv is not None else None

            # normalitzacions suaus
            if defaults.get("sexe") is not None:
                defaults["sexe"] = str(defaults["sexe"]).strip()
            for k in ("categoria", "subcategoria", "entitat"):
                if defaults.get(k) is not None:
                    defaults[k] = str(defaults[k]).strip()

            if document:
                obj, created = Inscripcio.objects.update_or_create(
                    competicio=competicio,
                    document=document,
                    defaults={**defaults, "extra": extra},
                )
                if created:
                    creats += 1
                else:
                    actualitzats += 1
            else:
                defaults["document"] = defaults.get("document") or ""   # assegura string, però sense duplicar kwargs
                Inscripcio.objects.create(
                    competicio=competicio,
                    extra=extra,
                    **defaults,
                )                
                creats += 1

        except Exception as e:
            errors += 1
            
            print(f"[IMPORT] fila {r} error: {e}")

    return {
        "full": ws.title,
        "creats": creats,
        "actualitzats": actualitzats,
        "ignorats": ignorats,
        "errors": errors,
        "noms_competicio_excel": sorted(noms_competicio_excel),
    }