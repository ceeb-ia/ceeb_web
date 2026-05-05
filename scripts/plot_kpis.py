from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


COLORS = {
    "requested": "#2F6DB0",
    "expected": "#F28E2B",
    "assigned": "#3BA55D",
    "damage": "#C44E52",
    "compliance": "#2A9D8F",
    "neutral": "#7A7A7A",
    "house": "#4E79A7",
    "away": "#76B7B2",
    "explicit": "#E15759",
    "blank": "#BAB0AC",
}

SECTION_KEYS = [
    "global_numbers",
    "by_modalitat",
    "entitats",
    "duples",
    "levels_modalitat",
    "levels_categoria",
    "fairness_entities",
    "analysis_rows",
]

PLOT_METADATA = {
    "01_expected_vs_assigned_global": {
        "title": "Numeros demanats vs assignats",
        "description": "Compara el volum global de numeros esperats i numeros finals assignats per al conjunt del run.",
        "source_sections": ["global_numbers"],
    },
    "02_number_delta_global": {
        "title": "Delta global per numero",
        "description": "Mostra la diferencia Assignats - Demanats per numero, per detectar sobreassignacio o infraassignacio.",
        "source_sections": ["global_numbers"],
    },
    "03_expected_vs_assigned_by_modalitat": {
        "title": "Numeros per modalitat",
        "description": "Compara peticions i assignacions finals per numero dins de cada modalitat.",
        "source_sections": ["by_modalitat"],
    },
    "04_before_after_casa_fora_global": {
        "title": "Abans/despres CASA/FORA global",
        "description": "Compara peticions explicites originals, numeros esperats finals i numeros assignats finals per veure l'efecte agregat de CASA/FORA.",
        "source_sections": ["analysis_rows"],
    },
    "05_before_after_casa_fora_by_modalitat": {
        "title": "Abans/despres CASA/FORA per modalitat",
        "description": "Mostra per modalitat com canvia la distribucio de numeros en incorporar les peticions CASA/FORA.",
        "source_sections": ["analysis_rows"],
    },
    "06_duples_balance": {
        "title": "Equilibri de duples CASA/FORA",
        "description": "Situa cada dupla segons el numero CASA i FORA, amb mida segons equips afectats i color segons compliment.",
        "source_sections": ["duples"],
    },
    "07_duples_entities_equips": {
        "title": "Pes de cada dupla",
        "description": "Resumeix quantes entitats i equips textuals recauen sobre cada dupla CASA/FORA.",
        "source_sections": ["duples"],
    },
    "08_entity_magnitude": {
        "title": "Magnitud de les entitats",
        "description": "Mostra les entitats amb mes equips i hi anota els equips amb peticio efectiva.",
        "source_sections": ["entitats"],
    },
    "09_entity_damage_total": {
        "title": "Dany total per entitat",
        "description": "Ordena les entitats pel dany total rebut i hi explicita volum d'equips i demanda.",
        "source_sections": ["entitats"],
    },
    "10_entity_damage_normalized": {
        "title": "Dany normalitzat per entitat",
        "description": "Compara el dany normalitzat per entitat, prioritzant dany per peticio efectiva i fent fallback a dany per equip.",
        "source_sections": ["entitats"],
    },
    "11_entity_incidence_vs_magnitude": {
        "title": "Incidencia vs magnitud",
        "description": "Relaciona la mida de l'entitat amb la seva incidencia, usant el dany com a mida i el compliment CASA/FORA com a color.",
        "source_sections": ["entitats"],
    },
    "12_entity_request_profile": {
        "title": "Perfil de demandes per entitat",
        "description": "Desglossa per entitat el mix de peticions CASA, FORA, explicites i indiferents.",
        "source_sections": ["entitats"],
    },
    "13_modalitat_incidence_damage": {
        "title": "Incidencia i dany per modalitat",
        "description": "Mostra la incidencia percentual i el dany percentual de calendari per modalitat.",
        "source_sections": ["by_modalitat"],
    },
    "14_modalitat_casa_fora_compliance": {
        "title": "Compliment CASA/FORA per modalitat",
        "description": "Compara el percentatge de compliment de CASA/FORA entre modalitats i hi anota la pressio de peticions.",
        "source_sections": ["by_modalitat"],
    },
    "15_levels_by_modalitat": {
        "title": "Qualitat de nivells per modalitat",
        "description": "Resumeix per modalitat el percentatge de grups AC, CE i mixtos trencats, i el rang mitja de nivells.",
        "source_sections": ["levels_modalitat"],
    },
    "16_levels_by_categoria_top_breakage": {
        "title": "Categories amb pitjor barreja de nivells",
        "description": "Ordena les categories pel percentatge de grups mixtos trencats per detectar on l'agrupacio per nivells falla mes.",
        "source_sections": ["levels_categoria"],
    },
    "17_fairness_entities_total": {
        "title": "Fairness total per entitat",
        "description": "Ordena les entitats pel cost total de fairness acumulat.",
        "source_sections": ["fairness_entities"],
    },
    "18_fairness_entities_normalized": {
        "title": "Fairness normalitzat per entitat",
        "description": "Ordena les entitats pel cost de fairness per equip.",
        "source_sections": ["fairness_entities"],
    },
}


def apply_style(style: str) -> None:
    if style != "report":
        raise ValueError(f"Unsupported style: {style}")
    sns.set_theme(style="whitegrid", context="talk")
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#D0D0D0",
            "axes.labelcolor": "#222222",
            "axes.titleweight": "bold",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": "#D8D8D8",
            "grid.alpha": 0.35,
            "legend.frameon": False,
        }
    )


def load_kpis(path: str | Path) -> tuple[dict, dict[str, pd.DataFrame]]:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig") as fh:
        raw = json.load(fh)
    tables = {}
    for key in SECTION_KEYS:
        value = raw.get(key, [])
        tables[key] = pd.DataFrame(value) if isinstance(value, list) else pd.DataFrame()
    return raw, tables


def _as_bool(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=bool)
    lowered = series.astype("object").where(series.notna(), "").astype(str).str.strip().str.lower()
    return lowered.isin({"true", "1", "yes", "si"})


def _to_numeric_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for column in columns:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def _number_count_frame(series: pd.Series, label: str, modalitat: str | None = None) -> pd.DataFrame:
    values = pd.to_numeric(series, errors="coerce").dropna()
    values = values[(values >= 1) & (values <= 8)].astype(int)
    counts = values.value_counts().reindex(range(1, 9), fill_value=0).sort_index()
    frame = pd.DataFrame({"Numero": list(range(1, 9)), "Valor": counts.values, "Serie": label})
    if modalitat is not None:
        frame["Modalitat"] = modalitat
    return frame


def _top_by(df: pd.DataFrame, column: str, limit: int) -> pd.DataFrame:
    if df.empty or column not in df.columns:
        return pd.DataFrame()
    ordered = df.sort_values(column, ascending=False, kind="stable").head(limit).copy()
    return ordered.sort_values(column, ascending=True, kind="stable")


def prepare_tables(raw: dict, frames: dict[str, pd.DataFrame], top_entities: int = 25) -> dict[str, pd.DataFrame | str]:
    del raw
    tables: dict[str, pd.DataFrame | str] = {key: value.copy() for key, value in frames.items()}

    global_numbers = tables["global_numbers"]
    if isinstance(global_numbers, pd.DataFrame) and not global_numbers.empty:
        tables["global_numbers"] = _to_numeric_frame(global_numbers, ["Numero", "Demanats", "Assignats", "Diferencia"])

    by_modalitat = tables["by_modalitat"]
    if isinstance(by_modalitat, pd.DataFrame) and not by_modalitat.empty:
        numeric_cols = [col for col in by_modalitat.columns if col.startswith("Peticio ") or col.startswith("Assignat ")]
        numeric_cols += [
            "Equips totals",
            "Equips amb peticio efectiva",
            "Incidencia",
            "Incidencia %",
            "Severitat mitjana",
            "Peticions CASA/FORA",
            "Compliment CASA/FORA %",
            "Dany total",
            "Dany % calendari",
            "Peticio CASA",
            "Peticio FORA",
        ]
        tables["by_modalitat"] = _to_numeric_frame(by_modalitat, numeric_cols)
        tables["by_modalitat"]["Modalitat"] = tables["by_modalitat"]["Modalitat"].fillna("Sense modalitat")

    entitats = tables["entitats"]
    if isinstance(entitats, pd.DataFrame) and not entitats.empty:
        numeric_cols = [
            "Equips totals",
            "Equips amb peticio efectiva",
            "# CASA",
            "# FORA",
            "# explicits",
            "# indiferents/buits",
            "Incidencia absoluta",
            "Incidencia %",
            "Severitat total",
            "Severitat mitjana",
            "Peticions CASA/FORA",
            "Compliment CASA/FORA %",
            "Dany total",
            "Dany per equip",
            "Dany per peticio efectiva",
            "Dany % calendari",
            "Cost fairness total",
            "Cost fairness per equip",
        ]
        tables["entitats"] = _to_numeric_frame(entitats, numeric_cols)
        tables["entitats"]["Entitat"] = tables["entitats"]["Entitat"].fillna("Sense entitat")
        tables["entitats"]["Demandes totals"] = (
            tables["entitats"][["# CASA", "# FORA", "# explicits"]].fillna(0).sum(axis=1)
        )

    duples = tables["duples"]
    if isinstance(duples, pd.DataFrame) and not duples.empty:
        tables["duples"] = _to_numeric_frame(
            duples,
            ["Dupla", "Numero CASA", "Numero FORA", "Entitats", "Equips afectats", "Compliment CASA/FORA %"],
        )
        if "Etiqueta" in tables["duples"].columns:
            tables["duples"]["Etiqueta"] = tables["duples"]["Etiqueta"].fillna(
                tables["duples"]["Dupla"].map(lambda x: f"Dupla {int(x)}" if pd.notna(x) else "Dupla")
            )
        else:
            tables["duples"]["Etiqueta"] = tables["duples"]["Dupla"].map(
                lambda x: f"Dupla {int(x)}" if pd.notna(x) else "Dupla"
            )

    levels_modalitat = tables["levels_modalitat"]
    if isinstance(levels_modalitat, pd.DataFrame) and not levels_modalitat.empty:
        tables["levels_modalitat"] = _to_numeric_frame(
            levels_modalitat,
            ["% grups AC", "% grups CE", "% grups mixtos trencats", "Rang mitja", "Rang maxim", "Distancia pairwise mitjana"],
        )
        tables["levels_modalitat"]["Modalitat"] = tables["levels_modalitat"]["Modalitat"].fillna("Sense modalitat")

    levels_categoria = tables["levels_categoria"]
    if isinstance(levels_categoria, pd.DataFrame) and not levels_categoria.empty:
        tables["levels_categoria"] = _to_numeric_frame(
            levels_categoria,
            ["% grups AC", "% grups CE", "% grups mixtos trencats", "Rang mitja", "Rang maxim", "Distancia pairwise mitjana"],
        )

    fairness_entities = tables["fairness_entities"]
    if isinstance(fairness_entities, pd.DataFrame) and not fairness_entities.empty:
        tables["fairness_entities"] = _to_numeric_frame(
            fairness_entities,
            ["Cost fairness total", "Cost fairness per equip", "Equips totals"],
        )
        tables["fairness_entities"]["Entitat"] = tables["fairness_entities"]["Entitat"].fillna("Sense entitat")

    analysis = tables["analysis_rows"]
    if isinstance(analysis, pd.DataFrame) and not analysis.empty:
        numeric_cols = ["numero_esperat", "numero_assignat", "dany_jornades", "dupla_numero_casa", "dupla_numero_fora"]
        analysis = _to_numeric_frame(analysis, numeric_cols)
        analysis["tipus_peticio"] = analysis.get("tipus_peticio", pd.Series(dtype=str)).fillna("").astype(str).str.lower()
        analysis["Modalitat"] = analysis.get("Modalitat", pd.Series(dtype=str)).fillna("Sense modalitat").astype(str)
        analysis["te_peticio_efectiva"] = _as_bool(analysis.get("te_peticio_efectiva", pd.Series(dtype=object)))
        analysis["te_incidencia"] = _as_bool(analysis.get("te_incidencia", pd.Series(dtype=object)))
        analysis["casa_fora_complert"] = _as_bool(analysis.get("casa_fora_complert", pd.Series(dtype=object)))
        tables["analysis_rows"] = analysis

        before = _number_count_frame(
            analysis.loc[analysis["tipus_peticio"] == "explicit", "numero_esperat"],
            "Explicites originals",
        )
        after = _number_count_frame(
            analysis.loc[analysis["te_peticio_efectiva"], "numero_esperat"],
            "Esperat despres CASA/FORA",
        )
        final = _number_count_frame(analysis["numero_assignat"], "Assignat final")
        tables["before_after_global"] = pd.concat([before, after, final], ignore_index=True)

        by_modalitat_frames = []
        for modalitat, sub in analysis.groupby("Modalitat", dropna=False):
            by_modalitat_frames.extend(
                [
                    _number_count_frame(
                        sub.loc[sub["tipus_peticio"] == "explicit", "numero_esperat"],
                        "Explicites originals",
                        modalitat=str(modalitat),
                    ),
                    _number_count_frame(
                        sub.loc[sub["te_peticio_efectiva"], "numero_esperat"],
                        "Esperat despres CASA/FORA",
                        modalitat=str(modalitat),
                    ),
                    _number_count_frame(sub["numero_assignat"], "Assignat final", modalitat=str(modalitat)),
                ]
            )
        tables["before_after_by_modalitat"] = (
            pd.concat(by_modalitat_frames, ignore_index=True) if by_modalitat_frames else pd.DataFrame()
        )
    else:
        tables["before_after_global"] = pd.DataFrame()
        tables["before_after_by_modalitat"] = pd.DataFrame()

    entitats_frame = tables["entitats"] if isinstance(tables["entitats"], pd.DataFrame) else pd.DataFrame()
    tables["entitats_top_magnitude"] = _top_by(entitats_frame, "Equips totals", top_entities)
    tables["entitats_top_damage_total"] = _top_by(entitats_frame, "Dany total", top_entities)

    damage_metric = "Dany per peticio efectiva"
    if entitats_frame.empty or "Dany per peticio efectiva" not in entitats_frame.columns or entitats_frame["Dany per peticio efectiva"].fillna(0).eq(0).all():
        damage_metric = "Dany per equip"
    tables["damage_normalized_metric"] = damage_metric
    tables["entitats_top_damage_normalized"] = _top_by(entitats_frame, damage_metric, top_entities)

    levels_categoria_frame = tables["levels_categoria"] if isinstance(tables["levels_categoria"], pd.DataFrame) else pd.DataFrame()
    tables["levels_categoria_top_breakage"] = _top_by(levels_categoria_frame, "% grups mixtos trencats", 20)

    fairness_frame = tables["fairness_entities"] if isinstance(tables["fairness_entities"], pd.DataFrame) else pd.DataFrame()
    tables["fairness_top_total"] = _top_by(fairness_frame, "Cost fairness total", top_entities)
    tables["fairness_top_normalized"] = _top_by(fairness_frame, "Cost fairness per equip", top_entities)

    return tables


def _missing_columns(df: pd.DataFrame, columns: list[str]) -> list[str]:
    return [col for col in columns if col not in df.columns]


def _apply_title(fig: plt.Figure, title: str, source_sections: list[str]) -> None:
    fig.suptitle(title, x=0.01, y=0.99, ha="left", va="top", fontsize=16, fontweight="bold")
    fig.text(0.01, 0.955, f"Font: {', '.join(source_sections)}", ha="left", va="top", fontsize=10, color="#666666")


def _style_axis(ax: plt.Axes, grid_axis: str = "y") -> None:
    ax.grid(axis=grid_axis, alpha=0.25)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _small_multiples_layout(num_items: int, ncols: int = 2) -> tuple[int, int]:
    ncols = min(max(1, ncols), max(1, num_items))
    nrows = int(math.ceil(num_items / ncols))
    return nrows, ncols


def _save_plot(fig: plt.Figure, out_dir: Path, plot_id: str, fmt: str, dpi: int) -> str:
    filename = f"{plot_id}.{fmt}"
    path = out_dir / filename
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return filename


def _skip_entry(plot_id: str, reason: str, fmt: str) -> dict:
    meta = PLOT_METADATA[plot_id]
    return {
        "id": plot_id,
        "filename": f"{plot_id}.{fmt}",
        "title": meta["title"],
        "description": meta["description"],
        "source_sections": meta["source_sections"],
        "status": "skipped",
        "reason": reason,
    }


def _generated_entry(plot_id: str, filename: str) -> dict:
    meta = PLOT_METADATA[plot_id]
    return {
        "id": plot_id,
        "filename": filename,
        "title": meta["title"],
        "description": meta["description"],
        "source_sections": meta["source_sections"],
        "status": "generated",
    }


def plot_01_expected_vs_assigned_global(tables: dict) -> plt.Figure | None:
    df = tables["global_numbers"]
    required = ["Numero", "Demanats", "Assignats"]
    if df.empty or _missing_columns(df, required):
        return None
    fig, ax = plt.subplots(figsize=(12, 7))
    x = np.arange(len(df))
    width = 0.38
    ax.bar(x - width / 2, df["Demanats"], width, color=COLORS["requested"], label="Demanats")
    ax.bar(x + width / 2, df["Assignats"], width, color=COLORS["assigned"], label="Assignats")
    ax.set_xticks(x, df["Numero"].astype(int))
    ax.set_xlabel("Numero")
    ax.set_ylabel("Equips")
    ax.legend()
    _style_axis(ax, "y")
    _apply_title(fig, PLOT_METADATA["01_expected_vs_assigned_global"]["title"], PLOT_METADATA["01_expected_vs_assigned_global"]["source_sections"])
    return fig


def plot_02_number_delta_global(tables: dict) -> plt.Figure | None:
    df = tables["global_numbers"]
    required = ["Numero", "Diferencia"]
    if df.empty or _missing_columns(df, required):
        return None
    fig, ax = plt.subplots(figsize=(12, 7))
    colors = [COLORS["assigned"] if val >= 0 else COLORS["damage"] for val in df["Diferencia"]]
    ax.bar(df["Numero"].astype(int), df["Diferencia"], color=colors)
    ax.axhline(0, color="#444444", linewidth=1)
    ax.set_xlabel("Numero")
    ax.set_ylabel("Assignats - Demanats")
    _style_axis(ax, "y")
    _apply_title(fig, PLOT_METADATA["02_number_delta_global"]["title"], PLOT_METADATA["02_number_delta_global"]["source_sections"])
    return fig


def plot_03_expected_vs_assigned_by_modalitat(tables: dict) -> plt.Figure | None:
    df = tables["by_modalitat"]
    required = ["Modalitat"] + [f"Peticio {num}" for num in range(1, 9)] + [f"Assignat {num}" for num in range(1, 9)]
    if df.empty or _missing_columns(df, required):
        return None
    ordered = df.sort_values("Equips totals", ascending=False).copy()
    nrows, ncols = _small_multiples_layout(len(ordered), ncols=2)
    fig, axes = plt.subplots(nrows, ncols, figsize=(16, max(10, 4.5 * nrows)), squeeze=False)
    for ax in axes.flat:
        ax.set_visible(False)
    for ax, (_, row) in zip(axes.flat, ordered.iterrows()):
        ax.set_visible(True)
        numbers = np.arange(8)
        requested = [row[f"Peticio {num}"] for num in range(1, 9)]
        assigned = [row[f"Assignat {num}"] for num in range(1, 9)]
        width = 0.38
        ax.bar(numbers - width / 2, requested, width, color=COLORS["requested"])
        ax.bar(numbers + width / 2, assigned, width, color=COLORS["assigned"])
        ax.set_xticks(numbers, list(range(1, 9)))
        ax.set_title(str(row["Modalitat"]))
        _style_axis(ax, "y")
    fig.legend(["Peticio", "Assignat"], loc="upper right")
    _apply_title(fig, PLOT_METADATA["03_expected_vs_assigned_by_modalitat"]["title"], PLOT_METADATA["03_expected_vs_assigned_by_modalitat"]["source_sections"])
    return fig


def plot_04_before_after_casa_fora_global(tables: dict) -> plt.Figure | None:
    df = tables["before_after_global"]
    required = ["Numero", "Valor", "Serie"]
    if df.empty or _missing_columns(df, required):
        return None
    fig, ax = plt.subplots(figsize=(12, 7))
    pivot = df.pivot(index="Numero", columns="Serie", values="Valor").fillna(0).reindex(range(1, 9), fill_value=0)
    series_order = ["Explicites originals", "Esperat despres CASA/FORA", "Assignat final"]
    colors = [COLORS["requested"], COLORS["expected"], COLORS["assigned"]]
    x = np.arange(len(pivot.index))
    width = 0.25
    for idx, (series_name, color) in enumerate(zip(series_order, colors)):
        ax.bar(x + (idx - 1) * width, pivot.get(series_name, pd.Series(index=pivot.index, data=0)), width, label=series_name, color=color)
    ax.set_xticks(x, pivot.index.astype(int))
    ax.set_xlabel("Numero")
    ax.set_ylabel("Equips")
    ax.legend()
    _style_axis(ax, "y")
    _apply_title(fig, PLOT_METADATA["04_before_after_casa_fora_global"]["title"], PLOT_METADATA["04_before_after_casa_fora_global"]["source_sections"])
    return fig


def plot_05_before_after_casa_fora_by_modalitat(tables: dict) -> plt.Figure | None:
    df = tables["before_after_by_modalitat"]
    required = ["Modalitat", "Numero", "Valor", "Serie"]
    if df.empty or _missing_columns(df, required):
        return None
    modalitats = sorted(df["Modalitat"].dropna().astype(str).unique().tolist())
    nrows, ncols = _small_multiples_layout(len(modalitats), ncols=2)
    fig, axes = plt.subplots(nrows, ncols, figsize=(16, max(10, 4.5 * nrows)), squeeze=False)
    for ax in axes.flat:
        ax.set_visible(False)
    series_order = ["Explicites originals", "Esperat despres CASA/FORA", "Assignat final"]
    colors = [COLORS["requested"], COLORS["expected"], COLORS["assigned"]]
    for ax, modalitat in zip(axes.flat, modalitats):
        ax.set_visible(True)
        sub = df[df["Modalitat"] == modalitat]
        pivot = sub.pivot(index="Numero", columns="Serie", values="Valor").fillna(0).reindex(range(1, 9), fill_value=0)
        x = np.arange(len(pivot.index))
        width = 0.25
        for idx, (series_name, color) in enumerate(zip(series_order, colors)):
            ax.bar(x + (idx - 1) * width, pivot.get(series_name, pd.Series(index=pivot.index, data=0)), width, color=color)
        ax.set_xticks(x, pivot.index.astype(int))
        ax.set_title(modalitat)
        _style_axis(ax, "y")
    fig.legend(series_order, loc="upper right")
    _apply_title(fig, PLOT_METADATA["05_before_after_casa_fora_by_modalitat"]["title"], PLOT_METADATA["05_before_after_casa_fora_by_modalitat"]["source_sections"])
    return fig


def plot_06_duples_balance(tables: dict) -> plt.Figure | None:
    df = tables["duples"]
    required = ["Numero CASA", "Numero FORA", "Equips afectats", "Compliment CASA/FORA %", "Etiqueta"]
    if df.empty or _missing_columns(df, required):
        return None
    fig, ax = plt.subplots(figsize=(12, 10))
    sizes = df["Equips afectats"].fillna(0) * 12 + 80
    scatter = ax.scatter(
        df["Numero CASA"],
        df["Numero FORA"],
        s=sizes,
        c=df["Compliment CASA/FORA %"],
        cmap="viridis",
        alpha=0.85,
        edgecolors="white",
        linewidths=0.8,
    )
    for _, row in df.iterrows():
        ax.annotate(str(row["Etiqueta"]), (row["Numero CASA"], row["Numero FORA"]), xytext=(5, 5), textcoords="offset points", fontsize=9)
    ax.set_xlabel("Numero CASA")
    ax.set_ylabel("Numero FORA")
    ax.set_xticks(range(1, 9))
    ax.set_yticks(range(1, 9))
    _style_axis(ax, "both")
    cbar = fig.colorbar(scatter, ax=ax)
    cbar.set_label("Compliment CASA/FORA %")
    _apply_title(fig, PLOT_METADATA["06_duples_balance"]["title"], PLOT_METADATA["06_duples_balance"]["source_sections"])
    return fig


def plot_07_duples_entities_equips(tables: dict) -> plt.Figure | None:
    df = tables["duples"]
    required = ["Etiqueta", "Entitats", "Equips afectats"]
    if df.empty or _missing_columns(df, required):
        return None
    ordered = df.sort_values("Equips afectats", ascending=False).copy().sort_values("Equips afectats", ascending=True)
    fig, ax = plt.subplots(figsize=(12, 10))
    y = np.arange(len(ordered))
    height = 0.38
    ax.barh(y - height / 2, ordered["Entitats"], height=height, color=COLORS["requested"], label="Entitats")
    ax.barh(y + height / 2, ordered["Equips afectats"], height=height, color=COLORS["assigned"], label="Equips afectats")
    ax.set_yticks(y, ordered["Etiqueta"])
    ax.set_xlabel("Volum")
    ax.legend()
    _style_axis(ax, "x")
    _apply_title(fig, PLOT_METADATA["07_duples_entities_equips"]["title"], PLOT_METADATA["07_duples_entities_equips"]["source_sections"])
    return fig


def plot_08_entity_magnitude(tables: dict, top_entities: int) -> plt.Figure | None:
    df = tables["entitats_top_magnitude"]
    required = ["Entitat", "Equips totals", "Equips amb peticio efectiva"]
    if df.empty or _missing_columns(df, required):
        return None
    fig, ax = plt.subplots(figsize=(12, 10))
    ax.barh(df["Entitat"], df["Equips totals"], color=COLORS["requested"])
    for _, row in df.iterrows():
        ax.text(row["Equips totals"] + 0.5, row["Entitat"], f"pet={int(row['Equips amb peticio efectiva'])}", va="center", fontsize=9)
    ax.set_xlabel("Equips totals")
    _style_axis(ax, "x")
    _apply_title(fig, f"{PLOT_METADATA['08_entity_magnitude']['title']} (Top {top_entities})", PLOT_METADATA["08_entity_magnitude"]["source_sections"])
    return fig


def plot_09_entity_damage_total(tables: dict, top_entities: int) -> plt.Figure | None:
    df = tables["entitats_top_damage_total"]
    required = ["Entitat", "Dany total", "Equips totals", "Equips amb peticio efectiva", "Demandes totals"]
    if df.empty or _missing_columns(df, required):
        return None
    fig, ax = plt.subplots(figsize=(12, 10))
    ax.barh(df["Entitat"], df["Dany total"], color=COLORS["damage"])
    for _, row in df.iterrows():
        label = f"eq={int(row['Equips totals'])} pet={int(row['Equips amb peticio efectiva'])} dem={int(row['Demandes totals'])}"
        ax.text(row["Dany total"] + 0.2, row["Entitat"], label, va="center", fontsize=8.5)
    ax.set_xlabel("Dany total")
    _style_axis(ax, "x")
    _apply_title(fig, f"{PLOT_METADATA['09_entity_damage_total']['title']} (Top {top_entities})", PLOT_METADATA["09_entity_damage_total"]["source_sections"])
    return fig


def plot_10_entity_damage_normalized(tables: dict, top_entities: int) -> plt.Figure | None:
    df = tables["entitats_top_damage_normalized"]
    metric = str(tables.get("damage_normalized_metric", "Dany per equip"))
    required = ["Entitat", metric, "Dany per equip"]
    if df.empty or _missing_columns(df, required):
        return None
    fig, ax = plt.subplots(figsize=(12, 10))
    ax.barh(df["Entitat"], df[metric], color=COLORS["damage"])
    for _, row in df.iterrows():
        ax.text(row[metric] + 0.02, row["Entitat"], f"dany/equip={row['Dany per equip']:.2f}", va="center", fontsize=8.5)
    ax.set_xlabel(metric)
    _style_axis(ax, "x")
    _apply_title(fig, f"{PLOT_METADATA['10_entity_damage_normalized']['title']} (Top {top_entities})", PLOT_METADATA["10_entity_damage_normalized"]["source_sections"])
    return fig


def plot_11_entity_incidence_vs_magnitude(tables: dict) -> plt.Figure | None:
    df = tables["entitats"]
    required = ["Entitat", "Equips totals", "Incidencia %", "Dany total", "Compliment CASA/FORA %"]
    if df.empty or _missing_columns(df, required):
        return None
    fig, ax = plt.subplots(figsize=(12, 10))
    size = df["Dany total"].fillna(0) * 10 + 50
    scatter = ax.scatter(
        df["Equips totals"],
        df["Incidencia %"],
        s=size,
        c=df["Compliment CASA/FORA %"].fillna(0),
        cmap="viridis",
        alpha=0.8,
        edgecolors="white",
        linewidths=0.8,
    )
    top_labels = set(df.nlargest(10, "Equips totals")["Entitat"]).union(set(df.nlargest(10, "Dany total")["Entitat"]))
    for _, row in df[df["Entitat"].isin(top_labels)].iterrows():
        ax.annotate(row["Entitat"], (row["Equips totals"], row["Incidencia %"]), xytext=(5, 5), textcoords="offset points", fontsize=8)
    ax.set_xlabel("Equips totals")
    ax.set_ylabel("Incidencia %")
    _style_axis(ax, "both")
    cbar = fig.colorbar(scatter, ax=ax)
    cbar.set_label("Compliment CASA/FORA %")
    _apply_title(fig, PLOT_METADATA["11_entity_incidence_vs_magnitude"]["title"], PLOT_METADATA["11_entity_incidence_vs_magnitude"]["source_sections"])
    return fig


def plot_12_entity_request_profile(tables: dict, top_entities: int) -> plt.Figure | None:
    df = tables["entitats_top_magnitude"]
    required = ["Entitat", "# CASA", "# FORA", "# explicits", "# indiferents/buits"]
    if df.empty or _missing_columns(df, required):
        return None
    fig, ax = plt.subplots(figsize=(12, 10))
    left = np.zeros(len(df))
    series_order = [
        ("# CASA", COLORS["house"]),
        ("# FORA", COLORS["away"]),
        ("# explicits", COLORS["explicit"]),
        ("# indiferents/buits", COLORS["blank"]),
    ]
    for label, color in series_order:
        values = df[label].fillna(0).to_numpy()
        ax.barh(df["Entitat"], values, left=left, color=color, label=label)
        left += values
    ax.set_xlabel("Nombre d'equips")
    ax.legend(loc="lower right")
    _style_axis(ax, "x")
    _apply_title(fig, f"{PLOT_METADATA['12_entity_request_profile']['title']} (Top {top_entities})", PLOT_METADATA["12_entity_request_profile"]["source_sections"])
    return fig


def plot_13_modalitat_incidence_damage(tables: dict) -> plt.Figure | None:
    df = tables["by_modalitat"]
    required = ["Modalitat", "Incidencia %", "Dany % calendari"]
    if df.empty or _missing_columns(df, required):
        return None
    ordered = df.sort_values("Incidencia %", ascending=False).copy()
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    axes[0].bar(ordered["Modalitat"], ordered["Incidencia %"], color=COLORS["damage"])
    axes[0].set_ylabel("Incidencia %")
    axes[0].tick_params(axis="x", rotation=45)
    _style_axis(axes[0], "y")
    axes[1].bar(ordered["Modalitat"], ordered["Dany % calendari"], color=COLORS["expected"])
    axes[1].set_ylabel("Dany % calendari")
    axes[1].tick_params(axis="x", rotation=45)
    _style_axis(axes[1], "y")
    _apply_title(fig, PLOT_METADATA["13_modalitat_incidence_damage"]["title"], PLOT_METADATA["13_modalitat_incidence_damage"]["source_sections"])
    return fig


def plot_14_modalitat_casa_fora_compliance(tables: dict) -> plt.Figure | None:
    df = tables["by_modalitat"]
    required = ["Modalitat", "Compliment CASA/FORA %", "Peticions CASA/FORA"]
    if df.empty or _missing_columns(df, required):
        return None
    ordered = df.sort_values("Compliment CASA/FORA %", ascending=False).copy()
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.bar(ordered["Modalitat"], ordered["Compliment CASA/FORA %"], color=COLORS["compliance"])
    for _, row in ordered.iterrows():
        ax.text(row["Modalitat"], row["Compliment CASA/FORA %"] + 0.5, f"pet={int(row['Peticions CASA/FORA'])}", ha="center", va="bottom", fontsize=8, rotation=90)
    ax.set_ylabel("Compliment CASA/FORA %")
    ax.tick_params(axis="x", rotation=45)
    _style_axis(ax, "y")
    _apply_title(fig, PLOT_METADATA["14_modalitat_casa_fora_compliance"]["title"], PLOT_METADATA["14_modalitat_casa_fora_compliance"]["source_sections"])
    return fig


def plot_15_levels_by_modalitat(tables: dict) -> plt.Figure | None:
    df = tables["levels_modalitat"]
    required = ["Modalitat", "% grups AC", "% grups CE", "% grups mixtos trencats", "Rang mitja"]
    if df.empty or _missing_columns(df, required):
        return None
    ordered = df.sort_values("% grups mixtos trencats", ascending=False).copy()
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    x = np.arange(len(ordered))
    width = 0.26
    axes[0].bar(x - width, ordered["% grups AC"], width, color=COLORS["assigned"], label="% AC")
    axes[0].bar(x, ordered["% grups CE"], width, color=COLORS["expected"], label="% CE")
    axes[0].bar(x + width, ordered["% grups mixtos trencats"], width, color=COLORS["damage"], label="% mixtos")
    axes[0].set_xticks(x, ordered["Modalitat"], rotation=45, ha="right")
    axes[0].set_ylabel("% de grups")
    axes[0].legend()
    _style_axis(axes[0], "y")
    axes[1].bar(ordered["Modalitat"], ordered["Rang mitja"], color=COLORS["neutral"])
    axes[1].set_ylabel("Rang mitja")
    axes[1].tick_params(axis="x", rotation=45)
    _style_axis(axes[1], "y")
    _apply_title(fig, PLOT_METADATA["15_levels_by_modalitat"]["title"], PLOT_METADATA["15_levels_by_modalitat"]["source_sections"])
    return fig


def plot_16_levels_by_categoria_top_breakage(tables: dict) -> plt.Figure | None:
    df = tables["levels_categoria_top_breakage"]
    required = ["Categoria", "% grups mixtos trencats"]
    if df.empty or _missing_columns(df, required):
        return None
    fig, ax = plt.subplots(figsize=(12, 10))
    ax.barh(df["Categoria"], df["% grups mixtos trencats"], color=COLORS["damage"])
    ax.set_xlabel("% grups mixtos trencats")
    _style_axis(ax, "x")
    _apply_title(fig, PLOT_METADATA["16_levels_by_categoria_top_breakage"]["title"], PLOT_METADATA["16_levels_by_categoria_top_breakage"]["source_sections"])
    return fig


def plot_17_fairness_entities_total(tables: dict, top_entities: int) -> plt.Figure | None:
    df = tables["fairness_top_total"]
    required = ["Entitat", "Cost fairness total"]
    if df.empty or _missing_columns(df, required):
        return None
    fig, ax = plt.subplots(figsize=(12, 10))
    ax.barh(df["Entitat"], df["Cost fairness total"], color=COLORS["damage"])
    ax.set_xlabel("Cost fairness total")
    _style_axis(ax, "x")
    _apply_title(fig, f"{PLOT_METADATA['17_fairness_entities_total']['title']} (Top {top_entities})", PLOT_METADATA["17_fairness_entities_total"]["source_sections"])
    return fig


def plot_18_fairness_entities_normalized(tables: dict, top_entities: int) -> plt.Figure | None:
    df = tables["fairness_top_normalized"]
    required = ["Entitat", "Cost fairness per equip"]
    if df.empty or _missing_columns(df, required):
        return None
    fig, ax = plt.subplots(figsize=(12, 10))
    ax.barh(df["Entitat"], df["Cost fairness per equip"], color=COLORS["damage"])
    ax.set_xlabel("Cost fairness per equip")
    _style_axis(ax, "x")
    _apply_title(fig, f"{PLOT_METADATA['18_fairness_entities_normalized']['title']} (Top {top_entities})", PLOT_METADATA["18_fairness_entities_normalized"]["source_sections"])
    return fig


PLOTTERS = [
    ("01_expected_vs_assigned_global", plot_01_expected_vs_assigned_global),
    ("02_number_delta_global", plot_02_number_delta_global),
    ("03_expected_vs_assigned_by_modalitat", plot_03_expected_vs_assigned_by_modalitat),
    ("04_before_after_casa_fora_global", plot_04_before_after_casa_fora_global),
    ("05_before_after_casa_fora_by_modalitat", plot_05_before_after_casa_fora_by_modalitat),
    ("06_duples_balance", plot_06_duples_balance),
    ("07_duples_entities_equips", plot_07_duples_entities_equips),
    ("08_entity_magnitude", plot_08_entity_magnitude),
    ("09_entity_damage_total", plot_09_entity_damage_total),
    ("10_entity_damage_normalized", plot_10_entity_damage_normalized),
    ("11_entity_incidence_vs_magnitude", plot_11_entity_incidence_vs_magnitude),
    ("12_entity_request_profile", plot_12_entity_request_profile),
    ("13_modalitat_incidence_damage", plot_13_modalitat_incidence_damage),
    ("14_modalitat_casa_fora_compliance", plot_14_modalitat_casa_fora_compliance),
    ("15_levels_by_modalitat", plot_15_levels_by_modalitat),
    ("16_levels_by_categoria_top_breakage", plot_16_levels_by_categoria_top_breakage),
    ("17_fairness_entities_total", plot_17_fairness_entities_total),
    ("18_fairness_entities_normalized", plot_18_fairness_entities_normalized),
]


def save_manifest(manifest: list[dict], out_dir: Path) -> None:
    path = out_dir / "manifest.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)


def generate_all_plots(
    raw: dict,
    tables: dict[str, pd.DataFrame | str],
    out_dir: str | Path,
    top_entities: int = 25,
    fmt: str = "png",
    dpi: int = 180,
    style: str = "report",
) -> list[dict]:
    del raw
    apply_style(style)
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    variable_top_plots = {
        "08_entity_magnitude",
        "09_entity_damage_total",
        "10_entity_damage_normalized",
        "12_entity_request_profile",
        "17_fairness_entities_total",
        "18_fairness_entities_normalized",
    }
    for plot_id, plotter in PLOTTERS:
        try:
            fig = plotter(tables, top_entities) if plot_id in variable_top_plots else plotter(tables)
            if fig is None:
                manifest.append(_skip_entry(plot_id, "missing or empty source data", fmt))
                continue
            filename = _save_plot(fig, output_dir, plot_id, fmt, dpi)
            manifest.append(_generated_entry(plot_id, filename))
        except Exception as exc:
            manifest.append(_skip_entry(plot_id, f"plot error: {exc}", fmt))
    save_manifest(manifest, output_dir)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Genera plots a partir d'un fitxer kpis_*.json.")
    parser.add_argument("kpis_json", help="Ruta al fitxer kpis_*.json")
    parser.add_argument("--out", help="Carpeta de sortida per als plots")
    parser.add_argument("--top-entities", type=int, default=25, help="Nombre maxim d'entitats als plots de ranking")
    parser.add_argument("--format", choices=["png", "svg"], default="png", help="Format d'exportacio dels plots")
    parser.add_argument("--dpi", type=int, default=180, help="Resolucio de sortida")
    parser.add_argument("--style", choices=["report"], default="report", help="Tema visual dels plots")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    source = Path(args.kpis_json)
    out_dir = Path(args.out) if args.out else source.parent / f"plots_{source.stem}"
    try:
        raw, frames = load_kpis(source)
        tables = prepare_tables(raw, frames, top_entities=args.top_entities)
        manifest = generate_all_plots(
            raw,
            tables,
            out_dir,
            top_entities=args.top_entities,
            fmt=args.format,
            dpi=args.dpi,
            style=args.style,
        )
    except Exception as exc:
        print(f"[ERROR] No s'han pogut generar els plots: {exc}")
        return 1

    generated = sum(1 for item in manifest if item["status"] == "generated")
    skipped = sum(1 for item in manifest if item["status"] == "skipped")
    print(f"[OK] Plots generats a {out_dir}")
    print(f"[OK] Generats: {generated} | Omesos: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
