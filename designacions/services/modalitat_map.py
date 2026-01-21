# designacions/services/modalitat_map_df.py
import pandas as pd
from designacions.models import ModalityMap

CSV_COLS = ["Id Categoria", "Modalitat", "Nom", "Descripció", "Nom Abreviat", "Ordre", "CodiExtern"]

def load_modalitat_map_df() -> pd.DataFrame:
    """
    Retorna un DataFrame amb les mateixes columnes que map_modalitat_nom.csv.
    Fa fallback amb registres antics (key/name) si els camps nous són buits.
    """
    qs = ModalityMap.objects.all().values(
        "id_categoria", "modalitat", "nom", "descripcio", "nom_abreviat", "ordre", "codi_extern",
        "key", "name",
    )

    rows = []
    for r in qs:
        modalitat = r.get("modalitat") or r.get("key")
        nom = r.get("nom") or r.get("name")
        rows.append({
            "Id Categoria": r.get("id_categoria"),
            "Modalitat": modalitat,
            "Nom": nom,
            "Descripció": r.get("descripcio"),
            "Nom Abreviat": r.get("nom_abreviat"),
            "Ordre": r.get("ordre"),
            "CodiExtern": r.get("codi_extern"),
        })

    df = pd.DataFrame(rows, columns=CSV_COLS)
    return df
