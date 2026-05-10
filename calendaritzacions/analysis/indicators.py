"""Indicator/KPI helpers extracted from the legacy pipeline."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re

import numpy as np
import pandas as pd

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
