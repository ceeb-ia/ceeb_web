"""Validation table builders for the legacy pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from calendaritzacions.analysis.indicators import _with_metric_descriptions


@dataclass
class ValidationTables:
    count_summary: pd.DataFrame
    count_by_category: pd.DataFrame
    entity_conflicts: pd.DataFrame
    level_spread: pd.DataFrame


def empty_validation_tables() -> ValidationTables:
    return ValidationTables(
        count_summary=pd.DataFrame(),
        count_by_category=pd.DataFrame(),
        entity_conflicts=pd.DataFrame(columns=["Categoria", "Grup", "Entitat", "Count"]),
        level_spread=pd.DataFrame(columns=["Categoria", "Grup", "Nivells", "Min", "Max", "Dif"]),
    )


def build_validation_tables(input_df: pd.DataFrame, metrics_pack: dict[str, pd.DataFrame]) -> ValidationTables:
    """Build legacy validation tables from input and indicator tables."""
    tables = empty_validation_tables()
    analysis = metrics_pack.get("analysis", pd.DataFrame())

    input_total = len(input_df)
    assigned_total = len(analysis)
    status = "OK" if input_total == assigned_total else "KO"
    tables.count_summary = pd.DataFrame(
        [
            {"Metrica": "Equips esperats (input)", "Valor": input_total},
            {"Metrica": "Equips assignats (sense dummies)", "Valor": assigned_total},
            {"Metrica": "Estat", "Valor": status},
        ]
    )
    tables.count_summary = _with_metric_descriptions(tables.count_summary)

    per_cat_in = input_df.groupby("Nom Lliga").size().rename("Esperats").to_frame()
    per_cat_assigned = analysis.groupby("Categoria").size().rename("Assignats").to_frame()
    tables.count_by_category = (
        per_cat_in.join(per_cat_assigned, how="outer")
        .fillna(0)
        .reset_index()
        .rename(columns={"Nom Lliga": "Categoria"})
    )
    tables.count_by_category["Esperats"] = tables.count_by_category["Esperats"].astype(int)
    tables.count_by_category["Assignats"] = tables.count_by_category["Assignats"].astype(int)
    tables.count_by_category["OK"] = (
        tables.count_by_category["Esperats"] == tables.count_by_category["Assignats"]
    )

    conflict_rows = []
    for cat, df_cat_res in analysis.groupby("Categoria"):
        for grup, df_grup in df_cat_res.groupby("Grup"):
            entities = [e for e in df_grup["Entitat"].tolist() if e and e != "Descans"]
            if not entities:
                continue
            counts = pd.Series(entities).value_counts()
            for entitat, count in counts.items():
                if count > 1:
                    conflict_rows.append(
                        {"Categoria": cat, "Grup": grup, "Entitat": entitat, "Count": int(count)}
                    )
    if conflict_rows:
        tables.entity_conflicts = pd.DataFrame(conflict_rows)

    levels_group = metrics_pack.get("levels_group", pd.DataFrame())
    if not levels_group.empty:
        spread_rows = []
        for _, row in levels_group.iterrows():
            if int(row["Rang nivell"]) >= 3:
                spread_rows.append(
                    {
                        "Categoria": row["Categoria"],
                        "Grup": row["Grup"],
                        "Nivells": row["Nivells presents"],
                        "Min": row["Min nivell"],
                        "Max": row["Max nivell"],
                        "Dif": int(row["Rang nivell"]),
                    }
                )
        if spread_rows:
            tables.level_spread = pd.DataFrame(spread_rows)

    return tables


__all__ = ["ValidationTables", "build_validation_tables", "empty_validation_tables"]
