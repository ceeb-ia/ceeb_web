from collections import Counter
import sys
import pandas as pd
import os
from convert import xlsx_to_csv
import shutil
from pathlib import Path
from calendaritzacions.domain.phases import (
    PRIMERA_FASE as primera_fase,
    SEGONA_FASE as segona_fase,
)

from calendaritzacions.analysis.indicators import (
    _build_indicator_tables,
)
from calendaritzacions.analysis.kpi_payload import build_kpis_payload
from calendaritzacions.analysis.run_audit import (
    build_constraints_report,
    build_home_away_resolution_payload,
    build_input_validation_payload,
    build_performance_payload,
    build_run_manifest,
    build_solver_trace,
)
from calendaritzacions.analysis.validation_tables import empty_validation_tables, build_validation_tables
from calendaritzacions.application.legacy_helpers import (
    crear_grups_equilibrats,
    llegir_csv,
)
from calendaritzacions.application.category_runner import run_legacy_categories
from calendaritzacions.application.progress import progress_for_task
from calendaritzacions.application.run_context import LegacyRunContext
from calendaritzacions.application.storage import finalize_result_path
from calendaritzacions.domain.normalization import normalize_seed_value, parse_int
from calendaritzacions.domain.errors import InfeasibleCalendarizationError
from calendaritzacions.engine.legacy.home_away import (
    HomeAwayResolutionError,
    resolve_home_away_requests,
)
from calendaritzacions.ingestion import InputValidationError, prepare_legacy_input, read_excel
from calendaritzacions.reporting.legacy_excel_writer import write_legacy_workbook
from calendaritzacions.reporting.json_writer import write_json_payload, write_kpis_json
from calendaritzacions.second_phase.classifications import enrich_second_phase_classifications


# Helper per convertir índex de columna (0-based) a lletra Excel, amb fallback si no hi ha xlsxwriter



MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/data/media")
BASE_PATH = MEDIA_ROOT



# De cada partit, obtenim l'equip local i visitant i mirem la seva posició a la classificació

















































def processar_dades_2(df, nom_fitxer="dades.csv", task_id=None, segona_fase_bool=False):
    print(df.head())
    progress = progress_for_task(task_id)
    entity_costs = {}
    try:
        df, map_modalitat_nom = prepare_legacy_input(df)
    except InputValidationError as exc:
        msg = str(exc)
        print(msg)
        progress.report(f"ERROR: {msg}", 100)
        raise

    # Llista per recollir equips que no s'ha pogut detectar a la classificació
    missing_classifications = []
    if segona_fase_bool:
        fase = segona_fase
    else:
        fase = primera_fase
    run_context = LegacyRunContext(
        input_file=os.path.basename(nom_fitxer),
        phase_name="segona_fase" if segona_fase_bool else "primera_fase",
        phase_rounds=len(fase),
    )
    run_context.input_rows = len(df)

    print("Columnes del DataFrame:", df.columns)
    progress.report("Assignant Ids als equips...", 20)

    # Calculem el nombre total de jornades que juga la entitat
    total_jornades = len(fase)
    
    # -------------------------------------------------------
    # Assignem a cada entitat casa/fora un numero de sorteig.
    # -------------------------------------------------------
    progress.report("Analitzant números de sorteig per assignacions casa/fora...", 30)
    try:
        home_away_resolution = resolve_home_away_requests(df)
    except HomeAwayResolutionError as exc:
        msg = str(exc)
        print(msg)
        progress.report(msg, 100)
        raise InfeasibleCalendarizationError(msg) from exc

    progress.report("Assignant números de sorteig als equips segons preferències...", 50)

    equip_to_num_sorteig = home_away_resolution.equip_to_num_sorteig
    entitats_assigned = home_away_resolution.entitats_assigned
    duples_casa_fora = home_away_resolution.duples_casa_fora
    run_context.home_away_traces = list(home_away_resolution.traces)

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
            progress=progress,
        )
        run_context.missing_classifications = list(missing_classifications)
        run_context.unused_classification_teams = list(unused_classification_teams)


    resultats_totals, info_totals, entity_costs = run_legacy_categories(
        df,
        fase=fase,
        equip_to_num_sorteig=equip_to_num_sorteig,
        segona_fase_bool=segona_fase_bool,
        progress=progress,
    )
    for info in info_totals:
        run_context.add_category_result(info.get("categoria", ""), info)

    '''
        print(f"[OK] {categoria} → {out_path}")

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
        run_context.add_category_result(categoria, info)
    '''


    
    # --- PREPARA VALIDACIONS PER ESCRIURE A L'EXCEL (si hi ha resultats) ---
    progress.report("Preparant excel final", 92)
    validation_tables = empty_validation_tables()
    metrics_pack = {}

    if resultats_totals:
        all_results = pd.concat(resultats_totals, ignore_index=True)
        if "Entitat" in all_results.columns:
            entity_text = all_results["Entitat"].fillna("").astype(str).str.strip()
            run_context.assigned_rows = int(((entity_text != "") & (entity_text != "Descans")).sum())
        else:
            run_context.assigned_rows = len(all_results)
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
        validation_tables = build_validation_tables(df, metrics_pack)


    # --- DESPRÉS DEL BUCLE PER CATEGORIES ---
    # Escriu tot en un sol Excel amb format
    # Agafem el nom sense l'extensio
    nom_fitxer = os.path.splitext(os.path.basename(nom_fitxer))[0]
    excel_path = os.path.join(BASE_PATH, f"assignacions_{nom_fitxer}.xlsx")
    kpis_path = os.path.join(BASE_PATH, f"kpis_{nom_fitxer}.json")
    run_manifest_path = os.path.join(BASE_PATH, f"run_manifest_{nom_fitxer}.json")
    input_validation_path = os.path.join(BASE_PATH, f"input_validation_{nom_fitxer}.json")
    solver_trace_path = os.path.join(BASE_PATH, f"solver_trace_{nom_fitxer}.json")
    home_away_resolution_path = os.path.join(BASE_PATH, f"home_away_resolution_{nom_fitxer}.json")
    constraints_report_path = os.path.join(BASE_PATH, f"constraints_report_{nom_fitxer}.json")
    performance_path = os.path.join(BASE_PATH, f"performance_{nom_fitxer}.json")
    run_context.excel_path = excel_path
    run_context.kpis_path = kpis_path
    run_context.audit_paths = {
        "run_manifest": run_manifest_path,
        "input_validation": input_validation_path,
        "solver_trace": solver_trace_path,
        "home_away_resolution": home_away_resolution_path,
        "constraints_report": constraints_report_path,
        "performance": performance_path,
    }
    os.makedirs(os.path.dirname(excel_path), exist_ok=True)
    df_info = pd.DataFrame(info_totals).drop(columns=["fairness"], errors="ignore") if info_totals else pd.DataFrame()
    df_incidents = write_legacy_workbook(
        excel_path,
        resultats_totals=resultats_totals,
        info_totals=info_totals,
        metrics_pack=metrics_pack,
        df_val_count_summary=validation_tables.count_summary,
        df_val_entity_conflicts=validation_tables.entity_conflicts,
        df_val_level_spread=validation_tables.level_spread,
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
        df_val_count_summary=validation_tables.count_summary,
        df_val_count_by_cat=validation_tables.count_by_category,
        df_val_entity_conflicts=validation_tables.entity_conflicts,
        df_val_level_spread=validation_tables.level_spread,
        df_incidents=df_incidents,
    )

    write_kpis_json(kpis_path, kpis_payload)
    run_context.finish()
    write_json_payload(
        run_manifest_path,
        build_run_manifest(
            input_file=run_context.input_file,
            phase=run_context.phase_name,
            phase_rounds=run_context.phase_rounds,
            engine=run_context.engine_name,
            started_at=run_context.started_at,
            finished_at=run_context.finished_at,
            input_rows=run_context.input_rows,
            assigned_rows=run_context.assigned_rows,
            excel_path=excel_path,
            kpis_path=kpis_path,
            audit_paths=run_context.audit_paths,
            warnings=run_context.warnings,
        ),
    )
    write_json_payload(
        input_validation_path,
        build_input_validation_payload(
            input_rows=run_context.input_rows,
            columns=list(df.columns),
            count_summary=validation_tables.count_summary,
            count_by_category=validation_tables.count_by_category,
            entity_conflicts=validation_tables.entity_conflicts,
            level_spread=validation_tables.level_spread,
            missing_classifications=missing_classifications,
            unused_classification_teams=unused_classification_teams,
        ),
    )
    write_json_payload(
        solver_trace_path,
        build_solver_trace(
            phase=run_context.phase_name,
            categories=run_context.categories,
            home_away_traces=run_context.home_away_traces,
            info_totals=info_totals,
        ),
    )
    write_json_payload(
        home_away_resolution_path,
        build_home_away_resolution_payload(
            equip_to_num_sorteig=equip_to_num_sorteig,
            entitats_assigned=entitats_assigned,
            duples_casa_fora=duples_casa_fora,
            traces=run_context.home_away_traces,
        ),
    )
    write_json_payload(
        constraints_report_path,
        build_constraints_report(
            entity_conflicts=validation_tables.entity_conflicts,
            level_spread=validation_tables.level_spread,
            missing_classifications=missing_classifications,
            unused_classification_teams=unused_classification_teams,
        ),
    )
    write_json_payload(
        performance_path,
        build_performance_payload(
            started_at=run_context.started_at,
            finished_at=run_context.finished_at,
            categories=len(info_totals),
            input_rows=run_context.input_rows,
            assigned_rows=run_context.assigned_rows,
        ),
    )

    print(f"[OK] KPIs generats → {kpis_path}")

    return excel_path


# ----------------------------------------------------------------------


def process_excel(input_path: str, return_logs: bool = False, task_id: str = None, segona_fase_bool: bool = False) -> str:
    """
    Llegeix l'Excel d'entrada, executa la pipeline i retorna el path
    a un ZIP amb els resultats generats (p.ex. 'csv_generats', informes, etc.).
    """
    from calendaritzacions.application.use_cases import process_calendarization

    return process_calendarization(
        input_path=input_path,
        return_logs=return_logs,
        task_id=task_id,
        segona_fase_bool=segona_fase_bool,
    )

    # Legacy implementation kept below as unreachable compatibility context.
    logs = []
    progress = progress_for_task(task_id)
    progress.report(f"Llegint fitxer Excel... {Path(input_path).name}", 10)
    df = read_excel(input_path)


    progress.report(f"S’han carregat {len(df)} inscripcions.", 15)
    #    Aquesta funció ja escriu sortides a BASE_PATH/csv_generats
    excel_path = processar_dades_2(df, nom_fitxer=Path(input_path).name, task_id=task_id, segona_fase_bool=segona_fase_bool)  # <- la teva funció existent

    progress.report(f"Resultat generat: {Path(excel_path).name}", 90)

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
