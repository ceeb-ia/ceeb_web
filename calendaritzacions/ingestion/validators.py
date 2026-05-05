REQUIRED_COLUMNS = {
    "Nom",
    "Entitat",
    "Nom Lliga",
    "Nivell",
    "Núm. sorteig",
    "Dia partit",
    "Categoria",
}


class InputValidationError(ValueError):
    def __init__(self, message, *, details=None):
        super().__init__(message)
        self.details = details or {}


def validate_required_columns(df):
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise InputValidationError(
            f"Falten columnes necessaries: {missing}",
            details={"missing_columns": sorted(missing)},
        )
    return df


def validate_no_mixed_home_away_requests(df):
    if "Id" not in df.columns:
        raise InputValidationError(
            "Falta la columna Id per validar peticions CASA/FORA",
            details={"missing_columns": ["Id"]},
        )
    if "Núm. sorteig" not in df.columns:
        raise InputValidationError(
            "Falta la columna Núm. sorteig per validar peticions CASA/FORA",
            details={"missing_columns": ["Núm. sorteig"]},
        )

    request_values = df["Núm. sorteig"].astype(str).str.strip().str.lower()
    requested = df[request_values.isin(["casa", "fora"])]
    if requested.empty:
        return df

    grouped = requested.groupby("Id")["Núm. sorteig"].apply(
        lambda values: {str(value).strip().lower() for value in values}
    )
    bad = grouped[grouped.apply(lambda values: len(values) > 1)]
    if bad.empty:
        return df

    conflicts = []
    for team_id, values in bad.items():
        rows = requested[requested["Id"] == team_id][
            ["Nom", "Nom Lliga", "Núm. sorteig"]
        ].drop_duplicates()
        team_name = rows["Nom"].iloc[0] if not rows.empty else "(desconegut)"
        conflicts.append(
            {
                "id": team_id,
                "nom": team_name,
                "requests": sorted(values),
                "rows": rows.to_dict("records"),
            }
        )

    raise InputValidationError(
        "El mateix equip te peticions CASA i FORA en categories diferents",
        details={"conflicts": conflicts},
    )
