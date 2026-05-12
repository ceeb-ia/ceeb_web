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

HYDRATION_VERSION = 2


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
        workspace.summary = _build_persisted_summary(workspace)
        workspace.status = AssignmentWorkspace.STATUS_ACTIVE
        workspace.source_artifact = "resource_solution"
        workspace.save(update_fields=["summary", "status", "source_artifact", "updated_at"])

    return workspace


def get_workspace_summary(workspace: AssignmentWorkspace) -> dict[str, Any]:
    """Build a compact triage payload for the overview page."""

    if not _workspace_is_current(workspace):
        hydrate_workspace_from_audits(workspace.run, workspace=workspace)

    incident_qs = WorkspaceResourceIncident.objects.filter(
        workspace=workspace,
        incident_type=WorkspaceResourceIncident.TYPE_RESOURCE_EXCESS,
    ).order_by("-excess", "-locals_count", "resource_id")
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


def _build_persisted_summary(workspace: AssignmentWorkspace) -> dict[str, Any]:
    incidents = WorkspaceResourceIncident.objects.filter(workspace=workspace)
    return {
        "hydration_version": HYDRATION_VERSION,
        "assignments": WorkspaceAssignment.objects.filter(workspace=workspace).count(),
        "matches": WorkspaceResourceMatch.objects.filter(workspace=workspace).count(),
        "resource_incidents": incidents.count(),
        "resource_excess_total": sum(incident.excess for incident in incidents),
    }


def _workspace_kpis(workspace: AssignmentWorkspace) -> list[dict[str, Any]]:
    assignments_count = WorkspaceAssignment.objects.filter(workspace=workspace).count()
    matches_count = WorkspaceResourceMatch.objects.filter(workspace=workspace).count()
    incidents = WorkspaceResourceIncident.objects.filter(workspace=workspace)
    excess_total = sum(incident.excess for incident in incidents)
    resource_count = incidents.count()
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
            "label": "Lligues",
            "value": len({row["name"] for row in _league_summaries(workspace)}),
            "status": "neutral",
        },
        {"label": "Workspace", "value": workspace.get_status_display(), "status": "neutral"},
    ]


def _incident_summary(incident: WorkspaceResourceIncident) -> dict[str, Any]:
    payload = incident.payload or {}
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
