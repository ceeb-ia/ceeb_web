"""Team-name matching helpers for second-phase classifications."""

from __future__ import annotations

import unicodedata

import pandas as pd

def _normalize_team_key(name: str) -> str:
    s = unicodedata.normalize('NFKC', str(name or '')).casefold().strip()
    # normalitza cometes “rares”
    s = s.replace('“', '"').replace('”', '"').replace('«', '"').replace('»', '"')
    s = s.replace('’', "'").replace('`', "'")
    s = " ".join(s.split())
    return s


def _get_team_position(equip: str, df_classificacions: pd.DataFrame, task_id) -> int:
    equip_norm = _normalize_team_key(equip)
    # Construeix l'set d'equips presents a la classificació (nom tal qual es mostra)
    category_teams = set()
    for _, row_df in df_classificacions.iterrows():
        team_name = row_df.get('NomEquipMostrar', '')
        if pd.isna(team_name):
            team_name = ''
        category_teams.add(_normalize_team_key(team_name))

    # Recorrem per trobar la posició (1-based) comparant noms normalitzats
    for idx, row in df_classificacions.iterrows():
        nom_equip = _normalize_team_key(row.get('NomEquipMostrar', ''))
        if nom_equip == equip_norm:
            
            return idx + 1, category_teams  # posició 1-based


    return -1, category_teams  # no trobat
