"""KPI payload construction helpers."""

from __future__ import annotations

from typing import Any

import pandas as pd

from calendaritzacions.analysis.indicators import _df_records, _json_default
from calendaritzacions.reporting.excel_writer import _format_diffs_excel

json_default = _json_default


def _build_analysis_export(metrics_pack: dict[str, Any]) -> pd.DataFrame:
    analysis_export = pd.DataFrame()
    analysis_df = metrics_pack.get("analysis", pd.DataFrame())
    if not analysis_df.empty:
        analysis_export = analysis_df.copy()
        diffs_col = next((col for col in analysis_export.columns if "Difer" in str(col) and "jornad" in str(col)), None)
        if diffs_col and diffs_col in analysis_export.columns:
            analysis_export[diffs_col] = analysis_export[diffs_col].apply(_format_diffs_excel)
        export_cols = [
            "Id",
            "Entitat",
            "Modalitat",
            "Categoria",
            "Subcategoria",
            "Grup",
            "Nom",
            "Nivell",
            "Dia partit",
            "Pista joc",
            "Horari partit",
            "req_type",
            "request_code",
            "expected_seed",
            "assigned_seed",
            "is_effective_request",
            "is_mismatch",
            "mismatch_jornades",
            "is_textual_request",
            "casa_fora_respected",
            "dupla_label",
            "numero_casa",
            "numero_fora",
        ]
        if diffs_col:
            export_cols.append(diffs_col)
        export_cols = [col for col in export_cols if col in analysis_export.columns]
        analysis_export = analysis_export[export_cols].rename(
            columns={
                "Nom": "Equip",
                "req_type": "tipus_peticio",
                "request_code": "peticio",
                "expected_seed": "numero_esperat",
                "assigned_seed": "numero_assignat",
                "is_effective_request": "te_peticio_efectiva",
                "is_mismatch": "te_incidencia",
                "mismatch_jornades": "dany_jornades",
                "is_textual_request": "te_peticio_casa_fora",
                "casa_fora_respected": "casa_fora_complert",
                "dupla_label": "dupla_assignada",
                "numero_casa": "dupla_numero_casa",
                "numero_fora": "dupla_numero_fora",
            }
        )
        if diffs_col and diffs_col in analysis_export.columns:
            analysis_export = analysis_export.rename(columns={diffs_col: "diferencies_jornades"})
    return analysis_export


def build_kpis_payload(
    *,
    nom_fitxer: str,
    segona_fase_bool: bool,
    fase: Any,
    excel_path: str,
    metrics_pack: dict[str, Any],
    df_info: pd.DataFrame,
    df_val_count_summary: pd.DataFrame,
    df_val_count_by_cat: pd.DataFrame,
    df_val_entity_conflicts: pd.DataFrame,
    df_val_level_spread: pd.DataFrame,
    df_incidents: pd.DataFrame,
    input_demand_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the KPI JSON payload from already prepared pipeline values."""
    analysis_export = _build_analysis_export(metrics_pack)
    input_demand_analysis = input_demand_analysis or {}

    return {
        "input_file": nom_fitxer,
        "fase": "segona_fase" if segona_fase_bool else "primera_fase",
        "jornades": len(fase),
        "excel_path": excel_path,
        "kpi_global": _df_records(metrics_pack.get("kpi_global", pd.DataFrame())),
        "casa_fora_summary": _df_records(metrics_pack.get("casa_fora_summary", pd.DataFrame())),
        "damage_summary": _df_records(metrics_pack.get("damage_summary", pd.DataFrame())),
        "global_numbers": _df_records(metrics_pack.get("global_numbers", pd.DataFrame())),
        "by_modalitat": _df_records(metrics_pack.get("by_modalitat", pd.DataFrame())),
        "by_categoria": _df_records(metrics_pack.get("by_categoria", pd.DataFrame())),
        "duples": _df_records(metrics_pack.get("duples", pd.DataFrame())),
        "fairness_summary": _df_records(metrics_pack.get("fairness_summary", pd.DataFrame())),
        "fairness_entities": _df_records(metrics_pack.get("fairness_entities", pd.DataFrame())),
        "entitats": _df_records(metrics_pack.get("entitats", pd.DataFrame())),
        "levels_modalitat": _df_records(metrics_pack.get("levels_modalitat", pd.DataFrame())),
        "levels_categoria": _df_records(metrics_pack.get("levels_category", pd.DataFrame())),
        "levels_group": _df_records(metrics_pack.get("levels_group", pd.DataFrame())),
        "solver_info_per_categoria": _df_records(df_info),
        "validacio_recompte_global": _df_records(df_val_count_summary),
        "validacio_recompte_categoria": _df_records(df_val_count_by_cat),
        "conflictes_entitat": _df_records(df_val_entity_conflicts),
        "nivells_dispars": _df_records(df_val_level_spread),
        "incidencies": _df_records(df_incidents),
        "analysis_rows": _df_records(analysis_export),
        "input_demand_summary": input_demand_analysis.get("summary", {}),
        "input_demand_by_venue": input_demand_analysis.get("by_venue", []),
        "input_demand_by_venue_day": input_demand_analysis.get("by_venue_day", []),
        "input_demand_by_venue_day_time": input_demand_analysis.get("by_venue_day_time", []),
        "input_demand_friday": input_demand_analysis.get("friday_by_venue_time", []),
        "input_demand_top_slots": input_demand_analysis.get("top_demand_slots", []),
    }


__all__ = ["build_kpis_payload", "json_default"]
