"""Persistent workspace helpers for resource-solver runs."""

from __future__ import annotations

from collections import Counter, defaultdict
import math
from pathlib import Path
from typing import Any

from django.db import transaction

from calendaritzacions.django.models import (
    AssignmentWorkspace,
    CalendarizationRun,
    WorkspaceAssignment,
    WorkspaceResourceIncident,
    WorkspaceResourceMatch,
)
from calendaritzacions.django.services.audit_reader import discover_audit_paths, read_json_file

HYDRATION_VERSION = 3


def get_or_create_workspace_for_run(
    run: CalendarizationRun,
    *,
    force: bool = False,
) -> AssignmentWorkspace:
    """Return the persisted assignment workspace for a successful resource-solver run."""

    _validate_workspace_run(run)
    workspace = AssignmentWorkspace.objects.filter(run=run).order_by("id").first()
    if workspace is None:
        workspace = AssignmentWorkspace.objects.create(
            run=run,
            name=f"Workspace run {run.pk}",
            status=AssignmentWorkspace.STATUS_ACTIVE,
            source_artifact="resource_solution",
        )
    if force or not _workspace_is_current(workspace):
        hydrate_workspace_from_audits(run, workspace=workspace)
    return workspace


def hydrate_workspace_from_audits(
    run: CalendarizationRun,
    *,
    workspace: AssignmentWorkspace | None = None,
) -> AssignmentWorkspace:
    """Materialize assignments, matches and resource-excess incidents from JSON audits."""

    _validate_workspace_run(run)
    workspace = workspace or get_or_create_workspace_for_run(run)
    payloads = _read_payloads(run)
    solution = payloads["resource_solution"]
    teams = _team_lookup(payloads["team_catalog"])
    candidates = _candidate_lookup(payloads["candidate_catalog"])
    pressure = _pressure_lookup(payloads["resource_pressure"])
    assignments = _list(solution.get("assignments"))
    matches = _list(solution.get("real_matches"))
    usage_rows = _list(solution.get("resource_usage"))
    usage_by_resource = _usage_lookup(usage_rows)

    with transaction.atomic():
        WorkspaceResourceIncident.objects.filter(workspace=workspace).delete()
        WorkspaceResourceMatch.objects.filter(workspace=workspace).delete()
        WorkspaceAssignment.objects.filter(workspace=workspace).delete()

        _create_assignments(workspace, assignments, teams, candidates, pressure, usage_by_resource)
        created_matches = _create_matches(workspace, matches, teams)
        _create_resource_incidents(workspace, usage_rows, created_matches, teams)
        _create_entity_conflict_incidents(workspace, solution, teams)
        workspace.summary = _build_persisted_summary(workspace)
        workspace.status = AssignmentWorkspace.STATUS_ACTIVE
        workspace.source_artifact = "resource_solution"
        workspace.save(update_fields=["summary", "status", "source_artifact", "updated_at"])

    return workspace


def get_workspace_summary(workspace: AssignmentWorkspace) -> dict[str, Any]:
    """Build a compact triage payload for the overview page."""

    if not _workspace_is_current(workspace):
        hydrate_workspace_from_audits(workspace.run, workspace=workspace)

    incident_qs = WorkspaceResourceIncident.objects.filter(workspace=workspace).order_by(
        "status",
        "-severity",
        "incident_type",
        "resource_id",
    )
    incidents = list(incident_qs)
    return {
        "kpis": _workspace_kpis(workspace),
        "top_incidents": [_incident_summary(incident) for incident in incidents[:50]],
        "incident_summaries": [_incident_summary(incident) for incident in incidents],
        "league_summaries": _league_summaries(workspace),
        "assignment_summaries": _assignment_summaries(workspace),
        "raw_summary": workspace.summary or {},
    }


def get_workspace_incident_detail(
    workspace: AssignmentWorkspace,
    incident_id: str | int,
) -> dict[str, Any] | None:
    """Return a display-ready incident detail payload."""

    try:
        incident_pk = int(incident_id)
    except (TypeError, ValueError):
        return None
    try:
        incident = WorkspaceResourceIncident.objects.get(workspace=workspace, pk=incident_pk)
    except WorkspaceResourceIncident.DoesNotExist:
        return None

    if incident.incident_type == WorkspaceResourceIncident.TYPE_ASSIGNMENT_CONFLICT:
        return _entity_conflict_incident_detail(workspace, incident)

    resource_id = incident.resource_id
    matches = WorkspaceResourceMatch.objects.filter(
        workspace=workspace,
        home_resource_id=resource_id,
    ).order_by("round_index", "group_id", "home_team_id")
    assignments = {
        assignment.team_id: assignment
        for assignment in WorkspaceAssignment.objects.filter(
            workspace=workspace,
            team_id__in=incident.team_ids or [],
        )
    }
    affected_matches = []
    for match in matches:
        home_assignment = assignments.get(match.home_team_id)
        affected_matches.append(
            {
                "id": match.pk,
                "match_id": match.pk,
                "round": match.round_index,
                "jornada": match.round_index,
                "group_id": match.group_id,
                "home_team": _team_label(match.home_team_id, match.payload.get("home_team_name", "")),
                "home_team_id": match.home_team_id,
                "away_team": _team_label(match.away_team_id, match.payload.get("away_team_name", "")),
                "away_team_id": match.away_team_id,
                "home_slot": _slot_label(home_assignment),
                "resource": _resource_label(resource_id),
                "venue": _resource_label(resource_id),
            }
        )

    return {
        **_incident_summary(incident),
        "detail": (
            "Aquest recurs supera la capacitat final calculada. "
            "Els equips llistats consumeixen la pista/franja com a locals en aquesta jornada."
        ),
        "facts": [
            {"label": "Recurs", "value": _resource_label(resource_id)},
            {"label": "Locals assignats", "value": incident.locals_count},
            {"label": "Capacitat", "value": incident.capacity},
            {"label": "Exces", "value": incident.excess},
            {"label": "Equips locals", "value": len(incident.team_ids or [])},
        ],
        "affected_matches": affected_matches,
        "recommendations": [
            "Revisar un equip local d'aquest recurs i provar un numero/grup que canviï la jornada de localia.",
            "Prioritzar moviments dins la mateixa lliga abans de tocar altres competicions.",
            "Si l'exces és acceptable operativament, deixar-lo marcat per revisio manual.",
        ],
    }


def _entity_conflict_incident_detail(
    workspace: AssignmentWorkspace,
    incident: WorkspaceResourceIncident,
) -> dict[str, Any]:
    payload = incident.payload or {}
    entity = str(payload.get("entity") or "-")
    group_id = str(payload.get("group_id") or "-")
    assignments = {
        assignment.team_id: assignment
        for assignment in WorkspaceAssignment.objects.filter(
            workspace=workspace,
            team_id__in=incident.team_ids or [],
        )
    }
    group_matches = list(
        WorkspaceResourceMatch.objects.filter(
            workspace=workspace,
            group_id=group_id,
        ).order_by("round_index", "id")
    )
    team_calendars = []
    affected_matches = []
    for team_id in incident.team_ids or []:
        assignment = assignments.get(team_id)
        if assignment is None:
            continue
        calendar = []
        for match in group_matches:
            if match.home_team_id != team_id and match.away_team_id != team_id:
                continue
            is_home = match.home_team_id == team_id
            opponent_id = match.away_team_id if is_home else match.home_team_id
            opponent_name = match.payload.get("away_team_name" if is_home else "home_team_name", "")
            row = {
                "id": match.pk,
                "round": match.round_index,
                "side": "Casa" if is_home else "Fora",
                "opponent_id": opponent_id,
                "opponent": _team_label(opponent_id, opponent_name),
                "resource": _resource_label(match.home_resource_id) if is_home else "-",
                "home_team": _team_label(match.home_team_id, match.payload.get("home_team_name", "")),
                "home_team_id": match.home_team_id,
                "away_team": _team_label(match.away_team_id, match.payload.get("away_team_name", "")),
                "away_team_id": match.away_team_id,
            }
            calendar.append(row)
            affected_matches.append(row)
        team_calendars.append(
            {
                "team_id": team_id,
                "team_name": assignment.team_name or team_id,
                "number": assignment.assigned_number,
                "group_id": assignment.group_id,
                "calendar": calendar,
            }
        )

    unique_matches = {row["id"]: row for row in affected_matches}
    return {
        **_incident_summary(incident),
        "detail": (
            "Hi ha mes d'un equip de la mateixa entitat dins el mateix grup. "
            "A sota es mostra el calendari dels equips implicats per revisar el conflicte esportiu."
        ),
        "facts": [
            {"label": "Entitat", "value": entity},
            {"label": "Grup", "value": group_id},
            {"label": "Equips implicats", "value": len(incident.team_ids or [])},
            {"label": "Exces", "value": incident.excess},
            {"label": "Lliga", "value": _top_league_label(payload.get("league_counts"))},
        ],
        "affected_matches": list(unique_matches.values()),
        "team_calendars": sorted(team_calendars, key=lambda row: (row["number"] or 99, row["team_name"])),
        "recommendations": [
            "Provar moure un dels equips implicats a un altre grup candidat de la mateixa competicio.",
            "Prioritzar canvis que mantinguin mida de grup i no crein exces de recurs.",
            "Comparar els numeros assignats abans de canviar-los: el conflicte principal es de composicio de grup.",
        ],
    }


def get_workspace_team_detail(
    workspace: AssignmentWorkspace,
    team_id: str,
) -> dict[str, Any] | None:
    """Return assignment explainability for one team."""

    if not _workspace_is_current(workspace):
        hydrate_workspace_from_audits(workspace.run, workspace=workspace)

    try:
        assignment = WorkspaceAssignment.objects.get(workspace=workspace, team_id=team_id)
    except WorkspaceAssignment.DoesNotExist:
        return None

    payload = assignment.payload or {}
    team = payload.get("team") if isinstance(payload.get("team"), dict) else {}
    selected_candidate = payload.get("selected_candidate") if isinstance(payload.get("selected_candidate"), dict) else {}
    home_resources = payload.get("home_resources") if isinstance(payload.get("home_resources"), list) else []
    alternatives = payload.get("alternatives") if isinstance(payload.get("alternatives"), list) else []
    home_matches = [
        _match_detail(match)
        for match in WorkspaceResourceMatch.objects.filter(
            workspace=workspace,
            home_team_id=team_id,
        ).order_by("round_index", "group_id")
    ]
    away_matches = [
        _match_detail(match)
        for match in WorkspaceResourceMatch.objects.filter(
            workspace=workspace,
            away_team_id=team_id,
        ).order_by("round_index", "group_id")
    ]
    incident_resources = {
        incident.resource_id: incident
        for incident in WorkspaceResourceIncident.objects.filter(workspace=workspace)
        if team_id in (incident.team_ids or [])
    }
    resource_rows = []
    for row in home_resources:
        if not isinstance(row, dict):
            continue
        incident = incident_resources.get(str(row.get("resource_id") or ""))
        resource_rows.append(
            {
                **row,
                "incident_status": "Amb incidencia" if incident else "Sense incidencia",
                "incident_excess": incident.excess if incident else 0,
            }
        )

    return {
        "team_id": team_id,
        "team_name": assignment.team_name or team_id,
        "entity": assignment.entity or "-",
        "competition": _competition_label(team),
        "group_id": assignment.group_id,
        "number": assignment.assigned_number,
        "seed_request_original": assignment.seed_request_original or "-",
        "selected_candidate": selected_candidate,
        "home_resources": resource_rows,
        "home_matches": home_matches,
        "away_matches": away_matches,
        "alternatives": alternatives[:16],
        "explanation": _team_explanation(assignment, resource_rows, selected_candidate),
    }


def get_workspace_calendar_view(workspace: AssignmentWorkspace) -> dict[str, Any]:
    """Return a read-only calendar matrix grouped by workspace group."""

    if not _workspace_is_current(workspace):
        hydrate_workspace_from_audits(workspace.run, workspace=workspace)

    assignments = list(
        WorkspaceAssignment.objects.filter(workspace=workspace).order_by(
            "group_id",
            "assigned_number",
            "team_name",
            "team_id",
        )
    )
    matches = list(
        WorkspaceResourceMatch.objects.filter(workspace=workspace).order_by(
            "group_id",
            "round_index",
            "id",
        )
    )
    incidents = list(WorkspaceResourceIncident.objects.filter(workspace=workspace))

    assignments_by_group: dict[str, list[WorkspaceAssignment]] = defaultdict(list)
    for assignment in assignments:
        assignments_by_group[assignment.group_id or "-"].append(assignment)

    matches_by_group: dict[str, list[WorkspaceResourceMatch]] = defaultdict(list)
    match_by_group_team_round: dict[tuple[str, str, int], WorkspaceResourceMatch] = {}
    home_venues_by_team: dict[str, str] = {}
    rounds = set()
    for match in matches:
        group_id = match.group_id or "-"
        round_index = int(match.round_index or 0)
        if round_index:
            rounds.add(round_index)
        matches_by_group[group_id].append(match)
        if match.home_team_id and match.home_resource_id:
            base_resource_id, _round_label = _split_resource_round(match.home_resource_id)
            venue = next((part for part in base_resource_id.split("|") if part), "")
            if venue:
                home_venues_by_team.setdefault(match.home_team_id, venue)
        if round_index:
            match_by_group_team_round[(group_id, match.home_team_id, round_index)] = match
            match_by_group_team_round[(group_id, match.away_team_id, round_index)] = match

    resource_incidents: dict[str, list[WorkspaceResourceIncident]] = defaultdict(list)
    entity_incidents: dict[tuple[str, str], list[WorkspaceResourceIncident]] = defaultdict(list)
    for incident in incidents:
        if incident.incident_type == WorkspaceResourceIncident.TYPE_RESOURCE_EXCESS and incident.resource_id:
            resource_incidents[incident.resource_id].append(incident)
            continue
        if incident.incident_type != WorkspaceResourceIncident.TYPE_ASSIGNMENT_CONFLICT:
            continue
        payload = incident.payload or {}
        group_id = str(payload.get("group_id") or "")
        for team_id in incident.team_ids or []:
            entity_incidents[(group_id, str(team_id))].append(incident)

    filter_values: dict[str, set[str]] = {
        "group": set(),
        "modality": set(),
        "category": set(),
        "subcategory": set(),
        "level": set(),
        "league": set(),
        "entity": set(),
        "venue": set(),
    }
    groups = []
    for group_id, group_assignments in sorted(assignments_by_group.items(), key=lambda item: _text_sort(item[0])):
        filter_values["group"].add(group_id)
        group_assignments = sorted(
            group_assignments,
            key=lambda assignment: (
                assignment.assigned_number if assignment.assigned_number is not None else 9999,
                _text_sort(assignment.team_name),
                assignment.team_id,
            ),
        )
        group_rounds = sorted({int(match.round_index or 0) for match in matches_by_group.get(group_id, []) if match.round_index})
        columns = [_calendar_column(round_index) for round_index in group_rounds]
        rows = []
        row_filter_fields = []
        for assignment in group_assignments:
            fields = _assignment_calendar_filter_fields(assignment)
            if not fields["venue"]:
                fields["venue"] = home_venues_by_team.get(assignment.team_id, "")
            row_filter_fields.append(fields)
            for key, value in fields.items():
                if key in filter_values and value:
                    filter_values[key].add(value)

            cells = []
            for round_index in group_rounds:
                match = match_by_group_team_round.get((group_id, assignment.team_id, round_index))
                cells.append(
                    _calendar_cell(
                        assignment,
                        match,
                        round_index,
                        resource_incidents,
                        entity_incidents.get((group_id, assignment.team_id), []),
                    )
                )
            has_entity_conflict = any(cell["has_entity_incident"] for cell in cells)
            has_resource_excess = any(cell["has_resource_incident"] for cell in cells)
            rows.append(
                {
                    "team_id": assignment.team_id,
                    "team_name": assignment.team_name or assignment.team_id,
                    "entity": assignment.entity,
                    "number": assignment.assigned_number,
                    "assigned_number": assignment.assigned_number,
                    "group_id": assignment.group_id,
                    "has_entity_conflict": has_entity_conflict,
                    "has_resource_excess": has_resource_excess,
                    **fields,
                    "filter_text": _calendar_filter_text(
                        [
                            assignment.team_id,
                            assignment.team_name,
                            assignment.entity,
                            assignment.group_id,
                            assignment.assigned_number,
                            *fields.values(),
                        ]
                    ),
                    "cells": cells,
                }
            )

        group_fields = _group_calendar_fields(row_filter_fields)
        has_entity_conflict = any(row["has_entity_conflict"] for row in rows)
        has_resource_excess = any(row["has_resource_excess"] for row in rows)
        group_filter_text = _calendar_filter_text(
            [
                group_id,
                group_fields.get("competition", ""),
                group_fields.get("league", ""),
                group_fields.get("modality", ""),
                group_fields.get("category", ""),
                group_fields.get("subcategory", ""),
                group_fields.get("level", ""),
                group_fields.get("entity", ""),
                group_fields.get("venue", ""),
                *[row["filter_text"] for row in rows],
            ]
        )
        groups.append(
            {
                "group_id": group_id,
                "group_token": _filter_token(group_id),
                **group_fields,
                "modality_tokens": _calendar_tokens(row.get("modality", "") for row in rows),
                "category_tokens": _calendar_tokens(row.get("category", "") for row in rows),
                "level_tokens": _calendar_tokens(row.get("level", "") for row in rows),
                "league_tokens": _calendar_tokens(row.get("league", "") for row in rows),
                "columns": columns,
                "rounds": [column["round"] for column in columns],
                "rows": rows,
                "team_count": len(rows),
                "match_count": len(matches_by_group.get(group_id, [])),
                "has_entity_conflict": has_entity_conflict,
                "has_resource_excess": has_resource_excess,
                "filter_text": group_filter_text,
            }
        )

    global_columns = [_calendar_column(round_index) for round_index in sorted(rounds)]
    filters = {
        key: [{"label": value, "token": _filter_token(value)} for value in sorted(values, key=_text_sort)]
        for key, values in filter_values.items()
    }
    filters.update(
        {
            "groups": filters["group"],
            "modalities": filters["modality"],
            "categories": filters["category"],
            "subcategories": filters["subcategory"],
            "levels": filters["level"],
            "leagues": filters["league"],
            "entities": filters["entity"],
            "venues": filters["venue"],
        }
    )
    return {
        "columns": global_columns,
        "rounds": [column["round"] for column in global_columns],
        "filters": filters,
        "groups": groups,
    }


def get_workspace_venue_round_sheets(workspace: AssignmentWorkspace) -> dict[str, Any]:
    """Return visual match sheets grouped by venue and round."""

    if not _workspace_is_current(workspace):
        hydrate_workspace_from_audits(workspace.run, workspace=workspace)

    payloads = _read_payloads(workspace.run)
    pressure_rows = _venue_pressure_rows(payloads.get("resource_pressure", []))
    venue_meta = _venue_sheet_meta(pressure_rows)
    assignments = {
        assignment.team_id: assignment
        for assignment in WorkspaceAssignment.objects.filter(workspace=workspace)
    }
    matches_by_venue_round: dict[tuple[str, int], dict[str, Any]] = {}

    for match in WorkspaceResourceMatch.objects.filter(workspace=workspace).order_by("round_index", "home_resource_id", "group_id"):
        base_resource_id, round_label = _split_resource_round(match.home_resource_id)
        meta = pressure_rows.get(base_resource_id) or _fallback_pressure_row(base_resource_id)
        venue = str(meta.get("venue") or "")
        day = str(meta.get("day") or "")
        hour_slot = str(meta.get("hour_slot") or "")
        venue_key = _venue_key(venue)
        round_index = match.round_index or _round_number(round_label) or 0
        slot_key = _slot_key(day, hour_slot)
        sheet = matches_by_venue_round.setdefault(
            (venue_key, round_index),
            {
                "venue_key": venue_key,
                "venue": venue or _resource_label(base_resource_id),
                "round": round_index,
                "round_label": f"J{round_index}" if round_index else round_label or "-",
                "slots": defaultdict(list),
            },
        )
        item = _venue_sheet_match(match, assignments)
        sheet["slots"][slot_key].append(item)

    sheets = []
    for key, sheet in sorted(matches_by_venue_round.items(), key=lambda item: (_text_sort(item[1]["venue"]), item[1]["round"])):
        venue_key, _round_index = key
        meta = venue_meta.get(venue_key, _empty_venue_meta(sheet["venue"], venue_key))
        if not meta["slots"]:
            for slot_key in sorted(sheet["slots"]):
                day, hour_slot = slot_key.split("||", 1)
                meta["slots"].append(
                    {
                        "day": day,
                        "hour_slot": hour_slot,
                        "estimated_capacity": 1,
                        "demand_count": 0,
                        "demand_per_court": 0,
                    }
                )
            meta["slot_count"] = len(meta["slots"])
        max_courts = max(1, int(meta.get("max_capacity") or 1))
        rows = []
        total_matches = 0
        sheet_modalities = set()
        for slot in meta.get("slots", []):
            slot_key = _slot_key(slot["day"], slot["hour_slot"])
            matches = list(sheet["slots"].get(slot_key, []))
            sheet_modalities.update(match["modality"] for match in matches if match.get("modality"))
            total_matches += len(matches)
            rows.append(
                {
                    **slot,
                    "matches": matches[:max_courts],
                    "overflow_matches": matches[max_courts:],
                    "match_count": len(matches),
                    "empty_cells": range(max(0, max_courts - min(len(matches), max_courts))),
                    "saturation_pct": _pct(len(matches), max_courts),
                    "over_capacity": len(matches) > int(slot.get("estimated_capacity") or max_courts),
                }
            )
        sheets.append(
            {
                **meta,
                "round": sheet["round"],
                "round_label": sheet["round_label"],
                "court_columns": range(1, max_courts + 1),
                "overflow_colspan": max_courts + 2,
                "rows": rows,
                "match_count": total_matches,
                "saturation_pct": _pct(total_matches, max(1, len(rows) * max_courts)),
                "modalities": sorted(sheet_modalities, key=_text_sort),
                "modality_filter": " ".join(sorted({_filter_token(value) for value in sheet_modalities if value})),
            }
        )

    modalities = sorted({modality for sheet in sheets for modality in sheet.get("modalities", [])}, key=_text_sort)
    return {
        "sheets": sheets,
        "venues": sorted(venue_meta.values(), key=lambda item: _text_sort(item["venue"])),
        "rounds": sorted({sheet["round"] for sheet in sheets}),
        "modalities": [{"label": modality, "token": _filter_token(modality)} for modality in modalities],
    }


def _calendar_column(round_index: int) -> dict[str, Any]:
    return {
        "round": round_index,
        "jornada": round_index,
        "label": f"J{round_index}",
    }


def _calendar_cell(
    assignment: WorkspaceAssignment,
    match: WorkspaceResourceMatch | None,
    round_index: int,
    resource_incidents: dict[str, list[WorkspaceResourceIncident]],
    entity_incidents: list[WorkspaceResourceIncident],
) -> dict[str, Any]:
    entity_incident_ids = [incident.pk for incident in entity_incidents]
    if match is None:
        return {
            "round": round_index,
            "jornada": round_index,
            "side": "Descans",
            "opponent": "",
            "opponent_id": "",
            "resource": "",
            "resource_id": "",
            "match_id": None,
            "has_incident": bool(entity_incident_ids),
            "has_resource_incident": False,
            "has_entity_incident": bool(entity_incident_ids),
            "has_resource_excess": False,
            "has_entity_conflict": bool(entity_incident_ids),
            "incident_ids": entity_incident_ids,
            "resource_incident_ids": [],
            "entity_incident_ids": entity_incident_ids,
        }

    is_home = match.home_team_id == assignment.team_id
    opponent_id = match.away_team_id if is_home else match.home_team_id
    opponent_name = match.payload.get("away_team_name" if is_home else "home_team_name", "")
    local_resource_incidents = resource_incidents.get(match.home_resource_id, []) if is_home else []
    resource_incident_ids = [incident.pk for incident in local_resource_incidents]
    incident_ids = [*resource_incident_ids, *entity_incident_ids]
    resource_id = match.home_resource_id if is_home else ""
    return {
        "round": round_index,
        "jornada": round_index,
        "side": "Casa" if is_home else "Fora",
        "opponent": _team_label(opponent_id, opponent_name),
        "opponent_id": opponent_id,
        "resource": _resource_label(resource_id) if is_home else "",
        "resource_id": resource_id,
        "match_id": match.pk,
        "has_incident": bool(incident_ids),
        "has_resource_incident": bool(resource_incident_ids),
        "has_entity_incident": bool(entity_incident_ids),
        "has_resource_excess": bool(resource_incident_ids),
        "has_entity_conflict": bool(entity_incident_ids),
        "incident_ids": incident_ids,
        "resource_incident_ids": resource_incident_ids,
        "entity_incident_ids": entity_incident_ids,
    }


def _assignment_calendar_filter_fields(assignment: WorkspaceAssignment) -> dict[str, str]:
    team = _assignment_team(assignment)
    return {
        "competition": _assignment_competition_label(assignment),
        "league": str(team.get("league_name") or "").strip(),
        "modality": str(team.get("modality") or "").strip(),
        "category": str(team.get("category") or "").strip(),
        "subcategory": str(team.get("subcategory") or "").strip(),
        "level": str(team.get("level") or "").strip(),
        "entity": assignment.entity.strip(),
        "venue": _assignment_venue(assignment, team),
    }


def _assignment_team(assignment: WorkspaceAssignment) -> dict[str, Any]:
    team = (assignment.payload or {}).get("team")
    return team if isinstance(team, dict) else {}


def _assignment_venue(assignment: WorkspaceAssignment, team: dict[str, Any]) -> str:
    for key in ("venue", "venue_name", "facility", "home_venue"):
        value = str(team.get(key) or "").strip()
        if value:
            return value
    home_resources = (assignment.payload or {}).get("home_resources")
    if not isinstance(home_resources, list):
        return ""
    for row in home_resources:
        if not isinstance(row, dict):
            continue
        resource_id = str(row.get("base_resource_id") or row.get("resource_id") or "").strip()
        base_resource_id, _round_label = _split_resource_round(resource_id)
        venue = str(row.get("venue") or "").strip() or next((part for part in base_resource_id.split("|") if part), "")
        if venue:
            return venue
    return ""


def _group_calendar_fields(rows: list[dict[str, str]]) -> dict[str, str]:
    keys = ("competition", "league", "modality", "category", "subcategory", "level", "entity", "venue")
    return {key: _common_text(row.get(key, "") for row in rows) for key in keys}


def _common_text(values: Any) -> str:
    unique = {str(value).strip() for value in values if str(value or "").strip()}
    return next(iter(unique)) if len(unique) == 1 else ""


def _calendar_filter_text(values: list[Any]) -> str:
    return " ".join(str(value).strip() for value in values if str(value or "").strip())


def _calendar_tokens(values: Any) -> str:
    return " ".join(sorted({_filter_token(value) for value in values if str(value or "").strip()}))


def _validate_workspace_run(run: CalendarizationRun) -> None:
    if run.status != CalendarizationRun.STATUS_SUCCESS:
        raise ValueError("El workspace nomes es pot crear per runs finalitzats correctament.")
    if run.engine_name != CalendarizationRun.ENGINE_RESOURCE_SOLVER:
        raise ValueError("El workspace nomes esta disponible pel motor resource_solver.")


def _workspace_is_hydrated(workspace: AssignmentWorkspace) -> bool:
    return (
        WorkspaceAssignment.objects.filter(workspace=workspace).exists()
        or WorkspaceResourceIncident.objects.filter(workspace=workspace).exists()
        or WorkspaceResourceMatch.objects.filter(workspace=workspace).exists()
    )


def _workspace_is_current(workspace: AssignmentWorkspace) -> bool:
    return _workspace_is_hydrated(workspace) and (workspace.summary or {}).get("hydration_version") == HYDRATION_VERSION


def _read_payloads(run: CalendarizationRun) -> dict[str, Any]:
    audit_paths = dict(run.audit_paths or {}) if isinstance(run.audit_paths, dict) else {}
    if run.output_path:
        discovered = discover_audit_paths(run.output_path)
        audit_paths = {**discovered, **audit_paths}

    return {
        "resource_solution": _read_dict(audit_paths.get("resource_solution")),
        "team_catalog": _read_list(audit_paths.get("team_catalog")),
        "candidate_catalog": _read_list(audit_paths.get("candidate_catalog")),
        "resource_pressure": _read_list(audit_paths.get("resource_pressure")),
    }


def _read_dict(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    payload = read_json_file(str(Path(path)))
    return payload if isinstance(payload, dict) else {}


def _read_list(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    payload = read_json_file(str(Path(path)))
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _create_assignments(
    workspace: AssignmentWorkspace,
    assignments: list[Any],
    teams: dict[str, dict[str, Any]],
    candidates: dict[tuple[str, str, int], dict[str, Any]],
    pressure: dict[str, dict[str, Any]],
    usage_by_resource: dict[str, dict[str, Any]],
) -> None:
    rows = []
    for item in assignments:
        if not isinstance(item, dict):
            continue
        team_id = str(item.get("team_id", ""))
        team = _json_safe(teams.get(team_id, {}))
        number = _int_or_none(item.get("number"))
        group_id = str(item.get("group_id") or "")
        candidate = candidates.get((team_id, group_id, int(number or 0)), {})
        home_resources = _assignment_home_resources(candidate, pressure, usage_by_resource, teams, team_id)
        alternatives = _assignment_alternatives(team_id, candidates, pressure, usage_by_resource)
        rows.append(
            WorkspaceAssignment(
                workspace=workspace,
                run=workspace.run,
                team_id=team_id,
                team_name=str(team.get("name") or team_id),
                entity=str(team.get("entity") or ""),
                group_id=group_id,
                assigned_number=number,
                previous_group_id=group_id,
                previous_number=number,
                seed_request_original=_text_or_blank(team.get("seed_request_original")),
                payload=_json_safe(
                    {
                        **item,
                        "team": team,
                        "selected_candidate": candidate,
                        "home_resources": home_resources,
                        "alternatives": alternatives,
                    }
                ),
            )
        )
    if rows:
        WorkspaceAssignment.objects.bulk_create(rows)


def _create_matches(
    workspace: AssignmentWorkspace,
    matches: list[Any],
    teams: dict[str, dict[str, Any]],
) -> list[WorkspaceResourceMatch]:
    rows = []
    for item in matches:
        if not isinstance(item, dict):
            continue
        home_team_id = str(item.get("home_team_id") or "")
        away_team_id = str(item.get("away_team_id") or "")
        resource_id = str(item.get("resource_id") or "")
        rows.append(
            WorkspaceResourceMatch(
                workspace=workspace,
                run=workspace.run,
                round_index=_int_or_none(item.get("round_index")),
                group_id=str(item.get("group_id") or ""),
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                home_resource_id=resource_id,
                payload=_json_safe({
                    **item,
                    "home_team_name": teams.get(home_team_id, {}).get("name", ""),
                    "away_team_name": teams.get(away_team_id, {}).get("name", ""),
                }),
            )
        )
    return list(WorkspaceResourceMatch.objects.bulk_create(rows)) if rows else []


def _create_resource_incidents(
    workspace: AssignmentWorkspace,
    usage_rows: list[Any],
    matches: list[WorkspaceResourceMatch],
    teams: dict[str, dict[str, Any]],
) -> None:
    matches_by_resource: dict[str, list[WorkspaceResourceMatch]] = defaultdict(list)
    for match in matches:
        matches_by_resource[match.home_resource_id].append(match)

    rows = []
    for item in usage_rows:
        if not isinstance(item, dict):
            continue
        excess = int(_number(item.get("excess")))
        if excess <= 0:
            continue
        resource_id = str(item.get("resource_id") or "")
        team_ids = [str(team_id) for team_id in (item.get("team_ids") or item.get("teams") or [])]
        league_counts = Counter(
            _competition_label(teams.get(team_id, {}))
            for team_id in team_ids
        )
        rows.append(
            WorkspaceResourceIncident(
                workspace=workspace,
                run=workspace.run,
                incident_type=WorkspaceResourceIncident.TYPE_RESOURCE_EXCESS,
                status=WorkspaceResourceIncident.STATUS_OPEN,
                severity=excess,
                resource_id=resource_id,
                excess=excess,
                locals_count=int(_number(item.get("locals_count"))),
                capacity=int(_number(item.get("capacity"))),
                team_ids=team_ids,
                payload=_json_safe({
                    **item,
                    "resource_label": _resource_label(resource_id),
                    "league_counts": dict(league_counts),
                    "match_count": len(matches_by_resource.get(resource_id, [])),
                }),
            )
        )
    if rows:
        WorkspaceResourceIncident.objects.bulk_create(rows)


def _create_entity_conflict_incidents(
    workspace: AssignmentWorkspace,
    solution: dict[str, Any],
    teams: dict[str, dict[str, Any]],
) -> None:
    rows = []
    for conflict in _entity_conflicts_from_solution(solution, teams):
        team_ids = conflict["team_ids"]
        if len(team_ids) <= 1:
            continue
        league_counts = Counter(_competition_label(teams.get(team_id, {})) for team_id in team_ids)
        excess = max(1, len(team_ids) - 1)
        rows.append(
            WorkspaceResourceIncident(
                workspace=workspace,
                run=workspace.run,
                incident_type=WorkspaceResourceIncident.TYPE_ASSIGNMENT_CONFLICT,
                status=WorkspaceResourceIncident.STATUS_OPEN,
                severity=excess,
                resource_id=f"{conflict['group_id']}|{conflict['entity']}"[:255],
                excess=excess,
                locals_count=len(team_ids),
                capacity=1,
                team_ids=team_ids,
                payload=_json_safe(
                    {
                        "entity": conflict["entity"],
                        "group_id": conflict["group_id"],
                        "team_slots": conflict["team_slots"],
                        "league_counts": dict(league_counts),
                    }
                ),
            )
        )
    if rows:
        WorkspaceResourceIncident.objects.bulk_create(rows)


def _entity_conflicts_from_solution(
    solution: dict[str, Any],
    teams: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    conflicts = []
    for summary in _list(solution.get("group_summary")):
        if not isinstance(summary, dict):
            continue
        group_id = str(summary.get("group_id") or "")
        assigned_numbers = summary.get("assigned_numbers") if isinstance(summary.get("assigned_numbers"), dict) else {}
        entity_excess = summary.get("entity_excess") if isinstance(summary.get("entity_excess"), dict) else {}
        for entity, excess in entity_excess.items():
            if int(_number(excess)) <= 0:
                continue
            entity_text = str(entity)
            team_slots = []
            for number, team_id_raw in assigned_numbers.items():
                team_id = str(team_id_raw)
                if str(teams.get(team_id, {}).get("entity") or "") != entity_text:
                    continue
                team_slots.append(
                    {
                        "team_id": team_id,
                        "team_name": str(teams.get(team_id, {}).get("name") or team_id),
                        "number": _int_or_none(number),
                    }
                )
            conflicts.append(
                {
                    "entity": entity_text,
                    "group_id": group_id,
                    "team_ids": [row["team_id"] for row in sorted(team_slots, key=lambda row: (row["number"] or 99, row["team_name"]))],
                    "team_slots": sorted(team_slots, key=lambda row: (row["number"] or 99, row["team_name"])),
                }
            )
    return conflicts


def _build_persisted_summary(workspace: AssignmentWorkspace) -> dict[str, Any]:
    incidents = WorkspaceResourceIncident.objects.filter(workspace=workspace)
    resource_incidents = incidents.filter(incident_type=WorkspaceResourceIncident.TYPE_RESOURCE_EXCESS)
    entity_conflicts = incidents.filter(incident_type=WorkspaceResourceIncident.TYPE_ASSIGNMENT_CONFLICT)
    return {
        "hydration_version": HYDRATION_VERSION,
        "assignments": WorkspaceAssignment.objects.filter(workspace=workspace).count(),
        "matches": WorkspaceResourceMatch.objects.filter(workspace=workspace).count(),
        "resource_incidents": resource_incidents.count(),
        "entity_conflicts": entity_conflicts.count(),
        "resource_excess_total": sum(incident.excess for incident in resource_incidents),
    }


def _workspace_kpis(workspace: AssignmentWorkspace) -> list[dict[str, Any]]:
    assignments_count = WorkspaceAssignment.objects.filter(workspace=workspace).count()
    matches_count = WorkspaceResourceMatch.objects.filter(workspace=workspace).count()
    resource_incidents = WorkspaceResourceIncident.objects.filter(
        workspace=workspace,
        incident_type=WorkspaceResourceIncident.TYPE_RESOURCE_EXCESS,
    )
    entity_conflicts = WorkspaceResourceIncident.objects.filter(
        workspace=workspace,
        incident_type=WorkspaceResourceIncident.TYPE_ASSIGNMENT_CONFLICT,
    )
    excess_total = sum(incident.excess for incident in resource_incidents)
    resource_count = resource_incidents.count()
    entity_conflict_count = entity_conflicts.count()
    return [
        {"label": "Equips assignats", "value": assignments_count, "status": "neutral"},
        {"label": "Partits", "value": matches_count, "status": "neutral"},
        {
            "label": "Exces recursos",
            "value": excess_total,
            "subtitle": f"{resource_count} recursos afectats",
            "status": "danger" if excess_total else "success",
        },
        {
            "label": "Conflictes entitat",
            "value": entity_conflict_count,
            "status": "warning" if entity_conflict_count else "success",
        },
        {
            "label": "Lligues",
            "value": len({row["name"] for row in _league_summaries(workspace)}),
            "status": "neutral",
        },
        {"label": "Workspace", "value": workspace.get_status_display(), "status": "neutral"},
    ]


def _incident_summary(incident: WorkspaceResourceIncident) -> dict[str, Any]:
    payload = incident.payload or {}
    if incident.incident_type == WorkspaceResourceIncident.TYPE_ASSIGNMENT_CONFLICT:
        entity = str(payload.get("entity") or "-")
        group_id = str(payload.get("group_id") or "-")
        return {
            "id": incident.pk,
            "incident_id": incident.pk,
            "type": "Conflicte entitat",
            "title": f"{entity} - {group_id}",
            "summary": f"{len(incident.team_ids or [])} equips de la mateixa entitat al grup",
            "description": f"{len(incident.team_ids or [])} equips de la mateixa entitat al grup",
            "impact": f"+{incident.excess}",
            "count": incident.excess,
            "severity": incident.severity,
            "status": incident.get_status_display(),
            "resource": group_id,
            "venue": group_id,
            "league": _top_league_label(payload.get("league_counts")),
            "competition": _top_league_label(payload.get("league_counts")),
            "team": entity,
            "team_name": entity,
            "team_ids": incident.team_ids or [],
            "payload": payload,
        }
    return {
        "id": incident.pk,
        "incident_id": incident.pk,
        "type": "Exces de recurs",
        "title": _resource_label(incident.resource_id),
        "summary": f"{incident.locals_count}/{incident.capacity} locals assignats",
        "description": f"{incident.locals_count}/{incident.capacity} locals assignats",
        "impact": f"+{incident.excess}",
        "count": incident.excess,
        "severity": incident.severity,
        "status": incident.get_status_display(),
        "resource": _resource_label(incident.resource_id),
        "venue": _resource_label(incident.resource_id),
        "league": _top_league_label(payload.get("league_counts")),
        "competition": _top_league_label(payload.get("league_counts")),
        "team": "-",
        "team_name": "-",
        "team_ids": incident.team_ids or [],
        "payload": payload,
    }


def _league_summaries(workspace: AssignmentWorkspace) -> list[dict[str, Any]]:
    teams_by_league: Counter[str] = Counter()
    for assignment in WorkspaceAssignment.objects.filter(workspace=workspace):
        teams_by_league[_assignment_competition_label(assignment)] += 1

    incidents_by_league: Counter[str] = Counter()
    excess_by_league: Counter[str] = Counter()
    for incident in WorkspaceResourceIncident.objects.filter(workspace=workspace):
        league_counts = (incident.payload or {}).get("league_counts")
        if not isinstance(league_counts, dict) or not league_counts:
            incidents_by_league["Sense lliga"] += 1
            excess_by_league["Sense lliga"] += incident.excess
            continue
        for league, count in league_counts.items():
            incidents_by_league[str(league)] += 1
            excess_by_league[str(league)] += int(count or 0)

    labels = set(teams_by_league) | set(incidents_by_league)
    rows = [
        {
            "name": label,
            "league": label,
            "teams": teams_by_league.get(label, 0),
            "team_count": teams_by_league.get(label, 0),
            "incidents": incidents_by_league.get(label, 0),
            "incident_count": incidents_by_league.get(label, 0),
            "resource_pressure": excess_by_league.get(label, 0),
            "pressure": excess_by_league.get(label, 0),
        }
        for label in labels
    ]
    return sorted(rows, key=lambda row: (row["incidents"], row["resource_pressure"], row["teams"]), reverse=True)[:50]


def _assignment_summaries(workspace: AssignmentWorkspace) -> list[dict[str, Any]]:
    rows = []
    for assignment in WorkspaceAssignment.objects.filter(workspace=workspace).order_by("group_id", "assigned_number", "team_name"):
        payload = assignment.payload or {}
        team = payload.get("team") if isinstance(payload.get("team"), dict) else {}
        home_resources = payload.get("home_resources") if isinstance(payload.get("home_resources"), list) else []
        resource_excess = sum(int(row.get("excess") or 0) for row in home_resources if isinstance(row, dict))
        shared_count = sum(1 for row in home_resources if isinstance(row, dict) and row.get("sharing_teams"))
        resource_labels = [
            str(row.get("resource") or "")
            for row in home_resources
            if isinstance(row, dict) and row.get("resource")
        ]
        resource_text = " ".join(
            str(row.get("resource") or row.get("resource_id") or "")
            for row in home_resources
            if isinstance(row, dict)
        )
        competition = _assignment_competition_label(assignment)
        rows.append(
            {
                "team_id": assignment.team_id,
                "team_name": assignment.team_name,
                "entity": assignment.entity,
                "competition": competition,
                "league_name": str(team.get("league_name") or ""),
                "modality": str(team.get("modality") or ""),
                "category": str(team.get("category") or ""),
                "subcategory": str(team.get("subcategory") or ""),
                "level": str(team.get("level") or ""),
                "venue": str(team.get("venue") or ""),
                "day": str(team.get("day") or ""),
                "time": str(team.get("time") or ""),
                "group_id": assignment.group_id,
                "number": assignment.assigned_number,
                "seed_request_original": assignment.seed_request_original or "",
                "home_resources": len(home_resources),
                "home_resource_labels": resource_labels[:4],
                "resource_excess": resource_excess,
                "shared_resources": shared_count,
                "has_resource_excess": resource_excess > 0,
                "has_shared_resources": shared_count > 0,
                "resource_text": resource_text,
                "filter_text": " ".join(
                    [
                        assignment.team_id,
                        assignment.team_name,
                        assignment.entity,
                        competition,
                        str(team.get("league_name") or ""),
                        str(team.get("modality") or ""),
                        str(team.get("category") or ""),
                        str(team.get("subcategory") or ""),
                        str(team.get("level") or ""),
                        str(team.get("venue") or ""),
                        str(team.get("day") or ""),
                        str(team.get("time") or ""),
                        assignment.group_id,
                        str(assignment.assigned_number or ""),
                        resource_text,
                    ]
                ),
                "explanation": _team_explanation(
                    assignment,
                    [row for row in home_resources if isinstance(row, dict)],
                    payload.get("selected_candidate") if isinstance(payload.get("selected_candidate"), dict) else {},
                ),
            }
        )
    return rows


def _venue_pressure_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    prepared = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        resource_id = str(row.get("resource_id") or "")
        if not resource_id:
            continue
        prepared[resource_id] = {
            "resource_id": resource_id,
            "venue": str(row.get("venue") or ""),
            "day": str(row.get("day") or ""),
            "hour_slot": str(row.get("hour_slot") or ""),
            "estimated_capacity": max(1, int(_number(row.get("estimated_capacity")) or 1)),
            "demand_count": int(_number(row.get("demand_count"))),
            "team_ids": [str(team_id) for team_id in (row.get("teams") or row.get("team_ids") or [])],
        }
    return prepared


def _venue_sheet_meta(pressure_rows: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    venues: dict[str, dict[str, Any]] = {}
    for row in pressure_rows.values():
        venue = str(row.get("venue") or "")
        venue_key = _venue_key(venue)
        meta = venues.setdefault(venue_key, _empty_venue_meta(venue or "-", venue_key))
        estimated_capacity = int(row.get("estimated_capacity") or 1)
        demand_count = int(row.get("demand_count") or 0)
        meta["max_capacity"] = max(int(meta["max_capacity"]), estimated_capacity)
        meta["max_demand_count"] = max(int(meta["max_demand_count"]), demand_count)
        meta["requested_team_ids"].update(str(team_id) for team_id in row.get("team_ids", []))
        meta["slots"].append(
            {
                "day": str(row.get("day") or ""),
                "hour_slot": str(row.get("hour_slot") or ""),
                "estimated_capacity": estimated_capacity,
                "demand_count": demand_count,
                "demand_per_court": round(demand_count / estimated_capacity, 2) if estimated_capacity else 0,
            }
        )

    for meta in venues.values():
        meta["slots"] = sorted(meta["slots"], key=lambda item: (_day_order(item["day"]), _time_order(item["hour_slot"]), item["day"], item["hour_slot"]))
        meta["slot_count"] = len(meta["slots"])
        meta["requested_team_count"] = len(meta["requested_team_ids"])
        meta["requested_team_ids"] = sorted(meta["requested_team_ids"])
    return venues


def _empty_venue_meta(venue: str, venue_key: str) -> dict[str, Any]:
    return {
        "venue": venue,
        "venue_key": venue_key,
        "max_capacity": 1,
        "max_demand_count": 0,
        "requested_team_ids": set(),
        "requested_team_count": 0,
        "slot_count": 0,
        "slots": [],
    }


def _fallback_pressure_row(base_resource_id: str) -> dict[str, Any]:
    parts = [part for part in str(base_resource_id).split("|") if part]
    return {
        "resource_id": base_resource_id,
        "venue": parts[0] if len(parts) > 0 else base_resource_id,
        "day": parts[1] if len(parts) > 1 else "",
        "hour_slot": parts[2] if len(parts) > 2 else "",
        "estimated_capacity": 1,
        "demand_count": 0,
        "team_ids": [],
    }


def _venue_sheet_match(
    match: WorkspaceResourceMatch,
    assignments: dict[str, WorkspaceAssignment],
) -> dict[str, Any]:
    home_assignment = assignments.get(match.home_team_id)
    away_assignment = assignments.get(match.away_team_id)
    return {
        "id": match.pk,
        "group_id": match.group_id,
        "home_team_id": match.home_team_id,
        "away_team_id": match.away_team_id,
        "home_team": _team_label(match.home_team_id, match.payload.get("home_team_name", "") or (home_assignment.team_name if home_assignment else "")),
        "away_team": _team_label(match.away_team_id, match.payload.get("away_team_name", "") or (away_assignment.team_name if away_assignment else "")),
        "home_team_name": match.payload.get("home_team_name", "") or (home_assignment.team_name if home_assignment else match.home_team_id),
        "away_team_name": match.payload.get("away_team_name", "") or (away_assignment.team_name if away_assignment else match.away_team_id),
        "competition": _assignment_competition_label(home_assignment) if home_assignment else "",
        "modality": _assignment_modality(home_assignment) if home_assignment else "",
        "home_entity": home_assignment.entity if home_assignment else "",
    }


def _slot_key(day: str, hour_slot: str) -> str:
    return f"{day}||{hour_slot}"


def _venue_key(venue: str) -> str:
    return str(venue or "-").strip().casefold()


def _filter_token(value: str) -> str:
    return str(value or "").strip().casefold().replace(" ", "-")


def _assignment_modality(assignment: WorkspaceAssignment | None) -> str:
    if assignment is None:
        return ""
    team = (assignment.payload or {}).get("team")
    if not isinstance(team, dict):
        return ""
    return str(team.get("modality") or "").strip()


def _round_number(round_label: str) -> int | None:
    text = str(round_label or "").strip().lstrip("Jj")
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _pct(value: int, total: int) -> int:
    return int(round((value / total) * 100)) if total else 0


def _day_order(day: str) -> int:
    key = str(day or "").strip().casefold()
    order = {
        "dilluns": 1,
        "dimarts": 2,
        "dimecres": 3,
        "dijous": 4,
        "divendres": 5,
        "dissabte": 6,
        "diumenge": 7,
    }
    return order.get(key, 99)


def _time_order(value: str) -> tuple[int, str]:
    text = str(value or "")
    parts = text.replace("-", ":").split(":")
    try:
        return (int(parts[0]) * 60 + int(parts[1]), text)
    except (IndexError, TypeError, ValueError):
        return (9999, text)


def _text_sort(value: str) -> str:
    return str(value or "").casefold()


def _team_lookup(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("team_id")): _json_safe(row) for row in rows if row.get("team_id") is not None}


def _candidate_lookup(rows: list[dict[str, Any]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    lookup = {}
    for row in rows:
        number = _int_or_none(row.get("number"))
        if row.get("team_id") is None or row.get("group_id") is None or number is None:
            continue
        lookup[(str(row.get("team_id")), str(row.get("group_id")), number)] = _json_safe(row)
    return lookup


def _pressure_lookup(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("resource_id")): _json_safe(row) for row in rows if row.get("resource_id") is not None}


def _usage_lookup(rows: list[Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("resource_id")): _json_safe(row)
        for row in rows
        if isinstance(row, dict) and row.get("resource_id") is not None
    }


def _assignment_home_resources(
    candidate: dict[str, Any],
    pressure: dict[str, dict[str, Any]],
    usage_by_resource: dict[str, dict[str, Any]],
    teams: dict[str, dict[str, Any]],
    team_id: str,
) -> list[dict[str, Any]]:
    rounds = _list(candidate.get("potential_home_rounds"))
    resources = _list(candidate.get("potential_resources"))
    rows = []
    for index, resource_id_raw in enumerate(resources):
        resource_id = str(resource_id_raw)
        base_resource_id, round_label = _split_resource_round(resource_id)
        pressure_row = pressure.get(base_resource_id, {})
        usage = usage_by_resource.get(resource_id, {})
        sharing_team_ids = [str(value) for value in (usage.get("team_ids") or usage.get("teams") or [])]
        peers = [
            _team_label(peer_id, str(teams.get(peer_id, {}).get("name") or ""))
            for peer_id in sharing_team_ids
            if peer_id != team_id
        ]
        rows.append(
            {
                "round": rounds[index] if index < len(rounds) else round_label,
                "resource_id": resource_id,
                "resource": _resource_label(resource_id),
                "base_resource_id": base_resource_id,
                "locals_count": int(_number(usage.get("locals_count"))),
                "capacity": int(_number(usage.get("capacity") or pressure_row.get("estimated_capacity"))),
                "excess": int(_number(usage.get("excess"))),
                "pressure": pressure_row.get("pressure", ""),
                "demand_count": pressure_row.get("demand_count", ""),
                "is_critical": bool(pressure_row.get("is_critical", False)),
                "sharing_teams": peers,
            }
        )
    return rows


def _assignment_alternatives(
    team_id: str,
    candidates: dict[tuple[str, str, int], dict[str, Any]],
    pressure: dict[str, dict[str, Any]],
    usage_by_resource: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for (candidate_team_id, group_id, number), candidate in sorted(candidates.items()):
        if candidate_team_id != team_id:
            continue
        resources = [str(resource_id) for resource_id in _list(candidate.get("potential_resources"))]
        current_excess = sum(int(_number(usage_by_resource.get(resource_id, {}).get("excess"))) for resource_id in resources)
        critical_count = sum(
            1
            for resource_id in resources
            if pressure.get(_split_resource_round(resource_id)[0], {}).get("is_critical")
        )
        rows.append(
            {
                "group_id": group_id,
                "number": number,
                "home_rounds": _list(candidate.get("potential_home_rounds")),
                "resources": [_resource_label(resource_id) for resource_id in resources],
                "current_resource_excess": current_excess,
                "critical_resources": critical_count,
            }
        )
    return sorted(rows, key=lambda row: (row["current_resource_excess"], row["critical_resources"], row["group_id"], row["number"]))


def _match_detail(match: WorkspaceResourceMatch) -> dict[str, Any]:
    return {
        "id": match.pk,
        "round": match.round_index,
        "group_id": match.group_id,
        "home_team": _team_label(match.home_team_id, match.payload.get("home_team_name", "")),
        "away_team": _team_label(match.away_team_id, match.payload.get("away_team_name", "")),
        "resource": _resource_label(match.home_resource_id),
    }


def _team_explanation(
    assignment: WorkspaceAssignment,
    resource_rows: list[dict[str, Any]],
    selected_candidate: dict[str, Any],
) -> str:
    clean_rows = [row for row in resource_rows if isinstance(row, dict)]
    excess_rows = [row for row in clean_rows if int(row.get("excess") or 0) > 0]
    shared_rows = [row for row in clean_rows if row.get("sharing_teams")]
    if excess_rows:
        state = f"té incidencia en {len(excess_rows)} recurs/os"
    else:
        state = "no supera cap capacitat final en els seus recursos de local"
    home_rounds = selected_candidate.get("potential_home_rounds") or [row.get("round") for row in clean_rows]
    shared = f" Comparteix recursos amb altres locals en {len(shared_rows)} jornada/es." if shared_rows else ""
    return (
        f"L'equip està assignat al grup {assignment.group_id} amb número {assignment.assigned_number}. "
        f"Aquest número el fa local a les jornades {home_rounds}; amb la solució actual {state}."
        f"{shared}"
    )


def _assignment_competition_label(assignment: WorkspaceAssignment) -> str:
    team = (assignment.payload or {}).get("team")
    return _competition_label(team if isinstance(team, dict) else {})


def _competition_label(team: dict[str, Any]) -> str:
    parts = [
        str(team.get("league_name") or "").strip(),
        str(team.get("modality") or "").strip(),
        str(team.get("category") or "").strip(),
        str(team.get("subcategory") or "").strip(),
    ]
    compact = [part for part in parts if part]
    return " / ".join(compact) if compact else "Sense lliga"


def _top_league_label(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return "-"
    label, count = max(value.items(), key=lambda item: int(item[1] or 0))
    suffix = f" (+{len(value) - 1})" if len(value) > 1 else ""
    return f"{label}{suffix}" if count else str(label)


def _resource_label(resource_id: str) -> str:
    if not resource_id:
        return "-"
    base, round_label = _split_resource_round(resource_id)
    parts = [part for part in base.split("|") if part]
    label = " - ".join(parts) if parts else resource_id
    return f"{label} - {round_label}" if round_label else label


def _split_resource_round(resource_id: str) -> tuple[str, str]:
    if "|J" not in resource_id:
        return resource_id, ""
    base, round_part = resource_id.rsplit("|J", 1)
    return base, f"J{round_part}"


def _slot_label(assignment: WorkspaceAssignment | None) -> str:
    if assignment is None:
        return "-"
    return f"{assignment.group_id} / {assignment.assigned_number}"


def _team_label(team_id: str, name: str = "") -> str:
    if name:
        return f"{name} ({team_id})"
    return team_id or "-"


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text_or_blank(value: Any) -> str:
    safe = _json_safe(value)
    return "" if safe is None else str(safe)


def _json_safe(value: Any) -> Any:
    """Return a PostgreSQL JSON-compatible value.

    Python's json module accepts NaN/Infinity, but PostgreSQL json/jsonb does not.
    Pandas-originated audit payloads can carry those values through json.load.
    """

    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value
