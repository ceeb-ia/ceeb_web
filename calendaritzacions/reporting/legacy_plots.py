"""Final plot generation for legacy calendarization runs."""

from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


def write_legacy_final_plots(
    output_dir: str | Path,
    *,
    metrics_pack: dict[str, pd.DataFrame],
    stem: str = "legacy",
    fmt: str = "png",
    dpi: int = 160,
) -> dict[str, str]:
    """Write final legacy plots and return a plot-id to path mapping."""

    import matplotlib

    matplotlib.use("Agg")

    import matplotlib.pyplot as plt

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    plots: dict[str, str] = {}
    plot_specs = [
        ("status_summary", _plot_status_summary(metrics_pack)),
        ("legacy_damage_by_modality", _plot_damage_by_modality(metrics_pack)),
        ("legacy_damage_by_entity", _plot_damage_by_entity(metrics_pack)),
        ("assigned_numbers_by_modality", _plot_assigned_numbers_by_modality(metrics_pack)),
        ("level_dispersion_by_modality", _plot_level_dispersion_by_modality(metrics_pack)),
        ("legacy_group_sizes", _plot_group_sizes(metrics_pack)),
    ]

    for plot_id, fig in plot_specs:
        if fig is None:
            continue
        file_path = output_path / f"{stem}_{plot_id}.{fmt}"
        fig.savefig(file_path, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        plots[plot_id] = str(file_path)

    manifest_path = output_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "artifact_type": "legacy_final_plots",
                "plots": plots,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    plots["manifest"] = str(manifest_path)
    return plots


def _plot_status_summary(metrics_pack: dict[str, pd.DataFrame]) -> Any | None:
    import matplotlib.pyplot as plt

    kpis = _metric_values(metrics_pack.get("kpi_global", pd.DataFrame()))
    metrics = {
        "Equips": int(kpis.get("Equips totals input", 0) or 0),
        "Assignats": int(kpis.get("Equips reals assignats", 0) or 0),
        "Peticions": int(kpis.get("Equips amb peticio efectiva", 0) or 0),
        "Incidencies": int(kpis.get("Incidencia total", 0) or 0),
        "Jornades afectades": int(kpis.get("Severitat total (jornades)", 0) or 0),
    }
    if not any(metrics.values()):
        return None

    fig, ax = plt.subplots(figsize=(9, 4.8))
    colors = ["#4E79A7", "#59A14F", "#76B7B2", "#E15759", "#F28E2B"]
    ax.bar(metrics.keys(), metrics.values(), color=colors[: len(metrics)])
    ax.set_title("Resum final legacy")
    ax.set_ylabel("Valor")
    ax.tick_params(axis="x", rotation=25)
    return fig


def _plot_damage_by_modality(metrics_pack: dict[str, pd.DataFrame]) -> Any | None:
    rows = metrics_pack.get("by_modalitat", pd.DataFrame())
    if rows is None or rows.empty or "Dany total" not in rows.columns:
        return None
    rows = rows.copy()
    rows["Dany total"] = pd.to_numeric(rows["Dany total"], errors="coerce").fillna(0)
    rows = rows[rows["Dany total"] > 0].sort_values("Dany total", ascending=False).head(20)
    if rows.empty:
        return None
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, max(5, 0.36 * len(rows))))
    ax.barh(rows["Modalitat"].astype(str), rows["Dany total"], color="#E15759")
    ax.invert_yaxis()
    ax.set_title("Jornades afectades per modalitat")
    ax.set_xlabel("Jornades afectades")
    return fig


def _plot_damage_by_entity(metrics_pack: dict[str, pd.DataFrame]) -> Any | None:
    rows = metrics_pack.get("entitats", pd.DataFrame())
    if rows is None or rows.empty or "Dany total" not in rows.columns:
        return None
    rows = rows.copy()
    rows["Dany total"] = pd.to_numeric(rows["Dany total"], errors="coerce").fillna(0)
    rows = rows[rows["Dany total"] > 0].sort_values("Dany total", ascending=False).head(25)
    if rows.empty:
        return None
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, max(5, 0.34 * len(rows))))
    ax.barh(rows["Entitat"].astype(str), rows["Dany total"], color="#F28E2B")
    ax.invert_yaxis()
    ax.set_title("Top entitats per dany de jornades")
    ax.set_xlabel("Jornades afectades")
    return fig


def _plot_assigned_numbers_by_modality(metrics_pack: dict[str, pd.DataFrame]) -> Any | None:
    analysis = metrics_pack.get("analysis", pd.DataFrame())
    if analysis is None or analysis.empty or "assigned_seed" not in analysis.columns:
        return None
    import matplotlib.pyplot as plt

    counts: Counter[tuple[str, int]] = Counter()
    totals: Counter[str] = Counter()
    for _, row in analysis.iterrows():
        number = _int_or_none(row.get("assigned_seed"))
        if number is None:
            continue
        modality = str(row.get("Modalitat") or "Sense modalitat")
        counts[(modality, number)] += 1
        totals[modality] += 1

    modalities = [modality for modality, _total in totals.most_common(12)]
    if not modalities:
        return None

    cols = min(3, len(modalities))
    rows_count = math.ceil(len(modalities) / cols)
    fig, axes = plt.subplots(rows_count, cols, figsize=(4.6 * cols, 3.8 * rows_count))
    try:
        axes = axes.flatten()
    except AttributeError:
        axes = [axes]

    palette = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", "#EDC948", "#B07AA1", "#FF9DA7"]
    for ax, modality in zip(axes, modalities):
        labels = []
        values = []
        for number in range(1, 9):
            value = counts.get((modality, number), 0)
            if value:
                labels.append(str(number))
                values.append(value)
        if not values:
            ax.axis("off")
            continue
        ax.pie(values, labels=labels, autopct="%1.0f%%", startangle=90, colors=palette[: len(values)], textprops={"fontsize": 8})
        ax.set_title(str(modality), fontsize=10)
    for ax in axes[len(modalities):]:
        ax.axis("off")
    fig.suptitle("Assignacio final de numeros per modalitat", fontsize=13)
    fig.tight_layout()
    return fig


def _plot_level_dispersion_by_modality(metrics_pack: dict[str, pd.DataFrame]) -> Any | None:
    rows = metrics_pack.get("levels_modalitat", pd.DataFrame())
    if rows is None or rows.empty or "Rang mitja" not in rows.columns:
        return None
    rows = rows.copy()
    rows["Rang mitja"] = pd.to_numeric(rows["Rang mitja"], errors="coerce").fillna(0)
    rows = rows.sort_values("Rang mitja", ascending=False).head(20)
    if rows.empty:
        return None
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, max(5, 0.36 * len(rows))))
    ax.barh(rows["Modalitat"].astype(str), rows["Rang mitja"], color="#76B7B2")
    ax.invert_yaxis()
    ax.set_title("Dispersio de nivells per modalitat")
    ax.set_xlabel("Rang mitja de nivell")
    return fig


def _plot_group_sizes(metrics_pack: dict[str, pd.DataFrame]) -> Any | None:
    analysis = metrics_pack.get("analysis", pd.DataFrame())
    if analysis is None or analysis.empty or "Grup" not in analysis.columns:
        return None
    grouped = analysis.groupby("Grup").size().sort_index()
    if grouped.empty:
        return None
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(max(7, 0.45 * len(grouped)), 4.8))
    ax.bar([str(index) for index in grouped.index], grouped.values, color="#4E79A7", label="Equips")
    ax.set_title("Mida dels grups legacy")
    ax.set_xlabel("Grup")
    ax.set_ylabel("Equips")
    ax.set_ylim(0, max(8, int(grouped.max())))
    ax.tick_params(axis="x", rotation=45)
    return fig


def _metric_values(frame: pd.DataFrame) -> dict[str, Any]:
    if frame is None or frame.empty or "Metrica" not in frame.columns or "Valor" not in frame.columns:
        return {}
    return {str(row["Metrica"]): row["Valor"] for _, row in frame.iterrows()}


def _int_or_none(value: Any) -> int | None:
    try:
        if pd.isna(value):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


__all__ = ["write_legacy_final_plots"]
