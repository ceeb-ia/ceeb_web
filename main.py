import asyncio
from collections import Counter, defaultdict
import io
import json
import sys
import pandas as pd
import os
import re
from consulta_resultats import fetch_ceeb_async, parse_ceeb_xml, xml_to_dataframe
from convert import xlsx_to_csv
import numpy as np
from assignacions import assignar_grups_hungares
import unicodedata, hashlib
import tempfile, shutil
from asgiref.sync import async_to_sync
from logs import push_log
from pathlib import Path
from logs import primera_fase, segona_fase


# Helper per convertir índex de columna (0-based) a lletra Excel, amb fallback si no hi ha xlsxwriter
try:
    from xlsxwriter.utility import xl_col_to_name as _xl_col_to_name
    def _col_letter(idx: int) -> str:
        return _xl_col_to_name(idx)
except Exception:
    def _col_letter(idx: int) -> str:
        # Conversió manual 0-based -> 'A', 'B', ..., 'Z', 'AA', ...
        if idx < 0:
            return "A"
        letters = ""
        n = idx
        while n >= 0:
            n, rem = divmod(n, 26)
            letters = chr(65 + rem) + letters
            n -= 1
        return letters



MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/data/media")
BASE_PATH = MEDIA_ROOT

def _normalize_team_key(name: str) -> str:
    s = unicodedata.normalize('NFKC', str(name or '')).casefold().strip()
    # normalitza cometes “rares”
    s = s.replace('“', '"').replace('”', '"').replace('«', '"').replace('»', '"')
    s = s.replace('’', "'").replace('`', "'")
    s = " ".join(s.split())
    return s


# De cada partit, obtenim l'equip local i visitant i mirem la seva posició a la classificació
def _get_team_position(equip: str, df_classificacions: pd.DataFrame, task_id) -> int:
    equip_norm = _normalize_team_key(equip)
    # Construeix l'set d'equips presents a la classificació (nom tal qual es mostra)
    category_teams = set()
    for _, row_df in df_classificacions.iterrows():
        team_name = row_df.get('NomEquipMostrar', '')
        if pd.isna(team_name):
            team_name = ''
        category_teams.add(_normalize_team_key(team_name))

    # Recorrem per trobar la posició (1-based) comparant noms normalitzats
    for idx, row in df_classificacions.iterrows():
        nom_equip = _normalize_team_key(row.get('NomEquipMostrar', ''))
        if nom_equip == equip_norm:
            
            return idx + 1, category_teams  # posició 1-based


    return -1, category_teams  # no trobat


def llegir_csv(nom_fitxer):
    try:
        df = pd.read_csv(nom_fitxer)
        print(df.head())  # Mostra les primeres 5 files
        return df
    except Exception as e:
        print(f"Error en llegir el fitxer: {e}")
        return None

def obtenir_entitat(nom):
        # Elimina l'espai i una sola lletra majúscula al final (ex: "Club Volei X A" -> "Club Volei X")
        return re.sub(r'\s+((["\']{1,2}).+?\2|[A-Za-zÀ-ÿ]+)$', '', nom)

def _format_diffs_excel(diffs) -> str:
    """
    Converteix una llista de diferències de jornades a text multi-línia per Excel.
    Accepta formats:
      - [(jornada, casa_fora, rival), ...]
      - [jornada1, jornada2, ...]
      - str ja formatat
    Retorna "—" si no hi ha diferències.
    """
    if diffs is None:
        return "—"
    if isinstance(diffs, str):
        s = diffs.strip()
        return s if s else "—"
    if not isinstance(diffs, (list, tuple)):
        try:
            return str(diffs)
        except Exception:
            return "—"
    if len(diffs) == 0:
        return "—"
    lines = []
    for item in diffs:
        try:
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                j = item[0]
                side = item[1]
                opp = item[2]
                try:
                    j_int = int(j)
                    j_txt = f"J{j_int}"
                except Exception:
                    j_txt = str(j)
                side_s = str(side).strip().lower()
                if side_s in ("c", "casa", "home", "local"):
                    side_txt = "Casa"
                elif side_s in ("f", "fora", "away", "visitant"):
                    side_txt = "Fora"
                else:
                    side_txt = str(side)
                lines.append(f"• {j_txt}: {side_txt} vs {opp}")
            else:
                try:
                    j_int = int(item)
                    lines.append(f"• J{j_int}")
                except Exception:
                    lines.append(f"• {item}")
        except Exception:
            lines.append(f"• {item}")
    return "\n".join(lines)

def analitzar_equitabilitat_costos(entity_costs, all_results):
    """
    Analitza si els costos s'estan repartint equitativament entre entitats.
    Retorna un diccionari amb estadístiques d'equitabilitat.
    """
    if not entity_costs:
        return {"status": "No hi ha costos d'entitat per analitzar"}
    
    # Filtrem les entitats reals (no Descans)
    costos_reals = {e: c for e, c in entity_costs.items() if e != 'Descans'}
    
    if not costos_reals:
        return {"status": "No hi ha entitats reals amb costos"}
    
    # Estadístiques bàsiques
    costos = list(costos_reals.values())
    entitats = list(costos_reals.keys())
    
    mitjana_cost = sum(costos) / len(costos)
    cost_min = min(costos)
    cost_max = max(costos)
    desviacio = np.std(costos)
    
    # Comptatge d'equips per entitat per normalitzar
    equips_per_entitat = {}
    for _, row in all_results.iterrows():
        entitat = row.get('Entitat', '')
        if entitat and entitat != 'Descans':
            equips_per_entitat[entitat] = equips_per_entitat.get(entitat, 0) + 1
    
    # Cost per equip (normalitzat)
    cost_per_equip = {}
    for entitat in costos_reals:
        num_equips = equips_per_entitat.get(entitat, 1)
        cost_per_equip[entitat] = costos_reals[entitat] / num_equips
    
    # Identifica entitats perjudicades
    threshold_alt = mitjana_cost + desviacio
    threshold_molt_alt = mitjana_cost + 2 * desviacio
    
    entitats_perjudicades = [e for e, c in costos_reals.items() if c > threshold_alt]
    entitats_molt_perjudicades = [e for e, c in costos_reals.items() if c > threshold_molt_alt]
    
    # Ràtio de desigualtat (màx/mín)
    ratio_desigualtat = cost_max / cost_min if cost_min > 0 else float('inf')
    
    return {
        "status": "Analitzat",
        "num_entitats": len(costos_reals),
        "cost_mitjà": mitjana_cost,
        "cost_min": cost_min,
        "cost_max": cost_max,
        "desviació_estàndard": desviacio,
        "ràtio_desigualtat": ratio_desigualtat,
        "entitats_perjudicades": entitats_perjudicades,
        "entitats_molt_perjudicades": entitats_molt_perjudicades,
        "costos_detallats": costos_reals,
        "cost_per_equip": cost_per_equip,
        "equips_per_entitat": equips_per_entitat
    }

def parse_int(x, default=np.nan):
    try:
        if pd.isna(x):
            return default
        v = float(x)
        if v.is_integer():
            return int(v)
        return default
    except Exception:
        return default

def normalize_seed_value(x):
    s = str(x).strip().lower()
    if s in ["casa", "fora"]:
        return s
    return parse_int(x, default=np.nan)


def _is_real_team_row(row) -> bool:
    nom = row.get("Nom", "")
    ent = row.get("Entitat", "")
    if pd.isna(nom) or str(nom).strip() == "":
        return False
    if str(ent).strip() in ("", "Descans", "—"):
        return False
    return True


def _request_type(raw_value) -> str:
    text = str(raw_value).strip().lower()
    if text == "casa":
        return "casa"
    if text == "fora":
        return "fora"
    try:
        value = int(float(raw_value))
        if 1 <= value <= 8:
            return "explicit"
    except Exception:
        pass
    return "none"


def _request_display_code(raw_value) -> str:
    req_type = _request_type(raw_value)
    if req_type == "casa":
        return "CASA"
    if req_type == "fora":
        return "FORA"
    if req_type == "explicit":
        try:
            return str(int(float(raw_value)))
        except Exception:
            return ""
    return ""


def _expected_seed(raw_value, equip_id, mapping):
    req_type = _request_type(raw_value)
    if req_type == "explicit":
        try:
            return int(float(raw_value))
        except Exception:
            return np.nan
    if req_type in {"casa", "fora"}:
        mapped = mapping.get(equip_id)
        if mapped is None:
            return np.nan
        return int(mapped)
    return np.nan


def _level_idx(val):
    text = str(val).strip()
    if not text or text in {"Descans", "—"}:
        return None
    match = re.search(r"(?i)(?:nivell\s*)?([A-E])\s*$", text)
    if match:
        return {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}.get(match.group(1).upper())
    return None


def _level_letter(idx):
    return {1: "A", 2: "B", 3: "C", 4: "D", 5: "E"}.get(idx, "")


def _pairwise_avg_distance(values):
    if len(values) < 2:
        return 0.0
    total = 0.0
    pairs = 0
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            total += abs(values[i] - values[j])
            pairs += 1
    return total / pairs if pairs else 0.0


def _entity_assignment_key_column(df):
    return "Pista joc" if "Pista joc" in df.columns else "Entitat"


def _dupla_label(dupla_idx, duples_casa_fora):
    if dupla_idx is None or dupla_idx == "":
        return ""
    try:
        casa_num, fora_num = duples_casa_fora[int(dupla_idx)]
        return f"{casa_num}/{fora_num}"
    except Exception:
        return ""


def _auto_fit_worksheet_columns(ws, df, extra_width=2, min_width=10, max_width=45, wrap_cols=None):
    wrap_cols = set(wrap_cols or [])
    for col_idx, col_name in enumerate(df.columns):
        values = [str(col_name)]
        if not df.empty:
            values.extend(str(x) for x in df[col_name].fillna("").astype(str).tolist())
        width = min(max(max(len(v) for v in values) + extra_width, min_width), max_width)
        ws.set_column(col_idx, col_idx, width)
        if col_name in wrap_cols:
            ws.set_column(col_idx, col_idx, max(width, 20))


def _write_df_block(writer, workbook, sheet_name, start_row, title, df, fmt_title, fmt_header, auto_filter=True, wrap_cols=None):
    if sheet_name not in writer.sheets:
        writer.sheets[sheet_name] = workbook.add_worksheet(sheet_name)
    ws = writer.sheets[sheet_name]
    ws.write(start_row, 0, title, fmt_title)
    if df is None or df.empty:
        ws.write(start_row + 1, 0, "Sense dades")
        return start_row + 3

    df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=start_row + 1)
    for col_idx, col_name in enumerate(df.columns):
        ws.write(start_row + 1, col_idx, col_name, fmt_header)
    if auto_filter:
        ws.autofilter(start_row + 1, 0, start_row + 1 + len(df), max(0, len(df.columns) - 1))
    _auto_fit_worksheet_columns(ws, df, wrap_cols=wrap_cols)
    return start_row + len(df) + 4


def _df_records(df):
    if df is None or df.empty:
        return []
    clean = df.copy()
    clean = clean.replace({np.nan: None})
    return clean.to_dict(orient="records")


def _json_default(value):
    if pd.isna(value):
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    return value


_METRIC_DESCRIPTIONS = {
    "Entitats analitzades": "Nombre d'entitats reals per a les quals s'ha calculat el cost/fairness acumulat.",
    "Cost mitja": "Valor mitjà del cost de fairness acumulat entre totes les entitats analitzades.",
    "Cost minim": "Cost de fairness més baix observat entre les entitats analitzades.",
    "Cost maxim": "Cost de fairness més alt observat entre les entitats analitzades.",
    "Desviacio estandard": "Dispersió dels costos de fairness entre entitats; com més alt, més desigualtat global.",
    "Ratio desigualtat": "Quocient entre el cost màxim i el cost mínim; mesura extrema de desigualtat entre entitats.",
    "Equips totals input": "Nombre total d'equips presents al fitxer d'entrada per a aquesta execució.",
    "Equips reals assignats": "Nombre d'equips reals que han acabat assignats, excloent els 'Descans' afegits com a dummy.",
    "Equips amb peticio efectiva": "Equips que fan una petició verificable de número de sorteig, sigui explícita (1..8) o CASA/FORA.",
    "Incidencia global %": "Percentatge d'equips amb petició efectiva que no han rebut el número esperat final.",
    "Incidencia total": "Nombre absolut d'equips amb petició efectiva incomplerta.",
    "Severitat total (jornades)": "Suma de totes les jornades on s'ha produït desviació respecte del calendari esperat derivat del número sol·licitat.",
    "Severitat mitjana": "Nombre mitjà de jornades afectades per cada incidència detectada.",
    "Peticions CASA/FORA": "Nombre d'equips que han fet una petició textual CASA o FORA.",
    "Compliment CASA/FORA %": "Percentatge de peticions CASA/FORA que han respectat la dupla assignada i, per tant, el número esperat associat.",
    "Dany % calendari": "Percentatge de jornades potencials afectades per incidències respecte del màxim possible sobre equips amb petició efectiva.",
    "Dummy ratio global": "Proporció de slots totals ocupats per 'Descans' per poder completar grups de 8 posicions.",
    "Complertes CASA/FORA": "Nombre de peticions CASA/FORA que han quedat satisfetes segons la dupla assignada a l'entitat.",
    "No complertes CASA/FORA": "Nombre de peticions CASA/FORA que no han quedat satisfetes segons la dupla assignada a l'entitat.",
    "Dany total (jornades)": "Suma total de jornades afectades per incompliments de número esperat.",
    "Dany per incidencia": "Mitjana de jornades afectades per cada equip amb incidència.",
    "Dany per equip assignat": "Dany total repartit entre tots els equips reals assignats, tinguin o no petició efectiva.",
    "Dany per peticio efectiva": "Dany total repartit només entre els equips amb petició efectiva.",
    "Equips esperats (input)": "Recompte d'equips d'entrada que s'esperaven processar en el run.",
    "Equips assignats (sense dummies)": "Recompte d'equips reals efectivament assignats al resultat final, excloent dummies.",
    "Estat": "Indicador resum del recompte: OK si els equips esperats i assignats coincideixen, KO en cas contrari.",
}


def _with_metric_descriptions(df):
    if df is None or df.empty or "Metrica" not in df.columns:
        return df
    out = df.copy()
    if "Descripcio" not in out.columns:
        out["Descripcio"] = out["Metrica"].map(_METRIC_DESCRIPTIONS).fillna("")
    else:
        out["Descripcio"] = out["Descripcio"].fillna(out["Metrica"].map(_METRIC_DESCRIPTIONS)).fillna("")
    metric_idx = out.columns.get_loc("Metrica")
    cols = list(out.columns)
    if "Valor" in cols and "Descripcio" in cols:
        cols.remove("Descripcio")
        cols.insert(metric_idx + 2, "Descripcio")
        out = out[cols]
    return out


def _build_indicator_tables(df_input, all_results, equip_to_num_sorteig, entitats_assigned, duples_casa_fora, entity_costs, info_totals, num_jornades):
    entity_key_col = _entity_assignment_key_column(df_input)

    input_meta_cols = ["Id", "Nom", "Entitat", "Nom Lliga", "Núm. sorteig"]
    for optional_col in ["Modalitat", "Categoria", "Subcategoria", entity_key_col]:
        if optional_col not in input_meta_cols and optional_col in df_input.columns:
            input_meta_cols.append(optional_col)

    input_meta = df_input[input_meta_cols].copy()
    input_meta = input_meta.drop_duplicates(subset=["Id"], keep="first")
    if entity_key_col not in input_meta.columns:
        input_meta[entity_key_col] = input_meta["Entitat"]

    if "Modalitat" not in input_meta.columns:
        input_meta["Modalitat"] = "Sense modalitat"
    else:
        input_meta["Modalitat"] = input_meta["Modalitat"].fillna("Sense modalitat")
    input_meta["Categoria resum"] = input_meta["Nom Lliga"].fillna("")
    input_meta["req_type"] = input_meta["Núm. sorteig"].apply(_request_type)
    input_meta["request_code"] = input_meta["Núm. sorteig"].apply(_request_display_code)
    input_meta["expected_seed"] = input_meta.apply(
        lambda row: _expected_seed(row.get("Núm. sorteig"), row.get("Id"), equip_to_num_sorteig),
        axis=1,
    )
    input_meta["is_effective_request"] = input_meta["expected_seed"].notna()

    all_real = all_results[all_results.apply(_is_real_team_row, axis=1)].copy()
    merge_cols = ["Id", "Modalitat", "Categoria", "Subcategoria", entity_key_col, "req_type", "request_code", "expected_seed", "is_effective_request"]
    analysis = all_real.merge(
        input_meta[merge_cols],
        on="Id",
        how="left",
        suffixes=("", "_input"),
    )
    analysis["Modalitat"] = analysis["Modalitat"].fillna("Sense modalitat")
    analysis["Categoria"] = analysis["Nom Lliga"].fillna("")
    analysis["assigned_seed"] = pd.to_numeric(analysis["Núm. sorteig assignat"], errors="coerce")
    analysis["mismatch_jornades"] = analysis["Diferències jornades"].apply(lambda diffs: len(diffs) if isinstance(diffs, list) else 0)
    analysis["is_mismatch"] = analysis["is_effective_request"] & (analysis["assigned_seed"] != analysis["expected_seed"])
    analysis.loc[~analysis["is_mismatch"], "mismatch_jornades"] = 0
    analysis["is_textual_request"] = analysis["req_type"].isin(["casa", "fora"])
    analysis["casa_fora_respected"] = analysis["is_textual_request"] & ~analysis["is_mismatch"]
    analysis["dupla_idx"] = analysis[entity_key_col].map(entitats_assigned)
    analysis["dupla_label"] = analysis["dupla_idx"].apply(lambda idx: _dupla_label(idx, duples_casa_fora))
    analysis["numero_casa"] = analysis["dupla_idx"].apply(
        lambda idx: duples_casa_fora[int(idx)][0] if idx == idx and idx in range(len(duples_casa_fora)) else np.nan
    )
    analysis["numero_fora"] = analysis["dupla_idx"].apply(
        lambda idx: duples_casa_fora[int(idx)][1] if idx == idx and idx in range(len(duples_casa_fora)) else np.nan
    )

    effective = analysis[analysis["is_effective_request"]].copy()
    request_incidents = effective[effective["is_mismatch"]].copy()

    fairness = analitzar_equitabilitat_costos(entity_costs, all_real)
    fairness_entities = pd.DataFrame()
    fairness_summary = pd.DataFrame()
    if fairness.get("status") == "Analitzat":
        fairness_summary = pd.DataFrame([
            {"Metrica": "Entitats analitzades", "Valor": fairness.get("num_entitats", 0)},
            {"Metrica": "Cost mitja", "Valor": fairness.get("cost_mitjà", 0.0)},
            {"Metrica": "Cost minim", "Valor": fairness.get("cost_min", 0.0)},
            {"Metrica": "Cost maxim", "Valor": fairness.get("cost_max", 0.0)},
            {"Metrica": "Desviacio estandard", "Valor": fairness.get("desviació_estàndard", 0.0)},
            {"Metrica": "Ratio desigualtat", "Valor": fairness.get("ràtio_desigualtat", 0.0)},
        ])
        fairness_summary = _with_metric_descriptions(fairness_summary)
        fairness_entities = pd.DataFrame(
            [
                {
                    "Entitat": entitat,
                    "Cost fairness total": fairness.get("costos_detallats", {}).get(entitat, 0.0),
                    "Cost fairness per equip": fairness.get("cost_per_equip", {}).get(entitat, 0.0),
                    "Equips totals": fairness.get("equips_per_entitat", {}).get(entitat, 0),
                }
                for entitat in sorted(fairness.get("costos_detallats", {}).keys(), key=lambda s: str(s).casefold())
            ]
        )

    total_input = len(input_meta)
    total_assigned = len(all_real)
    total_effective = int(analysis["is_effective_request"].sum())
    total_mismatch = int(analysis["is_mismatch"].sum())
    total_severity = int(analysis["mismatch_jornades"].sum())
    severity_avg = float(total_severity / total_mismatch) if total_mismatch else 0.0
    total_textual = int(analysis["is_textual_request"].sum())
    total_textual_respected = int(analysis["casa_fora_respected"].sum())
    casa_fora_pct = float((total_textual_respected / total_textual) * 100.0) if total_textual else 0.0
    damage_pct_calendar = float((total_severity / (total_effective * num_jornades)) * 100.0) if total_effective and num_jornades else 0.0
    total_slots = int(sum(info.get("num_slots", 0) for info in info_totals))
    total_dummies = int(sum(info.get("num_dummies", 0) for info in info_totals))
    dummy_ratio = float(total_dummies / total_slots) if total_slots else 0.0
    incidence_pct = float((total_mismatch / total_effective) * 100.0) if total_effective else 0.0

    df_kpi_global = pd.DataFrame(
        [
            {"Metrica": "Equips totals input", "Valor": total_input},
            {"Metrica": "Equips reals assignats", "Valor": total_assigned},
            {"Metrica": "Equips amb peticio efectiva", "Valor": total_effective},
            {"Metrica": "Incidencia global %", "Valor": incidence_pct},
            {"Metrica": "Incidencia total", "Valor": total_mismatch},
            {"Metrica": "Severitat total (jornades)", "Valor": total_severity},
            {"Metrica": "Severitat mitjana", "Valor": severity_avg},
            {"Metrica": "Peticions CASA/FORA", "Valor": total_textual},
            {"Metrica": "Compliment CASA/FORA %", "Valor": casa_fora_pct},
            {"Metrica": "Dany % calendari", "Valor": damage_pct_calendar},
            {"Metrica": "Dummy ratio global", "Valor": dummy_ratio},
        ]
    )
    df_kpi_global = _with_metric_descriptions(df_kpi_global)

    global_expected = effective.groupby("expected_seed").size()
    global_assigned = analysis.groupby("assigned_seed").size()
    df_global_numbers = pd.DataFrame(
        [
            {
                "Numero": num,
                "Demanats": int(global_expected.get(num, 0)),
                "Assignats": int(global_assigned.get(num, 0)),
                "Diferencia": int(global_assigned.get(num, 0) - global_expected.get(num, 0)),
            }
            for num in range(1, 9)
        ]
    )

    def _build_group_distribution(group_col):
        rows = []
        for group_value, sub in analysis.groupby(group_col, dropna=False):
            row = {
                group_col: group_value if pd.notna(group_value) else "",
                "Equips totals": int(len(sub)),
                "Equips amb peticio efectiva": int(sub["is_effective_request"].sum()),
                "Incidencia": int(sub["is_mismatch"].sum()),
                "Incidencia %": float((sub["is_mismatch"].sum() / sub["is_effective_request"].sum()) * 100.0) if sub["is_effective_request"].sum() else 0.0,
                "Severitat mitjana": float(sub.loc[sub["is_mismatch"], "mismatch_jornades"].mean()) if sub["is_mismatch"].any() else 0.0,
                "Peticions CASA/FORA": int(sub["is_textual_request"].sum()),
                "Compliment CASA/FORA %": float((sub["casa_fora_respected"].sum() / sub["is_textual_request"].sum()) * 100.0) if sub["is_textual_request"].sum() else 0.0,
                "Dany total": int(sub["mismatch_jornades"].sum()),
                "Dany % calendari": float((sub["mismatch_jornades"].sum() / (sub["is_effective_request"].sum() * num_jornades)) * 100.0) if sub["is_effective_request"].sum() and num_jornades else 0.0,
            }
            req_counts = sub["request_code"].value_counts()
            for num in range(1, 9):
                row[f"Peticio {num}"] = int(req_counts.get(str(num), 0))
                row[f"Assignat {num}"] = int((sub["assigned_seed"] == num).sum())
            row["Peticio CASA"] = int(req_counts.get("CASA", 0))
            row["Peticio FORA"] = int(req_counts.get("FORA", 0))
            rows.append(row)
        return pd.DataFrame(rows).sort_values(group_col).reset_index(drop=True) if rows else pd.DataFrame()

    df_by_modalitat = _build_group_distribution("Modalitat")
    df_by_categoria = _build_group_distribution("Categoria")

    dupla_entity_counts = Counter(entitats_assigned.values())
    text_mask = input_meta["req_type"].isin(["casa", "fora"])
    entity_text_counts = (
        input_meta.loc[text_mask]
        .groupby(entity_key_col)["Id"]
        .size()
        .to_dict()
    )
    df_duples = pd.DataFrame(
        [
            {
                "Dupla": idx,
                "Etiqueta": _dupla_label(idx, duples_casa_fora),
                "Numero CASA": casa_num,
                "Numero FORA": fora_num,
                "Entitats": int(dupla_entity_counts.get(idx, 0)),
                "Equips afectats": int(
                    sum(entity_text_counts.get(entitat, 0) for entitat, assigned_idx in entitats_assigned.items() if assigned_idx == idx)
                ),
                "Compliment CASA/FORA %": float(
                    (
                        analysis.loc[analysis["dupla_idx"] == idx, "casa_fora_respected"].sum()
                        / analysis.loc[analysis["dupla_idx"] == idx, "is_textual_request"].sum()
                    ) * 100.0
                ) if analysis.loc[analysis["dupla_idx"] == idx, "is_textual_request"].sum() else 0.0,
            }
            for idx, (casa_num, fora_num) in enumerate(duples_casa_fora)
        ]
    )

    entity_rows = []
    for entity_value, sub in analysis.groupby(entity_key_col, dropna=False):
        input_sub = input_meta[input_meta[entity_key_col] == entity_value]
        total_entity_teams = int(len(input_sub))
        effective_entity = int(sub["is_effective_request"].sum())
        mismatch_entity = int(sub["is_mismatch"].sum())
        severity_total = int(sub["mismatch_jornades"].sum())
        severity_entity_avg = float(severity_total / mismatch_entity) if mismatch_entity else 0.0
        textual_total = int(sub["is_textual_request"].sum())
        textual_respected = int(sub["casa_fora_respected"].sum())
        req_counts = input_sub["req_type"].value_counts()
        entity_rows.append(
            {
                "Entitat": entity_value,
                "Modalitats": ", ".join(sorted(set(str(x) for x in input_sub["Modalitat"].dropna() if str(x).strip()))),
                "Categories": ", ".join(sorted(set(str(x) for x in input_sub["Categoria resum"].dropna() if str(x).strip()))),
                "Equips totals": total_entity_teams,
                "Equips amb peticio efectiva": effective_entity,
                "# CASA": int(req_counts.get("casa", 0)),
                "# FORA": int(req_counts.get("fora", 0)),
                "# explicits": int(req_counts.get("explicit", 0)),
                "# indiferents/buits": int(req_counts.get("none", 0)),
                "Dupla assignada": _dupla_label(entitats_assigned.get(entity_value), duples_casa_fora),
                "Numero CASA": duples_casa_fora[int(entitats_assigned[entity_value])][0] if entity_value in entitats_assigned else np.nan,
                "Numero FORA": duples_casa_fora[int(entitats_assigned[entity_value])][1] if entity_value in entitats_assigned else np.nan,
                "Incidencia absoluta": mismatch_entity,
                "Incidencia %": float((mismatch_entity / effective_entity) * 100.0) if effective_entity else 0.0,
                "Severitat total": severity_total,
                "Severitat mitjana": severity_entity_avg,
                "Peticions CASA/FORA": textual_total,
                "Compliment CASA/FORA %": float((textual_respected / textual_total) * 100.0) if textual_total else 0.0,
                "Dany total": severity_total,
                "Dany per equip": float(severity_total / total_entity_teams) if total_entity_teams else 0.0,
                "Dany per peticio efectiva": float(severity_total / effective_entity) if effective_entity else 0.0,
                "Dany % calendari": float((severity_total / (effective_entity * num_jornades)) * 100.0) if effective_entity and num_jornades else 0.0,
            }
        )

    df_entitats = pd.DataFrame(entity_rows)
    if not fairness_entities.empty and not df_entitats.empty:
        df_entitats = df_entitats.merge(
            fairness_entities[["Entitat", "Cost fairness total", "Cost fairness per equip"]],
            on="Entitat",
            how="left",
        )
    else:
        df_entitats["Cost fairness total"] = 0.0
        df_entitats["Cost fairness per equip"] = 0.0

    if not df_entitats.empty:
        df_entitats["Cost fairness total"] = df_entitats["Cost fairness total"].fillna(0.0)
        df_entitats["Cost fairness per equip"] = df_entitats["Cost fairness per equip"].fillna(0.0)
        df_entitats = df_entitats.sort_values(["Equips totals", "Incidencia absoluta"], ascending=[False, False]).reset_index(drop=True)

    level_rows = []
    for (modalitat, categoria, grup), sub in analysis.groupby(["Modalitat", "Categoria", "Grup"]):
        idxs = [idx for idx in (_level_idx(x) for x in sub["Nivell"]) if idx is not None]
        if idxs:
            min_idx = min(idxs)
            max_idx = max(idxs)
            range_idx = max_idx - min_idx
            pairwise_avg = _pairwise_avg_distance(idxs)
            levels_present = ", ".join(sorted({_level_letter(idx) for idx in idxs}))
        else:
            min_idx = max_idx = range_idx = None
            pairwise_avg = 0.0
            levels_present = ""
        level_rows.append(
            {
                "Modalitat": modalitat,
                "Categoria": categoria,
                "Grup": grup,
                "Equips reals": int(len(sub)),
                "Nivells presents": levels_present,
                "Min nivell": _level_letter(min_idx) if min_idx else "",
                "Max nivell": _level_letter(max_idx) if max_idx else "",
                "Rang nivell": int(range_idx) if range_idx is not None else 0,
                "Distancia mitjana pairwise": float(pairwise_avg),
                "Grup AC": bool(max_idx is not None and max_idx <= 3),
                "Grup CE": bool(min_idx is not None and min_idx >= 3),
                "Grup mixt trencat": bool(min_idx is not None and max_idx is not None and min_idx <= 2 and max_idx >= 4),
            }
        )
    df_levels_group = pd.DataFrame(level_rows)

    def _summarize_levels(group_col):
        rows = []
        if df_levels_group.empty:
            return pd.DataFrame()
        for group_value, sub in df_levels_group.groupby(group_col):
            rows.append(
                {
                    group_col: group_value,
                    "Grups": int(len(sub)),
                    "% grups AC": float(sub["Grup AC"].mean() * 100.0),
                    "% grups CE": float(sub["Grup CE"].mean() * 100.0),
                    "% grups mixtos trencats": float(sub["Grup mixt trencat"].mean() * 100.0),
                    "Rang mitja": float(sub["Rang nivell"].mean()),
                    "Rang maxim": int(sub["Rang nivell"].max()),
                    "Distancia pairwise mitjana": float(sub["Distancia mitjana pairwise"].mean()),
                }
            )
        return pd.DataFrame(rows).sort_values(group_col).reset_index(drop=True)

    df_levels_category = _summarize_levels("Categoria")
    df_levels_modalitat = _summarize_levels("Modalitat")

    request_incidents = request_incidents.copy()
    if not request_incidents.empty:
        request_incidents["Esperat"] = request_incidents["expected_seed"].astype("Int64")
        request_incidents["Assignat"] = request_incidents["assigned_seed"].astype("Int64")
        request_incidents["Tipus peticio"] = request_incidents["req_type"]
        request_incidents["Mismatch jornades"] = request_incidents["mismatch_jornades"].astype(int)
        request_incidents = request_incidents[
            ["Entitat", "Modalitat", "Categoria", "Grup", "Nom", "Tipus peticio", "Esperat", "Assignat", "Mismatch jornades", "Diferències jornades"]
        ].rename(columns={"Nom": "Equip"})

    top_entities = df_entitats.head(15).copy() if not df_entitats.empty else pd.DataFrame()
    summary_modalitat = df_by_modalitat[
        ["Modalitat", "Equips totals", "Equips amb peticio efectiva", "Incidencia", "Incidencia %", "Severitat mitjana"]
    ].copy() if not df_by_modalitat.empty else pd.DataFrame()
    casa_fora_summary = _with_metric_descriptions(pd.DataFrame(
        [
            {"Metrica": "Peticions CASA/FORA", "Valor": total_textual},
            {"Metrica": "Complertes CASA/FORA", "Valor": total_textual_respected},
            {"Metrica": "No complertes CASA/FORA", "Valor": int(total_textual - total_textual_respected)},
            {"Metrica": "Compliment CASA/FORA %", "Valor": casa_fora_pct},
        ]
    ))
    damage_summary = _with_metric_descriptions(pd.DataFrame(
        [
            {"Metrica": "Dany total (jornades)", "Valor": total_severity},
            {"Metrica": "Dany per incidencia", "Valor": severity_avg},
            {"Metrica": "Dany per equip assignat", "Valor": float(total_severity / total_assigned) if total_assigned else 0.0},
            {"Metrica": "Dany per peticio efectiva", "Valor": float(total_severity / total_effective) if total_effective else 0.0},
            {"Metrica": "Dany % calendari", "Valor": damage_pct_calendar},
        ]
    ))

    return {
        "analysis": analysis,
        "request_incidents": request_incidents,
        "kpi_global": df_kpi_global,
        "global_numbers": df_global_numbers,
        "by_modalitat": df_by_modalitat,
        "by_categoria": df_by_categoria,
        "duples": df_duples,
        "fairness_summary": fairness_summary,
        "fairness_entities": fairness_entities,
        "entitats": df_entitats,
        "levels_group": df_levels_group,
        "levels_category": df_levels_category,
        "levels_modalitat": df_levels_modalitat,
        "summary_modalitat": summary_modalitat,
        "top_entities": top_entities,
        "casa_fora_summary": casa_fora_summary,
        "damage_summary": damage_summary,
    }



def crear_grups_equilibrats(num_equips, max_grup=8):
    """
    Dona el nombre d'equips, retorna una llista amb el nombre d'equips per grup,
    procurant que tots els grups tinguin el nombre més igual possible d'equips,
    i cap grup tingui més de max_grup equips.
    """
    # Nombre mínim de grups necessaris
    num_grups = (num_equips + max_grup - 1) // max_grup

    while True:
        base = num_equips // num_grups
        sobra = num_equips % num_grups
        grups = [base + 1 if i < sobra else base for i in range(num_grups)]
        if max(grups) <= max_grup:
            return grups
        num_grups += 1



def obtenir_entitat(nom):
    # Deducció senzilla del nom de l'entitat (es pot adaptar segons el format real)
    import re
    return re.sub(r'\s+((["\']{1,2}).+?\2|[A-Za-zÀ-ÿ]+)$', '', str(nom)).strip()



def _normalize_entity_name(name: str) -> str:
    # treu variacions d’accents/espais/majús-minus
    s = unicodedata.normalize('NFKC', str(name)).casefold().strip()
    s = " ".join(s.split())  # col·lapsa espais múltiples
    return s

def processar_dades_2(df, nom_fitxer="dades.csv", task_id=None, segona_fase_bool=False):
    print(df.head())
    entity_costs = {}
    
    map_modalitat_nom = pd.read_csv("map_modalitat_nom.csv", delimiter=';')

    # Llista per recollir equips que no s'ha pogut detectar a la classificació
    missing_classifications = []
    if segona_fase_bool:
        fase = segona_fase
    else:
        fase = primera_fase

    # Assegurem columnes mínimes
    cols_ok = {'Nom', 'Entitat', 'Nom Lliga', 'Nivell', 'Núm. sorteig', 'Dia partit', 'Categoria'}
    missing = cols_ok - set(df.columns)
    print("Columnes del DataFrame:", df.columns)
    if missing:
        print(f"Falten columnes necessàries: {missing}")
        if task_id:
            async_to_sync(push_log)(task_id, f"ERROR: Falten columnes necessàries: {missing}", 100)
        raise ValueError(f"Falten columnes necessàries: {missing}")

    df = df.copy()
    
    if 'Entitat' not in df.columns:
        if task_id:
            async_to_sync(push_log)(task_id, "Falta la columna 'Entitat' i no es pot deduir automàticament.", 100)
        sys.exit("Falta la columna 'Entitat' i no es pot deduir automàticament.")

        df['Entitat'] = df['Nom'].apply(obtenir_entitat)

    if 'Id' in df.columns:
        # fem el drop
        df = df.drop(columns=['Id'])
    # Afegim un Id estable per a cada equip basat en Nom i Nom Lliga
    if 'Id' not in df.columns:
        def _mk_id(row):
            nom = _normalize_entity_name(row.get('Nom', ''))
            lliga = _normalize_entity_name(row.get('Nom Lliga', ''))
            cat = _normalize_entity_name(row.get('Categoria', '')) 

            key = f"{nom}|{lliga}|{cat}"
            return hashlib.sha1(key.encode('utf-8')).hexdigest()[:10].upper()
        if task_id:
            async_to_sync(push_log)(task_id, "Assignant Ids als equips...", 20)
        df['Id'] = df.apply(_mk_id, axis=1)

    # Abans de construir el mapping, verifiquem incoherències: un mateix equip (Id)
    # no pot demanar alhora 'CASA' i 'FORA' en diferents categories.
    s_lower_req = df['Núm. sorteig'].astype(str).str.strip().str.lower()
    df_req = df[s_lower_req.isin(['casa', 'fora'])]
    if not df_req.empty:
        mix = (
            df_req.groupby('Id')['Núm. sorteig']
                 .apply(lambda s: set(str(x).strip().lower() for x in s))
        )
        bad = mix[mix.apply(lambda st: len(st) > 1)]
        if not bad.empty:
            details = []
            for equip_id, st in bad.items():
                cats = df_req[df_req['Id'] == equip_id][['Nom', 'Nom Lliga', 'Núm. sorteig']].drop_duplicates()
                nom_equip = cats['Nom'].iloc[0] if not cats.empty else '(desconegut)'
                cats_list = "; ".join(
                    f"{str(row['Nom Lliga'])} → {str(row['Núm. sorteig']).strip()}" for _, row in cats.iterrows()
                )
                details.append(f"- {nom_equip} [Id={equip_id}]: {', '.join(sorted(st))} · {cats_list}")
            msg = (
                "ERROR: El mateix equip té peticions 'CASA' i 'FORA' en categories diferents. "
                "Un equip només pot demanar un tipus. Equips afectats:\n" + "\n".join(details)
            )
            print(msg)
            if task_id:
                async_to_sync(push_log)(task_id, msg, 100)
            sys.exit(msg)

    # Calculem el nombre total de jornades que juga la entitat
    total_jornades = len(fase)
    
    # -------------------------------------------------------
    # Assignem a cada entitat casa/fora un numero de sorteig.
    # -------------------------------------------------------

    # 1) Commptem "enllaços" d'entitats que han demanat casa/fora amb altres que també han demanat
    entitats_links = {}
    # Per cada entitat del df
    if task_id:
        async_to_sync(push_log)(task_id, "Analitzant números de sorteig per assignacions casa/fora...", 30)
    for _, row in df.iterrows():
        entitat = row['Entitat']
        if "Pista joc" in df.columns:
            entitat = row['Pista joc']
        peticio = str(row['Núm. sorteig']).strip().lower()
        if peticio not in ('casa', 'fora'):
            continue
        if entitat in entitats_links:
           continue
        entitats_links[entitat] = set()

        # Repassem tots els equips de l'entitat que han demanat casa/fora
        # NOMÉS categories on aquesta entitat ha demanat casa/fora
        if "Pista joc" in df.columns:
            equips_entitat_req = df[
                (df['Pista joc'] == entitat) &
                (df['Núm. sorteig'].astype(str).str.strip().str.lower().isin(['casa', 'fora']))
            ]
        else:
            equips_entitat_req = df[
                (df['Entitat'] == entitat) &
                (df['Núm. sorteig'].astype(str).str.strip().str.lower().isin(['casa', 'fora']))
            ]
        # Obtenim les categories d'aquests equips
        categories_entitat = equips_entitat_req['Nom Lliga'].dropna().unique()

        # Dins de cada categoria, mirem altres equips que han demanat casa/fora
        for cat in categories_entitat:
            equips_cat = df[df['Nom Lliga'] == cat]
            for _, r in equips_cat.iterrows():
                equip = r['Id']
                entitat2 = r['Pista joc'] if "Pista joc" in df.columns else r['Entitat']
                peticio2 = str(r['Núm. sorteig']).strip().lower()
                if entitat2 != entitat and peticio2 in ('casa', 'fora'):
                    entitats_links[entitat].add(equip)

    # Ara, endrecem les entitats en funció del nombre d'enllaços (desempat pel nom d'entitat)
    entitats_links = {k: v for k, v in sorted(
        entitats_links.items(),
        key=lambda item: (-len(item[1]), str(item[0]).casefold())
    )}
    #print ("Entitats i nombre d'enllaços:", {k: len(v) for k, v in entitats_links.items()})

    # Orientem cada dupla com (CASA, FORA) segons preferits_casa/fora
    # 1↔5, 6↔2, 7↔3, 8↔4 per garantir que 'casa' cau a {8,6,7,1} i 'fora' a {5,4,3,2}
    duples_casa_fora = [(1,5), (6,2), (7,3), (8,4)]
    preferencies_entitat = {}
    # Recorrem les entitats en ordre d'importància (més enllaços primer)
    for entitat in list(entitats_links.keys()):  # preserva l'ordre establert i el fa explícit
        entitat_count = {} # {idx_dupla : count}
        
        # Ens assegurem que totes les duples estan representades
        for id_ in range(len(duples_casa_fora)):
            entitat_count.setdefault(id_, 0)

        # Per aquesta entitat, observem el panorama de números de sorteig que es pot trobar per
        # assignar la millor dupla casa/fora possible.
        # Categories on aquesta entitat HA DEMANAT casa/fora (no totes on juga)
        if "Pista joc" in df.columns:
            cats_req = (
                df.loc[
                    (df['Pista joc'] == entitat) &
                    (df['Núm. sorteig'].astype(str).str.strip().str.lower().isin(['casa', 'fora'])),
                    'Nom Lliga'
                ].dropna().unique()
            )
        else:
            cats_req = (
                df.loc[
                    (df['Entitat'] == entitat) &
                    (df['Núm. sorteig'].astype(str).str.strip().str.lower().isin(['casa', 'fora'])),
                    'Nom Lliga'
                ].dropna().unique()
            )

        for categoria in sorted(cats_req, key=lambda s: str(s).casefold()):
            cat = str(categoria).strip()
            #print(f"Analitzant entitat '{entitat}' a la categoria '{categoria}'...")
            # Recollim els números de sorteig demanats en aquesta categoria
            equips_cat = df[df['Nom Lliga'] == categoria]
            #print(f"  Equips a categoria '{categoria}': {len(equips_cat)}")
            # Fem value counts dels números de sorteig
            #print("  Comptatge de números de sorteig a la categoria:", equips_cat['Núm. sorteig'].value_counts().to_dict())
            for _, r_cat in equips_cat.iterrows():
                seed = normalize_seed_value(r_cat['Núm. sorteig'])
                if not pd.isna(seed):
                    # Identifiquem la dupla casa fora a la que pertany el seed
                    for id_, (casa, fora) in enumerate(duples_casa_fora):
                        if seed == casa or seed == fora:
                            entitat_count[id_] = entitat_count.get(id_, 0) + 1
                            #print(f"Entitat '{entitat}' veu el número {seed} a la categoria '{categoria}' (dupla {id_})")
                            break

            #print(f"Comptatge de duples per l'entitat '{entitat}' a la categoria '{categoria}': {entitat_count}")

        # Si no hi ha cap compte (per ex. només hi ha peticions textuals casa/fora), fem un fallback estable
        if sum(entitat_count.values()) == 0:

            h = int(hashlib.sha1(_normalize_entity_name(entitat).encode('utf-8')).hexdigest(), 16)
            entitat_count = {h % len(duples_casa_fora): 0}
        # Triem l'ordre de preferència de les duples endreçant per nombre ascendent d'aparicions
        entitat_count = dict(sorted(entitat_count.items(), key=lambda item: item[1]))
        # Guardem l'ordre de preferència per aquesta entitat
        preferencies_entitat[entitat] = entitat_count
        print(f"Preferències de duples per l'entitat '{entitat}': {preferencies_entitat[entitat]}")


    if task_id:
        async_to_sync(push_log)(task_id, "Assignant números de sorteig als equips segons preferències...", 50)


    # Ids dels equips que han demanat 'casa' o 'fora' (textual) per cada entitat
    mask_textual = df['Núm. sorteig'].astype(str).str.strip().str.lower().isin(['casa', 'fora'])

    if "Pista joc" in df.columns:
        ids_textuals_per_entitat = (
            df.loc[mask_textual, ['Pista joc', 'Id']]
            .dropna(subset=['Pista joc', 'Id'])
            .groupby('Pista joc')['Id']
            .apply(lambda s: set(s.values))
            .to_dict()
        )
    else:
        ids_textuals_per_entitat = (
            df.loc[mask_textual, ['Entitat', 'Id']]
            .dropna(subset=['Entitat', 'Id'])
            .groupby('Entitat')['Id']
            .apply(lambda s: set(s.values))
            .to_dict()
        )


    # Ara, tornem a recorrer tots els equips de cada entitat que han demanat casa/fora i, per cada
    # equip que ha demanat casa/fora, assignem el número de sorteig segons la preferència de l'entitat
    ids_assigned_per_dupla = {0: set(), 1: set(), 2: set(), 3: set()}
    equip_to_num_sorteig = {}
    entitats_assigned = {}
    for entitat, preferencies in preferencies_entitat.items():
        print(f"Processant entitat '{entitat}' per assignar números de sorteig...")
        if "Pista joc" in df.columns:
            equips_entitat = df[
                (df['Pista joc'] == entitat) & mask_textual
            ].copy()
        
        else:
            equips_entitat = df[
                (df['Entitat'] == entitat) & mask_textual
            ].copy()

        links = set(entitats_links.get(entitat, []))  # Ids d'equip "enllaçats" amb aquesta entitat

        total_assigned_ids = set().union(*ids_assigned_per_dupla.values())

        #print("  links:", len(links))
        #print("  assigned_ids:", len(total_assigned_ids))
        #print("  overlap links∩assigned:", len(links & total_assigned_ids))

        # Conflictes per dupla = quants Ids enllaçats ja estan assignats a aquella dupla
        duples_ocupades = Counter({
            d: len(links & ids_assigned_per_dupla[d])
            for d in range(len(duples_casa_fora))
        })
        #print("  duples_ocupades:", dict(duples_ocupades))

        # Tria la dupla amb menys conflictes, respectant ordre de preferència
        tupla_preferida = None
        min_conflictes = float('inf')

        for pref in preferencies.keys():  # IMPORTANT: no sorted()
            c = duples_ocupades.get(pref, 0)
            if c < min_conflictes:
                min_conflictes = c
                tupla_preferida = pref

        if tupla_preferida is None:
            tupla_preferida = next(iter(preferencies.keys()), None)
            min_conflictes = duples_ocupades.get(tupla_preferida, 0)

        #print(f"  Dupla assignada a l'entitat '{entitat}': {tupla_preferida} (conflictes: {min_conflictes})")


        casa_num, fora_num = duples_casa_fora[tupla_preferida]
        for _, equip in equips_entitat.iterrows():
            req = str(equip['Núm. sorteig']).strip().lower()
            if req == 'casa':
                if casa_num not in [8,7,6,1]:

                    if task_id:
                        async_to_sync(push_log)(task_id, "Número de sorteig assignat a 'casa' no vàlid", 100)
                    sys.exit("Número de sorteig assignat a 'casa' no vàlid")
                prev = equip_to_num_sorteig.get(equip['Id'])
                if prev is not None and prev != casa_num:
                    msg = (
                        f"ERROR: Conflicte de mapping per a l'equip '{equip['Id']}'. "
                        f"Ja tenia assignat {prev} i s'està intentant assignar {casa_num} (CASA)."
                    )

                    if task_id:
                        async_to_sync(push_log)(task_id, msg, 100)
                    sys.exit(msg)
                equip_to_num_sorteig[equip['Id']] = casa_num
            elif req == 'fora':
                if fora_num not in [5,4,3,2]:

                    if task_id:
                        async_to_sync(push_log)(task_id, "Número de sorteig assignat a 'fora' no vàlid", 100)
                    sys.exit("Número de sorteig assignat a 'fora' no vàlid")
                prev = equip_to_num_sorteig.get(equip['Id'])
                if prev is not None and prev != fora_num:
                    msg = (
                        f"ERROR: Conflicte de mapping per a l'equip '{equip['Id']}'. "
                        f"Ja tenia assignat {prev} i s'està intentant assignar {fora_num} (FORA)."
                    )

                    if task_id:
                        async_to_sync(push_log)(task_id, msg, 100)
                    sys.exit(msg)
                equip_to_num_sorteig[equip['Id']] = fora_num
            else: 

                if task_id:
                    async_to_sync(push_log)(task_id, f"Petició de número de sorteig no vàlida per a l'equip '{equip['Id']}' (ha de ser 'casa' o 'fora')", 100)
                sys.exit("Petició de número de sorteig no vàlida (ha de ser 'casa' o 'fora')")

        # Guardem la dupla assignada a aquesta entitat
        entitats_assigned[entitat] = tupla_preferida

        # IMPORTANT: actualitza l'acumulat d'Ids assignats per aquesta dupla
        ids_assigned_per_dupla[tupla_preferida] |= ids_textuals_per_entitat.get(entitat, set())
            
    #print("Assignació de números de sorteig per equips (segons peticions):", equip_to_num_sorteig)
    # Resum i comptatge de duples assignades
    counts = Counter(entitats_assigned.values())
    resum_duples = []
    for idx in range(len(duples_casa_fora)):
        casa, fora = duples_casa_fora[idx]
        resum_duples.append({
            "Dupla": idx,
            "Casa": casa,
            "Fora": fora,
            "#Entitats": int(counts.get(idx, 0)),
        })
    print("Repartiment de duples (comptatge per idx):", dict(counts))
    print("Detall duples:", resum_duples)    


    # En cas que estiguem a la segona fase, hem de consultar les classificacions
    if segona_fase_bool:
        print("Segona fase: processant classificacions prèvies...")
        if task_id:
            async_to_sync(push_log)(task_id, "Consultant classificacions per equips... (això pot portar uns minuts)", 60)
        # Agrupem tot el df per modalidat
        # Recull d'equips que apareixen a la classificació però no s'han utilitzat
        unused_classification_teams = []

        df_grouped_modalitat = df.groupby(['Modalitat', 'Categoria', 'Subcategoria'])
        for (modalitat, categoria, subcategoria), df_modalitat in df_grouped_modalitat:

            print(f"Processant modalitat '{modalitat}, {categoria}, {subcategoria}' amb {len(df_modalitat)} equips...")
            map_modalitat = map_modalitat_nom.loc[map_modalitat_nom['Modalitat'] == modalitat]
            p2 = map_modalitat[map_modalitat["Nom"] == categoria]  # agafem el primer (només n'hi ha un)
            if subcategoria == "MIXT":
                p5 = "SXMIX"
            elif subcategoria == "FEMENÍ" or subcategoria == "FEMENI" or subcategoria == "FEM" or subcategoria == "F":
                p5 = "SXFEM"
            else:
                raise ValueError(f"Subcategoria desconeguda: {subcategoria}")

            # ------------ Consultem classificacions actualitzades ------------
            #print("P2:", p2, "P5:", p5)
            root = asyncio.run(fetch_ceeb_async(str(p2["Id Categoria"].values[0]), p5))   #(idModalitat, Sexe/Subcategoria)
            if root is None:
                print(f"Error fetching classifications for modalitat: {modalitat}")
                continue
            parsed = parse_ceeb_xml(root)
            #print("Parsed XML:", parsed)
            classificacions_list = xml_to_dataframe(parsed)
            OUTPUT_COLUMNS = ['NomEquipMostrar', 'isBaixa', 'PJ', 'PG', 'PE', 'PP', 'PUNTS', 'PUNTSBASE', 'PUNTSTOTALSAMBVALORS', 'PUNTSVALORS', 'PUNTSVALORSESPORTISTA', 'PUNTSVALORSTECNIC', 'PUNTSVALORSFAMILIAR', 'AVG', 'PF', 'PC', 'SANC', 'BONIF', 'NOPRESENTAT']

            print(f"Classificació obtinguda per modalitat '{modalitat}, {categoria}, {subcategoria}':")
            print(classificacions_list)

            # Per cada equip de la modalitat, obtenim la seva posició a la classificació
            used_teams = set()
            total_teams = set()
            for idx, row in df_modalitat.iterrows():
                posicio = -1
                equip_id = row['Id']
                equip_nom = row['Nom']
                lliga_nom = row['Nom Lliga']

                # Busquem en la llista de classificacions de cada grup l'equip que es digui igual
                # clau fixa del “context” de la classificació (no depèn del Nom Lliga de l’Excel)
                ctx = f"{modalitat}||{categoria}||{subcategoria}"

                for idx2, df_grup in enumerate(classificacions_list):
                    posicio, category_teams_raw = _get_team_position(equip_nom, df_grup, task_id)

                    grup_id = f"G{idx2}"

                    # equips totals del grup (preservant variants)
                    group_team_tags = {
                        f"{_normalize_team_key(t)}||{ctx}||{grup_id}"
                        for t in category_teams_raw
                    }
                    total_teams.update(group_team_tags)

                    if posicio != -1:
                        found_tag = f"{_normalize_team_key(equip_nom)}||{ctx}||{grup_id}"
                        used_teams.add(found_tag)
                        break

                if posicio == -1:
                    print(f"    → NO TROBAT a cap grup per la modalitat '{modalitat}, {categoria}, {subcategoria}'")
                    #if task_id:
                    #    async_to_sync(push_log)(task_id, f"Equip '{equip_nom}' no trobat a la classificació de la modalitat '{modalitat}, {categoria}, {subcategoria}'. Revisa que el nom sigui correcte.", 99)
                    # recollim l'equip com a "no trobat" per full extra (segona fase)
                    missing_classifications.append({
                        'Modalitat': modalitat,
                        'Categoria': categoria,
                        'Subcategoria': subcategoria,
                        'Nom Lliga': row.get('Nom Lliga', ''),
                        'Id': equip_id,
                        'Nom': equip_nom,
                        'Motiu': 'No trobat a la classificació'
                    })
                    posicio = 10  # no trobat
                top = posicio <= 4 and posicio >= 0
                print(f"    → Posició final assignada: {posicio} (Top3: {top})")
                # Guardem la posició numèrica en una columna separada i
                # la columna `Posició Classificació` com a boolean indicant Top3
                df.loc[df['Id'] == equip_id, 'Posició Classificació Num'] = posicio
                df.loc[df['Id'] == equip_id, 'Posició Classificació'] = bool(top)

            # Unused teams for THIS modalitat: apareixien a la classificació però no s'han utilitzat
            unused_teams_modalitat = total_teams - used_teams
            print(f"Total equips a la classificació: {len(total_teams)} modalitat {modalitat}, equips utilitzats: {len(used_teams)}, no utilitzats: {len(unused_teams_modalitat)}")

            if unused_teams_modalitat:
                print(f"Equips no utilitzats a la classificació (modalitat {modalitat}): {unused_teams_modalitat}")
                for entry in sorted(unused_teams_modalitat):
                    try:
                        parts = entry.split('||')
                        team_name = parts[0] if len(parts) > 0 else entry
                        modalitat_name = parts[1] if len(parts) > 1 else ''
                        categoria_name = parts[2] if len(parts) > 2 else ''
                        subcat_name = parts[3] if len(parts) > 3 else ''
                        grup_name = parts[4] if len(parts) > 4 else ''
                    except Exception:
                        team_name = entry
                        modalitat_name = ''
                        categoria_name = ''
                        subcat_name = ''
                        grup_name = ''

                    unused_classification_teams.append({
                        'Modalitat': modalitat_name or modalitat,
                        'Categoria': categoria_name or categoria,
                        'Subcategoria': subcat_name or subcategoria,
                        'Nom Lliga': f"{modalitat_name} {categoria_name} {subcat_name}".strip(),
                        'Nom': team_name,
                        'Grup': grup_name,
                        'Motiu': "Present a la classificació però no trobat a l'input"
                    })

        print(f"Equips no utilitzats a la classificació (TOTAL): {len(unused_classification_teams)}")
        if len(unused_classification_teams) > 0:
            df_unused = pd.DataFrame(unused_classification_teams)
            print(df_unused)




        # Per totes les files del df, comprovem si tenen posició de classificació assignada, sino els hi donem False
        for idx, row in df.iterrows():
            if 'Posició Classificació Num' not in df.columns or pd.isna(row['Posició Classificació Num']):
                df.at[idx, 'Posició Classificació Num'] = 10  # no trobat
            if 'Posició Classificació' not in df.columns or pd.isna(row['Posició Classificació']):
                df.at[idx, 'Posició Classificació'] = False  # no trobat


        # Mostrem el DataFrame amb les posicions assignades
        print("DataFrame amb posicions de classificació assignades:")
        print(df[['Nom', 'Nom Lliga', 'Modalitat', 'Categoria', 'Subcategoria', 'Posició Classificació Num']])    



    categories = sorted(df['Nom Lliga'].dropna().unique())

    resultats_totals = []
    info_totals = []

    for num_cat, categoria in enumerate(categories):

        df_cat = df[df['Nom Lliga'] == categoria].copy()
        print(f"Processant categoria '{categoria}' amb {len(df_cat)} equips...")

        if task_id:
            # Normalitzem entre 50 i 100 la progressió
            prog = (50 + (num_cat + 1)*40 // len(categories))
            async_to_sync(push_log)(task_id, f"Processant categoria '{categoria}' amb {len(df_cat)} equips...", prog)
        if df_cat.empty:
            continue

        try:
            # Pots ajustar max_grup/min_grup i pesos segons necessitats
            res_df, entity_costs, info = assignar_grups_hungares(
                df_cat,
                max_grup=8,
                min_grup=6,
                entity_costs=entity_costs,
                equips_to_num_sorteig=equip_to_num_sorteig.copy(),
                fase=fase,
                weights={'w_dif_sorteig': np.log2(27)},
                segona_fase_bool=segona_fase_bool,
            )
        except ValueError as e:
            # p.ex. una entitat té més equips que grups (no factible separar)
            print(f"[{categoria}] ERROR d'assignació: {e}")
            continue



        '''# Desa CSV per categoria
        safe = "".join(c for c in categoria if c.isalnum() or c in "._- ").strip().replace(" ", "_")
        out_path = os.path.join(BASE_PATH, f"csv_generats/assignacio_{safe}.csv")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        res_df.to_csv(out_path, index=False, encoding="utf-8-sig")

        print(f"[OK] {categoria} → {out_path}")
        print("Info:", info)'''

        # Si estem a la segona fase, afegim la columna 'Posició Classificació'
        # a l'output per categoria, fent mapping des del `df` original via `Id`.
        if segona_fase_bool and 'Posició Classificació Num' in df.columns:
            pos_map = df[df['Nom Lliga'] == categoria].set_index('Id')['Posició Classificació Num'].to_dict()
            res_df = res_df.copy()
            if 'Id' in res_df.columns:
                res_df['Posició Classificació Num'] = res_df['Id'].map(pos_map).fillna('')
            else:
                res_df['Posició Classificació Num'] = ''

        resultats_totals.append(res_df.assign(_Categoria=categoria))
        info_totals.append({'categoria': categoria, **info})


    
    # --- PREPARA VALIDACIONS PER ESCRIURE A L'EXCEL (si hi ha resultats) ---
    if task_id:
        async_to_sync(push_log)(task_id, "Preparant excel final", 92)
    df_val_count_summary = pd.DataFrame()
    df_val_count_by_cat = pd.DataFrame()
    df_val_entity_conflicts = pd.DataFrame(columns=["Categoria", "Grup", "Entitat", "Count"])
    df_val_level_spread = pd.DataFrame(columns=["Categoria", "Grup", "Nivells", "Min", "Max", "Dif"])
    metrics_pack = {}

    if resultats_totals:
        all_results = pd.concat(resultats_totals, ignore_index=True)
        metrics_pack = _build_indicator_tables(
            df,
            all_results,
            equip_to_num_sorteig,
            entitats_assigned,
            duples_casa_fora,
            entity_costs,
            info_totals,
            len(fase),
        )

        input_total = len(df)
        assigned_total = len(metrics_pack["analysis"])
        status = "OK" if input_total == assigned_total else "KO"
        df_val_count_summary = pd.DataFrame([
            {"Metrica": "Equips esperats (input)", "Valor": input_total},
            {"Metrica": "Equips assignats (sense dummies)", "Valor": assigned_total},
            {"Metrica": "Estat", "Valor": status},
        ])
        df_val_count_summary = _with_metric_descriptions(df_val_count_summary)

        per_cat_in = df.groupby("Nom Lliga").size().rename("Esperats").to_frame()
        per_cat_assigned = metrics_pack["analysis"].groupby("Categoria").size().rename("Assignats").to_frame()
        df_val_count_by_cat = (
            per_cat_in.join(per_cat_assigned, how="outer")
            .fillna(0)
            .reset_index()
            .rename(columns={"Nom Lliga": "Categoria"})
        )
        df_val_count_by_cat["Esperats"] = df_val_count_by_cat["Esperats"].astype(int)
        df_val_count_by_cat["Assignats"] = df_val_count_by_cat["Assignats"].astype(int)
        df_val_count_by_cat["OK"] = df_val_count_by_cat["Esperats"] == df_val_count_by_cat["Assignats"]

        rows_conf = []
        for cat, df_cat_res in metrics_pack["analysis"].groupby("Categoria"):
            for grup, df_grup in df_cat_res.groupby("Grup"):
                ents = [e for e in df_grup["Entitat"].tolist() if e and e != "Descans"]
                if not ents:
                    continue
                cnt = pd.Series(ents).value_counts()
                for entitat, c in cnt.items():
                    if c > 1:
                        rows_conf.append({"Categoria": cat, "Grup": grup, "Entitat": entitat, "Count": int(c)})
        if rows_conf:
            df_val_entity_conflicts = pd.DataFrame(rows_conf)

        if not metrics_pack["levels_group"].empty:
            spread_rows = []
            for _, row in metrics_pack["levels_group"].iterrows():
                if int(row["Rang nivell"]) >= 3:
                    spread_rows.append({
                        "Categoria": row["Categoria"],
                        "Grup": row["Grup"],
                        "Nivells": row["Nivells presents"],
                        "Min": row["Min nivell"],
                        "Max": row["Max nivell"],
                        "Dif": int(row["Rang nivell"]),
                    })
            if spread_rows:
                df_val_level_spread = pd.DataFrame(spread_rows)


    # --- DESPRÉS DEL BUCLE PER CATEGORIES ---
    # Escriu tot en un sol Excel amb format
    # Agafem el nom sense l'extensio
    nom_fitxer = os.path.splitext(os.path.basename(nom_fitxer))[0]
    excel_path = os.path.join(BASE_PATH, f"assignacions_{nom_fitxer}.xlsx")
    kpis_path = os.path.join(BASE_PATH, f"kpis_{nom_fitxer}.json")
    os.makedirs(os.path.dirname(excel_path), exist_ok=True)
    output = io.BytesIO()
    df_incidents = pd.DataFrame()
    with pd.ExcelWriter(excel_path, engine="xlsxwriter") as writer:
        workbook = writer.book

        # Formats
        fmt_header = workbook.add_format({
            "bold": True, "align": "center", "valign": "vcenter",
            "bg_color": "#1F4E78", "font_color": "white", "border": 1
        })
        fmt_title = workbook.add_format({
            "bold": True, "font_size": 14, "align": "left", "valign": "vcenter"
        })
        fmt_default = workbook.add_format({"text_wrap": True, "border": 1})
        fmt_wrap = workbook.add_format({"text_wrap": True, "border": 1})
        fmt_group_colors = {
            # ajusta colors si vols (8 → blau, 7 → verd, 6 → taronja, 5 → gris, etc.)
            1: workbook.add_format({"bg_color": "#E2EFDA"}),  # verd clar
            2: workbook.add_format({"bg_color": "#FFF2CC"}),  # groc clar
            3: workbook.add_format({"bg_color": "#FCE4D6"}),  # salmó
            4: workbook.add_format({"bg_color": "#E7E6E6"}),  # gris clar
            5: workbook.add_format({"bg_color": "#DDEBF7"}),  # blau clar
            6: workbook.add_format({"bg_color": "#E2EFDA"}),
            7: workbook.add_format({"bg_color": "#FFF2CC"}),
            8: workbook.add_format({"bg_color": "#FCE4D6"}),
            9: workbook.add_format({"bg_color": "#E7E6E6"}),
            10: workbook.add_format({"bg_color": "#DDEBF7"}),
            11: workbook.add_format({"bg_color": "#E2EFDA"}),
            12: workbook.add_format({"bg_color": "#FFF2CC"}),
            13: workbook.add_format({"bg_color": "#FCE4D6"}),
            14: workbook.add_format({"bg_color": "#E7E6E6"}),
            15: workbook.add_format({"bg_color": "#DDEBF7"}),
        }
        
        # Formats per incidències amb colors per entitat
        fmt_incident_colors = {
            1: workbook.add_format({"bg_color": "#E2EFDA", "border": 1}),  # verd clar
            2: workbook.add_format({"bg_color": "#FFF2CC", "border": 1}),  # groc clar
            3: workbook.add_format({"bg_color": "#FCE4D6", "border": 1}),  # salmó
            4: workbook.add_format({"bg_color": "#E7E6E6", "border": 1}),  # gris clar
            5: workbook.add_format({"bg_color": "#DDEBF7", "border": 1}),  # blau clar
        }
        # Format per separador d'entitats
        fmt_separator = workbook.add_format({"bg_color": "#2F75B5", "border": 2, "border_color": "#1F4E78"})

        # --- FULLS DE RESUM I INDICADORS ---
        used_sheet_names = set()
        df_info = pd.DataFrame(info_totals).drop(columns=["fairness"], errors="ignore") if info_totals else pd.DataFrame()

        used_sheet_names.add("Resum")
        writer.sheets["Resum"] = workbook.add_worksheet("Resum")
        ws_info = writer.sheets["Resum"]
        start_row = 0
        start_row = _write_df_block(writer, workbook, "Resum", start_row, "KPI Global", metrics_pack.get("kpi_global", df_val_count_summary), fmt_title, fmt_header)
        start_row = _write_df_block(writer, workbook, "Resum", start_row, "Incidencia per modalitat", metrics_pack.get("summary_modalitat", pd.DataFrame()), fmt_title, fmt_header)
        start_row = _write_df_block(
            writer,
            workbook,
            "Resum",
            start_row,
            "Top entitats per magnitud",
            metrics_pack.get("top_entities", pd.DataFrame())[["Entitat", "Equips totals", "Equips amb peticio efectiva", "Incidencia absoluta", "Incidencia %", "Severitat total"]]
            if metrics_pack.get("top_entities") is not None and not metrics_pack.get("top_entities", pd.DataFrame()).empty
            else pd.DataFrame(),
            fmt_title,
            fmt_header,
            wrap_cols=["Entitat"],
        )
        resum_info = df_info[
            [
                col
                for col in [
                    "categoria",
                    "num_grups",
                    "repartiment",
                    "num_equips_reals",
                    "num_dummies",
                    "dummy_ratio",
                    "num_conflictes_finals",
                ]
                if col in df_info.columns
            ]
        ] if not df_info.empty else pd.DataFrame()
        start_row = _write_df_block(writer, workbook, "Resum", start_row, "Resum per categoria", resum_info, fmt_title, fmt_header, wrap_cols=["repartiment"])
        start_row = _write_df_block(writer, workbook, "Resum", start_row, "Conflictes d'entitat", df_val_entity_conflicts, fmt_title, fmt_header)
        ws_info.freeze_panes(2, 0)

        used_sheet_names.add("Indicadors")
        writer.sheets["Indicadors"] = workbook.add_worksheet("Indicadors")
        start_row = 0
        start_row = _write_df_block(writer, workbook, "Indicadors", start_row, "KPI Global", metrics_pack.get("kpi_global", pd.DataFrame()), fmt_title, fmt_header)
        start_row = _write_df_block(writer, workbook, "Indicadors", start_row, "Distribucio global de numeros", metrics_pack.get("global_numbers", pd.DataFrame()), fmt_title, fmt_header)
        start_row = _write_df_block(writer, workbook, "Indicadors", start_row, "Distribucio per modalitat", metrics_pack.get("by_modalitat", pd.DataFrame()), fmt_title, fmt_header)
        start_row = _write_df_block(writer, workbook, "Indicadors", start_row, "Distribucio per categoria", metrics_pack.get("by_categoria", pd.DataFrame()), fmt_title, fmt_header, wrap_cols=["Categoria"])
        start_row = _write_df_block(writer, workbook, "Indicadors", start_row, "Duples CASA/FORA", metrics_pack.get("duples", pd.DataFrame()), fmt_title, fmt_header)
        start_row = _write_df_block(writer, workbook, "Indicadors", start_row, "Compliment CASA/FORA", metrics_pack.get("casa_fora_summary", pd.DataFrame()), fmt_title, fmt_header)
        start_row = _write_df_block(writer, workbook, "Indicadors", start_row, "Dany global", metrics_pack.get("damage_summary", pd.DataFrame()), fmt_title, fmt_header)
        start_row = _write_df_block(writer, workbook, "Indicadors", start_row, "Fairness resum", metrics_pack.get("fairness_summary", pd.DataFrame()), fmt_title, fmt_header)
        start_row = _write_df_block(writer, workbook, "Indicadors", start_row, "Fairness per entitat", metrics_pack.get("fairness_entities", pd.DataFrame()), fmt_title, fmt_header, wrap_cols=["Entitat"])
        start_row = _write_df_block(writer, workbook, "Indicadors", start_row, "Info solver per categoria", df_info, fmt_title, fmt_header, wrap_cols=["repartiment", "conflictes_entitat"])

        used_sheet_names.add("Entitats")
        writer.sheets["Entitats"] = workbook.add_worksheet("Entitats")
        _write_df_block(
            writer,
            workbook,
            "Entitats",
            0,
            "Magnitud i incidencia per entitat",
            metrics_pack.get("entitats", pd.DataFrame()),
            fmt_title,
            fmt_header,
            wrap_cols=["Entitat", "Modalitats", "Categories"],
        )

        used_sheet_names.add("Nivells")
        writer.sheets["Nivells"] = workbook.add_worksheet("Nivells")
        start_row = 0
        start_row = _write_df_block(writer, workbook, "Nivells", start_row, "Resum per modalitat", metrics_pack.get("levels_modalitat", pd.DataFrame()), fmt_title, fmt_header)
        start_row = _write_df_block(writer, workbook, "Nivells", start_row, "Resum per categoria", metrics_pack.get("levels_category", pd.DataFrame()), fmt_title, fmt_header, wrap_cols=["Categoria"])
        _write_df_block(writer, workbook, "Nivells", start_row, "Detall per grup", metrics_pack.get("levels_group", pd.DataFrame()), fmt_title, fmt_header, wrap_cols=["Categoria", "Nivells presents"])

        # --- FULL "Incidencies" amb detall ampliat ---
        request_incidents = metrics_pack.get("request_incidents", pd.DataFrame()).copy()
        if not request_incidents.empty and "Diferències jornades" in request_incidents.columns:
            request_incidents["Diferències jornades"] = request_incidents["Diferències jornades"].apply(_format_diffs_excel)

        level_incidents = pd.DataFrame()
        if not df_val_level_spread.empty:
            level_incidents = df_val_level_spread.copy()
            level_incidents["Entitat"] = "— Grup amb nivells dispars —"
            level_incidents["Modalitat"] = ""
            level_incidents["Equip"] = ""
            level_incidents["Tipus peticio"] = "nivells"
            level_incidents["Esperat"] = ""
            level_incidents["Assignat"] = ""
            level_incidents["Mismatch jornades"] = 0
            level_incidents["Diferències jornades"] = level_incidents.apply(
                lambda r: f"Nivells: {r['Nivells']} | Min: {r['Min']} | Max: {r['Max']} | Dif: {r['Dif']}",
                axis=1,
            )
            level_incidents = level_incidents[["Entitat", "Modalitat", "Categoria", "Grup", "Equip", "Tipus peticio", "Esperat", "Assignat", "Mismatch jornades", "Diferències jornades"]]

        df_incidents = pd.concat([request_incidents, level_incidents], ignore_index=True) if not request_incidents.empty or not level_incidents.empty else pd.DataFrame()
        if not df_incidents.empty:
            df_incidents = df_incidents.sort_values(["Entitat", "Categoria", "Equip"]).reset_index(drop=True)

        used_sheet_names.add("Incidències")
        writer.sheets["Incidències"] = workbook.add_worksheet("Incidències")
        _write_df_block(
            writer,
            workbook,
            "Incidències",
            0,
            "Detall d'incidencies",
            df_incidents,
            fmt_title,
            fmt_header,
            wrap_cols=["Entitat", "Categoria", "Equip", "Diferències jornades"],
        )


        if segona_fase_bool and missing_classifications:
            try:
                df_missing = pd.DataFrame(missing_classifications)
                # Ordena per Modalitat → Categoria → Subcategoria → Nom
                df_missing.sort_values(['Modalitat', 'Categoria', 'Subcategoria', 'Nom'], inplace=True)
                sheet_missing = "Equips No Classificats"
                # Evita col·lisió amb noms existents
                orig_sheet = sheet_missing
                k = 1
                while sheet_missing in writer.sheets:
                    sheet_missing = f"{orig_sheet}_{k}"
                    k += 1
                df_missing.to_excel(writer, sheet_name=sheet_missing, index=False, startrow=0)
                ws_m = writer.sheets[sheet_missing]
                # capçalera
                for col_idx, _ in enumerate(df_missing.columns):
                    ws_m.write(0, col_idx, df_missing.columns[col_idx], fmt_header)
                    ws_m.set_column(col_idx, col_idx, max(12, min(40, len(str(df_missing.columns[col_idx])) + 5)))
                ws_m.autofilter(0, 0, max(0, len(df_missing)), max(0, len(df_missing.columns) - 1))
                ws_m.freeze_panes(1, 0)
            except Exception:
                # No volem que un error a aquesta funcionalitat pari tota la generació
                pass

        # Escriu equips que surten a la classificació però no han estat utilitzats
        try:
            if len(unused_classification_teams) > 0:
                df_unused = pd.DataFrame(unused_classification_teams)
                # Ordena per Modalitat → Categoria → Subcategoria → Nom
                df_unused.sort_values(['Modalitat', 'Categoria', 'Subcategoria', 'Nom'], inplace=True)
                orig_sheet_u = "Equips Classificació No Utilitzats"
                # Assegura que el nom del full compleixi el límit de 31 caràcters
                max_len = 31
                sheet_unused = orig_sheet_u[:max_len]
                k = 2
                while sheet_unused in writer.sheets:
                    suffix = f"_{k}"
                    allowed_base_len = max_len - len(suffix)
                    sheet_unused = (orig_sheet_u[:allowed_base_len] + suffix)[:max_len]
                    k += 1
                df_unused.to_excel(writer, sheet_name=sheet_unused, index=False, startrow=0)
                ws_u = writer.sheets[sheet_unused]
                # capçalera
                for col_idx, _ in enumerate(df_unused.columns):
                    ws_u.write(0, col_idx, df_unused.columns[col_idx], fmt_header)
                    ws_u.set_column(col_idx, col_idx, max(12, min(40, len(str(df_unused.columns[col_idx])) + 5)))
                ws_u.autofilter(0, 0, max(0, len(df_unused)), max(0, len(df_unused.columns) - 1))
                ws_u.freeze_panes(1, 0)
        except Exception as e:
            # No volem que un error a aquesta funcionalitat pari tota la generació
            print("Error escrivint equips de classificació no utilitzats.", str(e)) 


        # --- FULL per categoria ---
        for res_df_cat in resultats_totals:
            categoria = res_df_cat["_Categoria"].iloc[0] if "_Categoria" in res_df_cat.columns else "Categoria"
            base = "".join(c for c in categoria if c.isalnum() or c in "._- ").strip().replace(" ", "_") or "Categoria"
            # Garanteix unicitat i límit de 31 caràcters
            sheet_name = base[:31]
            if sheet_name in used_sheet_names:
                # Afegeix sufix _2, _3... mantenint límit 31
                i = 2
                while True:
                    suffix = f"_{i}"
                    candidate = (base[: (31 - len(suffix))] + suffix)
                    if candidate not in used_sheet_names:
                        sheet_name = candidate
                        break
                    i += 1
            used_sheet_names.add(sheet_name)

            # copia i ordena per “Grup” i dins de cada grup per “Núm. sorteig assignat” si existeixen
            df = res_df_cat.drop(columns=[c for c in ["_Categoria"] if c in res_df_cat.columns] + ["Id"]).copy()

            # Substitueix files DUMMY per "DESCANS"
            def _convertir_dummy_a_descans(row):
                if pd.isna(row.get('Nom')) or str(row.get('Nom')).strip() == '':
                    # Fila buida (slot buit)
                    return row
                if str(row.get('Entitat', '')).strip() == 'Descans':
                    # És un equip dummy, converteix a descans
                    row_copy = row.copy()
                    row_copy['Nom'] = 'DESCANS'
                    row_copy['Entitat'] = '—'
                    row_copy['Nivell'] = '—'
                    row_copy['Dia partit'] = '—'
                    # Mantenim Grup i Núm. sorteig assignat
                    # Netegem altres camps opcionals
                    for col in ['Núm. sorteig', 'Modalitat', 'Categoria', 'Subcategoria', 'Horari partit', 'Observacions']:
                        if col in row_copy:
                            row_copy[col] = '—'
                    if 'Diferències jornades' in row_copy:
                        row_copy['Diferències jornades'] = '—'
                    return row_copy
                return row

            # Aplica la conversió a cada fila
            df = df.apply(_convertir_dummy_a_descans, axis=1)

            
            # Format amigable per a "Diferències jornades" (multi-línia per Excel)
            if "Diferències jornades" in df.columns:
                df["Diferències jornades"] = df["Diferències jornades"].apply(_format_diffs_excel)
            if "Grup" in df.columns and "Núm. sorteig assignat" in df.columns:
                df.sort_values(["Grup", "Núm. sorteig assignat"], inplace=True, kind="stable")
            elif "Grup" in df.columns:
                df.sort_values(["Grup"], inplace=True, kind="stable")

            # escriu a partir de fila 1 (deixem fila 0 per al títol gran)
            start_row = 1
            df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=start_row)
            ws = writer.sheets[sheet_name]

            n_rows, n_cols = df.shape

            # Títol a la fila 0
            ws.merge_range(0, 0, 0, max(0, n_cols - 1), f"Assignació – {categoria}", fmt_title)

            # capçaleres amb format
            for col_idx, col_name in enumerate(df.columns):
                ws.write(start_row, col_idx, col_name, fmt_header)

            # vora per defecte + autoajust aproximat
            for col_idx, col_name in enumerate(df.columns):
                # Calcula la longitud màxima de totes les cel·les de la columna (capçalera + dades)
                max_len = max(
                    [len(str(col_name))] +
                    [len(str(x)) for x in df[col_name].astype(str).fillna("")]
                )
                # Amplada mínima de 10, màxima de 50 per evitar columnes massa estretes o amples
                width = min(max(max_len + 2, 10), 50)
                
                # Configuració específica per columnes especials
                if col_name == "Nom":
                    width = 35
                elif col_name == "Entitat":
                    width = 25
                elif col_name == "Nom Lliga":
                    width = 25
                elif col_name == "Diferències jornades":
                    width = 45
                elif col_name in ["Observacions", "Horari partit"]:
                    width = 30
                elif col_name in ["Nivell", "Grup", "Núm. sorteig", "Núm. sorteig assignat"]:
                    width = 12
                elif col_name == "Dia partit":
                    width = 15
                
                ws.set_column(col_idx, col_idx, width)
            # congela panell sota capçalera
            ws.freeze_panes(start_row + 1, 0)

            # filtres
            ws.autofilter(start_row, 0, start_row + max(0, n_rows), max(0, n_cols - 1))

            # text wrap per columnes llargues (opcional)
            #for col_idx, col_name in enumerate(df.columns):
            #    if any(isinstance(x, str) and len(x) > 40 for x in df[col_name].head(100)):
            #        ws.set_column(col_idx, col_idx, None, fmt_wrap)

            # Assegura wrap específic per a la columna "Diferències jornades"
            if "Diferències jornades" in df.columns:
                diffs_col_idx = df.columns.get_loc("Diferències jornades")
                # Amplada més gran i wrap activat per mostrar punts de bala en múltiples línies
                ws.set_column(diffs_col_idx, diffs_col_idx, 40, fmt_wrap)

            # condicional per color de “Grup” (si existeix) – pinta la fila sencera per cada grup
            if n_rows > 0 and "Grup" in df.columns:
                grup_col_idx = df.columns.get_loc("Grup")
                col_letter = _col_letter(grup_col_idx)  # p.ex. 'B'
                # recorrem els grups únics i apliquem format per fórmula (comparant text "G1", "G2", ...)
                for g in sorted(df["Grup"].dropna().astype(str).unique()):
                    g_str = str(g).strip()
                    # extreu número final per escollir color, si existeix
                    m = re.search(r"(\d+)$", g_str)
                    g_num = int(m.group(1)) if m else None
                    fmt = fmt_group_colors.get(g_num)
                    if not fmt:
                        continue
                    first_data_row = start_row + 1
                    last_data_row = start_row + n_rows
                    # compara el text del grup de la fila
                    ws.conditional_format(
                        first_data_row, 0, last_data_row, max(0, n_cols - 1),
                        {
                            "type": "formula",
                            "criteria": f'=${col_letter}{first_data_row+1}="{g_str}"',
                            "format": fmt           
                        }
                    )
                    # Truc: la fórmula s’avalua per cada fila; per assegurar que miri la fila correcta,
                    # xlsxwriter substitueix el número de fila segons la cel·la d’avaluació.

        

            # línies de taula (vora fina) a totes les cel·les
            for r in range(start_row + 1, start_row + 1 + n_rows):
                ws.set_row(r, None, fmt_default)
        # Si és segona fase, afegim full amb equips no classificats (agrupats per Modalitat)


        # missatge final
    print(f"[OK] Excel generat → {excel_path}")

    analysis_export = pd.DataFrame()
    analysis_df = metrics_pack.get("analysis", pd.DataFrame())
    if not analysis_df.empty:
        analysis_export = analysis_df.copy()
        diffs_col = next((col for col in analysis_export.columns if "Difer" in str(col) and "jornad" in str(col)), None)
        if "DiferÃ¨ncies jornades" in analysis_export.columns:
            analysis_export["DiferÃ¨ncies jornades"] = analysis_export["DiferÃ¨ncies jornades"].apply(_format_diffs_excel)
        export_cols = [
            "Entitat",
            "Modalitat",
            "Categoria",
            "Grup",
            "Nom",
            "Nivell",
            "Dia partit",
            "req_type",
            "request_code",
            "expected_seed",
            "assigned_seed",
            "is_effective_request",
            "is_mismatch",
            "mismatch_jornades",
            "is_textual_request",
            "casa_fora_respected",
            "dupla_label",
            "numero_casa",
            "numero_fora",
            "DiferÃ¨ncies jornades",
        ]
        if diffs_col and diffs_col not in export_cols:
            export_cols.append(diffs_col)
        export_cols = [col for col in export_cols if col in analysis_export.columns]
        analysis_export = analysis_export[export_cols].rename(
            columns={
                "Nom": "Equip",
                "req_type": "tipus_peticio",
                "request_code": "peticio",
                "expected_seed": "numero_esperat",
                "assigned_seed": "numero_assignat",
                "is_effective_request": "te_peticio_efectiva",
                "is_mismatch": "te_incidencia",
                "mismatch_jornades": "dany_jornades",
                "is_textual_request": "te_peticio_casa_fora",
                "casa_fora_respected": "casa_fora_complert",
                "dupla_label": "dupla_assignada",
                "numero_casa": "dupla_numero_casa",
                "numero_fora": "dupla_numero_fora",
                "DiferÃ¨ncies jornades": "diferencies_jornades",
            }
        )
        if diffs_col and diffs_col in analysis_export.columns:
            analysis_export = analysis_export.rename(columns={diffs_col: "diferencies_jornades"})

    kpis_payload = {
        "input_file": nom_fitxer,
        "fase": "segona_fase" if segona_fase_bool else "primera_fase",
        "jornades": len(fase),
        "excel_path": excel_path,
        "kpi_global": _df_records(metrics_pack.get("kpi_global", pd.DataFrame())),
        "casa_fora_summary": _df_records(metrics_pack.get("casa_fora_summary", pd.DataFrame())),
        "damage_summary": _df_records(metrics_pack.get("damage_summary", pd.DataFrame())),
        "global_numbers": _df_records(metrics_pack.get("global_numbers", pd.DataFrame())),
        "by_modalitat": _df_records(metrics_pack.get("by_modalitat", pd.DataFrame())),
        "by_categoria": _df_records(metrics_pack.get("by_categoria", pd.DataFrame())),
        "duples": _df_records(metrics_pack.get("duples", pd.DataFrame())),
        "fairness_summary": _df_records(metrics_pack.get("fairness_summary", pd.DataFrame())),
        "fairness_entities": _df_records(metrics_pack.get("fairness_entities", pd.DataFrame())),
        "entitats": _df_records(metrics_pack.get("entitats", pd.DataFrame())),
        "levels_modalitat": _df_records(metrics_pack.get("levels_modalitat", pd.DataFrame())),
        "levels_categoria": _df_records(metrics_pack.get("levels_category", pd.DataFrame())),
        "levels_group": _df_records(metrics_pack.get("levels_group", pd.DataFrame())),
        "solver_info_per_categoria": _df_records(df_info),
        "validacio_recompte_global": _df_records(df_val_count_summary),
        "validacio_recompte_categoria": _df_records(df_val_count_by_cat),
        "conflictes_entitat": _df_records(df_val_entity_conflicts),
        "nivells_dispars": _df_records(df_val_level_spread),
        "incidencies": _df_records(df_incidents),
        "analysis_rows": _df_records(analysis_export),
    }

    with open(kpis_path, "w", encoding="utf-8") as fh:
        json.dump(kpis_payload, fh, ensure_ascii=False, indent=2, default=_json_default)

    print(f"[OK] KPIs generats â†’ {kpis_path}")

    output.seek(0)
    return excel_path


# ----------------------------------------------------------------------


def process_excel(input_path: str, return_logs: bool = False, task_id: str = None, segona_fase_bool: bool = False) -> str:
    """
    Llegeix l'Excel d'entrada, executa la pipeline i retorna el path
    a un ZIP amb els resultats generats (p.ex. 'csv_generats', informes, etc.).
    """
    # 1) Llegeix l’Excel d’entrada
    logs = []
    async_to_sync(push_log)(task_id, f"Llegint fitxer Excel... {Path(input_path).name}", 10)
    df = pd.read_excel(input_path)


    async_to_sync(push_log)(task_id, f"S’han carregat {len(df)} inscripcions.", 15)
    #    Aquesta funció ja escriu sortides a BASE_PATH/csv_generats
    excel_path = processar_dades_2(df, nom_fitxer=Path(input_path).name, task_id=task_id, segona_fase_bool=segona_fase_bool)  # <- la teva funció existent

    async_to_sync(push_log)(task_id, f"Resultat generat: {Path(excel_path).name}", 90)

    # Ensure the produced file is moved into the MEDIA_ROOT (so external
    # services can access it via the app's RESULTS_DIR mounting). Use the
    # env var `MEDIA_ROOT` if present, otherwise default to `/data/results`.
    try:
        if isinstance(excel_path, (str, Path)) and os.path.exists(str(excel_path)):
            media_root = os.getenv('MEDIA_ROOT', '/data/results')
            os.makedirs(media_root, exist_ok=True)
            basename = os.path.basename(str(excel_path))
            dest_path = os.path.join(media_root, basename)
            # avoid clobbering existing files: add short hash suffix if needed
            if os.path.exists(dest_path):
                name, ext = os.path.splitext(basename)
                suffix = hashlib.sha1(basename.encode()).hexdigest()[:8]
                dest_path = os.path.join(media_root, f"{name}_{suffix}{ext}")
                logs.append(f"El fitxer de resultat ja existia a MEDIA_ROOT; s'ha afegit un sufix per evitar sobreescriptura: {os.path.basename(dest_path)}")
            try:
                shutil.move(str(excel_path), dest_path)
                excel_path = dest_path
                logs.append(f"Fitxer de resultat mogut a MEDIA_ROOT: {os.path.basename(dest_path)}")
            except Exception:
                try:
                    shutil.copy(str(excel_path), dest_path)
                    excel_path = dest_path
                    logs.append(f"Fitxer de resultat copiat a MEDIA_ROOT: {os.path.basename(dest_path)}")
                except Exception:
                    # if move/copy fail, keep original path
                    excel_path = str(excel_path)
                    logs.append("Warning: no s'ha pogut moure ni copiar el fitxer de resultat a MEDIA_ROOT.")
    except Exception:
        logs.append("Warning: no s'ha pogut moure el fitxer de resultat a MEDIA_ROOT.")
        # be resilient: don't fail the whole pipeline because of a move error
        pass

    if return_logs:
        return str(excel_path), logs
    return str(excel_path)



if __name__ == "__main__":
    # Llista tots els fitxers CSV del directori actual
    segona_fase_bool = False
    if len(sys.argv) > 1:
        in_path = sys.argv[1]
        out_path = sys.argv[2] if len(sys.argv) > 2 else None
        zip_path = process_excel(in_path, segona_fase_bool=segona_fase_bool)
        if out_path and out_path.lower().endswith(".zip"):
            shutil.move(zip_path, out_path)
        else:
            print(f"Resultat empaquetat: {zip_path}")


    else: 
        ruta_csv = os.path.join(BASE_PATH, "csv/")
        ruta_csv = "./csv/"
        print("Ruta CSV:", ruta_csv)
        fitxers_csv = [f for f in os.listdir(ruta_csv) if (f.endswith('.csv') or f.endswith('.xlsx'))]
        print("Fitxers CSV disponibles:")
        for idx, f in enumerate(fitxers_csv, 1):
            print(f"{idx}. {f}")

        try:
            num = int(input("Introdueix el número del fitxer CSV: "))
            if 1 <= num <= len(fitxers_csv):
                print(f"Has seleccionat: {fitxers_csv[num - 1]}")
                nom_fitxer = fitxers_csv[num - 1]
                df = llegir_csv(os.path.join(ruta_csv, nom_fitxer))
                if nom_fitxer.endswith('.xlsx') or nom_fitxer.endswith('.csv'):
                    path = xlsx_to_csv(os.path.join(ruta_csv, nom_fitxer))
                    df = llegir_csv(path)
                    # Prefiltre de les categories no vàlides, si estem a la segona fase
                    if segona_fase_bool:
                        # Exclou categories que corresponen a la "1ª FASE".
                        # Abans es filtrava per la columna `Categoria` (pot no ser la que conté la descripció
                        # de la categoria). Les categories principals s'obtenen de `Nom Lliga`, així que
                        # filtrem per allà. Regex cobreix "1ª FASE" o un " 1" a final de text.
                        mask = df['Nom Lliga'].astype(str).str.contains(r"1ª\s*FASE|\b1\b", case=False, na=False)
                        df = df[~mask]
                        print(df["Nom Lliga"].unique())

                else:
                    print("Format de fitxer no suportat. Només .csv o .xlsx")
                    df = None
                if df is not None:
                    processar_dades_2(df, nom_fitxer, segona_fase_bool=segona_fase_bool)
            else:
                print("Número fora de rang.")
        except ValueError as e:
            print("Has d'introduir un número vàlid.", e)
