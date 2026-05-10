"""Slot and dummy-row helpers for the legacy assignment engine."""

from __future__ import annotations

import numpy as np

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



def add_dummies(df_cat, repartiment, segona_fase_bool=False):
    """
    Afegeix files Descans fins a omplir tots els slots (8 per grup).
    Retorna nou df_cat i nombre de dummies afegits.
    """
    total_slots = 8 * len(repartiment)
    falta = total_slots - len(df_cat)
    if falta <= 0:
        return df_cat, 0
    nom_lliga = df_cat.iloc[0]['Nom Lliga'] if 'Nom Lliga' in df_cat.columns and len(df_cat) else ''
    
    if segona_fase_bool:
        for k in range(falta):
            df_cat.loc[len(df_cat)] = {
                'Nom': f'Descans {k+1}',
                'Nom Lliga': nom_lliga,
                'Núm. sorteig': np.nan,
                'Entitat': 'Descans',
                'Nivell': 'Descans',
                'Dia partit': 'Descans',
                'Posició Classificació': 'Descans',
                'Posició Classificació Num': 'Descans',
                'Id': f'DUMMY-{k+1}'
            }
    else:
        for k in range(falta):
            df_cat.loc[len(df_cat)] = {
                'Nom': f'Descans {k+1}',
                'Nom Lliga': nom_lliga,
                'Núm. sorteig': np.nan,
                'Entitat': 'Descans',
                'Nivell': 'Descans',
                'Dia partit': 'Descans',
                'Id': f'DUMMY-{k+1}'
            }
    return df_cat.reset_index(drop=True), falta


