"""Entity conflict detection and repair for the legacy assignment engine."""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
from scipy.optimize import linear_sum_assignment

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





