from collections import Counter
import sys
import pandas as pd
import os
from convert import xlsx_to_csv
import numpy as np
from assignacions import assignar_grups_hungares
import shutil
from asgiref.sync import async_to_sync
from logs import push_log
from pathlib import Path
from calendaritzacions.domain.phases import (
    PRIMERA_FASE as primera_fase,
    SEGONA_FASE as segona_fase,
)

from calendaritzacions.analysis.indicators import (
    _build_indicator_tables,
    _with_metric_descriptions,
)
from calendaritzacions.analysis.kpi_payload import build_kpis_payload
from calendaritzacions.application.legacy_helpers import (
    crear_grups_equilibrats,
    llegir_csv,
)
from calendaritzacions.application.storage import finalize_result_path
from calendaritzacions.domain.normalization import normalize_seed_value, parse_int
from calendaritzacions.engine.legacy.home_away import (
    HomeAwayResolutionError,
    resolve_home_away_requests,
)
from calendaritzacions.ingestion import InputValidationError, prepare_legacy_input, read_excel
from calendaritzacions.reporting.legacy_excel_writer import write_legacy_workbook
from calendaritzacions.reporting.json_writer import write_kpis_json
from calendaritzacions.second_phase.classifications import enrich_second_phase_classifications


# Helper per convertir índex de columna (0-based) a lletra Excel, amb fallback si no hi ha xlsxwriter



MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/data/media")
BASE_PATH = MEDIA_ROOT



# De cada partit, obtenim l'equip local i visitant i mirem la seva posició a la classificació

















































def processar_dades_2(df, nom_fitxer="dades.csv", task_id=None, segona_fase_bool=False):
    print(df.head())
    entity_costs = {}
    try:
        df, map_modalitat_nom = prepare_legacy_input(df)
    except InputValidationError as exc:
        msg = str(exc)
        print(msg)
        if task_id:
            async_to_sync(push_log)(task_id, f"ERROR: {msg}", 100)
        raise

    # Llista per recollir equips que no s'ha pogut detectar a la classificació
    missing_classifications = []
    if segona_fase_bool:
        fase = segona_fase
    else:
        fase = primera_fase

    print("Columnes del DataFrame:", df.columns)
    if task_id:
        async_to_sync(push_log)(task_id, "Assignant Ids als equips...", 20)

    # Calculem el nombre total de jornades que juga la entitat
    total_jornades = len(fase)
    
    # -------------------------------------------------------
    # Assignem a cada entitat casa/fora un numero de sorteig.
    # -------------------------------------------------------
    if task_id:
        async_to_sync(push_log)(task_id, "Analitzant números de sorteig per assignacions casa/fora...", 30)
    try:
        home_away_resolution = resolve_home_away_requests(df)
    except HomeAwayResolutionError as exc:
        msg = str(exc)
        print(msg)
        if task_id:
            async_to_sync(push_log)(task_id, msg, 100)
        sys.exit(msg)

    if task_id:
        async_to_sync(push_log)(task_id, "Assignant números de sorteig als equips segons preferències...", 50)

    equip_to_num_sorteig = home_away_resolution.equip_to_num_sorteig
    entitats_assigned = home_away_resolution.entitats_assigned
    duples_casa_fora = home_away_resolution.duples_casa_fora

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
    unused_classification_teams = []
    if segona_fase_bool:
        df, missing_classifications, unused_classification_teams = enrich_second_phase_classifications(
            df,
            map_modalitat_nom,
            task_id=task_id,
        )


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
    df_info = pd.DataFrame(info_totals).drop(columns=["fairness"], errors="ignore") if info_totals else pd.DataFrame()
    df_incidents = write_legacy_workbook(
        excel_path,
        resultats_totals=resultats_totals,
        info_totals=info_totals,
        metrics_pack=metrics_pack,
        df_val_count_summary=df_val_count_summary,
        df_val_entity_conflicts=df_val_entity_conflicts,
        df_val_level_spread=df_val_level_spread,
        segona_fase_bool=segona_fase_bool,
        missing_classifications=missing_classifications,
        unused_classification_teams=unused_classification_teams,
    )
    print(f"[OK] Excel generat → {excel_path}")

    kpis_payload = build_kpis_payload(
        nom_fitxer=nom_fitxer,
        segona_fase_bool=segona_fase_bool,
        fase=fase,
        excel_path=excel_path,
        metrics_pack=metrics_pack,
        df_info=df_info,
        df_val_count_summary=df_val_count_summary,
        df_val_count_by_cat=df_val_count_by_cat,
        df_val_entity_conflicts=df_val_entity_conflicts,
        df_val_level_spread=df_val_level_spread,
        df_incidents=df_incidents,
    )

    write_kpis_json(kpis_path, kpis_payload)

    print(f"[OK] KPIs generats → {kpis_path}")

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
    df = read_excel(input_path)


    async_to_sync(push_log)(task_id, f"S’han carregat {len(df)} inscripcions.", 15)
    #    Aquesta funció ja escriu sortides a BASE_PATH/csv_generats
    excel_path = processar_dades_2(df, nom_fitxer=Path(input_path).name, task_id=task_id, segona_fase_bool=segona_fase_bool)  # <- la teva funció existent

    async_to_sync(push_log)(task_id, f"Resultat generat: {Path(excel_path).name}", 90)

    excel_path = finalize_result_path(excel_path, logs)

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
