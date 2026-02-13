
from dataclasses import dataclass
from typing import List, Callable, Optional

@dataclass
class DatasetSpec:
    required_cols: List[str]
    numeric_cols: List[str]
    date_cols: List[str]
    custom_validator: Optional[Callable] = None


def validate_reserves_sample(df):
    errors = []

    # DuracionHoras ha de ser > 0
    if "DuracionHoras" in df.columns:
        invalid = df["DuracionHoras"].astype(str).str.replace(",", ".").astype(float) < 0
        if invalid.any():
            errors.append("Hi ha reserves amb DuracionHoras <= 0")

    return errors

def validate_clients_monthly_table(df):
    # df és "raw" (pot tenir Unnamed: x), així que no podem exigir cols GEN Q, FEB Q, ...
    # Aquí només fem validacions suaus o res.
    errors = []
    if df is None or df.empty:
        errors.append("clients: excel buit")
    return errors

SPECS = {
    "reserves": DatasetSpec(
        required_cols=[
            "NombreCompleto",
            "Recurso",
            "FechaReserva",
            "DuracionHoras",
            "Deporte",
            "Importe",
        ],
        numeric_cols=["DuracionHoras"],
        date_cols=["FechaReserva"],
        custom_validator=validate_reserves_sample,
    ),
    "clients": DatasetSpec(
        required_cols=[],          # 👈 IMPORTANT: no exigir mesos aquí
        numeric_cols=[],
        date_cols=[],
        custom_validator=validate_clients_monthly_table,
    ),
}

