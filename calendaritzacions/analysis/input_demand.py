"""Input demand analysis by venue, day and time slot."""

from __future__ import annotations

from datetime import datetime, time, timedelta
import math
from pathlib import Path
import re
from typing import Any
import unicodedata

import pandas as pd


VENUE_COLUMN = "Pista joc"
DAY_COLUMN = "Dia partit"
TIME_COLUMN = "Horari partit"
TEAM_ID_COLUMN = "Id"

MISSING_VENUE = "(sense pista)"
MISSING_DAY = "(sense dia)"
MISSING_TIME = "(sense hora)"

OPTIONAL_SEGMENT_COLUMNS = [
    "Nom",
    "Entitat",
    "Nom Lliga",
    "Modalitat",
    "Categoria",
    "Subcategoria",
]

DAY_ORDER = {
    "dilluns": 1,
    "dimarts": 2,
    "dimecres": 3,
    "dijous": 4,
    "divendres": 5,
    "dissabte": 6,
    "diumenge": 7,
}


def build_input_demand_analysis(df: pd.DataFrame) -> dict[str, Any]:
    """Build JSON-ready input demand KPIs by venue, day and time.

    The input DataFrame is not mutated. Demand is counted as unique team IDs when
    ``Id`` exists, and as row count otherwise.
    """

    prepared = _prepare_demand_frame(df)
    count_col = "_team_key"

    by_venue = _aggregate(prepared, ["pista_joc"], count_col)
    by_venue_day = _aggregate(prepared, ["pista_joc", "dia_partit"], count_col)
    by_venue_day_time = _aggregate(
        prepared,
        ["pista_joc", "dia_partit", "horari_partit"],
        count_col,
    )

    by_venue_day_time = _sort_slot_frame(by_venue_day_time)
    by_venue_day = _sort_day_frame(by_venue_day)
    by_venue = by_venue.sort_values(
        ["equips", "pista_joc"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)

    friday = by_venue_day_time[
        by_venue_day_time["dia_partit"].map(_day_key) == "divendres"
    ].reset_index(drop=True)
    top_slots = by_venue_day_time.sort_values(
        ["equips", "pista_joc", "dia_partit", "horari_partit"],
        ascending=[False, True, True, True],
        kind="stable",
    ).head(20).reset_index(drop=True)

    summary = {
        "total_files": int(len(prepared)),
        "total_equips": int(prepared[count_col].nunique()),
        "total_pistes": int(prepared["pista_joc"].nunique()),
        "total_dies": int(prepared["dia_partit"].nunique()),
        "total_franjes": int(prepared["horari_partit"].nunique()),
        "total_slots_pista_dia_hora": int(len(by_venue_day_time)),
        "max_demanda_slot": int(by_venue_day_time["equips"].max()) if not by_venue_day_time.empty else 0,
        "files_sense_pista": int(prepared["is_missing_venue"].sum()),
        "files_sense_dia": int(prepared["is_missing_day"].sum()),
        "files_sense_hora": int(prepared["is_missing_time"].sum()),
        "slots_divendres": int(len(friday)),
    }

    missing_fields = _missing_field_records(prepared)

    return {
        "summary": summary,
        "by_venue": by_venue.to_dict("records"),
        "by_venue_day": by_venue_day.to_dict("records"),
        "by_venue_day_time": by_venue_day_time.to_dict("records"),
        "friday_by_venue_time": friday.to_dict("records"),
        "top_demand_slots": top_slots.to_dict("records"),
        "missing_fields": missing_fields,
        "columns": {
            "venue": VENUE_COLUMN,
            "day": DAY_COLUMN,
            "time": TIME_COLUMN,
            "team_id": TEAM_ID_COLUMN if TEAM_ID_COLUMN in df.columns else None,
            "optional_segments": [col for col in OPTIONAL_SEGMENT_COLUMNS if col in df.columns],
        },
    }


def write_input_demand_plots(
    analysis: dict[str, Any],
    output_dir: str | Path,
    *,
    stem: str = "input_demand",
    fmt: str = "png",
    dpi: int = 160,
) -> dict[str, str]:
    """Write demand plots and return a plot-id to path mapping.

    Plot generation is best-effort: a single empty table simply skips its plot.
    Importing matplotlib happens lazily so the KPI JSON remains available even
    in environments without plotting dependencies.
    """

    import matplotlib

    matplotlib.use("Agg")

    import matplotlib.pyplot as plt

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    generated: dict[str, str] = {}

    slot_df = pd.DataFrame(analysis.get("by_venue_day_time", []))
    friday_df = pd.DataFrame(analysis.get("friday_by_venue_time", []))
    venue_df = pd.DataFrame(analysis.get("by_venue", []))
    top_df = pd.DataFrame(analysis.get("top_demand_slots", []))

    for plot_id, plotter, frame in [
        ("heatmap", _plot_global_heatmap, slot_df),
        ("friday", _plot_friday_heatmap, friday_df),
        ("by_venue", _plot_by_venue_bar, venue_df),
        ("top_slots", _plot_top_slots_bar, top_df),
    ]:
        if frame.empty:
            continue
        fig = plotter(frame)
        if fig is None:
            continue
        file_path = output_path / f"{stem}_{plot_id}.{fmt}"
        fig.savefig(file_path, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        generated[plot_id] = str(file_path)

    return generated


def _prepare_demand_frame(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy()
    row_index = pd.Series(range(len(prepared)), index=prepared.index)

    prepared["pista_joc"] = _normalized_text_column(prepared, VENUE_COLUMN, MISSING_VENUE)
    prepared["dia_partit"] = _normalized_day_column(prepared, DAY_COLUMN)
    prepared["horari_partit"] = _normalized_time_column(prepared, TIME_COLUMN)
    prepared["_day_order"] = prepared["dia_partit"].map(lambda value: DAY_ORDER.get(_day_key(value), 99))
    prepared["_time_order"] = prepared["horari_partit"].map(_time_order)
    prepared["_team_key"] = (
        prepared[TEAM_ID_COLUMN].where(~prepared[TEAM_ID_COLUMN].map(_is_missing), row_index)
        if TEAM_ID_COLUMN in prepared.columns
        else row_index
    )
    prepared["is_missing_venue"] = prepared["pista_joc"].eq(MISSING_VENUE)
    prepared["is_missing_day"] = prepared["dia_partit"].eq(MISSING_DAY)
    prepared["is_missing_time"] = prepared["horari_partit"].eq(MISSING_TIME)
    return prepared


def _aggregate(df: pd.DataFrame, group_cols: list[str], count_col: str) -> pd.DataFrame:
    grouped = (
        df.groupby(group_cols, dropna=False)
        .agg(
            equips=(count_col, "nunique"),
            files=(count_col, "size"),
            modalitats=("Modalitat", _nunique_if_available) if "Modalitat" in df.columns else (count_col, lambda _: 0),
            lligues=("Nom Lliga", _nunique_if_available) if "Nom Lliga" in df.columns else (count_col, lambda _: 0),
            categories=("Categoria", _nunique_if_available) if "Categoria" in df.columns else (count_col, lambda _: 0),
        )
        .reset_index()
    )
    for column in ["equips", "files", "modalitats", "lligues", "categories"]:
        grouped[column] = grouped[column].astype(int)
    return grouped


def _nunique_if_available(values: pd.Series) -> int:
    return int(values.dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique())


def _sort_day_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["_day_order"] = out["dia_partit"].map(lambda value: DAY_ORDER.get(_day_key(value), 99))
    return out.sort_values(
        ["pista_joc", "_day_order", "dia_partit"],
        kind="stable",
    ).drop(columns=["_day_order"]).reset_index(drop=True)


def _sort_slot_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["_day_order"] = out["dia_partit"].map(lambda value: DAY_ORDER.get(_day_key(value), 99))
    out["_time_order"] = out["horari_partit"].map(_time_order)
    return out.sort_values(
        ["pista_joc", "_day_order", "_time_order", "dia_partit", "horari_partit"],
        kind="stable",
    ).drop(columns=["_day_order", "_time_order"]).reset_index(drop=True)


def _missing_field_records(df: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    cols = [col for col in [TEAM_ID_COLUMN, "Nom", "Entitat", VENUE_COLUMN, DAY_COLUMN, TIME_COLUMN] if col in df.columns]
    base = df.copy()
    for source, normalized in [
        (VENUE_COLUMN, "pista_joc"),
        (DAY_COLUMN, "dia_partit"),
        (TIME_COLUMN, "horari_partit"),
    ]:
        if source not in base.columns:
            base[source] = base[normalized]

    def records(mask: pd.Series) -> list[dict[str, Any]]:
        return base.loc[mask, cols].head(50).to_dict("records")

    return {
        "sense_pista": records(df["is_missing_venue"]),
        "sense_dia": records(df["is_missing_day"]),
        "sense_hora": records(df["is_missing_time"]),
    }


def _normalized_text_column(df: pd.DataFrame, column: str, missing_label: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series([missing_label] * len(df), index=df.index)
    return df[column].map(lambda value: missing_label if _is_missing(value) or not str(value).strip() else " ".join(str(value).strip().split()))


def _normalized_day_column(df: pd.DataFrame, column: str) -> pd.Series:
    raw = _normalized_text_column(df, column, MISSING_DAY)
    return raw.map(lambda value: MISSING_DAY if value == MISSING_DAY else str(value).strip().capitalize())


def _normalized_time_column(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series([MISSING_TIME] * len(df), index=df.index)
    return df[column].map(_format_time_value)


def _format_time_value(value: Any) -> str:
    if _is_missing(value):
        return MISSING_TIME
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return MISSING_TIME
        return value.strftime("%H:%M")
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, timedelta):
        return _format_minutes(int(value.total_seconds() // 60))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isnan(float(value)):
            return MISSING_TIME
        numeric = float(value)
        if 0 <= numeric < 1:
            return _format_minutes(round(numeric * 24 * 60))
        if 0 <= numeric < 24:
            hours = int(numeric)
            minutes = round((numeric - hours) * 60)
            return _format_minutes(hours * 60 + minutes)
    text = " ".join(str(value).strip().split())
    if not text:
        return MISSING_TIME
    match = re.search(r"(\d{1,2})[:.hH](\d{2})", text)
    if match:
        return _format_minutes(int(match.group(1)) * 60 + int(match.group(2)))
    match = re.fullmatch(r"\d{1,2}", text)
    if match:
        return _format_minutes(int(text) * 60)
    return text


def _format_minutes(total_minutes: int) -> str:
    total_minutes = total_minutes % (24 * 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


def _time_order(value: Any) -> int:
    if value == MISSING_TIME:
        return 99_999
    match = re.fullmatch(r"(\d{2}):(\d{2})", str(value))
    if not match:
        return 99_998
    return int(match.group(1)) * 60 + int(match.group(2))


def _day_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value).strip().casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _plot_global_heatmap(df: pd.DataFrame):
    import matplotlib.pyplot as plt

    data = df.copy()
    data["slot"] = data["dia_partit"].astype(str) + " " + data["horari_partit"].astype(str)
    pivot = data.pivot_table(index="pista_joc", columns="slot", values="equips", aggfunc="sum", fill_value=0)
    if pivot.empty:
        return None
    fig, ax = plt.subplots(figsize=(max(10, 0.55 * len(pivot.columns)), max(6, 0.35 * len(pivot.index))))
    image = ax.imshow(pivot.to_numpy(), aspect="auto", cmap="YlGnBu")
    ax.set_xticks(range(len(pivot.columns)), pivot.columns, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(pivot.index)), pivot.index, fontsize=8)
    ax.set_xlabel("Dia i hora")
    ax.set_ylabel("Pista joc")
    ax.set_title("Demanda per pista, dia i hora")
    fig.colorbar(image, ax=ax, label="Equips")
    fig.tight_layout()
    return fig


def _plot_friday_heatmap(df: pd.DataFrame):
    import matplotlib.pyplot as plt

    pivot = df.pivot_table(index="pista_joc", columns="horari_partit", values="equips", aggfunc="sum", fill_value=0)
    if pivot.empty:
        return None
    fig, ax = plt.subplots(figsize=(max(8, 0.6 * len(pivot.columns)), max(5, 0.35 * len(pivot.index))))
    image = ax.imshow(pivot.to_numpy(), aspect="auto", cmap="OrRd")
    ax.set_xticks(range(len(pivot.columns)), pivot.columns, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(pivot.index)), pivot.index, fontsize=8)
    ax.set_xlabel("Hora")
    ax.set_ylabel("Pista joc")
    ax.set_title("Demanda de divendres per pista i hora")
    fig.colorbar(image, ax=ax, label="Equips")
    fig.tight_layout()
    return fig


def _plot_by_venue_bar(df: pd.DataFrame):
    import matplotlib.pyplot as plt

    ordered = df.sort_values("equips", ascending=True, kind="stable").tail(30)
    if ordered.empty:
        return None
    fig, ax = plt.subplots(figsize=(10, max(5, 0.35 * len(ordered))))
    ax.barh(ordered["pista_joc"], ordered["equips"], color="#4E79A7")
    ax.set_xlabel("Equips")
    ax.set_ylabel("Pista joc")
    ax.set_title("Demanda total per pista")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    return fig


def _plot_top_slots_bar(df: pd.DataFrame):
    import matplotlib.pyplot as plt

    ordered = df.sort_values("equips", ascending=True, kind="stable")
    if ordered.empty:
        return None
    labels = ordered["pista_joc"].astype(str) + " | " + ordered["dia_partit"].astype(str) + " | " + ordered["horari_partit"].astype(str)
    fig, ax = plt.subplots(figsize=(12, max(6, 0.35 * len(ordered))))
    ax.barh(labels, ordered["equips"], color="#E15759")
    ax.set_xlabel("Equips")
    ax.set_title("Franges amb mes demanda")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    return fig


__all__ = [
    "build_input_demand_analysis",
    "write_input_demand_plots",
]
