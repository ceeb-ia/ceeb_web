from __future__ import annotations

import os
import unicodedata
from typing import Any, Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# Acceptem variants amb/ sense espai i DIC/DES
MONTH_TOKENS = [
    "GENQ", "FEBQ", "MARQ", "ABRQ", "MAIQ", "JUNQ",
    "JULQ", "AGOQ", "SEPQ", "OCTQ", "NOVQ", "DICQ", "DESQ",
]

CANON_MONTH_LABEL = {
    "GENQ": "Gen",
    "FEBQ": "Feb",
    "MARQ": "Mar",
    "ABRQ": "Abr",
    "MAIQ": "Mai",
    "JUNQ": "Jun",
    "JULQ": "Jul",
    "AGOQ": "Ago",
    "SEPQ": "Sep",
    "OCTQ": "Oct",
    "NOVQ": "Nov",
    "DICQ": "Des",
    "DESQ": "Des",
}


def _norm_cell(x: object) -> str:
    if pd.isna(x):
        return ""
    s = str(x).strip().upper()
    return s.replace(" ", "")  # "GEN Q" -> "GENQ"


def _norm_label(x: object) -> str:
    if pd.isna(x):
        return ""
    s = str(x).strip().upper()
    # treu accents: "ACCÉS" -> "ACCES"
    s = "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")
    # compacta espais
    s = " ".join(s.split())
    return s


def _find_header_row(df: pd.DataFrame) -> Optional[int]:
    """
    Troba la fila on hi ha els mesos (GEN Q, FEB Q, ...).
    Una fila és header si conté >= 8 tokens de mesos.
    """
    for i in range(len(df)):
        cells = [_norm_cell(v) for v in df.iloc[i].tolist()]
        hits = sum(1 for c in cells if c in MONTH_TOKENS)
        if hits >= 8:
            return i
    return None


def _rebuild_table_from_header(df_raw: pd.DataFrame) -> Tuple[pd.DataFrame, List[str], str]:
    """
    Reconstrueix la taula quan la capçalera no està a la fila 0.
    Retorna:
      - table: df amb columnes = capçaleres reals
      - month_cols: llista de columnes corresponents a mesos (en ordre d'aparició)
      - label_col: la 1a columna (concepte/tipus)
    """
    df0 = df_raw.copy()

    header_idx = _find_header_row(df0)
    if header_idx is None:
        raise ValueError("No s'ha pogut detectar la fila de capçaleres (mesos).")

    header_row = df0.iloc[header_idx].tolist()
    header_row = [str(h).strip() if not pd.isna(h) else "" for h in header_row]

    data = df0.iloc[header_idx + 1 :].copy()
    data.columns = header_row
    data = data.dropna(how="all").reset_index(drop=True)

    label_col = data.columns[0]

    # Columnes de mesos (en ordre)
    month_cols: List[str] = []
    for c in data.columns[1:]:
        if _norm_cell(c) in MONTH_TOKENS:
            month_cols.append(c)

    if len(month_cols) < 8:
        raise ValueError("S'han detectat massa poques columnes de mesos.")

    return data, month_cols, label_col


def _last_valid_row(table: pd.DataFrame, label_col: str, month_cols: List[str]) -> pd.Series:
    """
    Agafa l'última fila amb:
      - label no buit
      - i almenys un valor mensual numèric/no-null
    """
    d = table.copy()
    labels_ok = d[label_col].astype(str).str.strip().ne("")

    m = d[month_cols].apply(pd.to_numeric, errors="coerce")
    months_ok = ~m.isna().all(axis=1)

    d2 = d[labels_ok & months_ok]
    if d2.empty:
        raise ValueError("No hi ha cap fila final/vàlida amb dades mensuals.")
    return d2.iloc[-1]


def _find_row_by_label_contains(table: pd.DataFrame, label_col: str, needle: str) -> Optional[pd.Series]:
    needle_n = _norm_label(needle)
    labels = table[label_col].map(_norm_label)
    hits = labels.str.contains(needle_n, na=False)
    if not hits.any():
        return None
    return table.loc[hits].iloc[-1]  # última coincidència

def apply_plot_defaults(plot_defaults: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aplica defaults globals a matplotlib i retorna un dict normalitzat.
    Ho fem aquí perquè tots els plots comparteixin la mateixa configuració.
    """
    pd = dict(plot_defaults or {})

    # Style
    style = pd.get("style", "seaborn-v0_8")
    if style and style != "default":
        plt.style.use(style)

    # rcParams
    plt.rcParams.update({
        "font.family": pd.get("font_family", "DejaVu Sans"),
        "font.size": int(pd.get("font_size", 10)),
        "axes.titlesize": int(pd.get("title_size", 14)),
        "axes.titleweight": pd.get("title_weight", "bold"),
    })

    return pd


def _get_figsize(pd: Dict[str, Any], kind: str, fallback: Tuple[float, float]) -> Tuple[float, float]:
    """
    kind: 'line' o 'pie' (per ara).
    """
    key = "figsize_line" if kind == "line" else "figsize_pie"
    v = pd.get(key, None)
    if isinstance(v, (list, tuple)) and len(v) == 2:
        try:
            return (float(v[0]), float(v[1]))
        except Exception:
            return fallback
    return fallback


def _get_dpi(pd: Dict[str, Any], fallback: int = 200) -> int:
    try:
        return int(pd.get("dpi", fallback))
    except Exception:
        return fallback
    

def _plot_year_evolution(
    month_labels: List[str],
    values: List[float],
    out_png: str,
    *,
    title: str,
    ylabel: str,
    plot_defaults: Optional[Dict[str, Any]] = None,
) -> bool:
    if not values:
        return False

    pd = apply_plot_defaults(plot_defaults)

    fig, ax = plt.subplots(figsize=_get_figsize(pd, "line", (9, 5)))
    ax.plot(month_labels, values, marker="o")

    ax.set_title(title, pad=12)
    ax.set_xlabel("Mes")
    ax.set_ylabel(ylabel)

    if bool(pd.get("grid", True)):
        ax.grid(True, alpha=float(pd.get("grid_alpha", 0.3)))

    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(out_png, dpi=_get_dpi(pd, 200))
    plt.close(fig)
    return True


def analyze_clients(
    df_raw: pd.DataFrame,
    *,
    plots_dir_abs: str,
    year: Optional[int] = None,
    plot_defaults: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[str], List[str]]:    
    """
    Excel mensual d'abonats:
      - capçalera pot començar més avall (detectem fila de mesos)
      - cada columna (excepte la primera) és un mes (GEN Q ... DIC Q)
      - files = tipus d'abonament / desglossaments
      - fila d'interès: últim total vàlid
      - també fem plot per la fila "Accés puntual" (si existeix)

    Retorna:
      - kpis (dict)
      - warnings (list[str])
      - plot_paths_abs (list[str])  # ABSOLUTS
    """
    warnings: List[str] = []
    plot_items_abs: List[Dict[str, Any]] = []
    kpis: Dict[str, Any] = {}

    # 1) Reconstruïm taula amb headers reals
    try:
        table, month_cols, label_col = _rebuild_table_from_header(df_raw)
    except Exception as e:
        warnings.append(f"clients: {e}")
        return {}, warnings, plot_items_abs

    # 2) Mesos (labels bonics)
    month_labels: List[str] = []
    for c in month_cols:
        tok = _norm_cell(c)
        month_labels.append(CANON_MONTH_LABEL.get(tok, str(c).strip()))

    # 3) Fila TOTAL (última vàlida)
    try:
        total_row = _last_valid_row(table, label_col, month_cols)
    except Exception as e:
        warnings.append(f"clients: {e}")
        return {}, warnings, plot_items_abs

    vals_total = pd.to_numeric(total_row[month_cols], errors="coerce").fillna(0).astype(float).tolist()

    kpis["abonats_total_fila_detectada"] = str(total_row[label_col]).strip()
    kpis["abonats_total_serie_mensual"] = dict(zip(month_labels, [float(v) for v in vals_total]))
    kpis["abonats_total_any"] = float(np.sum(vals_total))
    kpis["abonats_total_mitjana_mensual"] = float(np.mean(vals_total)) if vals_total else 0.0
    kpis["abonats_total_maxim"] = float(np.max(vals_total)) if vals_total else 0.0
    kpis["abonats_total_minim"] = float(np.min(vals_total)) if vals_total else 0.0
    if len(vals_total) >= 2:
        kpis["abonats_total_variacio_gener_desembre"] = float(vals_total[-1] - vals_total[0])

    os.makedirs(plots_dir_abs, exist_ok=True)
    out_abs_total = os.path.join(plots_dir_abs, "clients_evolucio_abonats_total.png")
    if _plot_year_evolution(
        month_labels,
        vals_total,
        out_abs_total,
        title="Evolució anual d'abonats (TOTAL mensual)",
        ylabel="Total abonats",
        plot_defaults=plot_defaults,
    ):
        plot_items_abs.append({
            "key": "clients.total",
            "kind": "line",
            "title": "Evolució anual d'abonats (TOTAL mensual)",
            "file_abs": out_abs_total,
            "params": {"ylabel": "Total abonats"},})
        
    else:
        warnings.append("clients: no s'ha pogut generar el gràfic del TOTAL.")

    # 4) Fila "Accés puntual" (si existeix)
    punctual_row = _find_row_by_label_contains(table, label_col, "ACCÉS PUNTUAL")

    if punctual_row is None:
        warnings.append("clients: no s'ha trobat la fila 'Accés puntual'.")
    else:
        vals_puntual = pd.to_numeric(punctual_row[month_cols], errors="coerce").fillna(0).astype(float).tolist()

        kpis["acces_puntual_fila_detectada"] = str(punctual_row[label_col]).strip()
        kpis["acces_puntual_serie_mensual"] = dict(zip(month_labels, [float(v) for v in vals_puntual]))
        kpis["acces_puntual_total_any"] = float(np.sum(vals_puntual))
        kpis["acces_puntual_mitjana_mensual"] = float(np.mean(vals_puntual)) if vals_puntual else 0.0
        kpis["acces_puntual_maxim"] = float(np.max(vals_puntual)) if vals_puntual else 0.0
        kpis["acces_puntual_minim"] = float(np.min(vals_puntual)) if vals_puntual else 0.0
        if len(vals_puntual) >= 2:
            kpis["acces_puntual_variacio_gener_desembre"] = float(vals_puntual[-1] - vals_puntual[0])

        out_abs_puntual = os.path.join(plots_dir_abs, "clients_evolucio_acces_puntual.png")
        if _plot_year_evolution(
            month_labels,
            vals_puntual,
            out_abs_puntual,
            title="Evolució anual d'Accés puntual",
            ylabel="Accessos puntuals",
            plot_defaults=plot_defaults,
        ):
            plot_items_abs.append({
                "key": "clients.puntual",
                "kind": "line",
                "title": "Evolució anual d'Accés puntual",
                "file_abs": out_abs_puntual,
                "params": {"ylabel": "Accessos puntuals"},
            })
        else:
            warnings.append("clients: no s'ha pogut generar el gràfic d'Accés puntual.")

    return kpis, warnings, plot_items_abs
