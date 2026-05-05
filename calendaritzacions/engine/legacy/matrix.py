"""Cost matrix construction for the legacy assignment engine."""

from __future__ import annotations

from collections import Counter

import numpy as np

from logs import primera_fase
from calendaritzacions.engine.legacy.costs import build_disposicions, cost_calc
from calendaritzacions.engine.legacy.fairness import rebuild_entitat_factor
from calendaritzacions.engine.legacy.slots import build_slots
from calendaritzacions.engine.legacy.utils import parse_int

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


