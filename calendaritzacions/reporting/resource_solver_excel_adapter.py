"""Excel adapter for resource-solver outputs."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import pandas as pd

from calendaritzacions.engine.variants.resource_solver.types import (
    Assignment,
    ResourceSolverResult,
    SolverContext,
    TeamRecord,
)
from calendaritzacions.reporting.legacy_excel_writer import write_legacy_workbook


def write_resource_solver_workbook(
    excel_path: str,
    *,
    result: ResourceSolverResult,
    context: SolverContext,
) -> pd.DataFrame:
    """Write a human-readable Excel workbook for a resource-solver result."""

    result_tables = _build_result_tables(result, context)
    info_totals = _build_info_totals(result_tables)
    entity_conflicts = _build_entity_conflicts(result, context)
    metrics_pack = _build_metrics_pack(result, context, result_tables)

    return write_legacy_workbook(
        excel_path,
        resultats_totals=result_tables,
        info_totals=info_totals,
        metrics_pack=metrics_pack,
        df_val_count_summary=metrics_pack.get("kpi_global", pd.DataFrame()),
        df_val_entity_conflicts=entity_conflicts,
        df_val_level_spread=pd.DataFrame(),
        segona_fase_bool=context.phase_name == "segona_fase",
    )


def _build_result_tables(
    result: ResourceSolverResult,
    context: SolverContext,
) -> list[pd.DataFrame]:
    teams_by_id = {team.team_id: team for team in context.teams}
    assignment_by_group_number = _assignments_by_group_number(result.assignments)
    grouped_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    group_ids_by_sheet: dict[str, set[str]] = defaultdict(set)

    empty_numbers_by_group: dict[str, list[int]] = {}
    for group_id in sorted(assignment_by_group_number, key=_natural_group_key):
        for number in range(1, 9):
            assignment = assignment_by_group_number[group_id].get(number)
            if assignment is None:
                empty_numbers_by_group.setdefault(group_id, []).append(number)
                continue

            team = teams_by_id.get(assignment.team_id)
            if team is None:
                continue
            sheet_key = _sheet_key(team)
            group_ids_by_sheet[sheet_key].add(assignment.group_id)
            grouped_rows[sheet_key].append(
                _team_row(
                    team=team,
                    assignment=assignment,
                    context=context,
                    assignment_by_group_number=assignment_by_group_number,
                    teams_by_id=teams_by_id,
                    sheet_key=sheet_key,
                )
            )

    tables: list[pd.DataFrame] = []
    for sheet_key in list(grouped_rows):
        for group_id in sorted(group_ids_by_sheet.get(sheet_key, set()), key=_natural_group_key):
            for number in empty_numbers_by_group.get(group_id, []):
                empty_row = _empty_slot_row(group_id, number)
                empty_row["_Categoria"] = sheet_key
                grouped_rows[sheet_key].append(empty_row)

    for sheet_key, rows in sorted(grouped_rows.items(), key=lambda item: item[0].casefold()):
        df = pd.DataFrame(rows)
        if df.empty:
            continue
        if "_Categoria" not in df.columns:
            df["_Categoria"] = sheet_key
        df.sort_values(["Grup", "Núm. sorteig assignat"], inplace=True, kind="stable")
        tables.append(df.reset_index(drop=True))
    return tables


def _team_row(
    *,
    team: TeamRecord,
    assignment: Assignment,
    context: SolverContext,
    assignment_by_group_number: dict[str, dict[int, Assignment]],
    teams_by_id: dict[str, TeamRecord],
    sheet_key: str,
) -> dict[str, Any]:
    requested_number = _requested_number(team.seed_request_original)
    differences = _round_differences(
        requested_number=requested_number,
        assigned_number=assignment.number,
        assignment=assignment,
        context=context,
        assignment_by_group_number=assignment_by_group_number,
        teams_by_id=teams_by_id,
    )

    row: dict[str, Any] = {
        "_Categoria": sheet_key,
        "Nom Lliga": team.league_name,
        "Modalitat": team.modality,
        "Categoria": team.category,
        "Subcategoria": team.subcategory,
        "Grup": _display_group_id(assignment.group_id),
        "Id": team.team_id,
        "Nom": team.name,
        "Entitat": team.entity,
        "Pista joc": team.venue,
        "Dia partit": team.day,
        "Horari partit": team.time,
        "Nivell": team.level,
        "Núm. sorteig": team.seed_request_original,
        "Núm. esperat resolt": requested_number if requested_number is not None else "",
        "Núm. sorteig assignat": assignment.number,
        "Resultat petició": _request_result(team.seed_request_original, requested_number, assignment.number),
        "Jornades afectades": len(differences),
        "Diferències jornades": differences,
    }
    return row


def _empty_slot_row(group_id: str, number: int) -> dict[str, Any]:
    return {
        "_Categoria": group_id,
        "Nom Lliga": "",
        "Modalitat": "",
        "Categoria": "",
        "Subcategoria": "",
        "Grup": _display_group_id(group_id),
        "Id": "",
        "Nom": "Descans",
        "Entitat": "Descans",
        "Pista joc": "",
        "Dia partit": "Descans",
        "Horari partit": "",
        "Nivell": "",
        "Núm. sorteig": "",
        "Núm. esperat resolt": "",
        "Núm. sorteig assignat": number,
        "Resultat petició": "Descans",
        "Jornades afectades": "",
        "Diferències jornades": [],
    }


def _round_differences(
    *,
    requested_number: int | None,
    assigned_number: int,
    assignment: Assignment,
    context: SolverContext,
    assignment_by_group_number: dict[str, dict[int, Assignment]],
    teams_by_id: dict[str, TeamRecord],
) -> list[tuple[int, str, str]]:
    if requested_number is None:
        return []

    group_assignments = assignment_by_group_number.get(assignment.group_id, {})
    differences: list[tuple[int, str, str]] = []
    for round_index, round_matches in enumerate(context.phase, start=1):
        desired = _home_away_for_number(requested_number, round_matches)
        actual = _home_away_for_number(assigned_number, round_matches)
        if desired is None or actual is None or desired == actual:
            continue
        opponent_number = _opponent_number_for_number(assigned_number, round_matches)
        opponent_name = ""
        if opponent_number is not None:
            opponent_name = _opponent_name(group_assignments.get(opponent_number), teams_by_id)
        differences.append((round_index, actual, opponent_name))
    return differences


def _build_info_totals(result_tables: list[pd.DataFrame]) -> list[dict[str, Any]]:
    info: list[dict[str, Any]] = []
    for df in result_tables:
        if df.empty:
            continue
        label = str(df["_Categoria"].iloc[0]) if "_Categoria" in df.columns else "Categoria"
        real_rows = df[df["Entitat"].astype(str) != "Descans"] if "Entitat" in df.columns else df
        group_counts = real_rows.groupby("Grup").size().tolist() if "Grup" in real_rows.columns else []
        num_groups = int(real_rows["Grup"].nunique()) if "Grup" in real_rows.columns else 0
        num_slots = num_groups * 8
        num_dummies = int((df["Entitat"].astype(str) == "Descans").sum()) if "Entitat" in df.columns else 0
        info.append(
            {
                "categoria": label,
                "num_grups": num_groups,
                "repartiment": group_counts,
                "num_equips_reals": int(len(real_rows)),
                "num_slots": num_slots,
                "num_dummies": num_dummies,
                "dummy_ratio": (num_dummies / num_slots) if num_slots else 0.0,
                "num_conflictes_finals": 0,
            }
        )
    return info


def _build_entity_conflicts(result: ResourceSolverResult, context: SolverContext) -> pd.DataFrame:
    teams_by_id = {team.team_id: team for team in context.teams}
    assigned_team_ids_by_group: dict[str, set[str]] = defaultdict(set)
    for assignment in result.assignments:
        assigned_team_ids_by_group[assignment.group_id].add(assignment.team_id)

    rows = []
    for (entity, group_id), excess in sorted(result.entity_excess.items()):
        categories = {
            _sheet_key(teams_by_id[team_id])
            for team_id in assigned_team_ids_by_group.get(group_id, set())
            if team_id in teams_by_id and teams_by_id[team_id].entity == entity
        }
        rows.append(
            {
                "Categoria": ", ".join(sorted(categories)) if categories else "",
                "Grup": _display_group_id(group_id),
                "Entitat": entity,
                "Count": int(excess) + 1,
            }
        )
    return pd.DataFrame(rows)


def _build_metrics_pack(
    result: ResourceSolverResult,
    context: SolverContext,
    result_tables: list[pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    total_input = len(context.teams)
    assigned = len(result.assignments)
    entity_conflicts = sum(int(value) for value in result.entity_excess.values())
    resource_excess = sum(int(usage.excess) for usage in result.resource_usage)
    kpi_global = pd.DataFrame(
        [
            {"Metrica": "Equips totals input", "Valor": total_input},
            {"Metrica": "Equips reals assignats", "Valor": assigned},
            {"Metrica": "Estat solver", "Valor": result.status},
            {"Metrica": "Conflictes entitat", "Valor": entity_conflicts},
            {"Metrica": "Exces recursos", "Valor": resource_excess},
        ]
    )
    summary_rows = []
    for df in result_tables:
        if df.empty:
            continue
        real = df[df["Entitat"].astype(str) != "Descans"] if "Entitat" in df.columns else df
        summary_rows.append(
            {
                "Modalitat": str(real["Modalitat"].iloc[0]) if "Modalitat" in real.columns and not real.empty else "",
                "Equips totals": int(len(real)),
                "Equips amb peticio efectiva": int((real["Núm. esperat resolt"].astype(str) != "").sum())
                if "Núm. esperat resolt" in real.columns
                else 0,
                "Incidencia": int((real["Resultat petició"] == "Incidència").sum())
                if "Resultat petició" in real.columns
                else 0,
                "Incidencia %": 0.0,
                "Severitat mitjana": float(real["Jornades afectades"].replace("", 0).astype(int).mean())
                if "Jornades afectades" in real.columns and not real.empty
                else 0.0,
            }
        )
    return {
        "kpi_global": kpi_global,
        "summary_modalitat": pd.DataFrame(summary_rows),
    }


def _assignments_by_group_number(
    assignments: tuple[Assignment, ...],
) -> dict[str, dict[int, Assignment]]:
    grouped: dict[str, dict[int, Assignment]] = defaultdict(dict)
    for assignment in assignments:
        grouped[assignment.group_id][assignment.number] = assignment
    return grouped


def _sheet_key(team: TeamRecord) -> str:
    parts = [team.modality, team.category, team.subcategory]
    if all(str(part).strip() for part in parts):
        return " - ".join(str(part).strip() for part in parts)
    return team.league_name or "Categoria"


def _requested_number(value: Any) -> int | None:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= 8 else None


def _request_result(original: Any, requested_number: int | None, assigned_number: int) -> str:
    text = "" if original is None else str(original).strip()
    if not text:
        return "Sense petició"
    if requested_number is None:
        return "Petició no numèrica"
    return "OK" if requested_number == assigned_number else "Incidència"


def _home_away_for_number(number: int, round_matches: Any) -> str | None:
    for home_number, away_number in round_matches:
        if number == home_number:
            return "Casa"
        if number == away_number:
            return "Fora"
    return None


def _opponent_number_for_number(number: int, round_matches: Any) -> int | None:
    for home_number, away_number in round_matches:
        if number == home_number:
            return away_number
        if number == away_number:
            return home_number
    return None


def _opponent_name(assignment: Assignment | None, teams_by_id: dict[str, TeamRecord]) -> str:
    if assignment is None:
        return ""
    team = teams_by_id.get(assignment.team_id)
    return team.name if team is not None else assignment.team_id


def _natural_group_key(group_id: str) -> tuple[str, int]:
    match = re.search(r"(\d+)$", str(group_id))
    if not match:
        return (str(group_id), 0)
    return (str(group_id)[: match.start()], int(match.group(1)))


def _display_group_id(group_id: str) -> str:
    match = re.match(r"^C\d+_(G\d+)$", str(group_id))
    if match:
        return match.group(1)
    return str(group_id)
