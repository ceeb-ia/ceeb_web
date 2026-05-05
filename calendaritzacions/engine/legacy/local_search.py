"""Local-search refinements for the legacy assignment engine."""

from __future__ import annotations

from logs import primera_fase
from calendaritzacions.engine.legacy.costs import (
    build_disposicions,
    cost_calc,
    day_entropy,
    level_entropy,
    position_entropy,
    recalcular_costos_base_sense_factors,
)
from calendaritzacions.engine.legacy.fairness import rebuild_entitat_factor
from calendaritzacions.engine.legacy.utils import normalize_seed_value

def homogeneitzar_nivell(df_cat, groups, max_iters=100, segona_fase_bool=False):
    """
    Optimitza la distribució de nivells entre grups minimitzant l'entropia,
    adaptat al format groups: {grup: {posició: índex_equip}}
    """

    # Si estema a la segona fase, primer homogeneitzem per posicio de classificació
    if segona_fase_bool:
        print("Homogeneitzant nivells amb control de posició de classificació...")
        # Fem swaps per tal de minimitzar la disparitat de posició
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

                            # Comprovem la disparitat de posicio, contant quants True té la columna
                            posicions1 = [df_cat.iloc[i]['Posició Classificació'] for _, i in items1]
                            posicions2 = [df_cat.iloc[i]['Posició Classificació'] for _, i in items2]
                            disparitat1 = sum(1 for pos in posicions1 if str(pos).strip().lower() == 'true')
                            disparitat2 = sum(1 for pos in posicions2 if str(pos).strip().lower() == 'true')
                            disparitat_abans = disparitat1 + disparitat2
                            posicions1_swap = [df_cat.iloc[i]['Posició Classificació'] for _, i in items1 if i != i1] + [df_cat.iloc[i2]['Posició Classificació']]
                            posicions2_swap = [df_cat.iloc[i]['Posició Classificació'] for _, i in items2 if i != i2] + [df_cat.iloc[i1]['Posició Classificació']]
                            disparitat1_swap = sum(1 for pos in posicions1_swap if str(pos).strip().lower() == 'true')
                            disparitat2_swap = sum(1 for pos in posicions2_swap if str(pos).strip().lower() == 'true')
                            disparitat_despres = disparitat1_swap + disparitat2_swap
                            if disparitat_despres >= disparitat_abans:
                                continue
                            # Accepta el swap
                            items1[idx1] = (p1, i2)
                            items2[idx2] = (p2, i1)
                            millora = True
            if not millora and _ > 5:
                print("Homogeneització per posició de classificació completa.")
                break
            # Reconstrueix groups amb el nou format
            groups = {g: {p: i for p, i in items} for g, items in grups_llista.items()}
        return groups


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



def homogeneitzar_costs(df_cat, groups, C, entity_costs_cat, entity_global_costs, entitats_casa_fora, slots,
                               equips_to_num_sorteig=None,
                               fase=primera_fase,
                               w_dif_sorteig=5,
                               lambda_entropia=1.0,
                               max_iters=3,
                               allow_intragroup=True,
                               same_pos_only=False,
                               segona_fase_bool=False,
                               update_entity_costs=True,
                               lambda_dummy_spread=100.0):
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

    def entropia_grup(g, segona_fase_bool=False):
        idxs = list(groups[g].values())

        if segona_fase_bool:
            posicions = [df_cat.iloc[i]['Posició Classificació Num'] for i in idxs if df_cat.iloc[i]['Entitat'] != 'Descans']
            #print("Entropia de posicions", day_entropy(posicions))
            return position_entropy(posicions)

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
    entropies = {g: entropia_grup(g, segona_fase_bool=segona_fase_bool) for g in groups}
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

                    if segona_fase_bool:
                        # Entropia nova (per posició de classificació)
                        posicions_g1_new = [df_cat.iloc[idx]['Posició Classificació Num'] for pos, idx in groups[g1].items()
                                        if pos != p1 and df_cat.iloc[idx]['Entitat'] != 'Descans']
                        if ent2 != 'Descans':
                            posicions_g1_new.append(df_cat.iloc[e2]['Posició Classificació Num'])
                        posicions_g2_new = [df_cat.iloc[idx]['Posició Classificació Num'] for pos, idx in groups[g2].items()
                                        if pos != p2 and df_cat.iloc[idx]['Entitat'] != 'Descans']
                        if ent1 != 'Descans':
                            posicions_g2_new.append(df_cat.iloc[e1]['Posició Classificació Num'])
                        ent_g1_new = position_entropy(posicions_g1_new)
                        ent_g2_new = position_entropy(posicions_g2_new)
                        

                    else:
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






