"""Category-level orchestration for the legacy engine."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from assignacions import assignar_grups_hungares
from calendaritzacions.application.progress import NoopProgressReporter, ProgressReporter


def run_legacy_categories(
    df: pd.DataFrame,
    *,
    fase,
    equip_to_num_sorteig: dict[Any, int],
    segona_fase_bool: bool = False,
    progress: ProgressReporter | None = None,
) -> tuple[list[pd.DataFrame], list[dict[str, Any]], dict[str, float]]:
    """Run the legacy assignment engine for every category in the prepared input."""
    progress = progress or NoopProgressReporter()
    entity_costs: dict[str, float] = {}
    resultats_totals: list[pd.DataFrame] = []
    info_totals: list[dict[str, Any]] = []

    categories = sorted(df["Nom Lliga"].dropna().unique())
    total_categories = len(categories)
    for num_cat, categoria in enumerate(categories):
        df_cat = df[df["Nom Lliga"] == categoria].copy()
        print(f"Processant categoria '{categoria}' amb {len(df_cat)} equips...")

        prog = 50 + (num_cat + 1) * 40 // total_categories if total_categories else 90
        progress.report(f"Processant categoria '{categoria}' amb {len(df_cat)} equips...", prog)
        if df_cat.empty:
            continue

        try:
            res_df, entity_costs, info = assignar_grups_hungares(
                df_cat,
                max_grup=8,
                min_grup=6,
                entity_costs=entity_costs,
                equips_to_num_sorteig=equip_to_num_sorteig.copy(),
                fase=fase,
                weights={"w_dif_sorteig": np.log2(27)},
                segona_fase_bool=segona_fase_bool,
            )
        except ValueError as exc:
            print(f"[{categoria}] ERROR d'assignació: {exc}")
            continue

        pos_col = next(
            (col for col in ["Posició Classificació Num", "PosiciÃ³ ClassificaciÃ³ Num"] if col in df.columns),
            None,
        )
        if segona_fase_bool and pos_col:
            pos_map = df[df["Nom Lliga"] == categoria].set_index("Id")[pos_col].to_dict()
            res_df = res_df.copy()
            if "Id" in res_df.columns:
                res_df[pos_col] = res_df["Id"].map(pos_map).fillna("")
            else:
                res_df[pos_col] = ""

        resultats_totals.append(res_df.assign(_Categoria=categoria))
        info_totals.append({"categoria": categoria, **info})

    return resultats_totals, info_totals, entity_costs


__all__ = ["run_legacy_categories"]
