from __future__ import annotations

import os
from typing import Dict, List, Tuple, Any, Optional

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np


# Tipologies normalitzades (clau interna → etiqueta)
ACCESS_MAP = {
    "OCASIONAL": "Ocasional",
    "ESPECTADOR": "Espectadors",
    "PARTICIPANTS EN JORNADES O ESDEVENIMENTS ESPORTIUS": "Participants esportius",
    "PARTICIPANTS EN JORNADES O ESDEVENIMENTS NO ESPORTIUS": "Participants no esportius",
}


def _norm(s: object) -> str:
    return str(s).strip().upper()


def analyze_ocasionals(
    monthly_dfs: Dict[int, pd.DataFrame],
    *,
    plots_dir_abs: str,
    year: Optional[int] = None,
    plot_defaults: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[str], List[Dict[str, Any]]]:
    """
    monthly_dfs: {1: df_gen, 2: df_feb, ...}

    Retorna:
      - kpis (dict)
      - warnings (list[str])
      - plot_items_abs (list[dict])  # mateix format que clients/reserves
    """
    warnings: List[str] = []
    plot_items_abs: List[Dict[str, Any]] = []
    kpis: Dict[str, Any] = {}

    rows = []

    # ---------- 1) Normalització + validació ----------
    for month, df in monthly_dfs.items():
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]

        required = ["Any", "Mes", "Tipus accés", "Nombre d'accessos"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            warnings.append(f"Ocasionals mes {month:02d}: falten columnes {missing}")
            continue

        # normalitza tipus
        df["_tipus_norm"] = df["Tipus accés"].map(_norm)
        df["_categoria"] = df["_tipus_norm"].map(ACCESS_MAP)

        df["_valor"] = (
            df["Nombre d'accessos"]
            .astype(str)
            .str.replace(".", "", regex=False)   # 4.850 → 4850
            .str.replace(",", ".", regex=False)
            .astype(float)
        )

        df["_mes"] = month
        rows.append(df[["_mes", "_categoria", "_valor"]])

    if not rows:
        return {}, ["Ocasionals: no s'han pogut carregar dades vàlides."], []

    data = pd.concat(rows, ignore_index=True)
    data = data.dropna(subset=["_categoria"])

    # ---------- 2) Pivot mensual ----------
    pivot = (
        data
        .groupby(["_mes", "_categoria"])["_valor"]
        .sum()
        .unstack(fill_value=0)
        .sort_index()
    )

    # assegura ordre i existència de columnes
    ordered_cols = list(ACCESS_MAP.values())
    for c in ordered_cols:
        if c not in pivot.columns:
            pivot[c] = 0.0
    pivot = pivot[ordered_cols]

    # ---------- 3) KPIs ----------
    kpis["ocasionals_total_any"] = float(pivot.sum().sum())
    kpis["ocasionals_total_per_tipus"] = {
        c: float(pivot[c].sum()) for c in ordered_cols
    }
    kpis["ocasionals_total_per_mes"] = {
        int(m): float(pivot.loc[m].sum()) for m in pivot.index
    }

    # ---------- 4) Plot: barres apilades ----------
    os.makedirs(plots_dir_abs, exist_ok=True)
    out_abs = os.path.join(plots_dir_abs, "ocasionals_accesos_mensuals_stack.png")

    # aplica defaults globals (mateix patró que clients/reserves)
    if plot_defaults:
        style = plot_defaults.get("style")
        if style and style != "default":
            plt.style.use(style)
        plt.rcParams.update({
            "font.family": plot_defaults.get("font_family", "DejaVu Sans"),
            "font.size": int(plot_defaults.get("font_size", 10)),
            "axes.titlesize": int(plot_defaults.get("title_size", 14)),
            "axes.titleweight": plot_defaults.get("title_weight", "bold"),
        })

    fig, ax = plt.subplots(figsize=plot_defaults.get("figsize_line", (10, 6)))
    bottom = np.zeros(len(pivot))

    colors = [
        "#94a3b8",  # Ocasional
        "#60a5fa",  # Espectadors
        "#34d399",  # Esportius
        "#fbbf24",  # No esportius
    ]

    for col, color in zip(ordered_cols, colors):
        ax.bar(pivot.index, pivot[col], bottom=bottom, label=col, color=color)
        bottom += pivot[col].values

    ax.set_title("Accessos ocasionals per mes (barres acumulatives)")
    ax.set_xlabel("Mes")
    ax.set_ylabel("Nombre d'accessos")
    ax.legend()

    if plot_defaults.get("grid", True):
        ax.grid(axis="y", alpha=float(plot_defaults.get("grid_alpha", 0.3)))

    plt.tight_layout()
    plt.savefig(out_abs, dpi=int(plot_defaults.get("dpi", 200)))
    plt.close(fig)

    plot_items_abs.append({
        "key": "ocasionals.accesos_stack",
        "kind": "bar",
        "title": "Accessos ocasionals mensuals (apilat)",
        "file_abs": out_abs,
        "params": {
            "stacked": True,
            "categories": ordered_cols,
        },
    })

    return kpis, warnings, plot_items_abs
