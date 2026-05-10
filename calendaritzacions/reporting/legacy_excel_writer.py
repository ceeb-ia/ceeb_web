"""Legacy workbook writer extracted from the application pipeline."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

import pandas as pd

from calendaritzacions.reporting.excel_writer import (
    _auto_fit_worksheet_columns,
    _col_letter,
    _format_diffs_excel,
    _write_df_block,
)


def _write_simple_df_sheet(writer, workbook, sheet_name: str, df: pd.DataFrame, fmt_header) -> None:
    df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=0)
    ws = writer.sheets[sheet_name]
    for col_idx, col_name in enumerate(df.columns):
        ws.write(0, col_idx, col_name, fmt_header)
    _auto_fit_worksheet_columns(ws, df, min_width=12, max_width=40, extra_width=5)
    ws.autofilter(0, 0, max(0, len(df)), max(0, len(df.columns) - 1))
    ws.freeze_panes(1, 0)


def _unique_limited_sheet_name(base: str, used_sheet_names: set[str], max_len: int = 31) -> str:
    sheet_name = base[:max_len]
    if sheet_name not in used_sheet_names:
        return sheet_name

    i = 2
    while True:
        suffix = f"_{i}"
        candidate = base[: max_len - len(suffix)] + suffix
        if candidate not in used_sheet_names:
            return candidate
        i += 1


def _legacy_category_sheet_name(categoria: Any, used_sheet_names: set[str]) -> str:
    base = "".join(c for c in str(categoria) if c.isalnum() or c in "._- ").strip().replace(" ", "_")
    return _unique_limited_sheet_name(base or "Categoria", used_sheet_names)


def _convertir_dummy_a_descans(row):
    if pd.isna(row.get("Nom")) or str(row.get("Nom")).strip() == "":
        return row
    if str(row.get("Entitat", "")).strip() != "Descans":
        return row

    row_copy = row.copy()
    row_copy["Nom"] = "DESCANS"
    row_copy["Entitat"] = "—"
    row_copy["Nivell"] = "—"
    row_copy["Dia partit"] = "—"
    for col in ["Núm. sorteig", "Modalitat", "Categoria", "Subcategoria", "Horari partit", "Observacions"]:
        if col in row_copy:
            row_copy[col] = "—"
    if "Diferències jornades" in row_copy:
        row_copy["Diferències jornades"] = "—"
    return row_copy


def _build_incidents_df(metrics_pack: dict[str, pd.DataFrame], df_val_level_spread: pd.DataFrame) -> pd.DataFrame:
    request_incidents = metrics_pack.get("request_incidents", pd.DataFrame()).copy()
    if not request_incidents.empty and "Diferències jornades" in request_incidents.columns:
        request_incidents["Diferències jornades"] = request_incidents["Diferències jornades"].apply(_format_diffs_excel)

    level_incidents = pd.DataFrame()
    if not df_val_level_spread.empty:
        level_incidents = df_val_level_spread.copy()
        level_incidents["Entitat"] = "— Grup amb nivells dispars —"
        level_incidents["Modalitat"] = ""
        level_incidents["Equip"] = ""
        level_incidents["Tipus peticio"] = "nivells"
        level_incidents["Esperat"] = ""
        level_incidents["Assignat"] = ""
        level_incidents["Mismatch jornades"] = 0
        level_incidents["Diferències jornades"] = level_incidents.apply(
            lambda r: f"Nivells: {r['Nivells']} | Min: {r['Min']} | Max: {r['Max']} | Dif: {r['Dif']}",
            axis=1,
        )
        level_incidents = level_incidents[
            [
                "Entitat",
                "Modalitat",
                "Categoria",
                "Grup",
                "Equip",
                "Tipus peticio",
                "Esperat",
                "Assignat",
                "Mismatch jornades",
                "Diferències jornades",
            ]
        ]

    if request_incidents.empty and level_incidents.empty:
        return pd.DataFrame()

    df_incidents = pd.concat([request_incidents, level_incidents], ignore_index=True)
    return df_incidents.sort_values(["Entitat", "Categoria", "Equip"]).reset_index(drop=True)


def write_legacy_workbook(
    excel_path: str,
    *,
    resultats_totals: Sequence[pd.DataFrame],
    info_totals: Sequence[dict[str, Any]],
    metrics_pack: dict[str, pd.DataFrame],
    df_val_count_summary: pd.DataFrame,
    df_val_entity_conflicts: pd.DataFrame,
    df_val_level_spread: pd.DataFrame,
    segona_fase_bool: bool = False,
    missing_classifications: Sequence[dict[str, Any]] | None = None,
    unused_classification_teams: Sequence[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """Write the legacy formatted workbook and return the incidents table."""
    missing_classifications = missing_classifications or []
    unused_classification_teams = unused_classification_teams or []
    df_incidents = pd.DataFrame()

    with pd.ExcelWriter(excel_path, engine="xlsxwriter") as writer:
        workbook = writer.book

        fmt_header = workbook.add_format(
            {
                "bold": True,
                "align": "center",
                "valign": "vcenter",
                "bg_color": "#1F4E78",
                "font_color": "white",
                "border": 1,
            }
        )
        fmt_title = workbook.add_format({"bold": True, "font_size": 14, "align": "left", "valign": "vcenter"})
        fmt_default = workbook.add_format({"text_wrap": True, "border": 1})
        fmt_wrap = workbook.add_format({"text_wrap": True, "border": 1})
        fmt_group_colors = {
            1: workbook.add_format({"bg_color": "#E2EFDA"}),
            2: workbook.add_format({"bg_color": "#FFF2CC"}),
            3: workbook.add_format({"bg_color": "#FCE4D6"}),
            4: workbook.add_format({"bg_color": "#E7E6E6"}),
            5: workbook.add_format({"bg_color": "#DDEBF7"}),
            6: workbook.add_format({"bg_color": "#E2EFDA"}),
            7: workbook.add_format({"bg_color": "#FFF2CC"}),
            8: workbook.add_format({"bg_color": "#FCE4D6"}),
            9: workbook.add_format({"bg_color": "#E7E6E6"}),
            10: workbook.add_format({"bg_color": "#DDEBF7"}),
            11: workbook.add_format({"bg_color": "#E2EFDA"}),
            12: workbook.add_format({"bg_color": "#FFF2CC"}),
            13: workbook.add_format({"bg_color": "#FCE4D6"}),
            14: workbook.add_format({"bg_color": "#E7E6E6"}),
            15: workbook.add_format({"bg_color": "#DDEBF7"}),
        }

        used_sheet_names: set[str] = set()
        df_info = pd.DataFrame(info_totals).drop(columns=["fairness"], errors="ignore") if info_totals else pd.DataFrame()

        used_sheet_names.add("Resum")
        writer.sheets["Resum"] = workbook.add_worksheet("Resum")
        ws_info = writer.sheets["Resum"]
        start_row = 0
        start_row = _write_df_block(
            writer,
            workbook,
            "Resum",
            start_row,
            "KPI Global",
            metrics_pack.get("kpi_global", df_val_count_summary),
            fmt_title,
            fmt_header,
        )
        start_row = _write_df_block(
            writer,
            workbook,
            "Resum",
            start_row,
            "Incidencia per modalitat",
            metrics_pack.get("summary_modalitat", pd.DataFrame()),
            fmt_title,
            fmt_header,
        )
        top_entities = metrics_pack.get("top_entities", pd.DataFrame())
        start_row = _write_df_block(
            writer,
            workbook,
            "Resum",
            start_row,
            "Top entitats per magnitud",
            top_entities[
                [
                    "Entitat",
                    "Equips totals",
                    "Equips amb peticio efectiva",
                    "Incidencia absoluta",
                    "Incidencia %",
                    "Severitat total",
                ]
            ]
            if top_entities is not None and not top_entities.empty
            else pd.DataFrame(),
            fmt_title,
            fmt_header,
            wrap_cols=["Entitat"],
        )
        resum_info = (
            df_info[
                [
                    col
                    for col in [
                        "categoria",
                        "num_grups",
                        "repartiment",
                        "num_equips_reals",
                        "num_dummies",
                        "dummy_ratio",
                        "num_conflictes_finals",
                    ]
                    if col in df_info.columns
                ]
            ]
            if not df_info.empty
            else pd.DataFrame()
        )
        start_row = _write_df_block(
            writer, workbook, "Resum", start_row, "Resum per categoria", resum_info, fmt_title, fmt_header, wrap_cols=["repartiment"]
        )
        _write_df_block(writer, workbook, "Resum", start_row, "Conflictes d'entitat", df_val_entity_conflicts, fmt_title, fmt_header)
        ws_info.freeze_panes(2, 0)

        used_sheet_names.add("Indicadors")
        writer.sheets["Indicadors"] = workbook.add_worksheet("Indicadors")
        start_row = 0
        for title, df_block, wrap_cols in [
            ("KPI Global", metrics_pack.get("kpi_global", pd.DataFrame()), None),
            ("Distribucio global de numeros", metrics_pack.get("global_numbers", pd.DataFrame()), None),
            ("Distribucio per modalitat", metrics_pack.get("by_modalitat", pd.DataFrame()), None),
            ("Distribucio per categoria", metrics_pack.get("by_categoria", pd.DataFrame()), ["Categoria"]),
            ("Duples CASA/FORA", metrics_pack.get("duples", pd.DataFrame()), None),
            ("Compliment CASA/FORA", metrics_pack.get("casa_fora_summary", pd.DataFrame()), None),
            ("Dany global", metrics_pack.get("damage_summary", pd.DataFrame()), None),
            ("Fairness resum", metrics_pack.get("fairness_summary", pd.DataFrame()), None),
            ("Fairness per entitat", metrics_pack.get("fairness_entities", pd.DataFrame()), ["Entitat"]),
            ("Info solver per categoria", df_info, ["repartiment", "conflictes_entitat"]),
        ]:
            start_row = _write_df_block(writer, workbook, "Indicadors", start_row, title, df_block, fmt_title, fmt_header, wrap_cols=wrap_cols)

        used_sheet_names.add("Entitats")
        writer.sheets["Entitats"] = workbook.add_worksheet("Entitats")
        _write_df_block(
            writer,
            workbook,
            "Entitats",
            0,
            "Magnitud i incidencia per entitat",
            metrics_pack.get("entitats", pd.DataFrame()),
            fmt_title,
            fmt_header,
            wrap_cols=["Entitat", "Modalitats", "Categories"],
        )

        used_sheet_names.add("Nivells")
        writer.sheets["Nivells"] = workbook.add_worksheet("Nivells")
        start_row = 0
        start_row = _write_df_block(
            writer, workbook, "Nivells", start_row, "Resum per modalitat", metrics_pack.get("levels_modalitat", pd.DataFrame()), fmt_title, fmt_header
        )
        start_row = _write_df_block(
            writer,
            workbook,
            "Nivells",
            start_row,
            "Resum per categoria",
            metrics_pack.get("levels_category", pd.DataFrame()),
            fmt_title,
            fmt_header,
            wrap_cols=["Categoria"],
        )
        _write_df_block(
            writer,
            workbook,
            "Nivells",
            start_row,
            "Detall per grup",
            metrics_pack.get("levels_group", pd.DataFrame()),
            fmt_title,
            fmt_header,
            wrap_cols=["Categoria", "Nivells presents"],
        )

        df_incidents = _build_incidents_df(metrics_pack, df_val_level_spread)
        used_sheet_names.add("Incidències")
        writer.sheets["Incidències"] = workbook.add_worksheet("Incidències")
        _write_df_block(
            writer,
            workbook,
            "Incidències",
            0,
            "Detall d'incidencies",
            df_incidents,
            fmt_title,
            fmt_header,
            wrap_cols=["Entitat", "Categoria", "Equip", "Diferències jornades"],
        )

        if segona_fase_bool and missing_classifications:
            try:
                df_missing = pd.DataFrame(missing_classifications)
                df_missing.sort_values(["Modalitat", "Categoria", "Subcategoria", "Nom"], inplace=True)
                sheet_missing = "Equips No Classificats"
                k = 1
                while sheet_missing in writer.sheets:
                    sheet_missing = f"Equips No Classificats_{k}"
                    k += 1
                _write_simple_df_sheet(writer, workbook, sheet_missing, df_missing, fmt_header)
            except Exception:
                pass

        try:
            if len(unused_classification_teams) > 0:
                df_unused = pd.DataFrame(unused_classification_teams)
                df_unused.sort_values(["Modalitat", "Categoria", "Subcategoria", "Nom"], inplace=True)
                sheet_unused = _unique_limited_sheet_name("Equips Classificació No Utilitzats", set(writer.sheets))
                _write_simple_df_sheet(writer, workbook, sheet_unused, df_unused, fmt_header)
        except Exception as exc:
            print("Error escrivint equips de classificació no utilitzats.", str(exc))

        for res_df_cat in resultats_totals:
            categoria = res_df_cat["_Categoria"].iloc[0] if "_Categoria" in res_df_cat.columns else "Categoria"
            sheet_name = _legacy_category_sheet_name(categoria, used_sheet_names)
            used_sheet_names.add(sheet_name)

            df = res_df_cat.drop(columns=[c for c in ["_Categoria"] if c in res_df_cat.columns] + ["Id"]).copy()
            df = df.apply(_convertir_dummy_a_descans, axis=1)

            if "Diferències jornades" in df.columns:
                df["Diferències jornades"] = df["Diferències jornades"].apply(_format_diffs_excel)
            if "Grup" in df.columns and "Núm. sorteig assignat" in df.columns:
                df.sort_values(["Grup", "Núm. sorteig assignat"], inplace=True, kind="stable")
            elif "Grup" in df.columns:
                df.sort_values(["Grup"], inplace=True, kind="stable")

            start_row = 1
            df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=start_row)
            ws = writer.sheets[sheet_name]
            n_rows, n_cols = df.shape
            ws.merge_range(0, 0, 0, max(0, n_cols - 1), f"Assignació – {categoria}", fmt_title)

            for col_idx, col_name in enumerate(df.columns):
                ws.write(start_row, col_idx, col_name, fmt_header)

            for col_idx, col_name in enumerate(df.columns):
                max_len = max([len(str(col_name))] + [len(str(x)) for x in df[col_name].astype(str).fillna("")])
                width = min(max(max_len + 2, 10), 50)
                if col_name == "Nom":
                    width = 35
                elif col_name == "Entitat":
                    width = 25
                elif col_name == "Nom Lliga":
                    width = 25
                elif col_name == "Diferències jornades":
                    width = 45
                elif col_name in ["Observacions", "Horari partit"]:
                    width = 30
                elif col_name in ["Nivell", "Grup", "Núm. sorteig", "Núm. sorteig assignat"]:
                    width = 12
                elif col_name == "Dia partit":
                    width = 15

                ws.set_column(col_idx, col_idx, width)

            ws.freeze_panes(start_row + 1, 0)
            ws.autofilter(start_row, 0, start_row + max(0, n_rows), max(0, n_cols - 1))

            if "Diferències jornades" in df.columns:
                diffs_col_idx = df.columns.get_loc("Diferències jornades")
                ws.set_column(diffs_col_idx, diffs_col_idx, 40, fmt_wrap)

            if n_rows > 0 and "Grup" in df.columns:
                grup_col_idx = df.columns.get_loc("Grup")
                col_letter = _col_letter(grup_col_idx)
                for g in sorted(df["Grup"].dropna().astype(str).unique()):
                    g_str = str(g).strip()
                    match = re.search(r"(\d+)$", g_str)
                    g_num = int(match.group(1)) if match else None
                    fmt = fmt_group_colors.get(g_num)
                    if not fmt:
                        continue
                    first_data_row = start_row + 1
                    last_data_row = start_row + n_rows
                    ws.conditional_format(
                        first_data_row,
                        0,
                        last_data_row,
                        max(0, n_cols - 1),
                        {
                            "type": "formula",
                            "criteria": f'=${col_letter}{first_data_row + 1}="{g_str}"',
                            "format": fmt,
                        },
                    )

            for row_idx in range(start_row + 1, start_row + 1 + n_rows):
                ws.set_row(row_idx, None, fmt_default)

    return df_incidents
