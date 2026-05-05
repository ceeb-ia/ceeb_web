"""Cost and entropy helpers for the legacy assignment engine."""

from __future__ import annotations

from collections import defaultdict
import sys

import numpy as np
import pandas as pd

from logs import primera_fase
from calendaritzacions.engine.legacy.utils import normalize_seed_value, parse_int

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


def position_entropy(posicions):
    # Excloem dummies i buits
    posicions_filtrades = [p for p in posicions if str(p).strip() not in ("", "Descans") and not pd.isna(p)]
    # Comptem quants True té la llista
    total = len(posicions_filtrades)
    if total == 0:
        raise ValueError("No hi ha posicions vàlides per calcular l'entropia")
    
    # Calculem la distancia intragrupal entre les posicions
    distancia = 0
    for i in range(total):
        for j in range(i + 1, total):
            if posicions_filtrades[i] != posicions_filtrades[j]:
                distancia += abs(posicions_filtrades[j] - posicions_filtrades[i])**2

    # Afegim una penalització per desviació de la mitjana
    mitjana = sum(posicions_filtrades) / total
    desviacio = sum(abs(p - mitjana)**2 for p in posicions_filtrades)
    #print("Distancia:", distancia, "Desviació:", desviacio)


    return distancia + desviacio*10


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




def recalcular_costos_base_sense_factors(df_cat, groups, equips_to_num_sorteig=None, fase=primera_fase):
    """
    Nova funció: Calcula els costos base reals sense factors entitat aplicats.
    Utilitza cost_calc() directament per obtenir costs nets.
    """
    from collections import defaultdict
    
    # Importem les funcions necessàries
    disposicions = build_disposicions(fase)
    
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
                                equips_to_num_sorteig=equips_to_num_sorteig, fase=fase, w_dif_sorteig=5)
            
            costos_base[entitat] += cost_base
    
    return dict(costos_base)


