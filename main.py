from collections import Counter
import io
import sys
import pandas as pd
import os
import re
from convert import xlsx_to_csv
import numpy as np
from assignacions import assignar_grups_hungares
import unicodedata, hashlib
import tempfile, shutil
from pathlib import Path
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



ENV = os.getenv("APP_ENV", "DEV")

if ENV == "DEV":
    BASE_PATH = os.getcwd()  # o una ruta fixa local
else:
    BASE_PATH = "/app/dades"  # ruta dins el contenidor en producció


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

def processar_dades_2(df, nom_fitxer="dades.csv"):
    print(df.head())
    entity_costs = {}
    # Assegurem columnes mínimes
    cols_ok = {'Nom', 'Entitat', 'Nom Lliga', 'Nivell', 'Núm. sorteig', 'Dia partit'}
    missing = cols_ok - set(df.columns)
    print("Columnes del DataFrame:", df.columns)
    if missing:
        print(f"Falten columnes necessàries: {missing}")
        raise ValueError(f"Falten columnes necessàries: {missing}")

    df = df.copy()
    
    if 'Entitat' not in df.columns:
        sys.exit("Falta la columna 'Entitat' i no es pot deduir automàticament.")
        df['Entitat'] = df['Nom'].apply(obtenir_entitat)

    if 'Id' in df.columns:
        # fem el drop
        df = df.drop(columns=['Id'])
    # Afegim un Id estable per a cada equip basat en Nom i Nom Lliga
    if 'Id' not in df.columns:
        def _mk_id(row):
            nom = _normalize_entity_name(row.get('Nom', ''))
            cat = _normalize_entity_name(row.get('Nom Lliga', ''))
            key = f"{nom}|{cat}"
            return hashlib.sha1(key.encode('utf-8')).hexdigest()[:10].upper()
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
            sys.exit(msg)

    from assignacions import primera_fase
    # Calculem el nombre total de jornades que juga la entitat
    total_jornades = len(primera_fase)
    
    # Per simplicitat, assumim que totes les entitats tenen el mateix nombre de jornades
    # Pots refinar això si tens diferents formats de lliga per entitat
    jornades_per_entitat = {}
    
    # Per cada entitat única, assignem el total de jornades
    for entitat in df['Entitat'].dropna().unique():
        # Comptem el nombre d'equips reals (no Descans) d'aquesta entitat
        num_equips = len(df[(df['Entitat'] == entitat) & (df['Nom'].notna()) & (df['Nom'].str.strip() != "")])
    
    jornades_per_entitat[entitat] = total_jornades * num_equips

    # -------------------------------------------------------
    # Assignem a cada entitat casa/fora un numero de sorteig.
    # -------------------------------------------------------

    # 1) Commptem "enllaços" d'entitats que han demanat casa/fora amb altres que també han demanat
    entitats_links = {}
    # Per cada entitat del df
    for _, row in df.iterrows():
        entitat = row['Entitat']
        peticio = str(row['Núm. sorteig']).strip().lower()
        if peticio not in ('casa', 'fora'):
            continue
        if entitat in entitats_links:
           continue
        entitats_links[entitat] = set()

        # Repassem tots els equips de l'entitat que han demanat casa/fora
        # NOMÉS categories on aquesta entitat ha demanat casa/fora
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
                equip = r['Nom']
                entitat2 = r['Entitat']
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
        # Per aquesta entitat, observem el panorama de números de sorteig que es pot trobar per
        # assignar la millor dupla casa/fora possible.
        # Categories on aquesta entitat HA DEMANAT casa/fora (no totes on juga)
        cats_req = (
            df.loc[
                (df['Entitat'] == entitat) &
                (df['Núm. sorteig'].astype(str).str.strip().str.lower().isin(['casa', 'fora'])),
                'Nom Lliga'
            ].dropna().unique()
        )

        for categoria in sorted(cats_req, key=lambda s: str(s).casefold()):
            cat = str(categoria).strip()
            if not any(sport in cat.lower() for sport in ["volei", "futbol", "hoquei"]):
                continue
            # Recollim els números de sorteig demanats en aquesta categoria
            equips_cat = df[df['Nom Lliga'] == categoria]
            for _, r_cat in equips_cat.iterrows():
                seed = normalize_seed_value(r_cat['Núm. sorteig'])
                if not pd.isna(seed):
                    # Identifiquem la dupla casa fora a la que pertany el seed
                    for id_, (casa, fora) in enumerate(duples_casa_fora):
                        if seed == casa or seed == fora:
                            entitat_count[id_] = entitat_count.get(id_, 0) + 1
                            break

        # Ens assegurem que totes les duples estan representades
        for id_ in range(len(duples_casa_fora)):
            entitat_count.setdefault(id_, 0)

        # Si no hi ha cap compte (per ex. només hi ha peticions textuals casa/fora), fem un fallback estable
        if not entitat_count:
            h = int(hashlib.sha1(_normalize_entity_name(entitat).encode('utf-8')).hexdigest(), 16)
            entitat_count = {h % len(duples_casa_fora): 0}
        # Triem l'ordre de preferència de les duples endreçant per nombre ascendent d'aparicions
        entitat_count = dict(sorted(entitat_count.items(), key=lambda item: item[1]))
        # Guardem l'ordre de preferència per aquesta entitat
        preferencies_entitat[entitat] = entitat_count

    print ("Preferències d'entitats estipulades")

    # Ara, tornem a recorrer tots els equips de cada entitat que han demanat casa/fora i, per cada
    # equip que ha demanat casa/fora, assignem el número de sorteig segons la preferència de l'entitat

    equip_to_num_sorteig = {}
    entitats_assigned = {}
    for entitat, preferencies in preferencies_entitat.items():
        equips_entitat = df[
            (df['Entitat'] == entitat) &
            (df['Núm. sorteig'].astype(str).str.strip().str.lower().isin(['casa', 'fora']))
        ].copy()
        # primera dupla preferida (clau int) si existeix
        tupla_preferida = next(iter(preferencies.keys()), None)
        tuples_used = set()
        tuples_used.add(tupla_preferida)
        # Verifiquem els links d'aquesta entitat amb qualsevol altra entitat que estigui
        # a entitats_assigned. Si hi ha conflicte, passem a la següent preferència
        for equip_link in sorted(entitats_links.get(entitat, []), key=lambda s: str(s).casefold()):
            for entitat2, dupla2 in entitats_assigned.items():
                equips_entitat2 = df[
                    (df['Entitat'] == entitat2) &
                    (df['Núm. sorteig'].astype(str).str.strip().str.lower().isin(['casa', 'fora']))
                ]
                if equip_link in equips_entitat2['Nom'].values:
                    # Hi ha un enllaç entre entitat i entitat2
                    if tupla_preferida == dupla2:
                        # Conflicte: mateixa dupla assignada
                        # Busquem la següent preferència
                        tupla_preferida = None
                        for pref in sorted(preferencies.keys()):
                            if pref != dupla2 and pref not in tuples_used:
                                tupla_preferida = pref
                                tuples_used.add(pref)
                                #print(f"Preferència actualitzada per l'entitat '{entitat}': {tupla_preferida}")
                                break
        # Si no hi ha preferència vàlida, assignem la original (no canviarem res)
        if tupla_preferida is None:
            tupla_preferida = next(iter(preferencies.keys()), None)

        casa_num, fora_num = duples_casa_fora[tupla_preferida]
        for _, equip in equips_entitat.iterrows():
            req = str(equip['Núm. sorteig']).strip().lower()
            if req == 'casa':
                if casa_num not in [8,7,6,1]:
                    print ("Atenció 2: ", equip, req)
                    sys.exit("Número de sorteig assignat a 'casa' no vàlid")
                prev = equip_to_num_sorteig.get(equip['Id'])
                if prev is not None and prev != casa_num:
                    msg = (
                        f"ERROR: Conflicte de mapping per a l'equip '{equip['Id']}'. "
                        f"Ja tenia assignat {prev} i s'està intentant assignar {casa_num} (CASA)."
                    )
                    print(msg)
                    sys.exit(msg)
                equip_to_num_sorteig[equip['Id']] = casa_num
            elif req == 'fora':
                if fora_num not in [5,4,3,2]:
                    print ("Atenció 3: ", equip, req)
                    sys.exit("Número de sorteig assignat a 'fora' no vàlid")
                prev = equip_to_num_sorteig.get(equip['Id'])
                if prev is not None and prev != fora_num:
                    msg = (
                        f"ERROR: Conflicte de mapping per a l'equip '{equip['Id']}'. "
                        f"Ja tenia assignat {prev} i s'està intentant assignar {fora_num} (FORA)."
                    )
                    print(msg)
                    sys.exit(msg)
                equip_to_num_sorteig[equip['Id']] = fora_num
            else: 
                print ("Atenció 4: ", equip, req)
                sys.exit("Petició de número de sorteig no vàlida (ha de ser 'casa' o 'fora')")

        # Guardem la dupla assignada a aquesta entitat
        entitats_assigned[entitat] = tupla_preferida
            
    print("Assignació de números de sorteig per equips (segons peticions):", equip_to_num_sorteig)
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
    #print("Repartiment de duples (comptatge per idx):", dict(counts))
    #print("Detall duples:", resum_duples)    
    #sys.exit()
    categories = sorted(df['Nom Lliga'].dropna().unique())

    resultats_totals = []
    info_totals = []

    for categoria in categories:
        if not any(sport in categoria.lower() for sport in ["volei", "futbol", "hoquei"]):
            continue
        df_cat = df[df['Nom Lliga'] == categoria].copy()
        print(f"\nProcessant categoria '{categoria}' amb {len(df_cat)} equips...")
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
                weights={'w_dif_sorteig': np.log2(27)}
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

        resultats_totals.append(res_df.assign(_Categoria=categoria))
        info_totals.append({'categoria': categoria, **info})


    
    # --- PREPARA VALIDACIONS PER ESCRIURE A L'EXCEL (si hi ha resultats) ---
    df_val_count_summary = pd.DataFrame()
    df_val_count_by_cat = pd.DataFrame()
    df_val_entity_conflicts = pd.DataFrame(columns=["Categoria", "Grup", "Entitat", "Count"])
    df_val_casa_fora = pd.DataFrame(columns=["Entitat", "Categoria", "Equip", "Petició", "Esperat", "Assignat", "Diferències jornades"])
    df_val_num_mismatch = pd.DataFrame(columns=["Entitat", "Categoria", "Equip", "Sol·licitat", "Assignat"])  # Núm. explícit diferent
    df_val_level_spread = pd.DataFrame(columns=["Categoria", "Grup", "Nivells", "Min", "Max", "Dif"])  # Nivells dispars
    df_entitat_slots = pd.DataFrame(columns=["Entitat", "Casa", "Fora", "#Equips CASA", "#Equips FORA"])  # Assignació per entitat
    
    # Comptatge de números demanats per categoria - format matricial
    # Comptatge de números demanats per categoria - format matricial
    df_num_requests_by_cat = pd.DataFrame()
    df_num_requests_by_cat_futbol = pd.DataFrame()
    df_num_requests_by_cat_hoquei = pd.DataFrame()

    # Obtenim totes les categories de volei
    categories_volei = sorted([cat for cat in df['Nom Lliga'].dropna().unique() if "volei" in cat.lower()])

    # Obtenim totes les categories de futbol
    categories_futbol = sorted([cat for cat in df['Nom Lliga'].dropna().unique() if "futbol" in cat.lower()])

    # Obtenim totes les categories d'hoquei
    categories_hoquei = sorted([cat for cat in df['Nom Lliga'].dropna().unique() if "hoquei" in cat.lower()])

    # TAULA PER VOLEI
    if categories_volei:
        # Definim tots els possibles números de sorteig
        numeros_sorteig = ['1', '2', '3', '4', '5', '6', '7', '8', 'CASA', 'FORA']
        
        # Creem la matriu: files = números de sorteig, columnes = categories
        matriu_data = {}
        
        # Inicialitzem totes les columnes de categories amb zeros
        for categoria in categories_volei:
            matriu_data[categoria] = [0] * len(numeros_sorteig)
        
        # Processem cada categoria per comptar les peticions
        for categoria in categories_volei:
            df_cat = df[df['Nom Lliga'] == categoria].copy()
            if df_cat.empty:
                continue
                
            # Comptem peticions de números específics (1-8)
            for i, num in enumerate(['1', '2', '3', '4', '5', '6', '7', '8']):
                count = len(df_cat[df_cat['Núm. sorteig'].astype(str).str.strip() == num])
                matriu_data[categoria][i] = count
            
            # Comptem peticions de CASA/FORA
            casa_count = len(df_cat[df_cat['Núm. sorteig'].astype(str).str.strip().str.lower() == 'casa'])
            fora_count = len(df_cat[df_cat['Núm. sorteig'].astype(str).str.strip().str.lower() == 'fora'])
            
            matriu_data[categoria][8] = casa_count  # CASA
            matriu_data[categoria][9] = fora_count  # FORA
        
        # Creem el DataFrame amb la matriu
        df_num_requests_by_cat = pd.DataFrame(matriu_data, index=numeros_sorteig)
        
        # Afegim la columna TOTAL sumant totes les categories
        df_num_requests_by_cat['TOTAL'] = df_num_requests_by_cat.sum(axis=1)
        
        # Resetem l'índex per fer que els números de sorteig siguin una columna
        df_num_requests_by_cat = df_num_requests_by_cat.reset_index()
        df_num_requests_by_cat = df_num_requests_by_cat.rename(columns={'index': 'Núm. sorteig'})

    # TAULA PER FUTBOL
    if categories_futbol:
        # Definim tots els possibles números de sorteig
        numeros_sorteig_futbol = ['1', '2', '3', '4', '5', '6', '7', '8', 'CASA', 'FORA']
        
        # Creem la matriu: files = números de sorteig, columnes = categories
        matriu_data_futbol = {}
        
        # Inicialitzem totes les columnes de categories amb zeros
        for categoria in categories_futbol:
            matriu_data_futbol[categoria] = [0] * len(numeros_sorteig_futbol)
        
        # Processem cada categoria per comptar les peticions
        for categoria in categories_futbol:
            df_cat = df[df['Nom Lliga'] == categoria].copy()
            if df_cat.empty:
                continue
                
            # Comptem peticions de números específics (1-8)
            for i, num in enumerate(['1', '2', '3', '4', '5', '6', '7', '8']):
                count = len(df_cat[df_cat['Núm. sorteig'].astype(str).str.strip() == num])
                matriu_data_futbol[categoria][i] = count
            
            # Comptem peticions de CASA/FORA
            casa_count = len(df_cat[df_cat['Núm. sorteig'].astype(str).str.strip().str.lower() == 'casa'])
            fora_count = len(df_cat[df_cat['Núm. sorteig'].astype(str).str.strip().str.lower() == 'fora'])
            
            matriu_data_futbol[categoria][8] = casa_count  # CASA
            matriu_data_futbol[categoria][9] = fora_count  # FORA
        
        # Creem el DataFrame amb la matriu
        df_num_requests_by_cat_futbol = pd.DataFrame(matriu_data_futbol, index=numeros_sorteig_futbol)
        
        # Afegim la columna TOTAL sumant totes les categories
        df_num_requests_by_cat_futbol['TOTAL'] = df_num_requests_by_cat_futbol.sum(axis=1)
        
        # Resetem l'índex per fer que els números de sorteig siguin una columna
        df_num_requests_by_cat_futbol = df_num_requests_by_cat_futbol.reset_index()
        df_num_requests_by_cat_futbol = df_num_requests_by_cat_futbol.rename(columns={'index': 'Núm. sorteig'})

    # TAULA PER HOQUEI
    if categories_hoquei:
        # Definim tots els possibles números de sorteig
        numeros_sorteig_hoquei = ['1', '2', '3', '4', '5', '6', '7', '8', 'CASA', 'FORA']
        
        # Creem la matriu: files = números de sorteig, columnes = categories
        matriu_data_hoquei = {}
        
        # Inicialitzem totes les columnes de categories amb zeros
        for categoria in categories_hoquei:
            matriu_data_hoquei[categoria] = [0] * len(numeros_sorteig_hoquei)
        
        # Processem cada categoria per comptar les peticions
        for categoria in categories_hoquei:
            df_cat = df[df['Nom Lliga'] == categoria].copy()
            if df_cat.empty:
                continue
                
            # Comptem peticions de números específics (1-8)
            for i, num in enumerate(['1', '2', '3', '4', '5', '6', '7', '8']):
                count = len(df_cat[df_cat['Núm. sorteig'].astype(str).str.strip() == num])
                matriu_data_hoquei[categoria][i] = count
            
            # Comptem peticions de CASA/FORA
            casa_count = len(df_cat[df_cat['Núm. sorteig'].astype(str).str.strip().str.lower() == 'casa'])
            fora_count = len(df_cat[df_cat['Núm. sorteig'].astype(str).str.strip().str.lower() == 'fora'])
            
            matriu_data_hoquei[categoria][8] = casa_count  # CASA
            matriu_data_hoquei[categoria][9] = fora_count  # FORA
        
        # Creem el DataFrame amb la matriu
        df_num_requests_by_cat_hoquei = pd.DataFrame(matriu_data_hoquei, index=numeros_sorteig_hoquei)
        
        # Afegim la columna TOTAL sumant totes les categories
        df_num_requests_by_cat_hoquei['TOTAL'] = df_num_requests_by_cat_hoquei.sum(axis=1)
        
        # Resetem l'índex per fer que els números de sorteig siguin una columna
        df_num_requests_by_cat_hoquei = df_num_requests_by_cat_hoquei.reset_index()
        df_num_requests_by_cat_hoquei = df_num_requests_by_cat_hoquei.rename(columns={'index': 'Núm. sorteig'})

    def _req_type(x):
        s = str(x).strip().casefold()
        if s == "casa":
            return "casa"
        if s == "fora":
            return "fora"
        return None

    def _is_real_team(row) -> bool:
        nom = row.get("Nom", "")
        ent = row.get("Entitat", "")
        if pd.isna(nom) or str(nom).strip() == "":
            return False
        if str(ent).strip() in ("", "Descans"):
            return False
        return True

    contraris = {1: 5, 2: 6, 3: 7, 4: 8, 5: 1, 6: 2, 7: 3, 8: 4}

    if resultats_totals:
        all_results = pd.concat(resultats_totals, ignore_index=True)

        # 1) Comptatge
        input_total = len(df)
        assigned_real = all_results[all_results.apply(_is_real_team, axis=1)]
        assigned_total = len(assigned_real)
        status = "OK" if input_total == assigned_total else "KO"
        df_val_count_summary = pd.DataFrame([
            {"Mètrica": "Equips esperats (input)", "Valor": input_total},
            {"Mètrica": "Equips assignats (sense dummies)", "Valor": assigned_total},
            {"Mètrica": "Estat", "Valor": status},
        ])
        per_cat_in = df.groupby("Nom Lliga").size().rename("Esperats").to_frame()
        per_cat_assigned = (
            assigned_real.groupby("Nom Lliga").size().rename("Assignats").to_frame()
            if not assigned_real.empty else pd.DataFrame(columns=["Assignats"])  # empty
        )
        df_val_count_by_cat = per_cat_in.join(per_cat_assigned, how="outer").fillna(0).reset_index().rename(columns={"Nom Lliga": "Categoria"})
        df_val_count_by_cat["Esperats"] = df_val_count_by_cat["Esperats"].astype(int)
        df_val_count_by_cat["Assignats"] = df_val_count_by_cat["Assignats"].astype(int)
        df_val_count_by_cat["OK"] = df_val_count_by_cat["Esperats"] == df_val_count_by_cat["Assignats"]

        # 2) Conflictes d'entitat per grup
        rows_conf = []
        for cat, df_cat_res in all_results.groupby("Nom Lliga"):
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

        # 3) Coherència CASA/FORA per equips segons mapping global (equips_to_num_sorteig)
        rows = []
        if 'equip_to_num_sorteig' in locals():
            mapping = equip_to_num_sorteig
            sub = all_results.copy()
            sub = sub[sub.apply(_is_real_team, axis=1)]
            for _, r in sub.iterrows():
                req = _req_type(r.get("Núm. sorteig"))
                if req is None:
                    continue
                equip_id = r.get("Id")
                expected = mapping.get(equip_id)
                if expected is None:
                    continue  # sense mapping global per aquest equip
                try:
                    assigned = int(r.get("Núm. sorteig assignat", 0))
                except Exception:
                    continue
                if assigned != expected:
                    diffs = r.get("Diferències jornades")
                    diffs_txt = _format_diffs_excel(diffs)
                    rows.append([r["Entitat"], r["Nom Lliga"], r.get("Nom"), req, expected, assigned, diffs_txt])
        if rows:
            df_val_casa_fora = pd.DataFrame(rows, columns=["Entitat", "Categoria", "Equip", "Petició", "Esperat", "Assignat", "Diferències jornades"])

        # 3c) Núm. sorteig explícit (enter) no complert
        num_rows = []
        sub2 = all_results.copy()
        sub2 = sub2[sub2.apply(_is_real_team, axis=1)]
        for _, r in sub2.iterrows():
            s = r.get("Núm. sorteig")
            try:
                desired = int(s)
            except Exception:
                continue
            try:
                assigned = int(r.get("Núm. sorteig assignat", 0))
            except Exception:
                continue
            if desired != assigned:
                diffs = r.get("Diferències jornades")
                diffs_txt = _format_diffs_excel(diffs)
                num_rows.append([r["Entitat"], r["Nom Lliga"], r.get("Nom"), desired, assigned, diffs_txt])
        if num_rows:
            df_val_num_mismatch = pd.DataFrame(num_rows, columns=["Entitat", "Categoria", "Equip", "Sol·licitat", "Assignat", "Diferències jornades"]).sort_values(["Categoria", "Entitat", "Equip"]).reset_index(drop=True)

        # 3b) Resum per entitat: números CASA/FORA assignats (segons dupla triada) + recompte de peticions
        ent_rows = []
        # Precalcula s_lower per comptar peticions
        s_lower = df['Núm. sorteig'].astype(str).str.strip().str.lower()
        for entitat, dupla_idx in (entitats_assigned.items() if 'entitats_assigned' in locals() else []):
            try:
                casa_num, fora_num = duples_casa_fora[int(dupla_idx)]
            except Exception:
                continue
            n_casa = int(((df['Entitat'] == entitat) & s_lower.eq('casa')).sum())
            n_fora = int(((df['Entitat'] == entitat) & s_lower.eq('fora')).sum())
            ent_rows.append({
                "Entitat": entitat,
                "Casa": casa_num,
                "Fora": fora_num,
                "Número Equips CASA": n_casa,
                "Número Equips FORA": n_fora,
            })
        if ent_rows:
            df_entitat_slots = pd.DataFrame(ent_rows).sort_values("Entitat").reset_index(drop=True)

        # 4) Nivells dispars (dif >= 3 lletres) per grup
        def _level_idx(val):
            s = str(val).strip()
            if not s:
                return None
            # Match a final standalone A–E, optionally preceded by 'Nivell'
            m = re.search(r"(?i)(?:nivell\s*)?([A-E])\s*$", s)
            if not m:
                # Fallback: take the last token if it is a single letter A–E
                toks = [t for t in re.split(r"\s+", s) if t]
                if toks:
                    last = toks[-1].upper()
                    if last in {"A", "B", "C", "D", "E"}:
                        m = [None, last]
                    else:
                        return None
            ch = (m[1] if isinstance(m, (list, tuple)) else m.group(1)).upper()
            return {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}.get(ch)

        spread_rows = []
        # Agrupa per categoria i grup
        for (cat, grup), df_grp in all_results.groupby(["Nom Lliga", "Grup"]):
            df_grp = df_grp[df_grp.apply(_is_real_team, axis=1)]
            if df_grp.empty:
                continue
            idxs = [idx for idx in ( _level_idx(x) for x in df_grp["Nivell"] ) if idx is not None]
            if not idxs:
                continue
            mn, mx = min(idxs), max(idxs)
            dif = mx - mn
            if dif >= 3:
                # Llista de nivells presents com a lletres ordenades
                letters = { {1:"A",2:"B",3:"C",4:"D",5:"E"}[i] for i in set(idxs) if i in {1,2,3,4,5} }
                levels_txt = ", ".join(sorted(letters)) if letters else ""
                spread_rows.append({
                    "Categoria": cat,
                    "Grup": grup,
                    "Nivells": levels_txt,
                    "Min": {1:"A",2:"B",3:"C",4:"D",5:"E"}[mn],
                    "Max": {1:"A",2:"B",3:"C",4:"D",5:"E"}[mx],
                    "Dif": int(dif),
                })
        if spread_rows:
            df_val_level_spread = pd.DataFrame(spread_rows)


    # --- DESPRÉS DEL BUCLE PER CATEGORIES ---
    # Escriu tot en un sol Excel amb format
    # Agafem el nom sense l'extensio
    nom_fitxer = os.path.splitext(os.path.basename(nom_fitxer))[0]
    excel_path = os.path.join(BASE_PATH, f"assignacions_{nom_fitxer}.xlsx")
    os.makedirs(os.path.dirname(excel_path), exist_ok=True)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
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

        # --- FULL "Resum" opcional amb info agregada ---
        used_sheet_names = set()
        if info_totals:
            # Construeix el DataFrame d'info i elimina camps no tabulars (com 'fairness')
            df_info = pd.DataFrame(info_totals)
            if 'fairness' in df_info.columns:
                df_info = df_info.drop(columns=['fairness'])
            df_info.to_excel(writer, sheet_name="Resum", index=False)
            ws_info = writer.sheets["Resum"]
            used_sheet_names.add("Resum")
            # capçalera
            for col_idx, _ in enumerate(df_info.columns):
                ws_info.write(0, col_idx, df_info.columns[col_idx], fmt_header)
                ws_info.set_column(col_idx, col_idx, 18)
            ws_info.autofilter(0, 0, max(0, len(df_info)), max(0, len(df_info.columns) - 1))
            ws_info.freeze_panes(1, 0)

            # Escriu seccions de VALIDACIONS a continuació
            start_row = len(df_info) + 2
            ws_info.write(start_row, 0, "VALIDACIONS", fmt_title)
            start_row += 2

            # Comptatge
            if not df_val_count_summary.empty:
                ws_info.write(start_row, 0, "Recompte global", fmt_header)
                df_val_count_summary.to_excel(writer, sheet_name="Resum", index=False, startrow=start_row+1)
                start_row = start_row + 2 + len(df_val_count_summary)

            if not df_val_count_by_cat.empty:
                start_row += 1
                ws_info.write(start_row, 0, "Recompte per categoria", fmt_header)
                df_val_count_by_cat.to_excel(writer, sheet_name="Resum", index=False, startrow=start_row+1)
                start_row = start_row + 2 + len(df_val_count_by_cat)

            # Comptatge de números demanats per categoria - VOLEI
            if not df_num_requests_by_cat.empty:
                start_row += 1
                ws_info.write(start_row, 0, "Comptatge de números demanats per categoria - VOLEI", fmt_header)
                df_num_requests_by_cat.to_excel(writer, sheet_name="Resum", index=False, startrow=start_row+1)
                # Configuració d'amplades per aquesta secció matricial
                ws_info.set_column(0, 0, 15)  # Núm. sorteig
                # Configurem amplades per les columnes de categories i total
                for col_idx in range(1, len(df_num_requests_by_cat.columns)):
                    col_name = df_num_requests_by_cat.columns[col_idx]
                    if col_name == 'TOTAL':
                        ws_info.set_column(col_idx, col_idx, 12)  # Columna TOTAL
                    else:
                        # Calculem amplada basada en el nom de la categoria (màxim 25)
                        width = min(max(len(str(col_name)), 12), 25)
                        ws_info.set_column(col_idx, col_idx, width)
                start_row = start_row + 2 + len(df_num_requests_by_cat)

            # Comptatge de números demanats per categoria - FUTBOL
            if not df_num_requests_by_cat_futbol.empty:
                start_row += 1
                ws_info.write(start_row, 0, "Comptatge de números demanats per categoria - FUTBOL", fmt_header)
                df_num_requests_by_cat_futbol.to_excel(writer, sheet_name="Resum", index=False, startrow=start_row+1)
                # Configuració d'amplades per aquesta secció matricial
                ws_info.set_column(0, 0, 15)  # Núm. sorteig
                # Configurem amplades per les columnes de categories i total
                for col_idx in range(1, len(df_num_requests_by_cat_futbol.columns)):
                    col_name = df_num_requests_by_cat_futbol.columns[col_idx]
                    if col_name == 'TOTAL':
                        ws_info.set_column(col_idx, col_idx, 12)  # Columna TOTAL
                    else:
                        # Calculem amplada basada en el nom de la categoria (màxim 25)
                        width = min(max(len(str(col_name)), 12), 25)
                        ws_info.set_column(col_idx, col_idx, width)
                start_row = start_row + 2 + len(df_num_requests_by_cat_futbol)

            # Comptatge de números demanats per categoria - HOQUEI
            if not df_num_requests_by_cat_hoquei.empty:
                start_row += 1
                ws_info.write(start_row, 0, "Comptatge de números demanats per categoria - HOQUEI", fmt_header)
                df_num_requests_by_cat_hoquei.to_excel(writer, sheet_name="Resum", index=False, startrow=start_row+1)
                # Configuració d'amplades per aquesta secció matricial
                ws_info.set_column(0, 0, 15)  # Núm. sorteig
                # Configurem amplades per les columnes de categories i total
                for col_idx in range(1, len(df_num_requests_by_cat_hoquei.columns)):
                    col_name = df_num_requests_by_cat_hoquei.columns[col_idx]
                    if col_name == 'TOTAL':
                        ws_info.set_column(col_idx, col_idx, 12)  # Columna TOTAL
                    else:
                        # Calculem amplada basada en el nom de la categoria (màxim 25)
                        width = min(max(len(str(col_name)), 12), 25)
                        ws_info.set_column(col_idx, col_idx, width)
                start_row = start_row + 2 + len(df_num_requests_by_cat_hoquei)

            # Conflictes d'entitat
            if not df_val_entity_conflicts.empty:
                start_row += 1
                ws_info.write(start_row, 0, "Conflictes d'entitat per grup", fmt_header)
                df_val_entity_conflicts.to_excel(writer, sheet_name="Resum", index=False, startrow=start_row+1)
                start_row = start_row + 2 + len(df_val_entity_conflicts)
            else:
                start_row += 1
                ws_info.write(start_row, 0, "Conflictes d'entitat per grup", fmt_header)
                ws_info.write(start_row+1, 0, "Cap conflicte detectat.")
                start_row += 3

            # Entitats – números CASA/FORA assignats
            if not df_entitat_slots.empty:
                ws_info.write(start_row, 0, "Entitats – números CASA/FORA assignats", fmt_header)
                df_entitat_slots.to_excel(writer, sheet_name="Resum", index=False, startrow=start_row+1)
                start_row = start_row + 2 + len(df_entitat_slots)
            else:
                ws_info.write(start_row, 0, "Entitats – números CASA/FORA assignats", fmt_header)
                ws_info.write(start_row+1, 0, "Cap entitat amb assignació CASA/FORA.")
                start_row += 3

        # --- FULL "Incidències" amb totes les incidències agrupades per entitat ---
        # Combinem totes les incidències en una sola taula agrupada per entitat
        all_incidents = []
        
        # Recopilem totes les incidències organitzades per entitat
        incidents_by_entity = {}
        
        # Processem incidències CASA/FORA per entitat
        if not df_val_casa_fora.empty:
            for _, r in df_val_casa_fora.iterrows():
                entitat = r["Entitat"]
                if entitat not in incidents_by_entity:
                    incidents_by_entity[entitat] = []
                incidents_by_entity[entitat].append({
                    "Entitat": entitat,
                    "Categoria": r["Categoria"],
                    "Equip": r["Equip"],
                    "Tipus Incidència": "CASA/FORA incoherència",
                    "Detall": f"Petició: {r['Petició']}, Esperat: {r['Esperat']}, Assignat: {r['Assignat']}",
                    "Info Addicional": _format_diffs_excel(r.get('Diferències jornades')),
                    "Grup": ""
                })
        
        # Processem incidències de números explícits per entitat
        if not df_val_num_mismatch.empty:
            for _, r in df_val_num_mismatch.iterrows():
                entitat = r["Entitat"]
                if entitat not in incidents_by_entity:
                    incidents_by_entity[entitat] = []
                incidents_by_entity[entitat].append({
                    "Entitat": entitat,
                    "Categoria": r["Categoria"],
                    "Equip": r["Equip"],
                    "Tipus Incidència": "Núm. sorteig no complert",
                    "Detall": f"Sol·licitat: {r['Sol·licitat']}, Assignat: {r['Assignat']}",
                    "Info Addicional": _format_diffs_excel(r.get('Diferències jornades')),
                    "Grup": ""
                })   

        # Construïm la llista final: primer per entitat (ordenada), després nivells dispars
        all_incidents = []
        for entitat in sorted(incidents_by_entity.keys(), key=lambda s: str(s).casefold()):
            # Dins de cada entitat, ordenem per categoria i equip
            entity_incidents = sorted(
                incidents_by_entity[entitat],
                key=lambda x: (str(x["Categoria"]).casefold(), str(x["Equip"]).casefold())
            )
            all_incidents.extend(entity_incidents)

        # Afegim incidències de nivells dispars
        if not df_val_level_spread.empty:
            for _, r in df_val_level_spread.iterrows():
                all_incidents.append({
                    "Entitat": "— Grup amb nivells dispars —",
                    "Categoria": r["Categoria"],
                    "Equip": "",
                    "Tipus Incidència": "Nivells dispars (≥3)",
                    "Detall": f"Nivells: {r['Nivells']}, Diferència: {r['Dif']} (Min: {r['Min']}, Max: {r['Max']})",
                    "Info Addicional": "",
                    "Grup": r["Grup"]
                })
        
        # Creem el DataFrame consolidat i l'ordenem per entitat i categoria
        if all_incidents:
            df_incidents = pd.DataFrame(all_incidents)
            df_incidents = df_incidents.sort_values(["Entitat", "Categoria", "Equip"]).reset_index(drop=True)
            
            used_sheet_names.add("Incidències")
            ws_inc = workbook.add_worksheet("Incidències")
            writer.sheets["Incidències"] = ws_inc
            row_ptr = 0
            ws_inc.write(row_ptr, 0, "INCIDÈNCIES AGRUPADES PER ENTITAT", fmt_title)
            row_ptr += 2
            
            # Escrivim les capçaleres manualment
            for col_idx, col_name in enumerate(df_incidents.columns):
                ws_inc.write(row_ptr, col_idx, col_name, fmt_header)
                # Ajustem amplades de columna
                if col_name == "Entitat":
                    ws_inc.set_column(col_idx, col_idx, 25)
                elif col_name == "Categoria":
                    ws_inc.set_column(col_idx, col_idx, 20)
                elif col_name == "Equip":
                    ws_inc.set_column(col_idx, col_idx, 30)
                elif col_name == "Tipus Incidència":
                    ws_inc.set_column(col_idx, col_idx, 20)
                elif col_name == "Detall":
                    ws_inc.set_column(col_idx, col_idx, 40)
                elif col_name == "Info Addicional":
                    ws_inc.set_column(col_idx, col_idx, 40)
                else:
                    ws_inc.set_column(col_idx, col_idx, 15)
            
            row_ptr += 1  # Salta la fila de capçaleres
            
            # Escrivim les incidències fila per fila amb colors per entitat
            entitats_uniques = df_incidents['Entitat'].unique()
            color_mapping = {}
            for idx, entitat in enumerate(entitats_uniques):
                color_mapping[entitat] = (idx % len(fmt_incident_colors)) + 1
            
            current_entitat = None
            for index, row in df_incidents.iterrows():
                entitat = row['Entitat']
                
                # Afegeix separador visual quan canvia l'entitat
                if current_entitat is not None and current_entitat != entitat:
                    for col_idx in range(len(df_incidents.columns)):
                        ws_inc.write(row_ptr, col_idx, "", fmt_separator)
                    row_ptr += 1
                
                current_entitat = entitat
                color_idx = color_mapping[entitat]
                fmt_color = fmt_incident_colors[color_idx]
                
                # Escriu cada cel·la de la fila amb el format colorejat
                for col_idx, col_name in enumerate(df_incidents.columns):
                    value = row[col_name]
                    needs_wrap = False
                    if col_name in ["Detall", "Info Addicional"]:
                        # Fes wrap si és llarg o si conté salts de línia
                        s = str(value)
                        needs_wrap = (len(s) > 50) or ("\n" in s)
                    if needs_wrap:
                        fmt_color_wrap = workbook.add_format({
                            "bg_color": fmt_incident_colors[color_idx].bg_color,
                            "border": 1,
                            "text_wrap": True
                        })
                        ws_inc.write(row_ptr, col_idx, value, fmt_color_wrap)
                    else:
                        ws_inc.write(row_ptr, col_idx, value, fmt_color)
                
                row_ptr += 1
            
            # Afegim filtres i congelació (ajustem per la nova estructura)
            header_row = 2  # Capçaleres estan a la fila 2 (0-indexed)
            last_row = row_ptr - 1  # Última fila amb dades
            ws_inc.autofilter(header_row, 0, last_row, len(df_incidents.columns) - 1)
            ws_inc.freeze_panes(header_row + 1, 0)
            
        else:
            # Si no hi ha incidències
            used_sheet_names.add("Incidències")
            ws_inc = workbook.add_worksheet("Incidències")
            writer.sheets["Incidències"] = ws_inc
            ws_inc.write(0, 0, "INCIDÈNCIES", fmt_title)
            ws_inc.write(2, 0, "Cap incidència detectada.", fmt_default)

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

        # missatge final
    print(f"[OK] Excel generat → {excel_path}")

    output.seek(0)
    return output

    # --- VALIDACIONS GLOBALS POST-PROCÉS ---
    def _req_type(x):
        s = str(x).strip().casefold()
        if s == "casa":
            return "casa"
        if s == "fora":
            return "fora"
        return None

    def _is_real_team(row) -> bool:
        nom = row.get("Nom", "")
        ent = row.get("Entitat", "")
        if pd.isna(nom) or str(nom).strip() == "":
            return False
        if str(ent).strip() in ("", "Descans"):
            return False
        return True

    contraris = {1: 5, 2: 6, 3: 7, 4: 8, 5: 1, 6: 2, 7: 3, 8: 4}

    if resultats_totals:
        all_results = pd.concat(resultats_totals, ignore_index=True)

        # 1) Verificació de recompte d'equips (excloent dummies i files buides)
        input_total = len(df)
        assigned_real = all_results[all_results.apply(_is_real_team, axis=1)]
        assigned_total = len(assigned_real)
        ok_count = (input_total == assigned_total)

        if not ok_count:
            print(f"VALIDACIÓ (COMPTATGE): Esperats {input_total} equips, assignats {assigned_total} (excloent dummies).")
            # detall per categoria
            per_cat_in = df.groupby("Nom Lliga").size().to_dict()
            per_cat_assigned = (
                assigned_real.groupby("Nom Lliga").size().to_dict()
                if not assigned_real.empty else {}
            )
            diffs = {k: (per_cat_in.get(k, 0), per_cat_assigned.get(k, 0)) for k in set(per_cat_in) | set(per_cat_assigned)}
            for cat, (exp, got) in sorted(diffs.items()):
                if exp != got:
                    print(f"  - [{cat}] esperats {exp}, assignats {got}")
        else:
            print("VALIDACIÓ (COMPTATGE): OK – totals coincideixen (excloent dummies).")

        # 2) Verificació de conflictes d'entitat dins de cada grup per categoria
        any_conflicts = False
        for cat, df_cat_res in all_results.groupby("Nom Lliga"):
            for grup, df_grup in df_cat_res.groupby("Grup"):
                ents = [e for e in df_grup["Entitat"].tolist() if e and e != "Descans"]
                cnt = pd.Series(ents).value_counts() if ents else pd.Series(dtype=int)
                dup = cnt[cnt > 1]
                if not dup.empty:
                    any_conflicts = True
                    print(f"VALIDACIÓ (ENTITAT): Conflicte a {cat} / {grup} → {dup.to_dict()}")
        if not any_conflicts:
            print("VALIDACIÓ (ENTITAT): OK – cap grup té duplicats d'entitat.")

        # 2.5) Anàlisi d'equitabilitat de costos entre entitats
        print("\n--- ANÀLISI D'EQUITABILITAT DE COSTOS ---")
        equitabilitat = analitzar_equitabilitat_costos(entity_costs, all_results)
        
        if equitabilitat["status"] == "Analitzat":
            print(f"Nombre d'entitats: {equitabilitat['num_entitats']}")
            print(f"Cost mitjà per entitat: {equitabilitat['cost_mitjà']:.2f}")
            print(f"Rang de costos: {equitabilitat['cost_min']:.2f} - {equitabilitat['cost_max']:.2f}")
            print(f"Desviació estàndard: {equitabilitat['desviació_estàndard']:.2f}")
            print(f"Ràtio de desigualtat (màx/mín): {equitabilitat['ràtio_desigualtat']:.2f}")
            
            if equitabilitat['entitats_molt_perjudicades']:
                print(f"\n⚠️  ENTITATS MOLT PERJUDICADES (>2σ): {equitabilitat['entitats_molt_perjudicades']}")
            
            if equitabilitat['entitats_perjudicades']:
                print(f"\n⚠️  ENTITATS PERJUDICADES (>1σ): {equitabilitat['entitats_perjudicades']}")
            
            # Mostra els 5 costos més alts i més baixos
            costos_ordenats = sorted(equitabilitat['costos_detallats'].items(), key=lambda x: x[1], reverse=True)
            print("\nTOP 5 ENTITATS AMB MÉS COST:")
            for i, (entitat, cost) in enumerate(costos_ordenats[:5]):
                num_equips = equitabilitat['equips_per_entitat'].get(entitat, 1)
                cost_per_equip = equitabilitat['cost_per_equip'].get(entitat, 0)
                print(f"  {i+1}. {entitat}: {cost:.2f} total ({num_equips} equips, {cost_per_equip:.2f}/equip)")
            
            print("\nTOP 5 ENTITATS AMB MENYS COST:")
            for i, (entitat, cost) in enumerate(costos_ordenats[-5:][::-1]):
                num_equips = equitabilitat['equips_per_entitat'].get(entitat, 1)
                cost_per_equip = equitabilitat['cost_per_equip'].get(entitat, 0)
                print(f"  {i+1}. {entitat}: {cost:.2f} total ({num_equips} equips, {cost_per_equip:.2f}/equip)")
            
            # Avaluació de l'equitabilitat
            if equitabilitat['ràtio_desigualtat'] > 5.0:
                print("\n🚨 AVALUACIÓ: Distribució MOLT DESIGUAL de costos (ràtio > 5.0)")
            elif equitabilitat['ràtio_desigualtat'] > 3.0:
                print("\n⚠️  AVALUACIÓ: Distribució DESIGUAL de costos (ràtio > 3.0)")
            elif equitabilitat['ràtio_desigualtat'] > 2.0:
                print("\n⚡ AVALUACIÓ: Distribució MODERADAMENT DESIGUAL (ràtio > 2.0)")
            else:
                print("\n✅ AVALUACIÓ: Distribució RELATIVAMENT EQUITATIVA de costos")
        else:
            print(f"No es pot analitzar equitabilitat: {equitabilitat['status']}")

        # 3) Coherència CASA/FORA per equips segons mapping global (equips_to_num_sorteig)
        incoherencies = []
        if 'equip_to_num_sorteig' in locals():
            mapping = equip_to_num_sorteig
            sub = all_results.copy()
            sub = sub[sub.apply(_is_real_team, axis=1)]
            for _, r in sub.iterrows():
                req = _req_type(r.get("Núm. sorteig"))
                if req is None:
                    continue
                equip_id = r.get("Id")
                expected = mapping.get(equip_id)
                if expected is None:
                    continue
                try:
                    assigned = int(r.get("Núm. sorteig assignat", 0))
                except Exception:
                    continue
                if assigned != expected:
                    diffs = r.get("Diferències jornades")
                    incoherencies.append((r["Entitat"], r["Nom Lliga"], r.get("Nom"), req, expected, assigned, diffs))
        if incoherencies:
            print("VALIDACIÓ (CASA/FORA): S'han detectat incoherències d'slot segons mapping global:")
            for entitat, cat, nom, req, esperat, assignat, diffs in incoherencies:
                print(f"  - {entitat} · {cat} · {nom} · petició={req} → esperat {esperat}, assignat {assignat} · diferències jornades: {diffs if diffs else '—'}")
        else:
            print("VALIDACIÓ (CASA/FORA): OK – cada equip amb CASA/FORA està al número del mapping global.")

        # 4) Nivells dispars (≥3) – consola
        level_spread_issues = []
        def _level_idx2(val):
            s = str(val).strip()
            if not s:
                return None
            m = re.search(r"(?i)(?:nivell\s*)?([A-E])\s*$", s)
            if not m:
                toks = [t for t in re.split(r"\s+", s) if t]
                if toks:
                    last = toks[-1].upper()
                    if last in {"A", "B", "C", "D", "E"}:
                        m = [None, last]
                    else:
                        return None
            ch = (m[1] if isinstance(m, (list, tuple)) else m.group(1)).upper()
            return {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}.get(ch)
        
        for (cat, grup), df_grp in all_results.groupby(["Nom Lliga", "Grup"]):
            df_grp = df_grp[df_grp.apply(_is_real_team, axis=1)]
            if df_grp.empty:
                continue
            idxs = [idx for idx in ( _level_idx2(x) for x in df_grp["Nivell"] ) if idx is not None]
            if not idxs:
                continue
            mn, mx = min(idxs), max(idxs)
            dif = mx - mn
            if dif >= 3:
                letters = { {1:"A",2:"B",3:"C",4:"D",5:"E"}[i] for i in set(idxs) if i in {1,2,3,4,5} }
                level_spread_issues.append((cat, grup, ", ".join(sorted(letters)), {1:"A",2:"B",3:"C",4:"D",5:"E"}[mn], {1:"A",2:"B",3:"C",4:"D",5:"E"}[mx], int(dif)))
        if level_spread_issues:
            print("VALIDACIÓ (NIVELLS): Grups amb diferència de nivell ≥ 3:")
            for cat, grup, lvls, mn, mx, dif in level_spread_issues:
                print(f"  - {cat} / {grup} → nivells: {lvls} · min={mn}, max={mx}, dif={dif}")
        else:
            print("VALIDACIÓ (NIVELLS): OK – cap grup té diferència de nivell ≥ 3.")

    # (Opcional) Retorna un únic DataFrame concatenat amb totes les categories
    if resultats_totals:
        return pd.concat(resultats_totals, ignore_index=True), info_totals
    return pd.DataFrame(), info_totals



# ----------------------------------------------------------------------


def process_excel(input_path: str, return_logs: bool = False) -> str:
    """
    Llegeix l'Excel d'entrada, executa la pipeline i retorna el path
    a un ZIP amb els resultats generats (p.ex. 'csv_generats', informes, etc.).
    """
    # 1) Llegeix l’Excel d’entrada
    logs = []
    logs.append("Llegint fitxer Excel...")
    df = pd.read_excel(input_path)
    logs.append(f"S’han carregat {len(df)} files.")

    print(f"[INFO] Processant fitxer: {input_path} ({len(df)} files)")
    # 2) Executa la teva lògica existent (fa servir processar_dades_2)
    #    Aquesta funció ja escriu sortides a BASE_PATH/csv_generats
    excel_path = processar_dades_2(df, nom_fitxer=Path(input_path).name)  # <- la teva funció existent
    '''logs.append("Procés de dades complet.")

    # 3) Empaqueta les sortides en un ZIP temporal
    base_dir = Path(os.getcwd()) if os.getenv("APP_ENV","DEV")=="DEV" else Path("/app/dades")
    out_dir = base_dir / "csv_generats"
    if not out_dir.exists():
        # Si no es generen CSVs, com a fallback, crea un "resultat_vuit.txt"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "resultat_vuit.txt").write_text("No s'han generat fitxers.")

    zip_fd, zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(zip_fd)
    zip_dst = Path(zip_path)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        # Copia tota la carpeta de sortida
        if out_dir.exists():
            shutil.copytree(out_dir, tmpdir / out_dir.name)
        shutil.make_archive(str(zip_dst.with_suffix("")), "zip", tmpdir)'''

    logs.append("Resultat generat correctament.")
    if return_logs:
            return excel_path, logs
    return str(excel_path)



if __name__ == "__main__":
    # Llista tots els fitxers CSV del directori actual
    if len(sys.argv) > 1:
        in_path = sys.argv[1]
        out_path = sys.argv[2] if len(sys.argv) > 2 else None
        zip_path = process_excel(in_path)
        if out_path and out_path.lower().endswith(".zip"):
            shutil.move(zip_path, out_path)
        else:
            print(f"Resultat empaquetat: {zip_path}")

        '''fitxer_csv = sys.argv[1]
        if not os.path.isfile(fitxer_csv):
            print(f"Error: El fitxer '{fitxer_csv}' no existeix.")
            sys.exit(1)

        # Verifiquem que el fitxer tingui extensió .csv o .xlsx
        if not (fitxer_csv.endswith('.csv') or fitxer_csv.endswith('.xlsx')):
            print(f"Error: El fitxer '{fitxer_csv}' no té una extensió vàlida.")
            sys.exit(1)

        # Si és un fitxer .xlsx, el convertim a .csv temporalment
        if fitxer_csv.endswith('.xlsx'):
            fitxer_csv = xlsx_to_csv(fitxer_csv)

        df = llegir_csv(fitxer_csv)
        # Llancem el procés principal
        if df is not None:
            processar_dades_2(df, fitxer_csv)
        sys.exit(0)'''
    
    else: 
        ruta_csv = os.path.join(BASE_PATH, "csv/")
        print("Ruta CSV:", ruta_csv)
        fitxers_csv = [f for f in os.listdir(ruta_csv) if (f.endswith('.csv') or f.endswith('.xlsx'))]
        print("Fitxers CSV disponibles:")
        for idx, f in enumerate(fitxers_csv, 1):
            print(f"{idx}. {f}")

        try:
            num = int(input("Introdueix el número del fitxer CSV: "))
            if 1 <= num <= len(fitxers_csv):
                nom_fitxer = fitxers_csv[num - 1]
                df = llegir_csv(os.path.join(ruta_csv, nom_fitxer))
                if nom_fitxer.endswith('.xlsx'):
                    path = xlsx_to_csv(os.path.join(ruta_csv, nom_fitxer))
                    df = llegir_csv(path)
                if df is not None:
                    processar_dades_2(df, nom_fitxer)
            else:
                print("Número fora de rang.")
        except ValueError:
            print("Has d'introduir un número vàlid.")