"""Persistent workspace helpers for resource-solver runs."""

from __future__ import annotations

from collections import Counter, defaultdict
import math
from pathlib import Path
import re
from typing import Any

from django.db import transaction

from calendaritzacions.domain.phases import phase_calendar, slot_count_for_numbers
from calendaritzacions.django.models import (
    AssignmentWorkspace,
    CalendarizationComponentRun,
    CalendarizationRun,
    WorkspaceAssignment,
    WorkspaceResourceIncident,
    WorkspaceResourceMatch,
)
from calendaritzacions.django.services.audit_reader import discover_audit_paths, read_json_file

HYDRATION_VERSION = 8
MAX_POSITIVE_SMALLINT = 32767
ENGINE_RESOURCE_SOLVER_PATTERN_MASTER = getattr(
    CalendarizationRun,
    "ENGINE_RESOURCE_SOLVER_PATTERN_MASTER",
    "resource_solver_pattern_master",
)
RESOURCE_WORKSPACE_ENGINES = {
    CalendarizationRun.ENGINE_LEGACY,
    CalendarizationRun.ENGINE_RESOURCE_SOLVER,
    CalendarizationRun.ENGINE_RESOURCE_SOLVER_LINKAGE,
    CalendarizationRun.ENGINE_RESOURCE_SOLVER_VINCULACIO,
    CalendarizationRun.ENGINE_RESOURCE_SOLVER_CONFLICT_REPAIR,
    ENGINE_RESOURCE_SOLVER_PATTERN_MASTER,
}


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
            source_artifact=_workspace_solution_artifact(run),
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
    if run.engine_name == CalendarizationRun.ENGINE_LEGACY:
        return _hydrate_legacy_workspace_from_kpis(run, workspace=workspace)

    payloads = _read_payloads(run)
    solution = payloads["resource_solution"]
    teams = _team_lookup(payloads["team_catalog"])
    candidates = _candidate_lookup(payloads["candidate_catalog"])
    pressure = _pressure_lookup(payloads["resource_pressure"])
    assignments = _list(solution.get("assignments"))
    matches = _list(solution.get("real_matches"))
    usage_rows = _list(solution.get("resource_usage"))
    solver_explanations = payloads.get("solver_explanations") if isinstance(payloads.get("solver_explanations"), dict) else {}
    usage_by_resource = _usage_lookup(usage_rows)

    with transaction.atomic():
        WorkspaceResourceIncident.objects.filter(workspace=workspace).delete()
        WorkspaceResourceMatch.objects.filter(workspace=workspace).delete()
        WorkspaceAssignment.objects.filter(workspace=workspace).delete()

        _create_assignments(workspace, assignments, teams, candidates, pressure, usage_by_resource)
        created_matches = _create_matches(workspace, matches, teams)
        _create_resource_incidents(workspace, usage_rows, created_matches, teams)
        _create_entity_conflict_incidents(workspace, solution, teams)
        _create_linkage_violation_incidents(workspace, solution, solver_explanations, teams)
        _create_level_mismatch_incidents(workspace, solver_explanations, teams)
        workspace.summary = _build_persisted_summary(workspace)
        workspace.status = AssignmentWorkspace.STATUS_ACTIVE
        workspace.source_artifact = str(payloads.get("resource_solution_artifact") or _workspace_solution_artifact(run))
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
    if incident.incident_type == WorkspaceResourceIncident.TYPE_LINKAGE_VIOLATION:
        return _linkage_violation_incident_detail(workspace, incident)
    if incident.incident_type == WorkspaceResourceIncident.TYPE_LEVEL_MISMATCH:
        return _level_mismatch_incident_detail(workspace, incident)
    if incident.incident_type == WorkspaceResourceIncident.TYPE_SEED_DEVIATION:
        return _seed_deviation_incident_detail(workspace, incident)

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


def _linkage_violation_incident_detail(
    workspace: AssignmentWorkspace,
    incident: WorkspaceResourceIncident,
) -> dict[str, Any]:
    payload = incident.payload or {}
    team_ids = [str(team_id) for team_id in (incident.team_ids or [])]
    assignments = {
        assignment.team_id: assignment
        for assignment in WorkspaceAssignment.objects.filter(
            workspace=workspace,
            team_id__in=team_ids,
        )
    }
    group_ids = {assignment.group_id for assignment in assignments.values() if assignment.group_id}
    matches = list(
        WorkspaceResourceMatch.objects.filter(
            workspace=workspace,
            group_id__in=group_ids,
        ).order_by("group_id", "round_index", "id")
    )
    team_calendars = []
    affected_matches = []
    for team in _list(payload.get("teams")):
        if not isinstance(team, dict):
            continue
        team_id = str(team.get("team_id") or "")
        if not team_id:
            continue
        assignment = assignments.get(team_id)
        team_matches = []
        for match in matches:
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
            team_matches.append(row)
            affected_matches.append(row)
        team_calendars.append(
            {
                "team_id": team_id,
                "team_name": str(team.get("team_name") or (assignment.team_name if assignment else team_id)),
                "number": team.get("assigned_number") or (assignment.assigned_number if assignment else None),
                "group_id": team.get("group_id") or (assignment.group_id if assignment else ""),
                "side": team.get("side") or "-",
                "calendar": team_matches,
            }
        )

    unique_matches = {row["id"]: row for row in affected_matches}
    times = payload.get("times")
    times_text = ", ".join(str(value) for value in times) if isinstance(times, list) else str(times or "-")
    return {
        **_incident_summary(incident),
        "detail": (
            "La solucio final incompleix una relacio de linkage entre equips. "
            "A sota es mostren els equips implicats i el seu calendari materialitzat quan esta disponible."
        ),
        "facts": [
            {"label": "Seu", "value": payload.get("venue") or "-"},
            {"label": "Dia", "value": payload.get("day") or "-"},
            {"label": "Hores", "value": times_text},
            {"label": "Grup linkage", "value": payload.get("linkage_group") or "-"},
            {"label": "Relacio esperada", "value": payload.get("expected_relation") or "-"},
            {"label": "Cost violacio", "value": payload.get("violation_cost") or incident.excess},
        ],
        "affected_matches": list(unique_matches.values()),
        "team_calendars": sorted(
            team_calendars,
            key=lambda row: (str(row.get("group_id") or ""), row.get("number") or 9999, row.get("team_name") or ""),
        ),
        "recommendations": [
            "Revisar els numeros assignats dels equips en el mateix grup de linkage.",
            "Comparar els calendaris dels equips implicats abans de canviar grup o numero.",
            "Si el cost es menor que altres pressions, deixar la incidencia marcada per decisio manual.",
        ],
    }


def _level_mismatch_incident_detail(
    workspace: AssignmentWorkspace,
    incident: WorkspaceResourceIncident,
) -> dict[str, Any]:
    payload = incident.payload or {}
    calendar_explanation = payload.get("calendar_explanation") if isinstance(payload.get("calendar_explanation"), dict) else {}
    inevitability = calendar_explanation.get("inevitability") if isinstance(calendar_explanation.get("inevitability"), dict) else {}
    team_ids = [str(team_id) for team_id in (incident.team_ids or [])]
    assignments = {
        assignment.team_id: assignment
        for assignment in WorkspaceAssignment.objects.filter(
            workspace=workspace,
            team_id__in=team_ids,
        )
    }
    group_id = str(payload.get("group_id") or "")
    group_matches = list(
        WorkspaceResourceMatch.objects.filter(
            workspace=workspace,
            group_id=group_id,
        ).order_by("round_index", "id")
    )
    team_calendars = []
    affected_matches = []
    for team in _list(payload.get("teams")):
        if not isinstance(team, dict):
            continue
        team_id = str(team.get("team_id") or "")
        if not team_id:
            continue
        assignment = assignments.get(team_id)
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
                "team_name": str(team.get("team_name") or (assignment.team_name if assignment else team_id)),
                "number": team.get("assigned_number") or (assignment.assigned_number if assignment else None),
                "group_id": team.get("group_id") or group_id or (assignment.group_id if assignment else ""),
                "raw_level": team.get("raw_level") or "-",
                "normalized_level": team.get("normalized_level") or "-",
                "calendar": calendar,
            }
        )

    unique_matches = {row["id"]: row for row in affected_matches}
    return {
        **_incident_summary(incident),
        "detail": (
            "El grup combina equips amb nivells normalitzats incompatibles segons la restriccio de nivell. "
            "La incidencia es soft: el solver ha prioritzat altres restriccions o no ha trobat una alternativa millor."
        ),
        "facts": [
            {"label": "Grup", "value": group_id or "-"},
            {"label": "Familia", "value": _level_families_label(payload)},
            {"label": "Dispersio", "value": payload.get("dispersion") or calendar_explanation.get("dispersion") or "-"},
            {"label": "Cost", "value": payload.get("violation_cost") or incident.excess},
            {"label": "Equips implicats", "value": len(team_ids)},
            {"label": "Nivells", "value": _level_pair_label(payload.get("teams"))},
            {"label": "Inevitabilitat", "value": inevitability.get("status", "-")},
        ],
        "affected_matches": list(unique_matches.values()),
        "team_calendars": sorted(
            team_calendars,
            key=lambda row: (row.get("number") or 9999, row.get("team_name") or ""),
        ),
        "recommendations": [
            "Provar moure un equip implicat a un grup amb nivell normalitzat compatible.",
            "Prioritzar no barrejar A amb no-A quan hi hagi alternativa.",
            "Usar equips B/C com a pont abans de barrejar directament B amb C.",
        ],
    }


def _seed_deviation_incident_detail(
    workspace: AssignmentWorkspace,
    incident: WorkspaceResourceIncident,
) -> dict[str, Any]:
    payload = incident.payload or {}
    team_ids = [str(team_id) for team_id in (incident.team_ids or [])]
    assignments = {
        assignment.team_id: assignment
        for assignment in WorkspaceAssignment.objects.filter(
            workspace=workspace,
            team_id__in=team_ids,
        )
    }
    group_ids = {assignment.group_id for assignment in assignments.values() if assignment.group_id}
    matches = list(
        WorkspaceResourceMatch.objects.filter(
            workspace=workspace,
            group_id__in=group_ids,
        ).order_by("group_id", "round_index", "id")
    )
    affected_rounds = {
        round_index
        for round_index in (_int_or_none(value) for value in _list(payload.get("rounds")))
        if round_index is not None
    }
    affected_matches = []
    team_calendars = []
    for team_id in team_ids:
        assignment = assignments.get(team_id)
        if assignment is None:
            continue
        calendar = []
        for match in matches:
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
                "is_affected_round": bool(match.round_index in affected_rounds),
            }
            calendar.append(row)
            if row["is_affected_round"]:
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

    return {
        **_incident_summary(incident),
        "detail": (
            "El motor legacy ha assignat un numero diferent del numero esperat per la peticio. "
            "La severitat representa les jornades on canvia el patró casa/fora."
        ),
        "facts": [
            {"label": "Equip", "value": payload.get("team_name") or ", ".join(team_ids) or "-"},
            {"label": "Grup", "value": payload.get("group_id") or "-"},
            {"label": "Peticio", "value": payload.get("requested") or "-"},
            {"label": "Numero esperat", "value": payload.get("expected_number") or "-"},
            {"label": "Numero assignat", "value": payload.get("assigned_number") or "-"},
            {"label": "Jornades afectades", "value": payload.get("damage_rounds") or incident.severity},
            {"label": "Detall", "value": payload.get("differences") or "-"},
        ],
        "affected_matches": affected_matches,
        "team_calendars": team_calendars,
        "recommendations": [
            "Comparar el numero esperat amb alternatives del mateix grup abans de moure l'equip.",
            "Prioritzar canvis que redueixin jornades afectades sense crear conflictes d'entitat.",
            "Si la peticio era CASA/FORA, revisar la dupla assignada a l'entitat.",
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
                    "level_label": _workspace_normalized_level_label(fields.get("level", "")),
                    "level_class": _workspace_normalized_level_class(fields.get("level", "")),
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
        level_summary = _calendar_level_summary(rows)
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
                "level_summary": level_summary,
                "has_level_dispersion": len([item for item in level_summary if item["token"] != "sense-nivell"]) > 1,
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


def get_workspace_linkage_view(workspace: AssignmentWorkspace) -> dict[str, Any]:
    """Return linkage groups with assigned teams, context and violations."""

    if not _workspace_is_current(workspace):
        hydrate_workspace_from_audits(workspace.run, workspace=workspace)

    assignments = list(
        WorkspaceAssignment.objects.filter(workspace=workspace).order_by(
            "team_name",
            "team_id",
        )
    )
    matches_by_team: dict[str, list[WorkspaceResourceMatch]] = defaultdict(list)
    for match in WorkspaceResourceMatch.objects.filter(workspace=workspace).order_by("round_index", "group_id", "id"):
        if match.home_team_id:
            matches_by_team[match.home_team_id].append(match)
        if match.away_team_id:
            matches_by_team[match.away_team_id].append(match)

    linkage_incidents = list(
        WorkspaceResourceIncident.objects.filter(
            workspace=workspace,
            incident_type=WorkspaceResourceIncident.TYPE_LINKAGE_VIOLATION,
        ).order_by("-severity", "id")
    )

    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    filter_values: dict[str, set[str]] = {
        "group": set(),
        "venue": set(),
        "source": set(),
        "status": set(),
    }
    for assignment in assignments:
        team = _assignment_team(assignment)
        linkage = _assignment_linkage_fields(assignment, team)
        linkage_group = linkage["group"]
        if not linkage_group:
            continue

        venue = _assignment_venue(assignment, team)
        day = str(team.get("day") or "").strip()
        time = str(team.get("time") or "").strip()
        key = (venue, day, linkage_group)
        bucket = buckets.setdefault(
            key,
            {
                "linkage_group": linkage_group,
                "venue": venue,
                "venue_key": _venue_key(venue),
                "day": day,
                "times": set(),
                "sources": set(),
                "competitions": set(),
                "modalities": set(),
                "teams": [],
                "incident_ids": set(),
                "filter_text_parts": [],
            },
        )
        if time:
            bucket["times"].add(time)
        if linkage["source"]:
            bucket["sources"].add(linkage["source"])
        competition = _assignment_competition_label(assignment)
        if competition:
            bucket["competitions"].add(competition)
        modality = str(team.get("modality") or "").strip()
        if modality:
            bucket["modalities"].add(modality)

        team_matches = [_linkage_match_row(match, assignment.team_id) for match in matches_by_team.get(assignment.team_id, [])]
        team_row = {
            "team_id": assignment.team_id,
            "team_name": assignment.team_name or assignment.team_id,
            "entity": assignment.entity,
            "competition": competition,
            "modality": modality,
            "category": str(team.get("category") or "").strip(),
            "subcategory": str(team.get("subcategory") or "").strip(),
            "level": str(team.get("level") or "").strip(),
            "venue": venue,
            "day": day,
            "time": time,
            "group_id": assignment.group_id,
            "number": assignment.assigned_number,
            "side": linkage["side"],
            "side_label": _linkage_side_label(linkage["side"]),
            "source": linkage["source"],
            "source_label": _linkage_source_label(linkage["source"]),
            "matches": team_matches,
            "match_count": len(team_matches),
        }
        bucket["teams"].append(team_row)
        bucket["filter_text_parts"].extend(
            [
                assignment.team_id,
                assignment.team_name,
                assignment.entity,
                competition,
                modality,
                team_row["category"],
                team_row["subcategory"],
                team_row["level"],
                venue,
                day,
                time,
                assignment.group_id,
                assignment.assigned_number,
                linkage_group,
                linkage["side"],
                linkage["source"],
            ]
        )

    for incident in linkage_incidents:
        payload = incident.payload or {}
        incident_group = str(payload.get("linkage_group") or "").strip()
        incident_team_ids = {str(team_id) for team_id in (incident.team_ids or [])}
        for bucket in buckets.values():
            if incident_group and incident_group != bucket["linkage_group"]:
                continue
            bucket_team_ids = {team["team_id"] for team in bucket["teams"]}
            if bucket_team_ids & incident_team_ids:
                bucket["incident_ids"].add(incident.pk)

    groups = []
    for (_venue, _day, linkage_group), bucket in sorted(
        buckets.items(),
        key=lambda item: (_text_sort(item[0][0]), _day_order(item[0][1]), _text_sort(item[0][2])),
    ):
        incident_ids = sorted(bucket["incident_ids"])
        status = "violation" if incident_ids else "ok"
        times = sorted(bucket["times"], key=_time_order)
        sources = sorted(bucket["sources"], key=_text_sort)
        teams = sorted(
            bucket["teams"],
            key=lambda row: (
                row["number"] if row["number"] is not None else 9999,
                _text_sort(row["team_name"]),
                row["team_id"],
            ),
        )
        for team in teams:
            team["has_violation"] = team["team_id"] in {
                str(team_id)
                for incident in linkage_incidents
                if incident.pk in incident_ids
                for team_id in (incident.team_ids or [])
            }

        filter_values["group"].add(linkage_group)
        if bucket["venue"]:
            filter_values["venue"].add(bucket["venue"])
        for source in sources:
            filter_values["source"].add(source)
        filter_values["status"].add(status)
        filter_text = _calendar_filter_text(bucket["filter_text_parts"])
        groups.append(
            {
                "linkage_group": linkage_group,
                "group_token": _filter_token(linkage_group),
                "venue": bucket["venue"],
                "venue_key": bucket["venue_key"],
                "venue_token": _filter_token(bucket["venue"]),
                "day": bucket["day"],
                "times": times,
                "times_label": ", ".join(times) if times else "-",
                "sources": sources,
                "source_tokens": " ".join(_filter_token(source) for source in sources),
                "source_label": ", ".join(_linkage_source_label(source) for source in sources) if sources else "-",
                "competitions": sorted(bucket["competitions"], key=_text_sort),
                "modalities": sorted(bucket["modalities"], key=_text_sort),
                "teams": teams,
                "team_count": len(teams),
                "incident_ids": incident_ids,
                "incident_count": len(incident_ids),
                "status": status,
                "status_label": "Amb violacio" if status == "violation" else "Correcte",
                "filter_text": filter_text,
            }
        )

    filters = {
        key: [{"label": value, "token": _filter_token(value)} for value in sorted(values, key=_text_sort)]
        for key, values in filter_values.items()
    }
    filters["statuses"] = [
        {"label": "Correcte", "token": "ok"},
        {"label": "Amb violacio", "token": "violation"},
    ]
    return {
        "groups": groups,
        "filters": filters,
        "group_count": len(groups),
        "team_count": sum(group["team_count"] for group in groups),
        "violation_count": sum(group["incident_count"] for group in groups),
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
        sheet_linkage_groups = set()
        for slot in meta.get("slots", []):
            slot_key = _slot_key(slot["day"], slot["hour_slot"])
            matches = list(sheet["slots"].get(slot_key, []))
            sheet_modalities.update(match["modality"] for match in matches if match.get("modality"))
            for match in matches:
                sheet_linkage_groups.update(match.get("linkage_groups") or [])
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
                "linkage_groups": sorted(sheet_linkage_groups, key=_text_sort),
                "linkage_group_count": len(sheet_linkage_groups),
                "modality_filter": " ".join(sorted({_filter_token(value) for value in sheet_modalities if value})),
                "linkage_filter": " ".join(sorted({_filter_token(value) for value in sheet_linkage_groups if value})),
            }
        )

    modalities = sorted({modality for sheet in sheets for modality in sheet.get("modalities", [])}, key=_text_sort)
    linkage_groups = sorted(
        {group for sheet in sheets for group in sheet.get("linkage_groups", [])},
        key=_text_sort,
    )
    return {
        "sheets": sheets,
        "venues": sorted(venue_meta.values(), key=lambda item: _text_sort(item["venue"])),
        "rounds": sorted({sheet["round"] for sheet in sheets}),
        "modalities": [{"label": modality, "token": _filter_token(modality)} for modality in modalities],
        "linkage_groups": [{"label": group, "token": _filter_token(group)} for group in linkage_groups],
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
        "level": _workspace_level_label(team.get("level")),
        "level_raw": str(team.get("level") or "").strip(),
        "entity": assignment.entity.strip(),
        "venue": _assignment_venue(assignment, team),
    }


def _assignment_linkage_fields(
    assignment: WorkspaceAssignment,
    team: dict[str, Any] | None = None,
) -> dict[str, str]:
    payload = assignment.payload or {}
    team = team if isinstance(team, dict) else _assignment_team(assignment)
    return {
        "group": str(team.get("linkage_group") or payload.get("linkage_group") or "").strip(),
        "side": str(team.get("linkage_side") or payload.get("linkage_side") or "").strip(),
        "source": str(team.get("linkage_source") or payload.get("linkage_source") or "").strip(),
    }


def _linkage_match_row(match: WorkspaceResourceMatch, team_id: str) -> dict[str, Any]:
    is_home = match.home_team_id == team_id
    opponent_id = match.away_team_id if is_home else match.home_team_id
    opponent_name = match.payload.get("away_team_name" if is_home else "home_team_name", "")
    return {
        "id": match.pk,
        "round": match.round_index,
        "group_id": match.group_id,
        "side": "Casa" if is_home else "Fora",
        "opponent_id": opponent_id,
        "opponent": _team_label(opponent_id, opponent_name),
        "resource": _resource_label(match.home_resource_id) if is_home else "-",
    }


def _linkage_side_label(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    labels = {
        "casa": "Casa",
        "fora": "Fora",
        "indiferent": "Indiferent",
    }
    return labels.get(normalized, value or "-")


def _linkage_source_label(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    labels = {
        "input": "Input",
        "simulated": "Simulat",
        "simulated_resource_solver": "Simulat",
    }
    return labels.get(normalized, value or "-")


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
    keys = ("competition", "league", "modality", "category", "subcategory", "level", "level_raw", "entity", "venue")
    return {key: _common_text(row.get(key, "") for row in rows) for key in keys}


def _calendar_level_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(_workspace_normalized_level_label(row.get("level") or row.get("level_raw")) for row in rows)
    order = {"A": 0, "B": 1, "B/C": 2, "C": 3, "Sense nivell": 4}
    return [
        {
            "label": label,
            "count": count,
            "token": _filter_token(label),
            "class": _workspace_level_class_for_label(label),
        }
        for label, count in sorted(counts.items(), key=lambda item: (order.get(item[0], 99), item[0]))
        if count
    ]


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
    if run.engine_name not in RESOURCE_WORKSPACE_ENGINES:
        raise ValueError("El workspace nomes esta disponible pels motors calendaritzables.")


def _workspace_solution_artifact(run: CalendarizationRun) -> str:
    if run.engine_name == CalendarizationRun.ENGINE_LEGACY:
        return "kpis"
    if run.engine_name == CalendarizationRun.ENGINE_RESOURCE_SOLVER_CONFLICT_REPAIR:
        return "resource_solver_conflict_repair_result"
    if run.engine_name == ENGINE_RESOURCE_SOLVER_PATTERN_MASTER:
        return "resource_solver_pattern_master_result"
    return "resource_solution"


def _workspace_is_hydrated(workspace: AssignmentWorkspace) -> bool:
    return (
        WorkspaceAssignment.objects.filter(workspace=workspace).exists()
        or WorkspaceResourceIncident.objects.filter(workspace=workspace).exists()
        or WorkspaceResourceMatch.objects.filter(workspace=workspace).exists()
    )


def _workspace_is_current(workspace: AssignmentWorkspace) -> bool:
    return _workspace_is_hydrated(workspace) and (workspace.summary or {}).get("hydration_version") == HYDRATION_VERSION


def _hydrate_legacy_workspace_from_kpis(
    run: CalendarizationRun,
    *,
    workspace: AssignmentWorkspace,
) -> AssignmentWorkspace:
    payload = _read_legacy_kpis(run)
    analysis_rows = _list_dicts(payload.get("analysis_rows"))
    phase = _legacy_phase_calendar(run, payload, analysis_rows)
    records = _legacy_assignment_records(analysis_rows, phase)

    with transaction.atomic():
        WorkspaceResourceIncident.objects.filter(workspace=workspace).delete()
        WorkspaceResourceMatch.objects.filter(workspace=workspace).delete()
        WorkspaceAssignment.objects.filter(workspace=workspace).delete()

        _create_legacy_assignments(workspace, records, phase)
        _create_legacy_matches(workspace, records, phase)
        _create_legacy_seed_deviation_incidents(workspace, records)
        _create_legacy_entity_conflict_incidents(workspace, payload)
        _create_legacy_level_mismatch_incidents(workspace, payload)
        workspace.summary = _build_persisted_summary(workspace)
        workspace.status = AssignmentWorkspace.STATUS_ACTIVE
        workspace.source_artifact = "kpis"
        workspace.save(update_fields=["summary", "status", "source_artifact", "updated_at"])

    return workspace


def _read_legacy_kpis(run: CalendarizationRun) -> dict[str, Any]:
    audit_paths = dict(run.audit_paths or {}) if isinstance(run.audit_paths, dict) else {}
    candidates = [
        run.kpis_path,
        audit_paths.get("kpis"),
        audit_paths.get("kpi"),
    ]
    if run.output_path:
        discovered = discover_audit_paths(run.output_path)
        candidates.extend(
            path
            for key, path in discovered.items()
            if key == "kpis" or str(key).startswith("kpis_")
        )
    for path in candidates:
        if not path:
            continue
        payload = read_json_file(str(Path(path)))
        if isinstance(payload, dict):
            return payload
    return {}


def _legacy_phase_calendar(
    run: CalendarizationRun,
    payload: dict[str, Any],
    analysis_rows: list[dict[str, Any]],
) -> tuple[tuple[tuple[int, int], ...], ...]:
    numbers = [
        number
        for number in (_int_or_none(row.get("numero_assignat")) for row in analysis_rows)
        if number is not None
    ]
    phase_name = str(payload.get("fase") or run.phase or CalendarizationRun.PHASE_FIRST)
    try:
        return phase_calendar(phase_name, slot_count_for_numbers(numbers))
    except Exception:
        return phase_calendar(phase_name, 8)


def _legacy_assignment_records(
    analysis_rows: list[dict[str, Any]],
    phase: tuple[tuple[tuple[int, int], ...], ...],
) -> list[dict[str, Any]]:
    records = []
    used_ids: set[str] = set()
    for index, row in enumerate(analysis_rows):
        team_name = _first_legacy_text(row, ("Equip", "Nom", "team_name", "name"))
        if not team_name or team_name == "DESCANS":
            continue
        assigned_number = _int_or_none(row.get("numero_assignat"))
        group_id = _first_legacy_text(row, ("Grup", "group_id"))
        if assigned_number is None or not group_id:
            continue
        team_id = _legacy_team_id(row, index, used_ids)
        team = _legacy_team_payload(row, team_id, team_name)
        home_rounds = _legacy_home_rounds(assigned_number, phase)
        home_resources = [
            _legacy_home_resource_row(team, group_id, round_index)
            for round_index in home_rounds
        ]
        selected_candidate = {
            "team_id": team_id,
            "group_id": group_id,
            "number": assigned_number,
            "potential_home_rounds": home_rounds,
            "potential_resources": [row["resource_id"] for row in home_resources],
        }
        records.append(
            {
                "row": row,
                "team_id": team_id,
                "team_name": team_name,
                "entity": _first_legacy_text(row, ("Entitat", "entity")) or "Sense entitat",
                "group_id": group_id,
                "assigned_number": assigned_number,
                "seed_request_original": _first_legacy_text(row, ("peticio", "Núm. sorteig", "Num. sorteig")),
                "team": team,
                "selected_candidate": selected_candidate,
                "home_resources": home_resources,
            }
        )
    return records


def _create_legacy_assignments(
    workspace: AssignmentWorkspace,
    records: list[dict[str, Any]],
    phase: tuple[tuple[tuple[int, int], ...], ...],
) -> None:
    rows = [
        WorkspaceAssignment(
            workspace=workspace,
            run=workspace.run,
            team_id=record["team_id"],
            team_name=record["team_name"],
            entity=record["entity"],
            group_id=record["group_id"],
            assigned_number=record["assigned_number"],
            previous_group_id=record["group_id"],
            previous_number=record["assigned_number"],
            seed_request_original=record["seed_request_original"],
            payload=_json_safe(
                {
                    "team": record["team"],
                    "selected_candidate": record["selected_candidate"],
                    "home_resources": record["home_resources"],
                    "alternatives": _legacy_alternatives(record["team"], record["group_id"], phase),
                    "legacy_row": record["row"],
                }
            ),
        )
        for record in records
    ]
    if rows:
        WorkspaceAssignment.objects.bulk_create(rows)


def _create_legacy_matches(
    workspace: AssignmentWorkspace,
    records: list[dict[str, Any]],
    phase: tuple[tuple[tuple[int, int], ...], ...],
) -> None:
    by_group_number: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for record in records:
        by_group_number[record["group_id"]][int(record["assigned_number"])] = record

    rows = []
    for group_id, by_number in by_group_number.items():
        for round_index, round_matches in enumerate(phase, start=1):
            for home_number, away_number in round_matches:
                home = by_number.get(int(home_number))
                away = by_number.get(int(away_number))
                if not home or not away:
                    continue
                resource_id = _legacy_resource_id(home["team"], group_id, round_index)
                rows.append(
                    WorkspaceResourceMatch(
                        workspace=workspace,
                        run=workspace.run,
                        round_index=round_index,
                        group_id=group_id,
                        home_team_id=home["team_id"],
                        away_team_id=away["team_id"],
                        home_resource_id=resource_id,
                        payload=_json_safe(
                            {
                                "engine": "legacy",
                                "round_index": round_index,
                                "group_id": group_id,
                                "home_number": home_number,
                                "away_number": away_number,
                                "home_team_name": home["team_name"],
                                "away_team_name": away["team_name"],
                                "resource_id": resource_id,
                            }
                        ),
                    )
                )
    if rows:
        WorkspaceResourceMatch.objects.bulk_create(rows)


def _create_legacy_seed_deviation_incidents(
    workspace: AssignmentWorkspace,
    records: list[dict[str, Any]],
) -> None:
    rows = []
    for record in records:
        row = record["row"]
        severity = _legacy_damage_rounds(row)
        if severity <= 0 and not _truthy(row.get("te_incidencia")):
            continue
        rounds = _legacy_incident_rounds(row)
        expected = _int_or_none(row.get("numero_esperat"))
        assigned = record["assigned_number"]
        league = _legacy_competition_label(record["team"])
        rows.append(
            WorkspaceResourceIncident(
                workspace=workspace,
                run=workspace.run,
                incident_type=WorkspaceResourceIncident.TYPE_SEED_DEVIATION,
                status=WorkspaceResourceIncident.STATUS_OPEN,
                severity=_incident_severity(severity or 1),
                resource_id=f"{record['group_id']}|seed_deviation|{record['team_id']}"[:255],
                excess=0,
                locals_count=severity,
                capacity=0,
                team_ids=[record["team_id"]],
                payload=_json_safe(
                    {
                        "engine": "legacy",
                        "team_id": record["team_id"],
                        "team_name": record["team_name"],
                        "group_id": record["group_id"],
                        "requested": row.get("peticio"),
                        "expected_number": expected,
                        "assigned_number": assigned,
                        "rounds": rounds,
                        "damage_rounds": severity,
                        "differences": row.get("diferencies_jornades"),
                        "league_counts": {league: 1},
                        "resource_label": f"{record['group_id']} - {record['team_name']}",
                    }
                ),
            )
        )
    if rows:
        WorkspaceResourceIncident.objects.bulk_create(rows)


def _create_legacy_entity_conflict_incidents(
    workspace: AssignmentWorkspace,
    payload: dict[str, Any],
) -> None:
    rows = []
    assignments = list(WorkspaceAssignment.objects.filter(workspace=workspace))
    for conflict in _list_dicts(payload.get("conflictes_entitat")):
        group_id = _first_legacy_text(conflict, ("Grup", "group_id"))
        entity = _first_legacy_text(conflict, ("Entitat", "entity"))
        if not group_id or not entity:
            continue
        team_ids = [
            assignment.team_id
            for assignment in assignments
            if assignment.group_id == group_id and assignment.entity == entity
        ]
        if len(team_ids) <= 1:
            continue
        count = _int_or_none(conflict.get("Count")) or len(team_ids)
        excess = max(1, count - 1)
        league_counts = Counter(
            _assignment_competition_label(assignment)
            for assignment in assignments
            if assignment.team_id in team_ids
        )
        rows.append(
            WorkspaceResourceIncident(
                workspace=workspace,
                run=workspace.run,
                incident_type=WorkspaceResourceIncident.TYPE_ASSIGNMENT_CONFLICT,
                status=WorkspaceResourceIncident.STATUS_OPEN,
                severity=_incident_severity(excess),
                resource_id=f"{group_id}|{entity}"[:255],
                excess=excess,
                locals_count=count,
                capacity=1,
                team_ids=team_ids,
                payload=_json_safe(
                    {
                        "engine": "legacy",
                        "entity": entity,
                        "group_id": group_id,
                        "team_slots": [
                            {
                                "team_id": assignment.team_id,
                                "team_name": assignment.team_name,
                                "number": assignment.assigned_number,
                            }
                            for assignment in assignments
                            if assignment.team_id in team_ids
                        ],
                        "league_counts": dict(league_counts),
                    }
                ),
            )
        )
    if rows:
        WorkspaceResourceIncident.objects.bulk_create(rows)


def _create_legacy_level_mismatch_incidents(
    workspace: AssignmentWorkspace,
    payload: dict[str, Any],
) -> None:
    rows = []
    assignments = list(WorkspaceAssignment.objects.filter(workspace=workspace))
    for incident in _list_dicts(payload.get("nivells_dispars")):
        group_id = _first_legacy_text(incident, ("Grup", "group_id"))
        if not group_id:
            continue
        group_assignments = [assignment for assignment in assignments if assignment.group_id == group_id]
        team_ids = [assignment.team_id for assignment in group_assignments]
        if len(team_ids) < 2:
            continue
        dispersion = _int_or_none(incident.get("Dif")) or 1
        league_counts = Counter(_assignment_competition_label(assignment) for assignment in group_assignments)
        rows.append(
            WorkspaceResourceIncident(
                workspace=workspace,
                run=workspace.run,
                incident_type=WorkspaceResourceIncident.TYPE_LEVEL_MISMATCH,
                status=WorkspaceResourceIncident.STATUS_OPEN,
                severity=_incident_severity(dispersion),
                resource_id=f"{group_id}|level_mismatch"[:255],
                excess=dispersion,
                locals_count=len(team_ids),
                capacity=0,
                team_ids=team_ids,
                payload=_json_safe(
                    {
                        "engine": "legacy",
                        "group_id": group_id,
                        "families": [str(incident.get("Nivells") or "")],
                        "dispersion": dispersion,
                        "violation_cost": dispersion,
                        "league_counts": dict(league_counts),
                        "teams": [
                            {
                                "team_id": assignment.team_id,
                                "team_name": assignment.team_name,
                                "group_id": assignment.group_id,
                                "assigned_number": assignment.assigned_number,
                                "raw_level": _assignment_team(assignment).get("level", ""),
                                "normalized_level": _workspace_level_label(_assignment_team(assignment).get("level", "")),
                            }
                            for assignment in group_assignments
                        ],
                    }
                ),
            )
        )
    if rows:
        WorkspaceResourceIncident.objects.bulk_create(rows)


def _legacy_team_payload(row: dict[str, Any], team_id: str, team_name: str) -> dict[str, Any]:
    league = _first_legacy_text(row, ("Categoria", "Nom Lliga", "league_name")) or "Sense lliga"
    return {
        "team_id": team_id,
        "name": team_name,
        "entity": _first_legacy_text(row, ("Entitat", "entity")) or "Sense entitat",
        "league_name": league,
        "modality": _first_legacy_text(row, ("Modalitat", "modality")) or "Sense modalitat",
        "category": _first_legacy_text(row, ("Categoria", "category")),
        "subcategory": _first_legacy_text(row, ("Subcategoria", "subcategory")),
        "level": _first_legacy_text(row, ("Nivell", "level")),
        "venue": _first_legacy_text(row, ("Pista joc", "venue")),
        "day": _first_legacy_text(row, ("Dia partit", "day")),
        "time": _first_legacy_text(row, ("Horari partit", "time")),
        "seed_request_original": _first_legacy_text(row, ("peticio", "request_code")),
    }


def _legacy_team_id(row: dict[str, Any], index: int, used_ids: set[str]) -> str:
    raw = _first_legacy_text(row, ("Id", "team_id", "id"))
    if not raw:
        raw = f"legacy-{index + 1}"
    candidate = raw
    suffix = 2
    while candidate in used_ids:
        candidate = f"{raw}-{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _legacy_home_rounds(
    assigned_number: int,
    phase: tuple[tuple[tuple[int, int], ...], ...],
) -> list[int]:
    rounds = []
    for round_index, round_matches in enumerate(phase, start=1):
        if any(int(home) == int(assigned_number) for home, _away in round_matches):
            rounds.append(round_index)
    return rounds


def _legacy_home_resource_row(team: dict[str, Any], group_id: str, round_index: int) -> dict[str, Any]:
    resource_id = _legacy_resource_id(team, group_id, round_index)
    base_resource_id, _round_label = _split_resource_round(resource_id)
    return {
        "round": round_index,
        "resource_id": resource_id,
        "resource": _resource_label(resource_id),
        "base_resource_id": base_resource_id,
        "locals_count": 0,
        "capacity": 1,
        "excess": 0,
        "pressure": "",
        "demand_count": "",
        "is_critical": False,
        "sharing_teams": [],
    }


def _legacy_resource_id(team: dict[str, Any], group_id: str, round_index: int) -> str:
    venue = _resource_token(team.get("venue") or "legacy")
    day = _resource_token(team.get("day") or group_id or "grup")
    hour = _resource_token(team.get("time") or "sense-hora")
    return f"{venue}|{day}|{hour}|J{round_index}"


def _legacy_alternatives(
    team: dict[str, Any],
    group_id: str,
    phase: tuple[tuple[tuple[int, int], ...], ...],
) -> list[dict[str, Any]]:
    rows = []
    for number in range(1, 9):
        rounds = _legacy_home_rounds(number, phase)
        rows.append(
            {
                "group_id": group_id,
                "number": number,
                "home_rounds": rounds,
                "resources": [_resource_label(_legacy_resource_id(team, group_id, round_index)) for round_index in rounds],
                "current_resource_excess": 0,
                "critical_resources": 0,
            }
        )
    return rows


def _legacy_damage_rounds(row: dict[str, Any]) -> int:
    value = _int_or_none(row.get("dany_jornades"))
    if value is not None:
        return max(0, value)
    value = _int_or_none(row.get("Mismatch jornades"))
    return max(0, value or 0)


def _legacy_incident_rounds(row: dict[str, Any]) -> list[int]:
    text = str(row.get("diferencies_jornades") or row.get("Diferències jornades") or "")
    rounds = []
    for match in re.finditer(r"\bJ\s*(\d+)\b", text, flags=re.IGNORECASE):
        try:
            rounds.append(int(match.group(1)))
        except ValueError:
            continue
    return sorted(set(rounds))


def _legacy_competition_label(team: dict[str, Any]) -> str:
    parts = [
        str(team.get("league_name") or "").strip(),
        str(team.get("modality") or "").strip(),
        str(team.get("category") or "").strip(),
        str(team.get("subcategory") or "").strip(),
    ]
    compact = [part for part in parts if part]
    return " / ".join(compact) if compact else "Sense lliga"


def _first_legacy_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.casefold() not in {"nan", "none", "null", "—", "-"}:
            return text
    return ""


def _resource_token(value: Any) -> str:
    text = str(value or "").strip()
    return re.sub(r"\|+", " ", text) if text else "sense-dada"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().casefold()
    return text in {"1", "true", "yes", "si", "sí"}


def _read_payloads(run: CalendarizationRun) -> dict[str, Any]:
    stored_audit_paths = dict(run.audit_paths or {}) if isinstance(run.audit_paths, dict) else {}
    audit_paths = dict(stored_audit_paths)
    if run.output_path:
        discovered = discover_audit_paths(run.output_path)
        audit_paths = {**discovered, **stored_audit_paths}

    resource_solution_artifact = _workspace_solution_artifact(run)
    resource_solution_path = (
        stored_audit_paths.get(resource_solution_artifact)
        or stored_audit_paths.get("resource_solution")
        or stored_audit_paths.get("component_merged_solution")
        or audit_paths.get(resource_solution_artifact)
        or audit_paths.get("resource_solution")
        or audit_paths.get("component_merged_solution")
    )
    component_context_payloads = (
        _component_context_audit_payloads(run)
        if not audit_paths.get("team_catalog")
        or not audit_paths.get("candidate_catalog")
        or not audit_paths.get("resource_pressure")
        or not audit_paths.get("solver_explanations")
        else {}
    )
    team_catalog = _read_list(audit_paths.get("team_catalog")) or _list_dicts(component_context_payloads.get("team_catalog"))
    candidate_catalog = _read_list(audit_paths.get("candidate_catalog")) or _list_dicts(component_context_payloads.get("candidate_catalog"))
    resource_pressure = _read_list(audit_paths.get("resource_pressure")) or _list_dicts(component_context_payloads.get("resource_pressure"))
    solution = _read_dict(resource_solution_path)
    solver_explanations = _read_dict(audit_paths.get("solver_explanations")) or _dict_value(
        component_context_payloads.get("solver_explanations")
    )
    return {
        "resource_solution": solution,
        "resource_solution_artifact": resource_solution_artifact,
        "team_catalog": team_catalog,
        "candidate_catalog": candidate_catalog,
        "resource_pressure": resource_pressure,
        "solver_explanations": solver_explanations,
    }


def _component_context_audit_payloads(run: CalendarizationRun) -> dict[str, Any]:
    components = [
        component
        for component in CalendarizationComponentRun.objects.filter(run=run).order_by("component_id", "attempt")
        if int(component.attempt) == int(component.active_attempt)
    ]
    if not components:
        return {}
    try:
        from calendaritzacions.django.services.component_tasks import _combined_context_from_components
        from calendaritzacions.django.services.component_tasks import _resource_solver_result_from_payload
        from calendaritzacions.engine.variants.resource_solver.audit import (
            build_candidate_catalog_audit,
            build_resource_pressure_audit,
            build_solver_explanations,
            build_team_catalog_audit,
        )

        context = _combined_context_from_components(components)
        payloads = {
            "team_catalog": build_team_catalog_audit(context),
            "candidate_catalog": build_candidate_catalog_audit(context),
            "resource_pressure": build_resource_pressure_audit(context),
        }
        solution_path = _component_merged_solution_path(run)
        if solution_path:
            solution = _read_dict(solution_path)
            if solution:
                payloads["solver_explanations"] = build_solver_explanations(
                    _resource_solver_result_from_payload(solution),
                    context,
                )
        return payloads
    except Exception:
        return {}


def _component_merged_solution_path(run: CalendarizationRun) -> str:
    audit_paths = dict(run.audit_paths or {}) if isinstance(run.audit_paths, dict) else {}
    path = audit_paths.get("resource_solution") or audit_paths.get("component_merged_solution")
    if path:
        return str(path)
    if run.output_path:
        candidate = Path(run.output_path).parent / "merged" / "merged_solution.json"
        if candidate.exists():
            return str(candidate)
    return ""


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


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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
                severity=_incident_severity(excess),
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
                severity=_incident_severity(excess),
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


def _create_linkage_violation_incidents(
    workspace: AssignmentWorkspace,
    solution: dict[str, Any],
    solver_explanations: dict[str, Any],
    teams: dict[str, dict[str, Any]],
) -> None:
    assignment_numbers = {
        assignment.team_id: assignment
        for assignment in WorkspaceAssignment.objects.filter(workspace=workspace)
    }
    rows = []
    for violation in _linkage_violations_from_audits(solution, solver_explanations):
        team_rows = _linkage_violation_teams(violation, teams, assignment_numbers)
        team_ids = [row["team_id"] for row in team_rows]
        if not team_ids:
            continue
        venue = _first_text(violation, ("venue", "site", "facility"))
        day = _first_text(violation, ("day", "weekday"))
        times = _linkage_violation_times(violation)
        linkage_group = _first_text(violation, ("linkage_group", "linkage_group_id", "group", "group_id", "link_id"))
        expected_relation = _first_text(violation, ("expected_relation", "expected", "relation", "constraint"))
        violation_cost = _linkage_violation_cost(violation)
        is_calendar_warning = str(violation.get("severity") or "").strip().casefold() == "warning" and int(
            _number(violation.get("calendar_mismatches"))
        ) <= 0
        league_counts = Counter(_competition_label(teams.get(team_id, {})) for team_id in team_ids)
        resource_id = _linkage_violation_resource_id(venue, day, times, linkage_group)
        payload = {
            **violation,
            "venue": venue,
            "day": day,
            "times": times,
            "linkage_group": linkage_group,
            "expected_relation": expected_relation,
            "teams": team_rows,
            "violation_cost": violation_cost,
            "league_counts": dict(league_counts),
        }
        rows.append(
            WorkspaceResourceIncident(
                workspace=workspace,
                run=workspace.run,
                incident_type=WorkspaceResourceIncident.TYPE_LINKAGE_VIOLATION,
                status=WorkspaceResourceIncident.STATUS_OPEN,
                severity=1 if is_calendar_warning else _incident_severity(violation_cost),
                resource_id=resource_id,
                excess=1 if is_calendar_warning else max(1, int(math.ceil(violation_cost))),
                locals_count=len(team_ids),
                capacity=0,
                team_ids=team_ids,
                payload=_json_safe(payload),
            )
        )
    if rows:
        WorkspaceResourceIncident.objects.bulk_create(rows)


def _create_level_mismatch_incidents(
    workspace: AssignmentWorkspace,
    solver_explanations: dict[str, Any],
    teams: dict[str, dict[str, Any]],
) -> None:
    level_band = solver_explanations.get("level_band") if isinstance(solver_explanations, dict) else None
    if not isinstance(level_band, dict) or not level_band.get("enabled"):
        return
    explanations_by_group = {
        str(item.get("group_id") or ""): item
        for item in _list(solver_explanations.get("level_calendar_explanations"))
        if isinstance(item, dict) and str(item.get("group_id") or "")
    }

    normalized_by_team = {
        str(row.get("team_id") or ""): row
        for row in _list(level_band.get("normalized_teams"))
        if isinstance(row, dict) and str(row.get("team_id") or "")
    }
    assignments = {
        assignment.team_id: assignment
        for assignment in WorkspaceAssignment.objects.filter(workspace=workspace)
    }
    rows = []
    for violation in _list(level_band.get("violations")):
        if not isinstance(violation, dict):
            continue
        team_ids = [str(team_id) for team_id in _list(violation.get("team_ids")) if str(team_id or "")]
        if len(team_ids) < 2:
            continue
        group_id = str(violation.get("group_id") or "")
        team_rows = []
        for team_id in team_ids:
            normalized = normalized_by_team.get(team_id, {})
            assignment = assignments.get(team_id)
            team = teams.get(team_id, {})
            team_rows.append(
                {
                    "team_id": team_id,
                    "team_name": str(
                        normalized.get("team_name")
                        or team.get("name")
                        or (assignment.team_name if assignment else team_id)
                    ),
                    "group_id": group_id or (assignment.group_id if assignment else ""),
                    "assigned_number": normalized.get("assigned_number")
                    or (assignment.assigned_number if assignment else None),
                    "raw_level": str(normalized.get("raw_level") or team.get("level") or ""),
                    "normalized_level": str(
                        normalized.get("normalized_level")
                        or (violation.get("team_levels") or {}).get(team_id)
                        or ""
                    ),
                }
            )
        league_counts = Counter(_competition_label(teams.get(team_id, {})) for team_id in team_ids)
        cost = _number(violation.get("violation_cost") or violation.get("cost") or 1)
        calendar_explanation = explanations_by_group.get(group_id, {})
        payload = {
            **violation,
            "group_id": group_id,
            "teams": team_rows,
            "violation_cost": cost,
            "league_counts": dict(league_counts),
            "calendar_explanation": calendar_explanation,
            "dispersion": violation.get("dispersion") or calendar_explanation.get("dispersion"),
        }
        rows.append(
            WorkspaceResourceIncident(
                workspace=workspace,
                run=workspace.run,
                incident_type=WorkspaceResourceIncident.TYPE_LEVEL_MISMATCH,
                status=WorkspaceResourceIncident.STATUS_OPEN,
                severity=_incident_severity(cost),
                resource_id=f"{group_id}|level_mismatch"[:255] if group_id else "level_mismatch",
                excess=max(1, int(math.ceil(cost))),
                locals_count=len(team_ids),
                capacity=0,
                team_ids=team_ids,
                payload=_json_safe(payload),
            )
        )
    if rows:
        WorkspaceResourceIncident.objects.bulk_create(rows)


def _linkage_violations_from_audits(
    solution: dict[str, Any],
    solver_explanations: dict[str, Any],
) -> list[dict[str, Any]]:
    for container in (solver_explanations, solution):
        if not isinstance(container, dict):
            continue
        for key in ("linkage_violations", "linkage_violation_incidents", "violated_linkages"):
            rows = container.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        nested = _linkage_violations_from_linkage_audit(container.get("linkage"))
        if nested:
            return nested
    return []


def _linkage_violations_from_linkage_audit(linkage: Any) -> list[dict[str, Any]]:
    if not isinstance(linkage, dict):
        return []
    violations = [row for row in _list(linkage.get("violations")) if isinstance(row, dict)]
    if not violations:
        return []
    groups = [row for row in _list(linkage.get("groups")) if isinstance(row, dict)]
    group_teams: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for group in groups:
        key = (
            str(group.get("venue") or ""),
            str(group.get("linkage_group") or ""),
        )
        team_rows = {}
        for team in _list(group.get("teams")):
            if not isinstance(team, dict):
                continue
            team_id = str(team.get("team_id") or "")
            if team_id:
                team_rows[team_id] = team
        group_teams[key] = team_rows

    enriched = []
    for violation in violations:
        key = (
            str(violation.get("venue") or ""),
            str(violation.get("linkage_group") or ""),
        )
        teams = []
        assigned_numbers = violation.get("assigned_numbers") if isinstance(violation.get("assigned_numbers"), dict) else {}
        for team_id in [str(value) for value in _list(violation.get("team_ids")) if str(value or "").strip()]:
            group_team = group_teams.get(key, {}).get(team_id, {})
            teams.append(
                {
                    "team_id": team_id,
                    "team_name": group_team.get("team_name") or team_id,
                    "side": group_team.get("linkage_side") or group_team.get("side") or "",
                    "assigned_number": assigned_numbers.get(team_id) or group_team.get("assigned_number"),
                    "group_id": group_team.get("assigned_group_id") or group_team.get("group_id") or "",
                }
            )
        enriched.append({**violation, "teams": teams} if teams else violation)
    return enriched


def _linkage_violation_teams(
    violation: dict[str, Any],
    teams: dict[str, dict[str, Any]],
    assignments: dict[str, WorkspaceAssignment],
) -> list[dict[str, Any]]:
    raw_teams = violation.get("teams")
    rows = []
    if isinstance(raw_teams, list):
        for item in raw_teams:
            if isinstance(item, dict):
                team_id = str(item.get("team_id") or item.get("id") or "")
                side = str(item.get("side") or item.get("linkage_side") or item.get("role") or "")
                number = _int_or_none(item.get("assigned_number") or item.get("number"))
            else:
                team_id = str(item or "")
                side = ""
                number = None
            if team_id:
                rows.append(_linkage_team_row(team_id, side, number, teams, assignments))

    if not rows:
        assigned_numbers = violation.get("assigned_numbers") if isinstance(violation.get("assigned_numbers"), dict) else {}
        linkage_sides = violation.get("linkage_sides") if isinstance(violation.get("linkage_sides"), dict) else {}
        for team_id in [str(value) for value in _list(violation.get("team_ids")) if str(value or "").strip()]:
            rows.append(
                _linkage_team_row(
                    team_id,
                    str(linkage_sides.get(team_id) or ""),
                    _int_or_none(assigned_numbers.get(team_id)),
                    teams,
                    assignments,
                )
            )

    if not rows:
        for key, side in (
            ("home_team_id", "home"),
            ("away_team_id", "away"),
            ("team_a_id", "team_a"),
            ("team_b_id", "team_b"),
        ):
            team_id = str(violation.get(key) or "")
            if team_id:
                rows.append(_linkage_team_row(team_id, side, None, teams, assignments))

    seen = set()
    unique_rows = []
    for row in rows:
        key = (row["team_id"], row.get("side") or "")
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    return unique_rows


def _linkage_team_row(
    team_id: str,
    side: str,
    number: int | None,
    teams: dict[str, dict[str, Any]],
    assignments: dict[str, WorkspaceAssignment],
) -> dict[str, Any]:
    assignment = assignments.get(team_id)
    team = teams.get(team_id, {})
    assigned_number = number if number is not None else (assignment.assigned_number if assignment else None)
    return {
        "team_id": team_id,
        "team_name": str(team.get("name") or (assignment.team_name if assignment else team_id)),
        "side": side or "-",
        "assigned_number": assigned_number,
        "group_id": assignment.group_id if assignment else str(team.get("group_id") or ""),
    }


def _linkage_violation_times(violation: dict[str, Any]) -> list[str]:
    for key in ("times", "time_slots", "hours", "hour_slots"):
        value = violation.get(key)
        if isinstance(value, list):
            return [str(item) for item in value if str(item or "").strip()]
        if str(value or "").strip():
            return [str(value)]
    start = str(violation.get("start_time") or "").strip()
    end = str(violation.get("end_time") or "").strip()
    if start and end:
        return [f"{start}-{end}"]
    time_value = str(violation.get("time") or violation.get("hour_slot") or "").strip()
    return [time_value] if time_value else []


def _linkage_violation_cost(violation: dict[str, Any]) -> float:
    for key in ("violation_cost", "cost", "penalty", "weight"):
        if key in violation:
            return _number(violation.get(key))
    return 1.0


def _linkage_violation_resource_id(
    venue: str,
    day: str,
    times: list[str],
    linkage_group: str,
) -> str:
    parts = [venue, day, ",".join(times), linkage_group]
    value = "|".join(part for part in parts if str(part or "").strip())
    return value[:255] if value else "linkage_violation"


def _first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if str(value or "").strip():
            return str(value)
    return ""


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
    seed_deviations = incidents.filter(incident_type=WorkspaceResourceIncident.TYPE_SEED_DEVIATION)
    linkage_violations = incidents.filter(incident_type=WorkspaceResourceIncident.TYPE_LINKAGE_VIOLATION)
    level_mismatches = incidents.filter(incident_type=WorkspaceResourceIncident.TYPE_LEVEL_MISMATCH)
    return {
        "hydration_version": HYDRATION_VERSION,
        "assignments": WorkspaceAssignment.objects.filter(workspace=workspace).count(),
        "matches": WorkspaceResourceMatch.objects.filter(workspace=workspace).count(),
        "resource_incidents": resource_incidents.count(),
        "entity_conflicts": entity_conflicts.count(),
        "seed_deviations": seed_deviations.count(),
        "linkage_violations": linkage_violations.count(),
        "level_mismatches": level_mismatches.count(),
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
    seed_deviations = WorkspaceResourceIncident.objects.filter(
        workspace=workspace,
        incident_type=WorkspaceResourceIncident.TYPE_SEED_DEVIATION,
    )
    linkage_violations = WorkspaceResourceIncident.objects.filter(
        workspace=workspace,
        incident_type=WorkspaceResourceIncident.TYPE_LINKAGE_VIOLATION,
    )
    level_mismatches = WorkspaceResourceIncident.objects.filter(
        workspace=workspace,
        incident_type=WorkspaceResourceIncident.TYPE_LEVEL_MISMATCH,
    )
    excess_total = sum(incident.excess for incident in resource_incidents)
    resource_count = resource_incidents.count()
    entity_conflict_count = entity_conflicts.count()
    seed_deviation_count = seed_deviations.count()
    linkage_violation_count = linkage_violations.count()
    level_mismatch_count = level_mismatches.count()
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
            "label": "Desviacions peticio",
            "value": seed_deviation_count,
            "subtitle": f"{sum(incident.severity for incident in seed_deviations)} jornades",
            "status": "warning" if seed_deviation_count else "success",
        },
        {
            "label": "Linkage violat",
            "value": linkage_violation_count,
            "status": "warning" if linkage_violation_count else "success",
        },
        {
            "label": "Nivell incompatible",
            "value": level_mismatch_count,
            "status": "warning" if level_mismatch_count else "success",
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
            "type_key": incident.incident_type,
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
    if incident.incident_type == WorkspaceResourceIncident.TYPE_LINKAGE_VIOLATION:
        linkage_group = str(payload.get("linkage_group") or "-")
        expected_relation = str(payload.get("expected_relation") or "-")
        is_warning = str(payload.get("severity") or "").strip().casefold() == "warning"
        venue = str(payload.get("venue") or "")
        day = str(payload.get("day") or "")
        times = payload.get("times")
        times_text = ", ".join(str(value) for value in times) if isinstance(times, list) else str(times or "")
        title_parts = [part for part in (linkage_group, venue, day, times_text) if part and part != "-"]
        team_labels = [
            str(team.get("team_name") or team.get("team_id") or "")
            for team in _list(payload.get("teams"))
            if isinstance(team, dict)
        ]
        return {
            "id": incident.pk,
            "incident_id": incident.pk,
            "type_key": incident.incident_type,
            "type": "Linkage warning" if is_warning else "Linkage violation",
            "title": " - ".join(title_parts) if title_parts else "Linkage violation",
            "summary": (
                f"{expected_relation} no coincideix en numero, calendari compatible"
                if is_warning
                else f"{expected_relation} incumplert"
            ),
            "description": (
                f"{expected_relation} no coincideix en numero, pero no genera mismatches casa/fora"
                if is_warning
                else f"{expected_relation} incumplert"
            ),
            "impact": f"+{payload.get('violation_cost') or incident.excess}",
            "count": incident.excess,
            "severity": incident.severity,
            "status": incident.get_status_display(),
            "resource": _resource_label(incident.resource_id),
            "venue": venue or _resource_label(incident.resource_id),
            "league": _top_league_label(payload.get("league_counts")),
            "competition": _top_league_label(payload.get("league_counts")),
            "team": ", ".join(team_labels) if team_labels else "-",
            "team_name": ", ".join(team_labels) if team_labels else "-",
            "team_ids": incident.team_ids or [],
            "payload": payload,
        }
    if incident.incident_type == WorkspaceResourceIncident.TYPE_LEVEL_MISMATCH:
        group_id = str(payload.get("group_id") or "-")
        family = _level_families_label(payload)
        calendar_explanation = payload.get("calendar_explanation") if isinstance(payload.get("calendar_explanation"), dict) else {}
        dispersion = str(payload.get("dispersion") or calendar_explanation.get("dispersion") or _level_pair_label(payload.get("teams")))
        team_labels = [
            str(team.get("team_name") or team.get("team_id") or "")
            for team in _list(payload.get("teams"))
            if isinstance(team, dict)
        ]
        return {
            "id": incident.pk,
            "incident_id": incident.pk,
            "type_key": incident.incident_type,
            "type": "Nivell incompatible",
            "title": f"{group_id} - {dispersion}",
            "summary": f"{family} al grup {group_id}",
            "description": f"{family} al grup {group_id}",
            "impact": f"+{payload.get('violation_cost') or incident.excess}",
            "count": incident.excess,
            "severity": incident.severity,
            "status": incident.get_status_display(),
            "resource": group_id,
            "venue": group_id,
            "league": _top_league_label(payload.get("league_counts")),
            "competition": _top_league_label(payload.get("league_counts")),
            "team": ", ".join(team_labels) if team_labels else "-",
            "team_name": ", ".join(team_labels) if team_labels else "-",
            "team_ids": incident.team_ids or [],
            "payload": payload,
        }
    if incident.incident_type == WorkspaceResourceIncident.TYPE_SEED_DEVIATION:
        team_name = str(payload.get("team_name") or "-")
        group_id = str(payload.get("group_id") or "-")
        expected = payload.get("expected_number") or "-"
        assigned = payload.get("assigned_number") or "-"
        damage = payload.get("damage_rounds") or incident.severity
        return {
            "id": incident.pk,
            "incident_id": incident.pk,
            "type_key": incident.incident_type,
            "type": "Desviacio peticio",
            "title": f"{team_name} - {group_id}",
            "summary": f"Esperat {expected}, assignat {assigned}",
            "description": f"{damage} jornada/es afectades",
            "impact": str(damage),
            "count": damage,
            "severity": incident.severity,
            "status": incident.get_status_display(),
            "resource": group_id,
            "venue": group_id,
            "league": _top_league_label(payload.get("league_counts")),
            "competition": _top_league_label(payload.get("league_counts")),
            "team": team_name,
            "team_name": team_name,
            "team_ids": incident.team_ids or [],
            "payload": payload,
        }
    return {
        "id": incident.pk,
        "incident_id": incident.pk,
        "type_key": incident.incident_type,
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
        linkage = _assignment_linkage_fields(assignment, team)
        linkage_text = " ".join(
            value
            for value in (linkage["group"], linkage["side"], linkage["source"])
            if value
        )
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
                "level_label": _workspace_level_label(team.get("level")),
                "level_class": _workspace_level_class(team.get("level")),
                "venue": str(team.get("venue") or ""),
                "day": str(team.get("day") or ""),
                "time": str(team.get("time") or ""),
                "group_id": assignment.group_id,
                "number": assignment.assigned_number,
                "seed_request_original": assignment.seed_request_original or "",
                "linkage_group": linkage["group"],
                "linkage_side": linkage["side"],
                "linkage_side_label": _linkage_side_label(linkage["side"]),
                "linkage_source": linkage["source"],
                "linkage_source_label": _linkage_source_label(linkage["source"]),
                "has_linkage": bool(linkage["group"]),
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
                        linkage_text,
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
    home_linkage = _assignment_linkage_fields(home_assignment) if home_assignment else {"group": "", "side": "", "source": ""}
    away_linkage = _assignment_linkage_fields(away_assignment) if away_assignment else {"group": "", "side": "", "source": ""}
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
        "home_number": home_assignment.assigned_number if home_assignment else None,
        "away_number": away_assignment.assigned_number if away_assignment else None,
        "home_linkage_group": home_linkage["group"],
        "home_linkage_side": home_linkage["side"],
        "home_linkage_side_label": _linkage_side_label(home_linkage["side"]),
        "away_linkage_group": away_linkage["group"],
        "away_linkage_side": away_linkage["side"],
        "away_linkage_side_label": _linkage_side_label(away_linkage["side"]),
        "linkage_groups": sorted(
            {
                group
                for group in (home_linkage["group"], away_linkage["group"])
                if group
            },
            key=_text_sort,
        ),
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


def _level_pair_label(value: Any) -> str:
    labels = []
    for team in _list(value):
        if not isinstance(team, dict):
            continue
        team_name = str(team.get("team_name") or team.get("team_id") or "").strip()
        raw = str(team.get("raw_level") or "-").strip()
        normalized = str(team.get("normalized_level") or "-").strip()
        if team_name:
            labels.append(f"{team_name}: {raw}->{normalized}")
    return " / ".join(labels) if labels else "-"


def _level_families_label(payload: dict[str, Any]) -> str:
    families = payload.get("families")
    if isinstance(families, list):
        clean = [str(family) for family in families if str(family or "")]
        if clean:
            return ", ".join(clean)
    return str(payload.get("family") or "-")


def _workspace_level_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "Sense nivell"
    folded = text.casefold()
    if "b-c" in folded or "b/c" in folded:
        return "B/C"
    match = re.search(r"\b([A-E])\b", text.upper())
    if not match:
        match = re.search(r"(?:NIVELL\s*)?([A-E])\s*$", text.upper())
    if not match:
        return text
    return {"A": "A", "B": "B", "C": "B/C", "D": "B/C", "E": "C"}[match.group(1)]


def _workspace_normalized_level_label(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"A", "B", "B/C", "C"}:
        return text
    return _workspace_level_label(text)


def _workspace_level_class(value: Any) -> str:
    label = _workspace_level_label(value)
    return _workspace_level_class_for_label(label)


def _workspace_normalized_level_class(value: Any) -> str:
    label = _workspace_normalized_level_label(value)
    return _workspace_level_class_for_label(label)


def _workspace_level_class_for_label(label: str) -> str:
    return {
        "A": "level-a",
        "B": "level-b",
        "B/C": "level-bc",
        "C": "level-c",
        "Sense nivell": "level-none",
    }.get(label, "level-other")


def _resource_label(resource_id: str) -> str:
    if not resource_id:
        return "-"
    base, round_label = _split_resource_round(resource_id)
    parts = [_resource_part_label(part) for part in base.split("|") if part]
    label = " - ".join(parts) if parts else resource_id
    return f"{label} - {round_label}" if round_label else label


def _resource_part_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"\d{1,2}-\d{2}", text):
        return text.replace("-", ":")

    days = {
        "dilluns": "Dilluns",
        "dimarts": "Dimarts",
        "dimecres": "Dimecres",
        "dijous": "Dijous",
        "divendres": "Divendres",
        "dissabte": "Dissabte",
        "diumenge": "Diumenge",
    }
    folded = text.casefold()
    if folded in days:
        return days[folded]

    humanized = re.sub(r"[-_]+", " ", text).strip()
    humanized = re.sub(r"\s+", " ", humanized).casefold()
    humanized = re.sub(r"\bl\s+([aeiouàèéíïòóúü])", r"l'\1", humanized)
    humanized = re.sub(
        r"(?<=\s)([a-z])(?=\s|$)",
        lambda match: match.group(1).upper(),
        humanized,
    )
    return humanized[:1].upper() + humanized[1:] if humanized else text


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


def _incident_severity(value: Any) -> int:
    return min(MAX_POSITIVE_SMALLINT, max(1, int(math.ceil(_number(value)))))


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
