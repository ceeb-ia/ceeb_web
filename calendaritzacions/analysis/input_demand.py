"""Input demand analysis by venue, day and time slot."""

from __future__ import annotations

import json
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
SEED_COLUMN_CANDIDATES = (
    "Núm. sorteig",
    "Num. sorteig",
    "NÃºm. sorteig",
)

LINKAGE_GROUP_COLUMN_CANDIDATES = (
    "linkage_group",
    "Linkage group",
    "Grup linkage",
    "Grup vinculacio",
    "Grup vinculaci\u00f3",
)
LINKAGE_SIDE_COLUMN_CANDIDATES = (
    "linkage_side",
    "Linkage side",
    "Costat linkage",
    "Costat vinculacio",
    "Costat vinculaci\u00f3",
)
LINKAGE_SOURCE_COLUMN_CANDIDATES = (
    "linkage_source",
    "Linkage source",
    "Origen linkage",
    "Origen vinculacio",
    "Origen vinculaci\u00f3",
)

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
    "Nivell",
]

LEVEL_COLUMN = "Nivell"
LEVEL_ORDER = ["A", "B", "B-C", "C", "Sense nivell"]

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
    seed_requests_by_modality = _seed_requests_by_modality(prepared, count_col)
    home_away_distribution = _home_away_distribution(prepared, count_col)
    linkage_presence = _linkage_presence_distribution(prepared, count_col)
    home_away_by_linkage = _home_away_by_linkage(prepared, count_col)
    linkage_side_distribution = _linkage_side_distribution(prepared, count_col)
    level_distribution_by_modality = _level_distribution_by_modality(prepared, count_col)

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
        "peticio_casa": _distribution_count(home_away_distribution, "Casa"),
        "peticio_fora": _distribution_count(home_away_distribution, "Fora"),
        "peticio_indiferent": _distribution_count(home_away_distribution, "Indiferent"),
    }

    missing_fields = _missing_field_records(prepared)

    return {
        "summary": summary,
        "by_venue": by_venue.to_dict("records"),
        "by_venue_day": by_venue_day.to_dict("records"),
        "by_venue_day_time": by_venue_day_time.to_dict("records"),
        "friday_by_venue_time": friday.to_dict("records"),
        "top_demand_slots": top_slots.to_dict("records"),
        "seed_requests_by_modality": seed_requests_by_modality,
        "home_away_distribution": home_away_distribution,
        "linkage_presence": linkage_presence,
        "home_away_by_linkage": home_away_by_linkage,
        "linkage_side_distribution": linkage_side_distribution,
        "level_distribution_by_modality": level_distribution_by_modality,
        "missing_fields": missing_fields,
        "columns": {
            "venue": VENUE_COLUMN,
            "day": DAY_COLUMN,
            "time": TIME_COLUMN,
            "team_id": TEAM_ID_COLUMN if TEAM_ID_COLUMN in df.columns else None,
            "linkage_group": _first_existing_column(df, LINKAGE_GROUP_COLUMN_CANDIDATES),
            "linkage_side": _first_existing_column(df, LINKAGE_SIDE_COLUMN_CANDIDATES),
            "linkage_source": _first_existing_column(df, LINKAGE_SOURCE_COLUMN_CANDIDATES),
            "level": LEVEL_COLUMN if LEVEL_COLUMN in df.columns else None,
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
    venue_df = pd.DataFrame(analysis.get("by_venue", []))
    top_df = pd.DataFrame(analysis.get("top_demand_slots", []))
    seed_request_df = pd.DataFrame(analysis.get("seed_requests_by_modality", []))
    home_away_df = pd.DataFrame(analysis.get("home_away_distribution", []))
    linkage_presence_df = pd.DataFrame(analysis.get("linkage_presence", []))
    home_away_linkage_df = pd.DataFrame(analysis.get("home_away_by_linkage", []))
    linkage_side_df = pd.DataFrame(analysis.get("linkage_side_distribution", []))
    level_distribution_df = pd.DataFrame(analysis.get("level_distribution_by_modality", []))

    for plot_id, plotter, frame in [
        ("heatmap", _plot_global_heatmap, slot_df),
        ("by_venue", _plot_by_venue_bar, venue_df),
        ("top_slots", _plot_top_slots_bar, top_df),
        ("seed_requests_by_modality", _plot_seed_requests_by_modality, seed_request_df),
        ("home_away_distribution", _plot_home_away_distribution, home_away_df),
        ("linkage_presence", _plot_linkage_presence, linkage_presence_df),
        ("home_away_by_linkage", _plot_home_away_by_linkage, home_away_linkage_df),
        ("linkage_side_distribution", _plot_linkage_side_distribution, linkage_side_df),
        ("level_distribution_by_modality", _plot_level_distribution_by_modality, level_distribution_df),
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

    manifest_path = output_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "artifact_type": "input_demand_plots",
                "plots": generated,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    generated["manifest"] = str(manifest_path)
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
    prepared["modalitat_peticio"] = (
        _normalized_text_column(prepared, "Modalitat", "Sense modalitat")
        if "Modalitat" in prepared.columns
        else pd.Series(["Sense modalitat"] * len(prepared), index=prepared.index)
    )
    seed_column = next((column for column in SEED_COLUMN_CANDIDATES if column in prepared.columns), None)
    prepared["numero_sorteig_peticio"] = prepared[seed_column].map(_seed_request_label) if seed_column else "Sense peticio"
    prepared["casa_fora_peticio"] = prepared["numero_sorteig_peticio"].map(_home_away_request_label)
    linkage_group_column = _first_existing_column(prepared, LINKAGE_GROUP_COLUMN_CANDIDATES)
    linkage_side_column = _first_existing_column(prepared, LINKAGE_SIDE_COLUMN_CANDIDATES)
    linkage_source_column = _first_existing_column(prepared, LINKAGE_SOURCE_COLUMN_CANDIDATES)
    prepared["linkage_group"] = (
        _normalized_text_column(prepared, linkage_group_column, "")
        if linkage_group_column
        else pd.Series([""] * len(prepared), index=prepared.index)
    )
    prepared["linkage_side"] = (
        _normalized_text_column(prepared, linkage_side_column, "")
        if linkage_side_column
        else pd.Series([""] * len(prepared), index=prepared.index)
    )
    prepared["linkage_source"] = (
        _normalized_text_column(prepared, linkage_source_column, "")
        if linkage_source_column
        else pd.Series([""] * len(prepared), index=prepared.index)
    )
    prepared["_linkage_available"] = bool(linkage_group_column)
    prepared["te_linkage"] = prepared["linkage_group"].astype(str).str.strip().ne("") if linkage_group_column else False
    prepared["linkage_status"] = prepared["te_linkage"].map(lambda value: "Amb linkage" if value else "Sense linkage")
    prepared["linkage_side_label"] = prepared["linkage_side"].map(_home_away_request_label)
    prepared["nivell_normalitzat"] = (
        prepared[LEVEL_COLUMN].map(_normalize_level_label)
        if LEVEL_COLUMN in prepared.columns
        else pd.Series(["Sense nivell"] * len(prepared), index=prepared.index)
    )
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


def _seed_requests_by_modality(df: pd.DataFrame, count_col: str) -> list[dict[str, Any]]:
    data = df.drop_duplicates(subset=[count_col]).copy()
    if data.empty:
        return []
    grouped = (
        data.groupby(["modalitat_peticio", "numero_sorteig_peticio"], dropna=False)
        .agg(equips=(count_col, "nunique"))
        .reset_index()
        .rename(columns={"modalitat_peticio": "modalitat", "numero_sorteig_peticio": "peticio"})
    )
    grouped["equips"] = grouped["equips"].astype(int)
    grouped["_request_order"] = grouped["peticio"].map(_seed_request_order)
    grouped = grouped.sort_values(["modalitat", "_request_order", "peticio"], kind="stable").drop(columns=["_request_order"])
    return grouped.to_dict("records")


def _home_away_distribution(df: pd.DataFrame, count_col: str) -> list[dict[str, Any]]:
    data = df.drop_duplicates(subset=[count_col]).copy()
    if data.empty:
        return []
    grouped = (
        data.groupby(["casa_fora_peticio"], dropna=False)
        .agg(equips=(count_col, "nunique"))
        .reset_index()
        .rename(columns={"casa_fora_peticio": "peticio"})
    )
    grouped["equips"] = grouped["equips"].astype(int)
    grouped["_order"] = grouped["peticio"].map(_home_away_order)
    return grouped.sort_values(["_order", "peticio"], kind="stable").drop(columns=["_order"]).to_dict("records")


def _linkage_presence_distribution(df: pd.DataFrame, count_col: str) -> list[dict[str, Any]]:
    if not bool(df["_linkage_available"].any()):
        return []
    data = df.drop_duplicates(subset=[count_col]).copy()
    grouped = (
        data.groupby(["linkage_status"], dropna=False)
        .agg(equips=(count_col, "nunique"))
        .reset_index()
        .rename(columns={"linkage_status": "linkage"})
    )
    grouped["equips"] = grouped["equips"].astype(int)
    grouped["_order"] = grouped["linkage"].map(lambda value: 0 if value == "Amb linkage" else 1)
    return grouped.sort_values(["_order", "linkage"], kind="stable").drop(columns=["_order"]).to_dict("records")


def _home_away_by_linkage(df: pd.DataFrame, count_col: str) -> list[dict[str, Any]]:
    if not bool(df["_linkage_available"].any()):
        return []
    data = df.drop_duplicates(subset=[count_col]).copy()
    grouped = (
        data.groupby(["linkage_status", "casa_fora_peticio"], dropna=False)
        .agg(equips=(count_col, "nunique"))
        .reset_index()
        .rename(columns={"linkage_status": "linkage", "casa_fora_peticio": "peticio"})
    )
    grouped["equips"] = grouped["equips"].astype(int)
    grouped["_linkage_order"] = grouped["linkage"].map(lambda value: 0 if value == "Amb linkage" else 1)
    grouped["_request_order"] = grouped["peticio"].map(_home_away_order)
    return grouped.sort_values(["_linkage_order", "_request_order", "peticio"], kind="stable").drop(
        columns=["_linkage_order", "_request_order"]
    ).to_dict("records")


def _linkage_side_distribution(df: pd.DataFrame, count_col: str) -> list[dict[str, Any]]:
    if not bool(df["linkage_side"].astype(str).str.strip().ne("").any()):
        return []
    data = df.drop_duplicates(subset=[count_col]).copy()
    grouped = (
        data.groupby(["linkage_side_label"], dropna=False)
        .agg(equips=(count_col, "nunique"))
        .reset_index()
        .rename(columns={"linkage_side_label": "side"})
    )
    grouped["equips"] = grouped["equips"].astype(int)
    grouped["_order"] = grouped["side"].map(_home_away_order)
    return grouped.sort_values(["_order", "side"], kind="stable").drop(columns=["_order"]).to_dict("records")


def _level_distribution_by_modality(df: pd.DataFrame, count_col: str) -> list[dict[str, Any]]:
    data = df.drop_duplicates(subset=[count_col]).copy()
    if data.empty:
        return []
    grouped = (
        data.groupby(["modalitat_peticio", "nivell_normalitzat"], dropna=False)
        .agg(equips=(count_col, "nunique"))
        .reset_index()
        .rename(columns={"modalitat_peticio": "modalitat", "nivell_normalitzat": "nivell"})
    )
    grouped["equips"] = grouped["equips"].astype(int)
    totals = grouped.groupby("modalitat", dropna=False)["equips"].transform("sum").replace(0, pd.NA)
    grouped["percentatge"] = (grouped["equips"] / totals * 100).fillna(0.0).round(2)
    grouped["_level_order"] = grouped["nivell"].map(_level_order)
    grouped = grouped.sort_values(["modalitat", "_level_order", "nivell"], kind="stable").drop(columns=["_level_order"])
    return grouped.to_dict("records")


def _distribution_count(rows: list[dict[str, Any]], label: str) -> int:
    for row in rows:
        if row.get("peticio") == label or row.get("side") == label:
            return int(row.get("equips", 0) or 0)
    return 0


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


def _first_existing_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    return next((column for column in candidates if column in df.columns), None)


def _home_away_request_label(value: Any) -> str:
    text = _day_key(value).upper()
    if text in {"CASA", "HOME", "LOCAL"}:
        return "Casa"
    if text in {"FORA", "AWAY", "VISITANT", "VISITOR"}:
        return "Fora"
    return "Indiferent"


def _home_away_order(value: Any) -> int:
    return {"Casa": 0, "Fora": 1, "Indiferent": 2}.get(str(value), 3)


def _seed_request_label(value: Any) -> str:
    if _is_missing(value):
        return "Sense peticio"
    text = " ".join(str(value).strip().split())
    if not text:
        return "Sense peticio"
    upper = _day_key(text).upper()
    if upper in {"CASA", "FORA"}:
        return upper
    try:
        number = int(float(text.replace(",", ".")))
    except (TypeError, ValueError):
        return "Altres"
    return str(number) if 1 <= number <= 8 else "Altres"


def _seed_request_order(value: Any) -> int:
    text = str(value)
    if text.isdigit():
        return int(text)
    return {"CASA": 20, "FORA": 21, "Altres": 98, "Sense peticio": 99}.get(text, 97)


def _normalize_level_label(value: Any) -> str:
    if _is_missing(value):
        return "Sense nivell"
    key = _day_key(value).upper()
    if not key:
        return "Sense nivell"
    if re.search(r"\bB\s*[-/]\s*C\b", key):
        return "B-C"
    match = re.search(r"\b([A-E])\b", key)
    if not match:
        match = re.search(r"(?:NIVELL\s*)?([A-E])\s*$", key)
    if not match:
        return "Sense nivell"
    return {"A": "A", "B": "B", "C": "B-C", "D": "B-C", "E": "C"}[match.group(1)]


def _level_order(value: Any) -> int:
    try:
        return LEVEL_ORDER.index(str(value))
    except ValueError:
        return len(LEVEL_ORDER)


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


def _plot_seed_requests_by_modality(df: pd.DataFrame):
    if df.empty:
        return None
    import matplotlib.pyplot as plt

    totals = df.groupby("modalitat", dropna=False)["equips"].sum().sort_values(ascending=False)
    modalities = list(totals.head(12).index)
    if not modalities:
        return None

    cols = min(3, len(modalities))
    rows = math.ceil(len(modalities) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(4.6 * cols, 3.8 * rows))
    if not isinstance(axes, (list, tuple)):
        try:
            axes = axes.flatten()
        except AttributeError:
            axes = [axes]
    else:
        axes = list(axes)

    palette = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC"]
    for ax, modality in zip(axes, modalities):
        subset = df[df["modalitat"] == modality].sort_values("peticio", key=lambda series: series.map(_seed_request_order), kind="stable")
        values = subset["equips"].astype(int).tolist()
        labels = subset["peticio"].astype(str).tolist()
        ax.pie(values, labels=labels, autopct="%1.0f%%", startangle=90, colors=palette[: len(values)], textprops={"fontsize": 8})
        ax.set_title(str(modality), fontsize=10)
    for ax in axes[len(modalities):]:
        ax.axis("off")
    fig.suptitle("Peticions de numero de sorteig per modalitat", fontsize=13)
    fig.tight_layout()
    return fig


def _plot_home_away_distribution(df: pd.DataFrame):
    if df.empty:
        return None
    import matplotlib.pyplot as plt

    ordered = df.sort_values("peticio", key=lambda series: series.map(_home_away_order), kind="stable")
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.bar(ordered["peticio"], ordered["equips"], color=["#4E79A7", "#F28E2B", "#BAB0AC"][: len(ordered)])
    ax.set_title("Distribucio Casa/Fora/Indiferent")
    ax.set_ylabel("Equips")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    return fig


def _plot_linkage_presence(df: pd.DataFrame):
    if df.empty:
        return None
    import matplotlib.pyplot as plt

    ordered = df.sort_values("linkage", kind="stable")
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.bar(ordered["linkage"], ordered["equips"], color=["#59A14F", "#BAB0AC"][: len(ordered)])
    ax.set_title("Equips amb i sense linkage")
    ax.set_ylabel("Equips")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    return fig


def _plot_home_away_by_linkage(df: pd.DataFrame):
    if df.empty:
        return None
    import matplotlib.pyplot as plt

    pivot = df.pivot_table(index="linkage", columns="peticio", values="equips", aggfunc="sum", fill_value=0)
    if pivot.empty:
        return None
    columns = sorted(pivot.columns, key=_home_away_order)
    pivot = pivot[columns]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    bottom = [0] * len(pivot.index)
    colors = {"Casa": "#4E79A7", "Fora": "#F28E2B", "Indiferent": "#BAB0AC"}
    for column in pivot.columns:
        values = pivot[column].astype(int).tolist()
        ax.bar(pivot.index.astype(str), values, bottom=bottom, label=str(column), color=colors.get(str(column), "#76B7B2"))
        bottom = [left + right for left, right in zip(bottom, values)]
    ax.set_title("Casa/Fora/Indiferent per linkage")
    ax.set_ylabel("Equips")
    ax.legend(loc="upper right")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    return fig


def _plot_linkage_side_distribution(df: pd.DataFrame):
    if df.empty:
        return None
    import matplotlib.pyplot as plt

    ordered = df.sort_values("side", key=lambda series: series.map(_home_away_order), kind="stable")
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.bar(ordered["side"], ordered["equips"], color=["#4E79A7", "#F28E2B", "#BAB0AC"][: len(ordered)])
    ax.set_title("Costat de linkage")
    ax.set_ylabel("Equips")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    return fig


def _plot_level_distribution_by_modality(df: pd.DataFrame):
    if df.empty:
        return None
    import matplotlib.pyplot as plt

    totals = df.groupby("modalitat", dropna=False)["equips"].sum().sort_values(ascending=False)
    modalities = list(totals.head(12).index)
    if not modalities:
        return None

    cols = min(3, len(modalities))
    rows = math.ceil(len(modalities) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(4.6 * cols, 3.8 * rows))
    try:
        axes = axes.flatten()
    except AttributeError:
        axes = [axes]

    colors = {"A": "#4E79A7", "B": "#59A14F", "B-C": "#EDC948", "C": "#E15759", "Sense nivell": "#BAB0AC"}
    for ax, modality in zip(axes, modalities):
        subset = df[df["modalitat"] == modality].sort_values("nivell", key=lambda series: series.map(_level_order), kind="stable")
        values = subset["equips"].astype(int).tolist()
        labels = subset["nivell"].astype(str).tolist()
        ax.pie(
            values,
            labels=labels,
            autopct="%1.0f%%",
            startangle=90,
            colors=[colors.get(label, "#76B7B2") for label in labels],
            textprops={"fontsize": 8},
        )
        ax.set_title(str(modality), fontsize=10)
    for ax in axes[len(modalities):]:
        ax.axis("off")
    fig.suptitle("Distribucio de nivells normalitzats per modalitat", fontsize=13)
    fig.tight_layout()
    return fig


__all__ = [
    "build_input_demand_analysis",
    "write_input_demand_plots",
]
