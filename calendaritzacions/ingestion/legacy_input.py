import pandas as pd

from calendaritzacions.ingestion.ids import ensure_team_ids
from calendaritzacions.ingestion.modalitat_map import load_modalitat_map
from calendaritzacions.ingestion.validators import validate_required_columns


def prepare_legacy_input(
    df: pd.DataFrame,
    modalitat_map_path: str = "map_modalitat_nom.csv",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Prepare the legacy pipeline input DataFrame and modalitat map.

    Missing required columns, including ``Entitat``, raise ``InputValidationError``,
    which is a ``ValueError`` subclass. Existing ``Id`` values are always discarded
    before regenerating the stable legacy IDs from ``Nom``, ``Nom Lliga`` and
    ``Categoria``.
    """
    validate_required_columns(df)

    prepared = df.copy()
    if "Id" in prepared.columns:
        prepared = prepared.drop(columns=["Id"])
    prepared = ensure_team_ids(prepared)

    modalitat_map = load_modalitat_map(modalitat_map_path)
    return prepared, modalitat_map
