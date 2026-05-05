"""Fairness helpers for the legacy assignment engine."""

from __future__ import annotations

from collections import defaultdict

from calendaritzacions.domain.phases import PRIMERA_FASE as primera_fase
from calendaritzacions.engine.legacy.costs import build_disposicions, cost_calc

def actualitzar_costos_entitat(disposicions, equips_to_num_sorteig, df_cat, C, row_ind, col_ind, fase=primera_fase):
    
    '''
    Actualitza els costos per entitat segons l'assignació.
    CORRECCIÓ: Usa el cost base real, no el multiplicat pel factor entitat.
    '''    
    from collections import defaultdict
    costs_base_per_entitat = defaultdict(float)
    
    # Necessitem les mateixes dades que build_cost_matrix
    disposicions = build_disposicions(fase)
    
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
    


