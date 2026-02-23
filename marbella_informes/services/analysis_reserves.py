from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple, Optional
import numpy as np 
import pandas as pd
import matplotlib.pyplot as plt


# Columnes que vols (flexible: només agafem les que existeixen)
WANTED_COLS = ["NombreCompleto", "Recurso", "FechaReserva", "DuracionHoras", "Deporte"]


def _to_float_hours(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str).str.replace(",", ".", regex=False),
        errors="coerce"
    )


def _normalize_categoria(x) -> Optional[str]:
    if pd.isna(x):
        return None
    s = str(x).strip().upper()
    # tolera variacions
    if "CLIENT" in s:
        return "client"
    if "ENTITAT" in s:
        return "entitat"
    return None


def _find_category_col(df: pd.DataFrame) -> Optional[str]:
    # columnes sense títol típiques: "Unnamed: 11" o ""
    unnamed = [c for c in df.columns if str(c).strip() == "" or str(c).startswith("Unnamed")]
    if not unnamed:
        return None

    # tria la que realment contingui CLIENT/ENTITAT (en alguna fila)
    for c in unnamed:
        vals = df[c].dropna().astype(str).str.upper()
        if vals.str.contains("CLIENT").any() or vals.str.contains("ENTITAT").any():
            return c

    return unnamed[0]  # fallback


def _spread_ys(ys, min_dy=0.08, y_min=-1.15, y_max=1.15):
    """
    Ajusta una llista de y (ordenada) perquè tinguin separació mínima.
    Retorna y ajustades dins [y_min, y_max].
    """
    ys = np.array(ys, dtype=float)

    # Clamp inicial
    ys = np.clip(ys, y_min, y_max)

    # Passada cap avall: assegura min_dy
    for i in range(1, len(ys)):
        if ys[i] - ys[i-1] < min_dy:
            ys[i] = ys[i-1] + min_dy

    # Si ens hem passat del límit superior, arrosseguem cap amunt
    overflow = ys[-1] - y_max
    if overflow > 0:
        ys -= overflow

    # Passada cap amunt (per si ara col·lisionen per baix)
    for i in range(len(ys)-2, -1, -1):
        if ys[i+1] - ys[i] < min_dy:
            ys[i] = ys[i+1] - min_dy

    # Clamp final
    ys = np.clip(ys, y_min, y_max)
    return ys

from typing import Any, Dict, Optional, Tuple, List
import matplotlib.pyplot as plt


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




def _plot_pie_hours_by_recurso(
    df: pd.DataFrame,
    out_png: str,
    *,
    plot_defaults: Optional[Dict[str, Any]] = None,
) -> bool:
    d = df.dropna(subset=["Recurso", "DuracionHoras"]).copy()
    if d.empty:
        return False

    s = d.groupby("Recurso")["DuracionHoras"].sum().sort_values(ascending=False)

    pd = apply_plot_defaults(plot_defaults)
    n_labels = int(len(s))

    # Si hi ha molts espais, fem la figura verticalment mes gran.
    base_w, base_h = _get_figsize(pd, "pie", (9, 7))
    estimated_per_side = int(np.ceil(n_labels / 2.0))
    fig_h = max(base_h, 2.8 + 0.6 * estimated_per_side)
    fig, ax = plt.subplots(figsize=(base_w, fig_h))

    cmap_name = "Pastel1" if n_labels <= 9 else "tab20"
    colors = plt.get_cmap(cmap_name)(np.linspace(0, 1, n_labels))

    wedges, _ = ax.pie(
        s.values,
        labels=None,
        startangle=90,
        colors=colors,
        wedgeprops=dict(width=0.42, edgecolor="white", linewidth=1.0)
    )

    total = float(s.sum())
    ax.set_title("Percentatge d'hores reservades per espai", pad=18)
    ax.text(0, 0, f"{int(total)}\nhores", ha="center", va="center", fontsize=13, weight="bold")

    def _short_label(lbl: str, max_len: int = 20) -> str:
        txt = str(lbl).strip()
        return txt if len(txt) <= max_len else (txt[: max_len - 3] + "...")

    # --- Preparem punts d'ancoratge i agrupem esquerra/dreta ---
    items_right = []
    items_left = []

    for i, (wedge, label, value) in enumerate(zip(wedges, s.index, s.values)):
        angle = (wedge.theta2 + wedge.theta1) / 2.0
        ang = np.deg2rad(angle)
        x = np.cos(ang)
        y = np.sin(ang)

        pct = (float(value) / total) * 100.0
        txt = f"{_short_label(label)} {pct:.1f}%"

        item = dict(i=i, txt=txt, x=x, y=y)

        if x >= 0:
            items_right.append(item)
        else:
            items_left.append(item)

    # Ordenem per y (de baix a dalt) i repartim y per evitar solapament
    items_right.sort(key=lambda it: it["y"])
    items_left.sort(key=lambda it: it["y"])

    ys_r = [it["y"] for it in items_right]
    ys_l = [it["y"] for it in items_left]

    max_side = max(len(items_right), len(items_left), 1)
    y_lim = max(1.25, 0.16 * max_side + 0.25)
    min_dy = max(0.10, min(0.22, (2.0 * y_lim - 0.20) / max_side))

    ys_r_adj = _spread_ys(ys_r, min_dy=min_dy, y_min=-y_lim, y_max=y_lim) if ys_r else []
    ys_l_adj = _spread_ys(ys_l, min_dy=min_dy, y_min=-y_lim, y_max=y_lim) if ys_l else []

    # Paràmetres de posició etiqueta
    x_text_right = 1.42 + min(0.35, 0.01 * max_side)
    x_text_left = -x_text_right
    r_anchor = 0.82  # on enganxem la fletxa al donut
    label_fontsize = 9 if n_labels <= 16 else 8
    box_pad = 0.35 if n_labels <= 16 else 0.25

    def _draw(items, ys_adj, side):
        for it, y_txt in zip(items, ys_adj):
            i = it["i"]
            x = it["x"]
            y = it["y"]

            ax.annotate(
                it["txt"],
                xy=(x * r_anchor, y * r_anchor),
                xytext=(x_text_right if side == "right" else x_text_left, y_txt),
                ha="left" if side == "right" else "right",
                va="center",
                fontsize=label_fontsize,
                bbox=dict(
                    boxstyle=f"round,pad={box_pad}",
                    fc="white",
                    ec=colors[i],
                    lw=1
                ),
                arrowprops=dict(
                    arrowstyle="-",
                    color=colors[i],
                    lw=1,
                    connectionstyle="angle3,angleA=0,angleB=90"
                )
            )

    _draw(items_right, ys_r_adj, "right")
    _draw(items_left, ys_l_adj, "left")

    # Dona aire a les etiquetes
    x_lim = max(1.70, abs(x_text_right) + 0.35)
    ax.set_xlim(-x_lim, x_lim)
    ax.set_ylim(-y_lim - 0.15, y_lim + 0.15)

    plt.tight_layout()
    plt.savefig(out_png, dpi=_get_dpi(pd, 200), bbox_inches="tight")
    plt.close(fig)
    return True

def _plot_year_evolution(
    df: pd.DataFrame,
    out_png: str,
    *,
    plot_defaults: Optional[Dict[str, Any]] = None,
) -> bool:
    d = df.dropna(subset=["FechaReserva", "DuracionHoras"]).copy()
    if d.empty:
        return False

    s = d.set_index("FechaReserva")["DuracionHoras"].resample("MS").sum()

    pd = apply_plot_defaults(plot_defaults)

    fig, ax = plt.subplots(figsize=_get_figsize(pd, "line", (9, 5)))
    ax.plot(s.index, s.values)

    ax.set_title("Evolució anual d'hores reservades")
    ax.set_xlabel("Mes")
    ax.set_ylabel("Hores")

    if bool(pd.get("grid", True)):
        ax.grid(True, alpha=float(pd.get("grid_alpha", 0.3)))

    plt.tight_layout()
    plt.savefig(out_png, dpi=_get_dpi(pd, 150))
    plt.close(fig)
    return True


def analyze_reserves(
    df_raw: pd.DataFrame,
    *,
    plots_dir_abs: str,
    year: Optional[int] = None,
    plot_defaults: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """
    Retorna:
      - kpis (dict)
      - warnings (list[str])
      - plot_paths_abs (list[str])  # ABSOLUTS; l'orquestrador els convertirà a relatius
    """
    warnings: List[str] = []
    plot_items_abs: List[Dict[str, Any]] = []


    # normalitza columnes
    df_raw = df_raw.copy()
    df_raw.columns = [str(c).strip() for c in df_raw.columns]

    # Filtra files: exclou Anónimas/PEIXERA/Importe=0 (Importe pot no ser numèric)
    if all(col in df_raw.columns for col in ["NombreCompleto", "Recurso", "Importe"]):
        importe_num = pd.to_numeric(df_raw["Importe"], errors="coerce")
        mask = ~((df_raw["NombreCompleto"] == "Anónimas") & (df_raw["Recurso"] == "PEIXERA") & (importe_num == 0))
        df_raw = df_raw[mask]

    # selecciona només les columnes que vols (si existeixen)
    cols = [c for c in WANTED_COLS if c in df_raw.columns]
    df = df_raw[cols].copy()

    # Normalitza la columna 'Recurso' per tractar variants com el mateix esport
    if "Recurso" in df.columns:
        def _normalize_recurso(val):
            v = str(val).strip().upper()
            if v.startswith("ATLETISME"):
                return "ATLETISME"
            if v.startswith("GESPA"):
                return "GESPA"
            return v
        df["Recurso"] = df["Recurso"].map(_normalize_recurso)

    # columna categoria (sense títol)
    cat_col = _find_category_col(df_raw)
    if cat_col is not None:
        df["categoria"] = df_raw[cat_col].map(_normalize_categoria)
        if "NombreCompleto" in df.columns:
            # propaga cap avall quan torna a aparèixer el mateix nom
            df["categoria"] = df.groupby("NombreCompleto")["categoria"].ffill()
    else:
        df["categoria"] = pd.NA

    # conversions flexibles
    if "DuracionHoras" in df.columns:
        df["DuracionHoras"] = _to_float_hours(df["DuracionHoras"])
    else:
        warnings.append("Falta columna 'DuracionHoras' (obligatòria per fer els gràfics).")

    if "FechaReserva" in df.columns:
        df["FechaReserva"] = pd.to_datetime(df["FechaReserva"], errors="coerce", dayfirst=True)
    else:
        warnings.append("Falta columna 'FechaReserva' (obligatòria per fer l'evolució anual).")

    if "Recurso" not in df.columns:
        warnings.append("Falta columna 'Recurso' (obligatòria per fer el pastís per espai).")

    # filtre per any (opcional)
    if year is not None and "FechaReserva" in df.columns:
        df = df[df["FechaReserva"].dt.year == year]

    # KPIs mínims
    kpis: Dict[str, Any] = {}
    d_hours = df.dropna(subset=["DuracionHoras"])
    kpis["reserves_total_registres"] = int(len(df))
    kpis["reserves_total_hores"] = float(d_hours["DuracionHoras"].fillna(0).sum()) if "DuracionHoras" in df.columns else 0.0

    # Comptatge de categories úniques (client i entitat conjuntament)
    if "categoria" in df.columns:
        # Considera només files amb categoria vàlida
        cat_valid = df["categoria"].dropna()
        kpis["reserves_total_categories_uniques"] = int(cat_valid.nunique())
        kpis["reserves_categories_uniques"] = sorted(cat_valid.unique())

    if "categoria" in df.columns and "NombreCompleto" in df.columns:
        noms = df["NombreCompleto"].astype(str).str.strip()
        nom_valid = noms.ne("") & noms.str.upper().ne("NAN")
        entitats = noms[(df["categoria"] == "entitat") & nom_valid]
        clients = noms[(df["categoria"] == "client") & nom_valid]
        kpis["reserves_total_entitats_uniques"] = int(entitats.nunique())
        kpis["reserves_total_clients_uniques"] = int(clients.nunique())

    if "Deporte" in df.columns:
        esport_valid = df["Deporte"].dropna().astype(str).str.strip()
        esport_valid = esport_valid[esport_valid != ""]
        kpis["reserves_total_esports_uniques"] = int(esport_valid.nunique())
        kpis["reserves_esports_uniques"] = sorted(esport_valid.unique())

    # Distribució d'hores i registres per espai
    if "Recurso" in df.columns and "DuracionHoras" in df.columns:
        d_space = df.dropna(subset=["Recurso", "DuracionHoras"]).copy()
        if not d_space.empty:
            hores_per_espai = d_space.groupby("Recurso")["DuracionHoras"].sum().sort_values(ascending=False)
            registres_per_espai = d_space.groupby("Recurso").size().sort_values(ascending=False)
            total_hores_espais = float(hores_per_espai.sum())

            kpis["reserves_total_espais_uniques"] = int(hores_per_espai.index.nunique())
            kpis["reserves_hores_per_espai"] = {
                str(espai): float(hores) for espai, hores in hores_per_espai.items()
            }
            kpis["reserves_registres_per_espai"] = {
                str(espai): int(registres) for espai, registres in registres_per_espai.items()
            }

            if total_hores_espais > 0:
                kpis["reserves_percentatge_hores_per_espai"] = {
                    str(espai): float((hores / total_hores_espais) * 100.0)
                    for espai, hores in hores_per_espai.items()
                }
            else:
                kpis["reserves_percentatge_hores_per_espai"] = {
                    str(espai): 0.0 for espai in hores_per_espai.index
                }

    # Evolució d'hores reservades per mes
    if "FechaReserva" in df.columns and "DuracionHoras" in df.columns:
        d_month = df.dropna(subset=["FechaReserva", "DuracionHoras"]).copy()
        if not d_month.empty:
            serie_mensual = d_month.set_index("FechaReserva")["DuracionHoras"].resample("MS").sum().sort_index()

            if year is not None:
                first_month = pd.Timestamp(year=year, month=1, day=1)
                months_index = pd.date_range(start=first_month, periods=12, freq="MS")
                serie_mensual = serie_mensual.reindex(months_index, fill_value=0.0)

            kpis["reserves_hores_serie_mensual"] = {
                str(idx.strftime("%Y-%m")): float(v) for idx, v in serie_mensual.items()
            }

            vals_mensuals = serie_mensual.astype(float).tolist()
            if vals_mensuals:
                kpis["reserves_hores_mitjana_mensual"] = float(np.mean(vals_mensuals))
                kpis["reserves_hores_maxim_mensual"] = float(np.max(vals_mensuals))
                kpis["reserves_hores_minim_mensual"] = float(np.min(vals_mensuals))
                kpis["reserves_hores_mes_maxim"] = str(serie_mensual.idxmax().strftime("%Y-%m"))
                kpis["reserves_hores_mes_minim"] = str(serie_mensual.idxmin().strftime("%Y-%m"))
                if len(vals_mensuals) >= 2:
                    kpis["reserves_hores_variacio_primer_ultim_mes"] = float(
                        vals_mensuals[-1] - vals_mensuals[0]
                    )


    # Generació de plots (ignora nulls per col objectiu)
    os.makedirs(plots_dir_abs, exist_ok=True)

    pie_abs = os.path.join(plots_dir_abs, "reserves_pie_hores_per_espai.png")
    if _plot_pie_hours_by_recurso(df, pie_abs, plot_defaults=plot_defaults):
        plot_items_abs.append({
        "key": "reserves.hores_per_espai",
        "kind": "pie",
        "title": "Percentatge d'hores reservades per espai",
        "file_abs": pie_abs,
        "params": {},
    })
        
    else:
        warnings.append("No s'ha pogut generar el pastís (dades insuficients o nulls).")

    line_abs = os.path.join(plots_dir_abs, "reserves_evolucio_hores.png")
    if _plot_year_evolution(df, line_abs, plot_defaults=plot_defaults):
        plot_items_abs.append({
        "key": "reserves.evolucio_hores",
        "kind": "line",
        "title": "Evolució anual d'hores reservades",
        "file_abs": line_abs,
        "params": {},
    })

    else:
        warnings.append("No s'ha pogut generar l'evolució anual (dades insuficients o nulls).")

    return kpis, warnings, plot_items_abs
