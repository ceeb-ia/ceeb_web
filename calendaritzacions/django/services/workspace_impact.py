"""Impact analytics for calendarization assignment workspaces."""

from __future__ import annotations

from collections import defaultdict
import re
import unicodedata
from typing import Any

from calendaritzacions.django.models import (
    AssignmentWorkspace,
    WorkspaceAssignment,
    WorkspaceResourceIncident,
    WorkspaceResourceMatch,
)


TYPE_LABELS = {
    WorkspaceResourceIncident.TYPE_RESOURCE_EXCESS: "Exces de recurs",
    WorkspaceResourceIncident.TYPE_ASSIGNMENT_CONFLICT: "Conflicte entitat",
    WorkspaceResourceIncident.TYPE_LINKAGE_VIOLATION: "Linkage violat",
    WorkspaceResourceIncident.TYPE_LEVEL_MISMATCH: "Nivell incompatible",
    WorkspaceResourceIncident.TYPE_SEED_DEVIATION: "Desviacio peticio",
    WorkspaceResourceIncident.TYPE_OTHER: "Altres",
}


EMPTY_VIEW = {
    "kpis": [],
    "filters": {
        "modalities": [],
        "leagues": [],
        "categories": [],
        "subcategories": [],
        "entities": [],
        "levels": [],
        "types": [],
        "rounds": [],
    },
    "modality_rows": [],
    "entity_rows": [],
    "league_rows": [],
    "round_rows": [],
    "type_rows": [],
    "affected_rows": [],
    "charts": [],
}


def get_workspace_impact_view(workspace: AssignmentWorkspace) -> dict[str, Any]:
    """Return aggregate impact analytics for the workspace overview tab."""

    assignments = {
        assignment.team_id: assignment
        for assignment in WorkspaceAssignment.objects.filter(workspace=workspace).order_by("team_name", "team_id")
    }
    incidents = list(
        WorkspaceResourceIncident.objects.filter(workspace=workspace).order_by(
            "incident_type",
            "-severity",
            "id",
        )
    )
    if not incidents:
        return _empty_view()

    matches = list(
        WorkspaceResourceMatch.objects.filter(workspace=workspace).order_by("group_id", "round_index", "id")
    )
    rounds_by_group, rounds_by_team = _round_indexes(matches)

    affected_rows = []
    for incident in incidents:
        team_ids = [str(team_id) for team_id in (incident.team_ids or []) if str(team_id or "")]
        if not team_ids:
            affected_rows.append(_row_for_unassigned_incident(incident, rounds_by_group))
            continue
        for team_id in team_ids:
            affected_rows.append(
                _row_for_team_incident(
                    incident,
                    team_id=team_id,
                    assignment=assignments.get(team_id),
                    rounds_by_group=rounds_by_group,
                    rounds_by_team=rounds_by_team,
                )
            )

    return {
        "kpis": _kpis(incidents, affected_rows),
        "filters": _filters(affected_rows),
        "modality_rows": _aggregate_rows(affected_rows, "modality", "modality_token", include=("entity",)),
        "entity_rows": _aggregate_rows(affected_rows, "entity", "entity_token", include=("modality",))[:25],
        "league_rows": _aggregate_rows(affected_rows, "league", "league_token", include=("entity", "modality"))[:50],
        "round_rows": _round_rows(affected_rows),
        "type_rows": _aggregate_rows(affected_rows, "type_label", "type_key", include=("entity", "modality")),
        "affected_rows": affected_rows,
        "charts": _charts(affected_rows),
    }


def _empty_view() -> dict[str, Any]:
    return {
        "kpis": _kpis([], []),
        "filters": dict(EMPTY_VIEW["filters"]),
        "modality_rows": [],
        "entity_rows": [],
        "league_rows": [],
        "round_rows": [],
        "type_rows": [],
        "affected_rows": [],
        "charts": [],
    }


def _row_for_team_incident(
    incident: WorkspaceResourceIncident,
    *,
    team_id: str,
    assignment: WorkspaceAssignment | None,
    rounds_by_group: dict[str, set[int]],
    rounds_by_team: dict[str, set[int]],
) -> dict[str, Any]:
    team = _assignment_team(assignment)
    team_name = (assignment.team_name if assignment else "") or str(team.get("name") or team_id)
    entity = (assignment.entity if assignment else "") or str(team.get("entity") or "Sense entitat")
    group_id = (assignment.group_id if assignment else "") or _incident_group_id(incident)
    rounds = _incident_rounds(incident, team_id=team_id, group_id=group_id, rounds_by_group=rounds_by_group, rounds_by_team=rounds_by_team)
    row = {
        "incident_id": incident.pk,
        "team_id": team_id,
        "team_name": team_name,
        "entity": entity,
        "entity_token": _filter_token(entity),
        "league": str(team.get("league_name") or "Sense lliga"),
        "modality": str(team.get("modality") or "Sense modalitat"),
        "category": str(team.get("category") or "Sense categoria"),
        "subcategory": str(team.get("subcategory") or ""),
        "level": str(team.get("level") or "Sense nivell"),
        "group_id": group_id,
        "type_key": incident.incident_type,
        "type_label": TYPE_LABELS.get(incident.incident_type, incident.incident_type),
        "resource": _incident_resource_label(incident),
        "rounds": rounds,
        "round_tokens": _round_tokens(rounds),
        "round_labels": _round_labels(rounds),
        "excess": int(incident.excess or 0),
        "severity": int(incident.severity or 0),
        "impact": _impact_label(incident),
    }
    row.update(
        {
            "league_token": _filter_token(row["league"]),
            "modality_token": _filter_token(row["modality"]),
            "category_token": _filter_token(row["category"]),
            "subcategory_token": _filter_token(row["subcategory"]),
            "level_token": _filter_token(row["level"]),
        }
    )
    row["filter_text"] = _filter_text(row)
    return row


def _row_for_unassigned_incident(
    incident: WorkspaceResourceIncident,
    rounds_by_group: dict[str, set[int]],
) -> dict[str, Any]:
    group_id = _incident_group_id(incident)
    rounds = _incident_rounds(incident, team_id="", group_id=group_id, rounds_by_group=rounds_by_group, rounds_by_team={})
    row = {
        "incident_id": incident.pk,
        "team_id": "",
        "team_name": "Sense equip",
        "entity": "Sense entitat",
        "entity_token": "sense-entitat",
        "league": _top_league_label((incident.payload or {}).get("league_counts")),
        "modality": "Sense modalitat",
        "category": "Sense categoria",
        "subcategory": "",
        "level": "Sense nivell",
        "group_id": group_id,
        "type_key": incident.incident_type,
        "type_label": TYPE_LABELS.get(incident.incident_type, incident.incident_type),
        "resource": _incident_resource_label(incident),
        "rounds": rounds,
        "round_tokens": _round_tokens(rounds),
        "round_labels": _round_labels(rounds),
        "excess": int(incident.excess or 0),
        "severity": int(incident.severity or 0),
        "impact": _impact_label(incident),
    }
    row.update(
        {
            "league_token": _filter_token(row["league"]),
            "modality_token": _filter_token(row["modality"]),
            "category_token": _filter_token(row["category"]),
            "subcategory_token": "",
            "level_token": _filter_token(row["level"]),
        }
    )
    row["filter_text"] = _filter_text(row)
    return row


def _round_indexes(
    matches: list[WorkspaceResourceMatch],
) -> tuple[dict[str, set[int]], dict[str, set[int]]]:
    rounds_by_group: dict[str, set[int]] = defaultdict(set)
    rounds_by_team: dict[str, set[int]] = defaultdict(set)
    for match in matches:
        round_index = int(match.round_index or 0)
        if not round_index:
            continue
        if match.group_id:
            rounds_by_group[match.group_id].add(round_index)
        for team_id in (match.home_team_id, match.away_team_id):
            if team_id:
                rounds_by_team[team_id].add(round_index)
    return rounds_by_group, rounds_by_team


def _incident_rounds(
    incident: WorkspaceResourceIncident,
    *,
    team_id: str,
    group_id: str,
    rounds_by_group: dict[str, set[int]],
    rounds_by_team: dict[str, set[int]],
) -> list[int]:
    parsed = _round_from_resource(incident.resource_id)
    if parsed:
        return [parsed]
    if team_id and rounds_by_team.get(team_id):
        return sorted(rounds_by_team[team_id])
    if group_id and rounds_by_group.get(group_id):
        return sorted(rounds_by_group[group_id])
    return []


def _round_from_resource(resource_id: str) -> int | None:
    match = re.search(r"(?:^|\|)J(\d+)$", str(resource_id or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _kpis(incidents: list[WorkspaceResourceIncident], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    affected_teams = {row["team_id"] for row in rows if row.get("team_id")}
    affected_entities = {row["entity"] for row in rows if row.get("entity")}
    affected_rounds = {
        round_index
        for row in rows
        for round_index in row.get("rounds", [])
    }
    affected_modalities = {row["modality"] for row in rows if row.get("modality")}
    return [
        {"key": "affected_teams", "label": "Equips afectats", "value": len(affected_teams), "status": "warning" if affected_teams else "success"},
        {"key": "affected_incidents", "label": "Incidencies", "value": len(incidents), "status": "warning" if incidents else "success"},
        {"key": "affected_rounds", "label": "Jornades afectades", "value": len(affected_rounds), "status": "neutral"},
        {"key": "affected_entities", "label": "Entitats afectades", "value": len(affected_entities), "status": "neutral"},
        {"key": "affected_modalities", "label": "Modalitats", "value": len(affected_modalities), "status": "neutral"},
        {"key": "excess_total", "label": "Impacte acumulat", "value": sum(int(incident.excess or 0) for incident in incidents), "status": "danger" if incidents else "success"},
        {"key": "severity_total", "label": "Severitat", "value": sum(int(incident.severity or 0) for incident in incidents), "status": "warning" if incidents else "success"},
    ]


def _filters(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    return {
        "modalities": _filter_options(rows, "modality", "modality_token"),
        "leagues": _filter_options(rows, "league", "league_token"),
        "categories": _filter_options(rows, "category", "category_token"),
        "subcategories": _filter_options(rows, "subcategory", "subcategory_token"),
        "entities": _filter_options(rows, "entity", "entity_token"),
        "levels": _filter_options(rows, "level", "level_token"),
        "types": _filter_options(rows, "type_label", "type_key"),
        "rounds": [
            {"label": row["label"], "token": row["token"]}
            for row in _round_rows(rows)
        ],
    }


def _filter_options(rows: list[dict[str, Any]], label_key: str, token_key: str) -> list[dict[str, str]]:
    values = {}
    for row in rows:
        label = str(row.get(label_key) or "").strip()
        token = str(row.get(token_key) or "").strip()
        if label and token:
            values[token] = label
    return [
        {"label": label, "token": token}
        for token, label in sorted(values.items(), key=lambda item: _text_sort(item[1]))
    ]


def _aggregate_rows(rows: list[dict[str, Any]], label_key: str, token_key: str, *, include: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        token = str(row.get(token_key) or "")
        label = str(row.get(label_key) or "")
        if not token:
            continue
        bucket = buckets.setdefault(
            token,
            {
                "label": label,
                "token": token,
                "team_ids": set(),
                "incident_ids": set(),
                "entities": set(),
                "modalities": set(),
                "excess_total": 0,
                "severity_total": 0,
            },
        )
        if row.get("team_id"):
            bucket["team_ids"].add(row["team_id"])
        if row.get("incident_id"):
            bucket["incident_ids"].add(row["incident_id"])
        if row.get("entity"):
            bucket["entities"].add(row["entity"])
        if row.get("modality"):
            bucket["modalities"].add(row["modality"])
        bucket["excess_total"] += int(row.get("excess") or 0)
        bucket["severity_total"] += int(row.get("severity") or 0)

    output = []
    for bucket in buckets.values():
        item = {
            "label": bucket["label"],
            "token": bucket["token"],
            "team_count": len(bucket["team_ids"]),
            "incident_count": len(bucket["incident_ids"]),
            "entity_count": len(bucket["entities"]),
            "modality_count": len(bucket["modalities"]),
            "excess_total": bucket["excess_total"],
            "severity_total": bucket["severity_total"],
        }
        for key in include:
            plural_key = {"entity": "entities", "modality": "modalities", "incident": "incident_ids", "team": "team_ids"}.get(key)
            if plural_key:
                item[f"{key}_count"] = len(bucket[plural_key])
        output.append(item)
    return sorted(output, key=lambda item: (item["team_count"], item["incident_count"], item["severity_total"], item["label"]), reverse=True)


def _round_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expanded = []
    for row in rows:
        for round_index in row.get("rounds", []):
            expanded.append({**row, "round_label": f"J{round_index}", "round_token": f"j{round_index}", "round_number": round_index})
    aggregated = _aggregate_rows(expanded, "round_label", "round_token", include=("entity", "modality"))
    return sorted(aggregated, key=lambda item: _round_sort(item["token"]))


def _charts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _chart("Equips afectats per modalitat", _aggregate_rows(rows, "modality", "modality_token")),
        _chart("Top entitats afectades", _aggregate_rows(rows, "entity", "entity_token")[:10]),
        _chart("Tipus d'incidencia", _aggregate_rows(rows, "type_label", "type_key")),
        _chart("Jornades afectades", _round_rows(rows)),
    ]


def _chart(title: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    max_value = max((row["team_count"] for row in rows), default=0)
    bars = [
        {
            "label": row["label"],
            "value": row["team_count"],
            "value_text": str(row["team_count"]),
            "percent": int(round((row["team_count"] / max_value) * 100)) if max_value else 0,
        }
        for row in rows[:10]
    ]
    return {"title": title, "bars": bars}


def _assignment_team(assignment: WorkspaceAssignment | None) -> dict[str, Any]:
    if assignment is None:
        return {}
    payload = assignment.payload or {}
    team = payload.get("team")
    return team if isinstance(team, dict) else {}


def _incident_group_id(incident: WorkspaceResourceIncident) -> str:
    payload = incident.payload or {}
    return str(payload.get("group_id") or payload.get("group") or "")


def _incident_resource_label(incident: WorkspaceResourceIncident) -> str:
    payload = incident.payload or {}
    label = payload.get("resource_label")
    if label:
        return str(label)
    resource_id = str(incident.resource_id or "")
    if not resource_id:
        return _incident_group_id(incident) or incident.incident_type
    base = resource_id
    round_label = ""
    if "|J" in resource_id:
        base, round_part = resource_id.rsplit("|J", 1)
        round_label = f"J{round_part}"
    parts = [_resource_part(part) for part in base.split("|") if part]
    return " - ".join([*parts, round_label] if round_label else parts) or resource_id


def _resource_part(value: str) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{1,2}-\d{2}", text):
        return text.replace("-", ":")
    return re.sub(r"[-_]+", " ", text).strip().title()


def _impact_label(incident: WorkspaceResourceIncident) -> str:
    excess = int(incident.excess or 0)
    if excess:
        return f"+{excess}"
    severity = int(incident.severity or 0)
    return str(severity) if severity else "-"


def _round_tokens(rounds: list[int]) -> str:
    return " ".join(f"j{round_index}" for round_index in rounds)


def _round_labels(rounds: list[int]) -> str:
    return ", ".join(f"J{round_index}" for round_index in rounds)


def _filter_text(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in (
            "team_id",
            "team_name",
            "entity",
            "league",
            "modality",
            "category",
            "subcategory",
            "level",
            "group_id",
            "type_label",
            "resource",
            "round_labels",
        )
    )


def _top_league_label(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return "Sense lliga"
    label, _count = max(value.items(), key=lambda item: int(item[1] or 0))
    return str(label)


def _filter_token(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text.casefold())
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    token = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return token or "valor"


def _round_sort(token: str) -> tuple[int, str]:
    match = re.search(r"(\d+)", str(token))
    return (int(match.group(1)) if match else 9999, str(token))


def _text_sort(value: str) -> str:
    return str(value or "").casefold()


__all__ = ["get_workspace_impact_view"]
