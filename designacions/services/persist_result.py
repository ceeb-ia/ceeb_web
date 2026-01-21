# designacions_app/services/persist_result.py
import pandas as pd
from django.db import transaction
from ..models import Referee, Match, Assignment

def _read_assignacions_sheet(path: str) -> pd.DataFrame:
    # el motor escriu "Assignacions" com a sheet principal :contentReference[oaicite:5]{index=5}
    return pd.read_excel(path, sheet_name="Assignacions", engine="openpyxl")

def _to_str(v):
    if pd.isna(v):
        return ""
    return str(v).strip()

@transaction.atomic
def persist_engine_output(run, engine_output_path: str):
    df = _read_assignacions_sheet(engine_output_path)

    # columnes esperades segons main_fixed 
    if "Codi Partit" not in df.columns or "Tutor Codi" not in df.columns:
        raise ValueError("El resultat del motor no conté les columnes 'Codi Partit' i/o 'Tutor Codi'.")

    updated = 0
    not_found_matches = 0

    for _, row in df.iterrows():
        codi_partit = _to_str(row.get("Codi Partit"))
        tutor_codi = _to_str(row.get("Tutor Codi"))

        if not codi_partit:
            continue

        match = Match.objects.filter(run=run, code=codi_partit).first()
        if not match:
            not_found_matches += 1
            continue

        assign = Assignment.objects.get(run=run, match=match)
        if assign.locked:
            continue

        ref = None
        if tutor_codi:
            ref = Referee.objects.filter(code=tutor_codi).first()
            # si no existeix per algun motiu, el creem amb la info de la sortida
            if not ref:
                nom = _to_str(row.get("Tutor Nom"))
                cognoms = _to_str(row.get("Tutor Cognoms"))
                full_name = (nom + " " + cognoms).strip() or tutor_codi
                ref = Referee.objects.create(
                    code=tutor_codi,
                    name=full_name,
                    level=_to_str(row.get("Tutor Nivell")) or None,
                    active=True
                )

        assign.referee = ref
        assign.save(update_fields=["referee", "updated_at"])
        updated += 1

    return {"updated_assignments": updated, "not_found_matches": not_found_matches}
