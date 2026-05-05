"""Legacy assignment engine service.

This module preserves the behavior of the former top-level assignacions.py
implementation while moving the implementation behind a package boundary.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from calendaritzacions.domain.phases import PRIMERA_FASE as primera_fase
from calendaritzacions.engine.legacy.costs import recalcular_costos_base_sense_factors
from calendaritzacions.engine.legacy.group_sizing import crear_grups_equilibrats
from calendaritzacions.engine.legacy.local_search import (
    homogeneitzar_costs,
    homogeneitzar_nivell,
)
from calendaritzacions.engine.legacy.matrix import build_cost_matrix
from calendaritzacions.engine.legacy.repairs import (
    build_groups_from_assignment,
    check_feasibility_entity,
    entity_conflicts,
    repair_by_hungarian_per_position,
)
from calendaritzacions.engine.legacy.slots import add_dummies
from calendaritzacions.engine.legacy.utils import normalize_seed_value, obtenir_entitat

# ---------- FUNCIÓ PRINCIPAL ----------

def assignar_grups_hungares(df_categoria, 
                            max_grup=8, min_grup=6, 
                            entity_costs=None, equips_to_num_sorteig=None, 
                            weights=None, fase=primera_fase, 
                            segona_fase_bool=False):
    """
    df_categoria ha de tenir com a mínim:
      - 'Nom', 'Nom Lliga', 'Núm. sorteig'
      - i opcionalment 'Entitat' (si no, es deriva de 'Nom')
    """
    selected_phase = fase if fase is not None else primera_fase


    entity_global_costs = entity_costs.copy() if entity_costs else {}

    df_cat = df_categoria.copy().reset_index(drop=True)  
    if 'Entitat' not in df_cat.columns:
        df_cat['Entitat'] = df_cat['Nom'].apply(obtenir_entitat)

    num_equips_reals = len(df_cat)
    repartiment = crear_grups_equilibrats(len(df_cat), max_grup=max_grup, min_grup=min_grup)
    impossible = check_feasibility_entity(df_cat, repartiment)

    # De moment, no resolem el cas impossible
    if impossible:
        print(f"No és possible separar entitats: {impossible}")

    # Afegim dummys si cal
    df_cat, num_dummies = add_dummies(df_cat, repartiment, segona_fase_bool=segona_fase_bool)
    num_slots = 8 * len(repartiment)

    if weights is None:
        weights = dict(w_seed_group=5, w_seed_pos=1)
    C, slots, entity_costs = build_cost_matrix(
        df_cat,
        entity_costs=entity_global_costs,
        equips_to_num_sorteig=equips_to_num_sorteig,
        repartiment=repartiment,
        w_dif_sorteig=weights.get('w_dif_sorteig', np.log2(27)),
        fase=selected_phase
    )
    
    
    # El dict entity_costs no s'ha modificat del global, només s'han afegit entitats noves amb cost 0
    entity_global_costs = entity_costs.copy() if entity_costs else {}

    # resolució hongaresa

    row_ind, col_ind = linear_sum_assignment(C)

    # CORRECCIÓ: Calcular costos base reals sense factors per evitar amplificació
    groups = build_groups_from_assignment(df_cat, slots, col_ind)
    
    # Utilitzem la nova funció per obtenir costos base nets
    costos_base_nets = recalcular_costos_base_sense_factors(df_cat, groups, equips_to_num_sorteig, fase=selected_phase)
    # son costos base de la categoria, sense factors entitat

    entity_costs_cat = {entitat: 0.0 for entitat in df_cat['Entitat'].unique()}

    # Actualitzem costos d'entitat amb els costos base de la categoria
    for entitat, cost_base in costos_base_nets.items():
        entity_costs_cat[entitat] += cost_base
    
    

    # Es creen els grups i es comproven conflictes
    g_assigned = build_groups_from_assignment(df_cat, slots, col_ind)
    conflicts = entity_conflicts(df_cat, g_assigned)
    num_conflictes_inicials = sum(len(v) for v in conflicts.values())
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
    costos_base_nets = recalcular_costos_base_sense_factors(df_cat, groups, equips_to_num_sorteig, fase=selected_phase)
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
 
    groups = homogeneitzar_nivell(df_cat, groups, segona_fase_bool=segona_fase_bool)
    groups, entity_costs_cat = homogeneitzar_costs(
        df_cat, groups, C, entity_costs_cat, entity_global_costs, entitats_casa_fora, slots,
        fase=selected_phase, equips_to_num_sorteig=equips_to_num_sorteig, segona_fase_bool=segona_fase_bool,
        w_dif_sorteig=5, lambda_entropia=1.0, max_iters=5
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
                for j_idx, jornada in enumerate(selected_phase, start=1):
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

    def _level_to_idx(val):
        text = str(val).strip()
        if not text or text == "Descans":
            return None
        direct = {
            "Nivell A": 1,
            "Nivell B": 2,
            "Nivell C": 3,
            "Nivell D": 4,
            "Nivell E": 5,
        }
        if text in direct:
            return direct[text]
        last = text[-1:].upper()
        if last in {"A", "B", "C", "D", "E"}:
            return {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}[last]
        return None

    nivell_rangs = []
    for pos_dict in groups.values():
        idxs = []
        for i in pos_dict.values():
            idx = _level_to_idx(df_cat.iloc[i]['Nivell'])
            if idx is not None:
                idxs.append(idx)
        if idxs:
            nivell_rangs.append(max(idxs) - min(idxs))

    nivell_rang_mitja = float(sum(nivell_rangs) / len(nivell_rangs)) if nivell_rangs else 0.0
    nivell_rang_max = int(max(nivell_rangs)) if nivell_rangs else 0
    num_conflictes_finals = sum(len(v) for v in conflicts_final.values())
    
        
    # Retorna el DataFrame amb l'assignació, els costos globals i informació addicional
    return res, entity_global_costs, {
        'num_grups': len(repartiment),
        'repartiment': repartiment,
        'conflictes_entitat': conflicts_final,
        'categoria': df_cat.iloc[0]['Nom Lliga'],
        'num_equips_reals': num_equips_reals,
        'num_slots': num_slots,
        'num_dummies': num_dummies,
        'dummy_ratio': (num_dummies / num_slots) if num_slots else 0.0,
        'num_conflictes_inicials': num_conflictes_inicials,
        'num_conflictes_finals': num_conflictes_finals,
        'repair_iters_executades': repair_iter,
        'nivell_rang_mitja_grups': nivell_rang_mitja,
        'nivell_rang_max_grups': nivell_rang_max,
    }
