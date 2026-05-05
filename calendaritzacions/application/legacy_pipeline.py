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

from calendaritzacions.analysis.indicators import (
    _METRIC_DESCRIPTIONS,
    _build_indicator_tables,
    _df_records,
    _dupla_label,
    _entity_assignment_key_column,
    _expected_seed,
    _is_real_team_row,
    _json_default,
    _level_idx,
    _level_letter,
    _pairwise_avg_distance,
    _request_display_code,
    _request_type,
    _with_metric_descriptions,
    analitzar_equitabilitat_costos,
)
from calendaritzacions.application.legacy_helpers import (
    _normalize_entity_name,
    crear_grups_equilibrats,
    llegir_csv,
    obtenir_entitat,
)
from calendaritzacions.application.storage import finalize_result_path
from calendaritzacions.domain.normalization import normalize_seed_value, parse_int
from calendaritzacions.reporting.excel_writer import (
    _auto_fit_worksheet_columns,
    _col_letter,
    _format_diffs_excel,
    _write_df_block,
)
from calendaritzacions.second_phase.matching import (
    _get_team_position,
    _normalize_team_key,
)
from calendaritzacions.second_phase.classifications import enrich_second_phase_classifications


# Helper per convertir índex de columna (0-based) a lletra Excel, amb fallback si no hi ha xlsxwriter



MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/data/media")
BASE_PATH = MEDIA_ROOT



# De cada partit, obtenim l'equip local i visitant i mirem la seva posició a la classificació

















































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
