from __future__ import annotations

import pandas as pd


TUTOR_LICENSE_CATEGORY = "TUTOR/TUTORA DE JOC"
EXCLUDED_REFEREE_CODES = ["TJ PROPI", "TJ LEXIA", "CEBLL", "CEVOSABADELL", "CELH", "CEBN"]
EXCLUDED_MATCH_GROUPS = [
    "FUTBOL 5 SENSE BARRERES JUVENIL MIXT GRUP 06 1a FASE CEEB",
    "AMISTÓS FUTBOL 5",
]


def _read_xlsx(path: str) -> pd.DataFrame:
    return pd.read_excel(path, engine="openpyxl")


def _normalize_date_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.normalize()


def _normalize_text_series(series: pd.Series) -> pd.Series:
    normalized = series.astype("string").str.strip()
    return normalized.mask(normalized == "")


def _normalize_modalitats(values) -> list[str]:
    result = []
    for value in values or []:
        text = str(value or "").strip()
        if text:
            result.append(text)
    return result


def filter_run_dataframes(
    df_disp: pd.DataFrame,
    df_partits: pd.DataFrame,
    params: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    params = params or {}
    scoped_disp = df_disp.copy()
    scoped_partits = df_partits.copy()

    if "Data" in scoped_disp.columns:
        scoped_disp["Data"] = _normalize_date_series(scoped_disp["Data"])
    if "Data" in scoped_partits.columns:
        scoped_partits["Data"] = _normalize_date_series(scoped_partits["Data"])

    if "Modalitat" in scoped_disp.columns:
        scoped_disp["Modalitat"] = _normalize_text_series(scoped_disp["Modalitat"])
    if "Modalitat" in scoped_partits.columns:
        scoped_partits["Modalitat"] = _normalize_text_series(scoped_partits["Modalitat"])

    if "Categoria" in scoped_disp.columns:
        scoped_disp = scoped_disp[scoped_disp["Categoria"] == TUTOR_LICENSE_CATEGORY].copy()

    if "Codi Tutor de Joc" in scoped_disp.columns:
        scoped_disp["Codi Tutor de Joc"] = _normalize_text_series(scoped_disp["Codi Tutor de Joc"])
        scoped_disp = scoped_disp[~scoped_disp["Codi Tutor de Joc"].isin(EXCLUDED_REFEREE_CODES)].copy()

    if "Grup" in scoped_partits.columns:
        scoped_partits["Grup"] = _normalize_text_series(scoped_partits["Grup"])
        scoped_partits = scoped_partits[~scoped_partits["Grup"].isin(EXCLUDED_MATCH_GROUPS)].copy()

    date_from = params.get("date_from") or None
    date_to = params.get("date_to") or None
    normalized_from = pd.to_datetime(date_from, errors="coerce").normalize() if date_from else pd.NaT
    normalized_to = pd.to_datetime(date_to, errors="coerce").normalize() if date_to else pd.NaT

    if "Data" in scoped_partits.columns:
        if pd.notna(normalized_from):
            scoped_partits = scoped_partits[scoped_partits["Data"] >= normalized_from].copy()
        if pd.notna(normalized_to):
            scoped_partits = scoped_partits[scoped_partits["Data"] <= normalized_to].copy()

    if "Data" in scoped_disp.columns:
        if pd.notna(normalized_from):
            scoped_disp = scoped_disp[scoped_disp["Data"] >= normalized_from].copy()
        if pd.notna(normalized_to):
            scoped_disp = scoped_disp[scoped_disp["Data"] <= normalized_to].copy()

    selected_modalitats = _normalize_modalitats(params.get("modalitats") or [])
    if selected_modalitats and "Modalitat" in scoped_partits.columns:
        scoped_partits = scoped_partits[scoped_partits["Modalitat"].isin(selected_modalitats)].copy()

    final_modalitats = (
        scoped_partits["Modalitat"].dropna().drop_duplicates().tolist()
        if "Modalitat" in scoped_partits.columns
        else []
    )
    if "Modalitat" in scoped_disp.columns:
        if final_modalitats:
            scoped_disp = scoped_disp[scoped_disp["Modalitat"].isin(final_modalitats)].copy()
        else:
            scoped_disp = scoped_disp.iloc[0:0].copy()

    return scoped_disp.reset_index(drop=True), scoped_partits.reset_index(drop=True)


def load_scoped_run_data(
    path_disponibilitats: str,
    path_partits: str,
    params: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df_disp = _read_xlsx(path_disponibilitats)
    df_partits = _read_xlsx(path_partits)
    return filter_run_dataframes(df_disp, df_partits, params=params)
