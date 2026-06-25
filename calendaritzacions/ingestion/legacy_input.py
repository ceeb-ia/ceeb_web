import pandas as pd

from calendaritzacions.ingestion.ids import ensure_team_ids
from calendaritzacions.ingestion.modalitat_map import load_modalitat_map
from calendaritzacions.ingestion.validators import validate_required_columns


COLUMN_ALIASES = {
    "Id Equip": "Id",
    "ID Equip": "Id",
    "ID equip": "Id",
    "Equip Id": "Id",
    "Hora partit": "Horari partit",
    "Hora Partit": "Horari partit",
    "Hora": "Horari partit",
    "SubCategoria": "Subcategoria",
    "Sub-categoria": "Subcategoria",
    "Sub categoria": "Subcategoria",
}


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
    normalized = normalize_legacy_input_columns(df)
    validate_required_columns(normalized)

    prepared = normalized.copy()
    if "Id" in prepared.columns:
        prepared = prepared.drop(columns=["Id"])
    prepared = ensure_team_ids(prepared)

    modalitat_map = load_modalitat_map(modalitat_map_path)
    return prepared, modalitat_map


def normalize_legacy_input_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with known export aliases mapped to legacy column names."""

    normalized = df.copy()
    rename_map = {
        column: canonical
        for column in normalized.columns
        if (canonical := COLUMN_ALIASES.get(str(column).strip()))
        and canonical not in normalized.columns
    }
    if rename_map:
        normalized = normalized.rename(columns=rename_map)
    if "Nom Lliga" not in normalized.columns:
        normalized["Nom Lliga"] = normalized.apply(_derived_league_name, axis=1)
    return normalized


def _derived_league_name(row: pd.Series) -> str:
    parts = [
        _clean_text(row.get("Modalitat")),
        _clean_text(row.get("Categoria")),
        _clean_text(row.get("Subcategoria")),
    ]
    parts = [part for part in parts if part]
    return " - ".join(parts)


def _clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return " ".join(str(value).strip().split())
