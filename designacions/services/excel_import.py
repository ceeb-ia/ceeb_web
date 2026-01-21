# designacions_app/services/excel_import.py
import pandas as pd
from django.db import transaction
import numpy as np
from ..models import Referee, Match, Availability, Assignment
import datetime as dt
import json

def _read_xlsx(path: str) -> pd.DataFrame:
    return pd.read_excel(path, engine="openpyxl")

def _to_str(v):
    if pd.isna(v):
        return ""
    return str(v).strip()


def _json_safe(v):
    # NULLs / NaN / NaT
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass

    # pandas Timestamp
    if isinstance(v, pd.Timestamp):
        return v.isoformat()

    # numpy datetime64
    if isinstance(v, np.datetime64):
        return pd.to_datetime(v).isoformat()

    # python datetime/date/time
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()

    # numpy scalars -> python native
    if isinstance(v, (np.integer, np.floating, np.bool_)):
        return v.item()

    # altres numpy types (fallback)
    if isinstance(v, np.generic):
        return v.item()

    return v

def row_to_json_safe_dict(row):
    d = row.to_dict()
    safe = {str(k): _json_safe(v) for k, v in d.items()}

    # prova dura: si encara queda alguna cosa no serialitzable, la convertim a string
    try:
        json.dumps(safe, ensure_ascii=False)
    except TypeError:
        safe = {k: (val if isinstance(val, (str, int, float, bool)) or val is None else str(val))
                for k, val in safe.items()}
    return safe



@transaction.atomic
def import_excels_to_db(run, path_disponibilitats: str, path_partits: str):
    df_disp = _read_xlsx(path_disponibilitats)
    df_partits = _read_xlsx(path_partits)

    # --- Referees + Availability (dispos_tutors_23_01.xlsx)
    # Columnes reals: "Codi Tutor de Joc", "Nom", "Cognoms", "Nif/Nie", "Nivell", "Modalitat", "Mitjà de Transport", etc.
    for _, row in df_disp.iterrows():
        code = _to_str(row.get("Codi Tutor de Joc"))
        nom = _to_str(row.get("Nom"))
        cognoms = _to_str(row.get("Cognoms"))
        if not code:
            continue

        full_name = (nom + " " + cognoms).strip() or code

        ref, _ = Referee.objects.update_or_create(
            code=code,
            defaults={
                "name": full_name,
                "nif": _to_str(row.get("Nif/Nie")) or None,
                "level": _to_str(row.get("Nivell")) or None,
                "modality": _to_str(row.get("Modalitat")) or None,
                "transport": _to_str(row.get("Mitjà de Transport")) or None,
                "active": True,
            }
        )
        Availability.objects.create(run=run, referee=ref, raw=row_to_json_safe_dict(row))

    # --- Matches (partits_23_01.xlsx)
    # Columnes reals: "Codi", "Club Local", "Equip local", "Equip visitant", "Lliga", "Grup", "Jornada",
    #                "Modalitat", "Categoria", "Subcategoria", "Data", "Hora", "Domicili", "Municipi",
    #                "Pista joc", "SubPista joc"...
    matches_created = 0
    for _, row in df_partits.iterrows():
        code = _to_str(row.get("Codi"))
        if not code:
            continue

        m = Match.objects.create(
            run=run,
            code=code,
            club_local=_to_str(row.get("Club Local")) or None,
            equip_local=_to_str(row.get("Equip local")) or None,
            equip_visitant=_to_str(row.get("Equip visitant")) or None,
            lliga=_to_str(row.get("Lliga")) or None,
            group=_to_str(row.get("Grup")) or None,
            jornada=_to_str(row.get("Jornada")) or None,
            modality=_to_str(row.get("Modalitat")) or None,
            category=_to_str(row.get("Categoria")) or None,
            subcategory=_to_str(row.get("Subcategoria")) or None,
            date=(row.get("Data") if not pd.isna(row.get("Data")) else None),
            hour_raw=_to_str(row.get("Hora")) or None,
            domicile=_to_str(row.get("Domicili")) or None,
            municipality=_to_str(row.get("Municipi")) or None,
            venue=_to_str(row.get("Pista joc")) or None,
            sub_venue=_to_str(row.get("SubPista joc")) or None,
        )

        Assignment.objects.create(run=run, match=m, referee=None)
        matches_created += 1

    return {
        "n_availabilities": run.availabilities.count(),
        "n_matches": matches_created,
    }
