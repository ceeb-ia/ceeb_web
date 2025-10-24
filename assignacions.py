import pandas as pd
import numpy as np
from collections import defaultdict, Counter
import sys
from math import log2
import unicodedata, hashlib

from scipy.optimize import linear_sum_assignment
SCIPY_OK = True
#except Exception:
#    SCIPY_OK = False


# ---------- UTILITATS ----------
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

def obtenir_entitat(nom):
    # Deducció senzilla del nom de l'entitat (es pot adaptar segons el format real)
    import re
    return re.sub(r'\s+((["\']{1,2}).+?\2|[A-Za-zÀ-ÿ]+)$', '', str(nom)).strip()

def crear_grups_equilibrats(num_equips, max_grup=8, min_grup=6):
    '''
        Calcula el número de grups i el nombre d'equips per grup.
    '''

    # Si hi ha menys equips que el mínim, tot en un sol grup
    if num_equips < min_grup:
        return [num_equips]
    # Calcula quants equips per grup (mides equilibrades entre min i max)
    num_grups = max(1, (num_equips + max_grup - 1) // max_grup)
    while True:
        base = num_equips // num_grups
        sobra = num_equips % num_grups
        grups = [base + 1 if i < sobra else base for i in range(num_grups)]
        # Acceptem si complim el màxim; el mínim és desitjable però no forçat
        if max(grups) <= max_grup:
            return grups
        num_grups += 1


# ---------- CONSTRUCCIÓ DE LA MATRIU DE COSTOS ----------
def build_slots(repartiment):
    '''
        Genera la llista de "slots" (grup, posició dins del grup). És a dir, genera una llista
        que guarda totes les posicions disponibles segons el repartiment (nº de grups i equips per grup)
        donat.
    '''
    slots_per_group = 8
    slots = []
    for g, size in enumerate(repartiment):
        for p in range(slots_per_group):
            slots.append((g, p))
    return slots

primera_fase = [
    [(8,5),(6,4), (7,3),(1,2)],
    [(2,8),(3,1), (4,7),(5,6)],
    [(8,6),(7,5), (1,4),(2,3)],
    [(3,8),(4,2), (5,1),(6,7)],
    [(8,7),(1,6), (2,5),(3,4)],
    [(8,4),(5,3), (6,2),(7,1)],
    [(1,8),(2,7), (3,6),(4,5)],
] 


def cost_calc(equip, seed, g, p, disposicions, equips_to_num_sorteig, fase, w_dif_sorteig=3):
    """
    Calcula el cost per situar l'equip en el slot (g,p) segons el seu número preferit/sol·licitat.
    - Si el seed és "casa"/"fora", s'utilitza equips_to_num_sorteig[equip] per obtenir el número concret (1..8).
    - Si el seed és un enter 1..8, s'utilitza directament.
    - Si no hi ha seed vàlid, el cost és 0 (no es biaixa la posició).
    El cost base és (1 + diferències_pattern)^w_dif_sorteig, on diferències_pattern és el nombre de diferències
    entre la seqüència casa/fora del número preferit i la de la posició p.
    """

    cost = 0.0

    # Normalitza seed
    seed_norm = normalize_seed_value(seed)
    if pd.isna(seed_norm):
        seed_norm = None
    elif isinstance(seed_norm, str) and seed_norm in ("casa", "fora"):
        # Mapegem al número escollit prèviament per l'equip
        mapped = equips_to_num_sorteig.get(equip, None)
        if mapped is None:
            print ("Atenció 1: ", equip, seed)
            sys.exit("No hi ha mapping vàlid per a l'equip")
        # Verifiquem que seed_norm està dins dels valors valids per casa o fora
        if seed_norm == "casa" and mapped not in [8,7,6,1]:
            print ("Atenció 2: ", equip, seed)
            sys.exit("No hi ha número vàlid per a l'equip")
        elif seed_norm == "fora" and mapped not in [5,4,3,2]:
            print ("Atenció 3: ", equip, seed)
            sys.exit("No hi ha número vàlid per a l'equip")

        seed_norm = int(mapped)

        if seed_norm is None:
            print ("Atenció: ", equip, seed)
            sys.exit("No hi ha número vàlid per a l'equip")
            
        cost += -5.0  # Petita bonificació per demanar casa/fora
    else:
        try:
            seed_int = int(seed_norm)
            if 1 <= seed_int <= 8:
                seed_norm = seed_int
        except Exception:
            seed_norm = None

    # Si no hi ha número vàlid, no apliquem cap biaix
    if seed_norm is None:
        return 0.0

    # Construïm la seqüència de casa/fora del número preferit
    seed_matches = []
    for jornada in fase:
        for partit in jornada:
            if partit[0] == seed_norm:
                seed_matches.append("casa")
            if partit[1] == seed_norm:
                seed_matches.append("fora")

    # Seqüència del slot p (p és 0-based i disposicions és llista de 8 seqüències)
    match = disposicions[p]
    difs = sum(a != b for a, b in zip(seed_matches, match))

    # Penalització creixent amb les diferències del patró casa/fora

    cost += 4 ** difs
    return cost


def build_disposicions(fase):

    matches_0 = []
    matches_1 = []
    matches_2 = []
    matches_3 = []
    matches_4 = []
    matches_5 = []
    matches_6 = []
    matches_7 = []

    # Trobem la disposicio de partits casa, fora per cada equip
    for jornada in fase:
        for partit in jornada:
            # Cree la configuració de partits per equip
            if partit[0] == 1:
                matches_0.append("casa")
            if partit[1] == 1:
                matches_0.append("fora")
            if partit[0] == 2:
                matches_1.append("casa")
            if partit[1] == 2:
                matches_1.append("fora")
            if partit[0] == 3:
                matches_2.append("casa")
            if partit[1] == 3:
                matches_2.append("fora")
            if partit[0] == 4:
                matches_3.append("casa")
            if partit[1] == 4:
                matches_3.append("fora")
            if partit[0] == 5:
                matches_4.append("casa")
            if partit[1] == 5:
                matches_4.append("fora")
            if partit[0] == 6:
                matches_5.append("casa")
            if partit[1] == 6: 
                matches_5.append("fora")
            if partit[0] == 7:
                matches_6.append("casa")
            if partit[1] == 7:
                matches_6.append("fora")
            if partit[0] == 8:
                matches_7.append("casa")
            if partit[1] == 8:
                matches_7.append("fora")
                
        
    disposicions = [ matches_0, matches_1, matches_2, matches_3, matches_4, matches_5, matches_6, matches_7 ]


    return disposicions

def add_dummies(df_cat, repartiment):
    """
    Afegeix files Descans fins a omplir tots els slots (8 per grup).
    Retorna nou df_cat i nombre de dummies afegits.
    """
    total_slots = 8 * len(repartiment)
    falta = total_slots - len(df_cat)
    if falta <= 0:
        return df_cat, 0
    nom_lliga = df_cat.iloc[0]['Nom Lliga'] if 'Nom Lliga' in df_cat.columns and len(df_cat) else ''
    for k in range(falta):
        df_cat.loc[len(df_cat)] = {
            'Nom': f'Descans {k+1}',
            'Nom Lliga': nom_lliga,
            'Núm. sorteig': np.nan,
            'Entitat': 'Descans',
            'Nivell': 'Descans',
            'Id': f'DUMMY-{k+1}'
        }
    return df_cat.reset_index(drop=True), falta


def build_cost_matrix(df_cat, entity_costs, equips_to_num_sorteig, repartiment, w_dif_sorteig=5, fase=primera_fase):
    """
    Matriu de costos (equips x slots) amb criteris:
    - proximitat al número de sorteig
    """
    #print ("equips_to_num_sorteig:", equips_to_num_sorteig)
    slots = build_slots(repartiment) # Llista de (grup, posició)
    n_e = len(df_cat)   # Nombre d'equips
    n_s = len(slots)    # Nombre de slots (ha de ser igual a grups x 8)
    C = np.zeros((n_e, n_s), dtype=float)

    # Es crea una llista amb el número de sorteig de cada equip. Segueix l'ordre de df_cat
    seeds = df_cat['Núm. sorteig'].apply(
        lambda x: str(x).strip() if str(x).strip().lower() in ["fora", "casa"] else parse_int(x, default=np.nan)
    ).tolist()    
    entitats = df_cat['Entitat'].tolist()

    # Trobem la disposicio de partits casa, fora per cada equip
    disposicions = build_disposicions(fase)


    # Per cada num. sorteig (en ordre d'equips))
    vals = []
    if entity_costs:
        vals = [v for k, v in entity_costs.items() if k in set(entitats) and k != 'Descans']
    if vals:
        vmin, vmax = min(vals), max(vals)
        def norm(v):
            if vmax == vmin:
                return 1.0
            return (v - vmin) / (vmax - vmin)  # [0,1]
        
    equips_per_entitat = Counter(df_cat['Entitat'])
    
    # Calculem els factors d'entitat utilitzant la desviació estàndard
    entitat_factors = rebuild_entitat_factor(df_cat, entity_costs)


    for i, seed in enumerate(seeds):
        # i numera els equips.
        equip_id = df_cat.iloc[i]['Id']
        # Obtenim l'entitat de l'equip
        entitat = entitats[i]

        # Verifiquem si hi ha cost per entitat, sino, afegim l'entitat amb cost 0
        if entity_costs and entitat not in entity_costs:
            entity_costs[entitat] = 0

        # i el seu cost acumulat
        num_equips = equips_per_entitat.get(entitat, 1)
        cost_entitat = entity_costs.get(entitat, 0) if entity_costs else 0
        #factor_entitat = 1.0 + norm(cost_entitat) if vals else 1.0
        factor_entitat = entitat_factors[entitat]
        for j, (g, p) in enumerate(slots):
            # j númera els slots, combinacions úniques (grup, posició)
            cost = 0.

            cost = cost_calc(equip_id, seed, g, p, disposicions, equips_to_num_sorteig, fase, w_dif_sorteig=w_dif_sorteig)

            C[i, j] = cost * factor_entitat

    return C, slots, entity_costs


def level_entropy(nivells):
    # Excloem dummies i buits
    nivells_filtrats = [n for n in nivells if str(n).strip() not in ("", "Descans") and not pd.isna(n)]
    total = len(nivells_filtrats)
    if total == 0:
        return 0.0
    map_val = {
        "Nivell A": 1,
        "Nivell B": 2,
        "Nivell C": 3,
        "Nivell D": 4,
        "Nivell E": 5,
    }
    nums = [map_val.get(n, 5) for n in nivells_filtrats]
    entropia = 0.0
    for i, n1 in enumerate(nums):
        for j, n2 in enumerate(nums):
            if j > i and n1 != n2:
                if abs(n1 - n2) > 3:
                    entropia += 1/3*(abs(n1 - n2))
                #entropia += 3**(abs(n1 - n2))
    return entropia

def day_entropy(dies):
    # Excloem dummies i buits
    dies_filtrats = [d for d in dies if str(d).strip() not in ("", "Descans") and not pd.isna(d)]
    total = len(dies_filtrats)
    #print("Dies filtrats:", dies_filtrats)
    if total == 0:
        return 0.0
    map_val = {
        "Dilluns": 1,
        "Dimarts": 2,
        "Dimecres": 3,
        "Dijous": 4,
        "Divendres": 5,
        "Dissabte": 6,
        "Diumenge": 7,
    }
    nums = [map_val.get(d, 0) for d in dies_filtrats if d in map_val]
    if not nums:
        return 0.0
    entropia = 0.0
    for i, n1 in enumerate(nums):
        for j, n2 in enumerate(nums):
            if j > i and n1 != n2:
                entropia += abs(n1 - n2)
    return entropia



# ---------- CONTROL DE CONFLICTES PER ENTITAT ----------

def check_feasibility_entity(df_cat, repartiment):
    '''
        Comprova si hi ha alguna entitat amb més equips que grups
        Retorna un diccionari {entitat:count} de les entitats que no es poden separar.
        Exemple:
        Si tens 3 grups i el "Club X" té 4 equips, la funció retornarà {'Club X': 4}.
    '''
    num_grups = len(repartiment)
    counts = Counter(df_cat['Entitat']) # Contem nombre d'equips per entitat
    impossible = {e:c for e,c in counts.items() if c > num_grups} # Les fiquem al dict si hi ha més que grups
    return impossible


def build_groups_from_assignment(df_cat, slots, col_ind):
    '''
    Genera els grups a partir de l'assignació de slots. 
    La sortida és un diccionari {grup: [índexs equips]}, en ordre de 
    posició (numero sorteig) dins del grup.
    '''
    n_e_reals = len(df_cat)
    groups = defaultdict(dict)
    # Guardem (p, i_equ) per cada grup, 
    for i_equ, j_slot in enumerate(col_ind):
        if i_equ >= n_e_reals:
            continue  
        g, p = slots[int(j_slot)]
        groups[g][p] = i_equ
    return groups

def entity_conflicts(df_cat, groups):
    '''
    Comprova si hi ha conflictes d'entitat dins dels grups. 
    Retorna un diccionari {grup: {entitat:count}} de les entitats que tenen conflicte dins del grup.
    Exemple:
    Si en el grup 0 hi ha 2 equips del "Club X" i 1 del "Club Y", la funció retornarà {0: {'Club X': 2}}.
    '''
    conflicts = {}
    for g, pos_dict in groups.items():
        idxs = list(pos_dict.values())  # Ara pos_dict és {posició: índex_equip}
        ents = [df_cat.iloc[i]['Entitat'] for i in idxs]
        cnt = Counter(ents)
        over = {e: c for e, c in cnt.items() if c > 1 and e != 'Descans'}
        if over:
            conflicts[g] = over
    return conflicts



def repair_by_hungarian_per_position(df_cat, C, slots, row_ind, col_ind, conflicting_groups, groups,max_iters=10, penalty=1e6):
    """
    Per cada posició p conflictiva, resol una assignació òptima penalitzant molt si un grup ja té un equip de la mateixa entitat.
    """
    n_e = len(df_cat) # Nombre d'equips
    entitats = df_cat['Entitat'].tolist()
    equip_to_slot = {i: col_ind[i] for i in range(n_e)} # {índex equip: índex slot}

    # Dins conflicting_groups hi ha els grups amb conflictes
    for conflict_group in conflicting_groups:
        # Obtenim el grup i identifiquem els equips de la mateixa entitat
        grup_teams = list(groups[conflict_group].values())
        entitats_in_group = [entitats[i] for i in grup_teams]
        entitats_repetides = {e for e, c in Counter(entitats_in_group).items() if c > 1}
        entitats_considerades = set()
        conflicting_ps = set()
        # Per cada equip del grup
        for i_equ in grup_teams:
            # Si la seva entitat està repetida, marquem la seva posició com conflictiva
            if entitats[i_equ] in entitats_repetides and entitats[i_equ] not in entitats_considerades:
                _, p = slots[int(equip_to_slot[i_equ])]
                conflicting_ps.add(p)
                entitats_considerades.add(entitats[i_equ])


        if not conflicting_ps:
            continue
        else:

            for p in conflicting_ps:
                #print(f"Reparant posició {p} del grup {conflict_group}...")
                # Obtenim els equips i slots de la posició p en els diferents grups
                equips_p = [i for i in range(n_e) if slots[equip_to_slot[i]][1] == p]
                slots_p = [j for j, (g, p2) in enumerate(slots) if p2 == p]

                if not equips_p or not slots_p:
                    continue

                # Construïm una matriu de costos local per aquests equips i slots
                C_local = np.zeros((len(equips_p), len(slots_p)))
                grups_entitats = defaultdict(set)
                for i in range(n_e):
                    g, p2 = slots[equip_to_slot[i]]
                    #if p2 == p:
                    grups_entitats[g].add(entitats[i])

                # Per cada equip de la posició p, i cada slot de la posició p, assigna cost
                for i_loc, i_equ in enumerate(equips_p):
                    entitat_i = entitats[i_equ]
                
                    for j_loc, j_slot in enumerate(slots_p):
                        g, _ = slots[j_slot]
                        # S'obté el cost previ de la matriu original
                        cost = C[i_equ, j_slot]
                        # Si el grup ja té aquesta entitat, penalitza molt
                        if entitat_i in grups_entitats[g]:
                            cost += penalty
                        C_local[i_loc, j_loc] = cost

                row_l, col_l = linear_sum_assignment(C_local)
                for i_loc, j_loc in zip(row_l, col_l):
                    i_equ = equips_p[i_loc]
                    j_slot = slots_p[j_loc]
                    equip_to_slot[i_equ] = j_slot

                # Reconstruim els grups segons la nova assignació per la següent iteració
                groups_actual = build_groups_from_assignment(df_cat, slots, [equip_to_slot[i] for i in range(n_e)])
                groups = groups_actual

    new_col_ind = np.array([equip_to_slot[i] for i in range(n_e)])
    return row_ind, new_col_ind





def recalcular_costos_base_sense_factors(df_cat, groups, equips_to_num_sorteig=None):
    """
    Nova funció: Calcula els costos base reals sense factors entitat aplicats.
    Utilitza cost_calc() directament per obtenir costs nets.
    """
    from collections import defaultdict
    
    # Importem les funcions necessàries
    disposicions = build_disposicions(primera_fase)
    
    costos_base = defaultdict(float)
    
    for g, pos_dict in groups.items():
        for p, i_equ in pos_dict.items():
            if i_equ >= len(df_cat):
                continue
                
            equip = df_cat.iloc[i_equ]
            entitat = equip['Entitat']
            
            if entitat == 'Descans':
                continue
            
            # Calculem el cost base directament sense factors
            equip_id = equip.get('Id', '')
            raw_seed = equip.get('Núm. sorteig', '')
            seed = normalize_seed_value(raw_seed)
            
            # Cost base sense factor entitat
            cost_base = cost_calc(equip_id, seed, g, p, disposicions, 
                                equips_to_num_sorteig=equips_to_num_sorteig, fase=primera_fase, w_dif_sorteig=5)
            
            costos_base[entitat] += cost_base
    
    return dict(costos_base)


def normalize_seed_value(x):
    s = str(x).strip().lower()
    if s in ["casa", "fora"]:
        return s
    return parse_int(x, default=np.nan)




def homogeneitzar_nivell(df_cat, groups, max_iters=100):
    """
    Optimitza la distribució de nivells entre grups minimitzant l'entropia,
    adaptat al format groups: {grup: {posició: índex_equip}}
    """
    for _ in range(max_iters):
        millora = False
        # Convertim els dicts de posicions a llistes per facilitar els swaps
        grups_llista = {g: list(pos_dict.items()) for g, pos_dict in groups.items()}
        for g1, items1 in grups_llista.items():
            for g2, items2 in grups_llista.items():
                if g1 >= g2:
                    continue
                for idx1, (p1, i1) in enumerate(items1):
                    for idx2, (p2, i2) in enumerate(items2):
                        if p1 != p2:
                            continue
                        # Comprova que el swap no genera conflicte d'entitat
                        ent1 = df_cat.iloc[i1]['Entitat']
                        ent2 = df_cat.iloc[i2]['Entitat']
                        ents1 = [df_cat.iloc[i]['Entitat'] for _, i in sorted(items1) if i != i1] + [ent2]
                        ents2 = [df_cat.iloc[i]['Entitat'] for _, i in sorted(items2) if i != i2] + [ent1]
                        if len(ents1) != len(set(ents1)) or len(ents2) != len(set(ents2)):
                            continue
                        # Calcula entropia abans i després
                        nivells1 = [df_cat.iloc[i]['Nivell'] for _, i in items1]
                        nivells2 = [df_cat.iloc[i]['Nivell'] for _, i in items2]
                        entropia_abans = level_entropy(nivells1) + level_entropy(nivells2)
                        nivells1_swap = [df_cat.iloc[i]['Nivell'] for _, i in items1 if i != i1] + [df_cat.iloc[i2]['Nivell']]
                        nivells2_swap = [df_cat.iloc[i]['Nivell'] for _, i in items2 if i != i2] + [df_cat.iloc[i1]['Nivell']]
                        entropia_despres = level_entropy(nivells1_swap) + level_entropy(nivells2_swap)
                        if entropia_despres < entropia_abans:
                            # Accepta el swap
                            items1[idx1] = (p1, i2)
                            items2[idx2] = (p2, i1)
                            millora = True
        if not millora:
            break
        # Reconstrueix groups amb el nou format
        groups = {g: {p: i for p, i in items} for g, items in grups_llista.items()}
    # Retorna el diccionari amb el nou format
    return groups


def actualitzar_costos_entitat(disposicions, equips_to_num_sorteig, df_cat, C, row_ind, col_ind):
    
    '''
    Actualitza els costos per entitat segons l'assignació.
    CORRECCIÓ: Usa el cost base real, no el multiplicat pel factor entitat.
    '''    
    from collections import defaultdict
    costs_base_per_entitat = defaultdict(float)
    
    # Necessitem les mateixes dades que build_cost_matrix
    disposicions = build_disposicions(primera_fase)
    
    for r, c in zip(row_ind, col_ind):
        if r >= len(df_cat):
            continue
        
        equip = df_cat.iloc[r]
        entitat = equip['Entitat']
        
        if entitat == 'Descans':
            continue
        
        # Reconstruim els paràmetres per cost_calc
        equip_id = equip.get('Id', '')
        raw_seed = equip.get('Núm. sorteig', '')
        
        # Obtenim g, p del slot c
        # Assumint que els slots segueixen l'ordre: g*8 + p
        g = c // 8
        p = c % 8
        
        # AQUÍ: Usem cost_calc directament
        cost_base_real = cost_calc(
            equip_id, raw_seed, g, p, disposicions, 
            equips_to_num_sorteig=equips_to_num_sorteig,  # O el valor correcte si està disponible
            fase=primera_fase, 
            w_dif_sorteig=5
        )
        #cost_base_real = C[r, c]  # cost base amb factors
        
        costs_base_per_entitat[entitat] += cost_base_real
    

    return costs_base_per_entitat


def rebuild_entitat_factor(df_cat, entity_costs):
    '''
        Reconstrueix els factors d'entitat a partir dels costos que se li passin d'entitat.
    '''
    if not entity_costs:
        return defaultdict(lambda: 1.0)
    
    vals = [v for e, v in entity_costs.items() if e != 'Descans']
    if not vals or len(vals) < 2:
        return defaultdict(lambda: 1.0)
    
    # Calculem estadístiques per una normalització més equitativa
    mitjana = sum(vals) / len(vals)
    desviacio = (sum((v - mitjana) ** 2 for v in vals) / len(vals)) ** 0.5
    
    # Factor màxim d'amplificació basat en desviació estàndard
    max_factor = 4 # Factor màxim d'amplificació
    
    ef = {}
    for e in df_cat['Entitat'].unique():
        if e == 'Descans':
            ef[e] = 1.0
        else:
            cost_entitat = entity_costs.get(e, 0.0)
            
            if desviacio > 0:
                # Factor basat en quant es desvia de la mitjana
                desviacions = (cost_entitat - mitjana) / desviacio
                # Apliquem una funció suau per evitar salts bruscos
                factor_amplificacio = min(max_factor, 1.0 + max(0, desviacions * 0.5))
                factor_amplificacio = max(0.1, factor_amplificacio) # Com a mínim 0.1
            else:
                factor_amplificacio = 1.0
            
            ef[e] = factor_amplificacio
    
    return ef
    


# --- Afegir penalització per mala distribució de dummies ---
def homogeneitzar_costs(df_cat, groups, C, entity_costs_cat, entity_global_costs, entitats_casa_fora, slots,
                               equips_to_num_sorteig=None,
                               fase=primera_fase,
                               w_dif_sorteig=5,
                               lambda_entropia=1.0,
                               max_iters=3,
                               allow_intragroup=True,
                               same_pos_only=False,
                               incorpora_entity_costs=True,
                               update_entity_costs=True,
                               lambda_dummy_spread=50.0):
    """
    Millora local sobre:
        cost_sorteig * factor_entitat
        + lambda_entropia * entropia_nivells
        + lambda_dummy_spread * penalització_mala_distribució_dummies

    Nova part:
      - lambda_dummy_spread controla el pes de penalitzar que els dummies estiguin concentrats en pocs grups.
        Penalització = sum( (d_g - d_avg)^2 ) on d_g = #dummies del grup g i d_avg = total_dummies/num_grups
    """

    disposicions = build_disposicions(fase)

    def slot_idx(g, p): return g * 8 + p


    def cost_equip_slot(i_equ, g, p, entitat_factor):
        raw = df_cat.loc[i_equ]['Núm. sorteig']
        # Normalització del seed: "casa"/"fora" o enter, sinó NaN
        seed = normalize_seed_value(raw)
        equip_id = df_cat.loc[i_equ]['Id']

        base = cost_calc(equip_id, seed, g, p, disposicions, equips_to_num_sorteig, fase, w_dif_sorteig)
        fact = entitat_factor[df_cat.iloc[i_equ]['Entitat']]
        num_equips = len(df_cat[df_cat['Entitat'] == df_cat.iloc[i_equ]['Entitat']])
        return base * fact

    def entropia_grup(g):
        idxs = list(groups[g].values())
        nivells = [df_cat.iloc[i]['Nivell'] for i in idxs if df_cat.iloc[i]['Entitat'] != 'Descans']
        dies = [df_cat.iloc[i]['Dia partit'] for i in idxs if df_cat.iloc[i]['Entitat'] != 'Descans']
        #print("Entropia de dies", day_entropy(dies))
        return level_entropy(nivells) + day_entropy(dies)

    def dummy_counts(groups):
        return {g: sum(1 for idx in pos_dict.values() if df_cat.iloc[idx]['Entitat'] == 'Descans')
                for g, pos_dict in groups.items()}

    def dummy_penalty(counts):
        if lambda_dummy_spread == 0.0:
            return 0.0
        total_dum = sum(counts.values())
        if not counts:
            return 0.0
        d_avg = total_dum / len(counts)
        # Variància no normalitzada (sum (d_g - d_avg)^2)
        return sum((c - d_avg) ** 2 for c in counts.values())


    def rebuild_global_costs(entity_costs_cat, entity_costs_global):
        '''
            Combina els costos d'entitat globals (costos base globlas, no modificats per la categoria) amb els específics de categoria.
        '''
        if not entity_costs_cat:
            return entity_costs_global
        
        global_copy = entity_costs_global.copy()
        for e, v in entity_costs_cat.items():
            global_copy[e] = global_copy.get(e, 0.0) + v

        return global_copy

    # Inicial
    entropies = {g: entropia_grup(g) for g in groups}
    entropia_total = sum(entropies.values())

    d_counts = dummy_counts(groups)
    d_penalty = dummy_penalty(d_counts)

    actual_global_costs = rebuild_global_costs(entity_costs_cat, entity_global_costs)
    entitat_factor = rebuild_entitat_factor(df_cat, actual_global_costs)

    grups_ids_ordenats = sorted(groups.keys())

    for _ in range(max_iters):
        for i_g, g1 in enumerate(grups_ids_ordenats):
            for g2 in grups_ids_ordenats[i_g:]:
                
                # INTER-GRUP
                if same_pos_only:
                    parelles = [(p, p) for p in sorted(groups[g1].keys() & groups[g2].keys())]
                else:
                    parelles = [(p1, p2) for p1 in sorted(groups[g1].keys()) for p2 in sorted(groups[g2].keys())]

                for p1, p2 in parelles:
                    e1 = groups[g1][p1]
                    e2 = groups[g2][p2]
                    if e1 == e2:
                        continue

                    ent1 = df_cat.iloc[e1]['Entitat']
                    ent2 = df_cat.iloc[e2]['Entitat']
                    ents_g1_rest = [df_cat.iloc[idx]['Entitat'] for pos, idx in sorted(groups[g1].items()) if pos != p1]
                    ents_g2_rest = [df_cat.iloc[idx]['Entitat'] for pos, idx in sorted(groups[g2].items()) if pos != p2]

                    # Si algun equip pertany a entitats_casa_fora, només es permet swap si mantenen el mateix número (posició)
                    #if (ent1 in entitats_casa_fora or ent2 in entitats_casa_fora) and p1 != p2:
                    #    continue

                    if p1 == p2:
                        if (ent2 != 'Descans') and (ent2 in ents_g1_rest):
                            continue
                        if (ent1 != 'Descans') and (ent1 in ents_g2_rest):
                            continue
                    else:
                        # Comprova que el swap no genera conflicte d'entitat
                        if (ent2 != 'Descans') and (ent2 in ents_g1_rest):# or ent2 in entitats_casa_fora):
                            continue
                        if (ent1 != 'Descans') and (ent1 in ents_g2_rest):# or ent1 in entitats_casa_fora):
                            continue

                    # Cost actual

                    cost1_cur = cost_equip_slot(e1, g1, p1, entitat_factor)
                    cost2_cur = cost_equip_slot(e2, g2, p2, entitat_factor)
                    cost_actual_parell = cost1_cur + cost2_cur

                    # Entropia actual ja inclosa via entropia_total
                    # Descans penalty actual = d_penalty

                    total_actual = cost_actual_parell + lambda_entropia * entropia_total 
                    swap_toca_dummy = (ent1 == 'Descans') or (ent2 == 'Descans')
                    if swap_toca_dummy:
                        total_actual += lambda_dummy_spread * d_penalty

                    # Cost nou
                    cost1_new = cost_equip_slot(e1, g2, p2, entitat_factor)
                    cost2_new = cost_equip_slot(e2, g1, p1, entitat_factor)
                    parell_nou = cost1_new + cost2_new

                    # Entropia nova
                    nivells_g1_new = [df_cat.iloc[idx]['Nivell'] for pos, idx in groups[g1].items()
                                      if pos != p1 and df_cat.iloc[idx]['Entitat'] != 'Descans']
                    dies_g1_new = [df_cat.iloc[idx]['Dia partit'] for pos, idx in groups[g1].items()
                                   if pos != p1 and df_cat.iloc[idx]['Entitat'] != 'Descans']
                    if ent2 != 'Descans':
                        nivells_g1_new.append(df_cat.iloc[e2]['Nivell'])
                        dies_g1_new.append(df_cat.iloc[e2]['Dia partit'])
                    nivells_g2_new = [df_cat.iloc[idx]['Nivell'] for pos, idx in groups[g2].items()
                                      if pos != p2 and df_cat.iloc[idx]['Entitat'] != 'Descans']
                    dies_g2_new = [df_cat.iloc[idx]['Dia partit'] for pos, idx in groups[g2].items()
                                   if pos != p2 and df_cat.iloc[idx]['Entitat'] != 'Descans']
                    if ent1 != 'Descans':
                        nivells_g2_new.append(df_cat.iloc[e1]['Nivell'])
                        dies_g2_new.append(df_cat.iloc[e1]['Dia partit'])
                    ent_g1_new = level_entropy(nivells_g1_new) + day_entropy(dies_g1_new)
                    ent_g2_new = level_entropy(nivells_g2_new) + day_entropy(dies_g2_new)
                    
                    entropia_total_new = entropia_total - entropies[g1] - entropies[g2] + ent_g1_new + ent_g2_new

                    # Descans penalty nova (només canvien counts dels dos grups si algun involucrat és Descans)
                    if ent1 == 'Descans' or ent2 == 'Descans':
                        d_counts_new = d_counts.copy()
                        # Ajustar
                        if ent1 == 'Descans':
                            d_counts_new[g1] -= 1
                            d_counts_new[g2] += 1
                        if ent2 == 'Descans':
                            d_counts_new[g2] -= 1
                            d_counts_new[g1] += 1
                        d_penalty_new = dummy_penalty(d_counts_new)
                    else:
                        d_penalty_new = d_penalty  # sense canvi

                    total_nou = parell_nou + lambda_entropia * entropia_total_new #+ lambda_dummy_spread * d_penalty_new
                    # Si el swap toca Descans, inclou la penalització
                    if swap_toca_dummy:
                        total_nou += lambda_dummy_spread * d_penalty_new

                    if total_nou < total_actual:
                        # Accepta swap
                        groups[g1][p1], groups[g2][p2] = e2, e1
                        C[e1, slot_idx(g2, p2)] = cost1_new
                        C[e2, slot_idx(g1, p1)] = cost2_new
                        entropies[g1] = ent_g1_new
                        entropies[g2] = ent_g2_new
                        entropia_total = entropia_total_new
                        if ent1 == 'Descans' or ent2 == 'Descans':
                            d_counts = d_counts_new
                            d_penalty = d_penalty_new
                        if update_entity_costs:
                            old_factors = dict(entitat_factor)

                            # Actualitzem costs de la categoria
                            entity_costs = recalcular_costos_base_sense_factors(df_cat, groups, equips_to_num_sorteig)

                            # Actualitzem el entity_costs_cat
                            for e, v in entity_costs.items():
                                if e in entity_costs_cat:
                                    entity_costs_cat[e] = v
                                
                            # Actualitzem costos globals
                            actual_global_costs = rebuild_global_costs(entity_costs_cat, entity_global_costs)

                            # Recalculem factors
                            entitat_factor = rebuild_entitat_factor(df_cat, actual_global_costs)

                            #if changed:
                            #    recalc_rows_for_entities(changed, entitat_factor, entity_costs)

        # INTRA-GRUP. Només swaps amb números de sorteig, no casa/fora

        for i_g, g1 in enumerate(grups_ids_ordenats):
            if not allow_intragroup:
                continue
            # Repetim fins que no hi hagi millores dins del grup
            changed = True
            for _ in range(4):
                posicions = sorted(groups[g1].keys())
                for a in range(len(posicions)):
                    for b in range(a + 1, len(posicions)):
                        changed = False
                        i_equ1 = groups[g1][posicions[a]]
                        i_equ2 = groups[g1][posicions[b]]
                        p1, p2 = posicions[a], posicions[b]
                        e1, e2 = groups[g1][p1], groups[g1][p2]
                        ent1_ent = df_cat.iloc[e1]['Entitat']
                        ent2_ent = df_cat.iloc[e2]['Entitat']
                        if e1 == e2 or ent1_ent in entitats_casa_fora or ent2_ent in entitats_casa_fora:
                            continue
                        cost_cur = cost_equip_slot(e1, g1, p1, entitat_factor) + cost_equip_slot(e2, g1, p2, entitat_factor)
                        cost_new = cost_equip_slot(e1, g1, p2, entitat_factor) + cost_equip_slot(e2, g1, p1, entitat_factor)

                        if cost_new < cost_cur:
                            # Accepta swap
                            groups[g1][p1], groups[g1][p2] = e2, e1
                            C[e1, slot_idx(g1, p2)] = cost_equip_slot(e1, g1, p2, entitat_factor)
                            C[e2, slot_idx(g1, p1)] = cost_equip_slot(e2, g1, p1, entitat_factor)

                            old_factors = dict(entitat_factor)
                            entity_costs = recalcular_costos_base_sense_factors(df_cat, groups, equips_to_num_sorteig)

                            # Actualitzem el entity_costs_cat
                            for e, v in entity_costs.items():
                                if e in entity_costs_cat:
                                    entity_costs_cat[e] = v
                                
                            # Actualitzem costos globals
                            actual_global_costs = rebuild_global_costs(entity_costs_cat, entity_global_costs)

                            # Recalculem factors
                            entitat_factor = rebuild_entitat_factor(df_cat, actual_global_costs)
                    

    return groups, entity_costs_cat






# ---------- FUNCIÓ PRINCIPAL ----------

def assignar_grups_hungares(df_categoria, max_grup=8, min_grup=6, entity_costs=None, equips_to_num_sorteig=None, weights=None):
    """
    df_categoria ha de tenir com a mínim:
      - 'Nom', 'Nom Lliga', 'Núm. sorteig'
      - i opcionalment 'Entitat' (si no, es deriva de 'Nom')
    """
    disposicions = build_disposicions(primera_fase)

    entity_global_costs = entity_costs.copy() if entity_costs else {}

    df_cat = df_categoria.copy().reset_index(drop=True)  
    if 'Entitat' not in df_cat.columns:
        df_cat['Entitat'] = df_cat['Nom'].apply(obtenir_entitat)

    repartiment = crear_grups_equilibrats(len(df_cat), max_grup=max_grup, min_grup=min_grup)
    impossible = check_feasibility_entity(df_cat, repartiment)

    # De moment, no resolem el cas impossible
    if impossible:
        print(f"No és possible separar entitats: {impossible}")

    # Afegim dummys si cal
    df_cat, _ = add_dummies(df_cat, repartiment)

    if weights is None:
        weights = dict(w_seed_group=5, w_seed_pos=1)
    C, slots, entity_costs = build_cost_matrix(df_cat, entity_costs=entity_global_costs, equips_to_num_sorteig=equips_to_num_sorteig, repartiment=repartiment, w_dif_sorteig=weights.get('w_dif_sorteig', np.log2(27)) )
    
    
    # El dict entity_costs no s'ha modificat del global, només s'han afegit entitats noves amb cost 0
    entity_global_costs = entity_costs.copy() if entity_costs else {}

    # resolució hongaresa

    row_ind, col_ind = linear_sum_assignment(C)

    # CORRECCIÓ: Calcular costos base reals sense factors per evitar amplificació
    groups = build_groups_from_assignment(df_cat, slots, col_ind)
    
    # Utilitzem la nova funció per obtenir costos base nets
    costos_base_nets = recalcular_costos_base_sense_factors(df_cat, groups, equips_to_num_sorteig)
    # son costos base de la categoria, sense factors entitat

    entity_costs_cat = {entitat: 0.0 for entitat in df_cat['Entitat'].unique()}

    # Actualitzem costos d'entitat amb els costos base de la categoria
    for entitat, cost_base in costos_base_nets.items():
        entity_costs_cat[entitat] += cost_base
    
    

    # Es creen els grups i es comproven conflictes
    g_assigned = build_groups_from_assignment(df_cat, slots, col_ind)
    conflicts = entity_conflicts(df_cat, g_assigned)
    #print("Conflictes inicials d'entitat:", conflicts)
    
    max_repair_iters = 10
    repair_iter = 0
    while conflicts and repair_iter < max_repair_iters:

        # Reparem conflictes
        row_ind, col_ind = repair_by_hungarian_per_position(
            df_cat, C, slots, row_ind=row_ind, col_ind=col_ind, conflicting_groups=conflicts, groups=g_assigned, max_iters=5
        )
        # Torna a construir grups i comprovar conflictes
        g_assigned = build_groups_from_assignment(df_cat, slots, col_ind)
        conflicts = entity_conflicts(df_cat, g_assigned)
        repair_iter += 1
    

    # Obtenim costos base nets de la categoria segons la disposició de grups
    costos_base_nets = recalcular_costos_base_sense_factors(df_cat, groups, equips_to_num_sorteig)
    entity_costs_cat = {entitat: 0.0 for entitat in df_cat['Entitat'].unique()}
    
    # Actualitzem costos d'entitat amb els costos base de la categoria
    for entitat, cost_base in costos_base_nets.items():
        entity_costs_cat[entitat] += cost_base
    
    # Reconstuïm els grups segons l'assignació final
    groups = build_groups_from_assignment(df_cat, slots, col_ind)
    
    # Entitats amb equips que tenen número preassignat (casa/fora): restringeix swaps
    if equips_to_num_sorteig:
        ids_pref = set(equips_to_num_sorteig.keys())
        entitats_casa_fora = set(
            df_cat.loc[df_cat['Id'].isin(ids_pref), 'Entitat'].dropna().astype(str)
        )
        entitats_casa_fora.discard('Descans')
    else:
        entitats_casa_fora = set()
 
    groups = homogeneitzar_nivell(df_cat, groups)
    groups, entity_costs_cat = homogeneitzar_costs(
        df_cat, groups, C, entity_costs_cat, entity_global_costs, entitats_casa_fora, slots,
        equips_to_num_sorteig=equips_to_num_sorteig,
        w_dif_sorteig=5, lambda_entropia=1.0, max_iters=3
    )

    # Actualitzem els costs globals de les entitats segons l'assignació final
    for e, v in entity_costs_cat.items():
        entity_global_costs[e] = entity_global_costs.get(e, 0.0) + v


    # Calculem l'ordre dels grups segons el nivell més alt    
    nivell_map = {"Nivell A": 1, "Nivell B": 2, "Nivell C": 3, "Nivell D": 4, "Nivell E": 5}
    grup_ordre_nivell = {}
    for g, pos_dict in groups.items():
        nums = []
        for i in pos_dict.values():
            niv = df_cat.iloc[i]['Nivell']
            if pd.isna(niv) or str(niv).strip() in ("", "Descans"):
                continue
            nums.append(nivell_map.get(str(niv), 99))
        grup_ordre_nivell[g] = sum(nums) if nums else 99
    
    # Crea el resultat
    assign = []
    diferencies_jornades = {}
    for g, pos_dict in sorted(groups.items()):
        for pos in sorted(pos_dict.keys()):
            i = pos_dict[pos]
            r = df_cat.iloc[i]
            equip = r['Nom']

            # Comprovem jornades diferents
            raw = r['Núm. sorteig']
            seed = normalize_seed_value(raw)
            # Determina el número de referència per calcular diferències:
            # - si seed és 'casa'/'fora' → usa el número preassignat a l'equip (equips_to_num_sorteig)
            # - si seed és enter 1..8 → usa aquest número
            # - altrament → None (no es calculen diferències)
            seed_num = None
            if isinstance(seed, str) and seed in ("casa", "fora"):
                if equips_to_num_sorteig:
                    id_equip = r['Id']
                    seed_num = equips_to_num_sorteig.get(id_equip)
            else:
                try:
                    seed_int = int(seed)
                    if 1 <= seed_int <= 8:
                        seed_num = seed_int
                except Exception:
                    seed_num = None

            
            # Diferències amb detall: (jornada, Casa/Fora assignat, Opponent dins el grup)
            dif_jornades = []
            assigned_num = pos + 1
            if seed_num is not None:
                for j_idx, jornada in enumerate(primera_fase, start=1):
                    # Estat desitjat per al seed_num en aquesta jornada
                    desired = None
                    for a, b in jornada:
                        if a == seed_num:
                            desired = "Casa"
                        elif b == seed_num:
                            desired = "Fora"
                    # Estat assignat i oponent per al número assignat en aquesta jornada
                    actual = None
                    opponent_num = None
                    for a, b in jornada:
                        if a == assigned_num:
                            actual = "Casa"
                            opponent_num = b
                            break
                        if b == assigned_num:
                            actual = "Fora"
                            opponent_num = a
                            break
                    # Si hi ha diferència, afegeix (jornada, Casa/Fora assignat, nom de l'oponent)
                    if desired is not None and actual is not None and desired != actual:
                        opponent_name = ""
                        if opponent_num is not None and (opponent_num - 1) in pos_dict:
                            i_op = pos_dict[opponent_num - 1]
                            opponent_name = df_cat.iloc[i_op]['Nom']
                        dif_jornades.append((j_idx, actual, opponent_name))
            diferencies_jornades[i] = dif_jornades

    # Ordenem els grups segons el nivell més alt
    grups_ordenats = sorted(groups.keys(), key=lambda g: grup_ordre_nivell[g])

    # Ara reassignem números de grup: G1 = millor nivell, G2 = segon millor, etc.
    # Calculem el nombre de dígits necessaris per als noms de grups
    num_digits = len(str(len(grups_ordenats)))
    
    for nou_num_grup, g_original in enumerate(grups_ordenats):
        pos_dict = groups[g_original]
        # Format amb zeros a l'esquerra per ordenació correcta a Excel
        nom_grup = f"G{nou_num_grup+1:0{num_digits}d}"
        
        for pos in range(8):
            if pos in pos_dict:
                i = pos_dict[pos]
                r = df_cat.iloc[i]
                assign.append({
                    'Nom Lliga': r['Nom Lliga'],
                    'Grup': nom_grup,  # Usa format amb zeros a l'esquerra
                    'Id': r.get('Id', ''),
                    'Nom': r['Nom'],
                    'Entitat': r['Entitat'],
                    'Nivell': r['Nivell'],
                    'Dia partit': r['Dia partit'],
                    'Núm. sorteig': r['Núm. sorteig'],  # Sol·licitat
                    'Núm. sorteig assignat': pos + 1,    # Assignat realment
                    'Diferències jornades': diferencies_jornades[i],
                    'Ordre nivell grup': nou_num_grup + 1,  # Ordre final per Excel
                })
            else:
                # Escriu la fila buida o amb valors per slot buit
                assign.append({
                    'Nom Lliga': '',
                    'Grup': nom_grup,  # Usa format amb zeros a l'esquerra
                    'Id': '',
                    'Nom': '',
                    'Entitat': '',
                    'Nivell': '',
                    'Dia partit': '',
                    'Núm. sorteig': '',
                    'Núm. sorteig assignat': pos + 1,
                    'Diferències jornades': [],
                    'Ordre nivell grup': nou_num_grup + 1,  # Ordre final per Excel
                })
    res = pd.DataFrame(assign).sort_values(by=['Ordre nivell grup','Grup','Núm. sorteig assignat']).reset_index(drop=True)
    res = res.drop(columns=['Ordre nivell grup'])
   
   
    # comprova conflictes finals
    groups_final = defaultdict(list)
    for _, r in res.iterrows():
        groups_final[r['Grup']].append(r['Entitat'])
        conflicts_final = {
        g: {e: c for e, c in Counter([e for e in v if e and e != 'Descans']).items() if c > 1}
        for g, v in groups_final.items()
    }
    conflicts_final = {g: d for g, d in conflicts_final.items() if d}    
    
        
    # Retorna el DataFrame amb l'assignació, els costos globals i informació addicional
    return res, entity_global_costs, {
        'num_grups': len(repartiment),
        'repartiment': repartiment,
        'conflictes_entitat': conflicts_final,
        'categoria': df_cat.iloc[0]['Nom Lliga'],
    }
