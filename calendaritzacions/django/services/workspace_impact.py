"""Impact analytics for calendarization assignment workspaces."""

from __future__ import annotations

from collections import defaultdict
import math
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
    "total_teams": 0,
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
    total_teams = len(assignments)
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

    affected_rows = _with_interpretable_impact(affected_rows)
    return {
        "total_teams": total_teams,
        "kpis": _kpis(incidents, affected_rows, total_teams=total_teams),
        "filters": _filters(affected_rows),
        "modality_rows": _aggregate_rows(affected_rows, "modality", "modality_token", total_teams=total_teams, include=("entity",)),
        "entity_rows": _aggregate_rows(affected_rows, "entity", "entity_token", total_teams=total_teams, include=("modality",))[:25],
        "league_rows": _aggregate_rows(affected_rows, "league", "league_token", total_teams=total_teams, include=("entity", "modality"))[:50],
        "round_rows": _round_rows(affected_rows),
        "type_rows": _aggregate_rows(affected_rows, "type_label", "type_key", total_teams=total_teams, include=("entity", "modality")),
        "affected_rows": affected_rows,
        "charts": _charts(affected_rows),
    }


def _empty_view() -> dict[str, Any]:
    return {
        "total_teams": 0,
        "kpis": _kpis([], [], total_teams=0),
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
        "impact_score": 0,
        "impact_band": "Net",
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
        "impact_score": 0,
        "impact_band": "Net",
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


def _with_interpretable_impact(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for row in rows:
        severity = int(row.get("severity") or 0)
        excess = int(row.get("excess") or 0)
        severity_score = _semantic_severity_score(severity)
        excess_score = _semantic_excess_score(excess, str(row.get("type_key") or ""))
        impact_score = max(severity_score, excess_score)
        item = {
            **row,
            "severity_score": severity_score,
            "excess_score": excess_score,
            "impact_score": impact_score,
            "impact_band": _impact_band(impact_score),
            "impact": _impact_label_from_scores(impact_score, severity, excess),
        }
        enriched.append(item)
    return enriched


def _kpis(
    incidents: list[WorkspaceResourceIncident],
    rows: list[dict[str, Any]],
    *,
    total_teams: int,
) -> list[dict[str, Any]]:
    affected_teams = {row["team_id"] for row in rows if row.get("team_id")}
    affected_entities = {row["entity"] for row in rows if row.get("entity")}
    affected_rounds = {
        round_index
        for row in rows
        for round_index in row.get("rounds", [])
    }
    affected_modalities = {row["modality"] for row in rows if row.get("modality")}
    raw_severity_total = sum(int(row.get("severity") or 0) for row in rows)
    material_excess_total = sum(
        int(incident.excess or 0)
        for incident in incidents
        if incident.incident_type
        in {
            WorkspaceResourceIncident.TYPE_RESOURCE_EXCESS,
            WorkspaceResourceIncident.TYPE_ASSIGNMENT_CONFLICT,
        }
    )
    impact_score_total = sum(float(row.get("impact_score") or 0) for row in rows)
    incident_scores: dict[Any, float] = {}
    for row in rows:
        incident_id = row.get("incident_id")
        if not incident_id:
            continue
        incident_scores[incident_id] = max(
            incident_scores.get(incident_id, 0.0),
            float(row.get("impact_score") or 0),
        )
    affected_team_count = len(affected_teams)
    incident_count = len(incidents)
    avg_severity_per_team = min(10.0, _safe_div(impact_score_total, affected_team_count))
    avg_severity_per_incident = _safe_div(sum(incident_scores.values()), incident_count)
    avg_impact_score = _safe_div(impact_score_total, len(rows))
    max_impact_score = max((float(row.get("impact_score") or 0) for row in rows), default=0.0)
    affected_ratio = _safe_div(affected_team_count * 100, total_teams)
    return [
        {"key": "affected_teams", "label": "Equips afectats", "value": affected_team_count, "subtitle": f"{_fmt_decimal(affected_ratio)}% del total", "status": "warning" if affected_teams else "success"},
        {"key": "affected_team_ratio", "label": "% equips afectats", "value": f"{_fmt_decimal(affected_ratio)}%", "subtitle": f"Sobre {total_teams} equips", "status": "warning" if affected_ratio else "success"},
        {"key": "avg_severity_per_team", "label": "Severitat mitjana/equip", "value": _fmt_decimal(avg_severity_per_team), "subtitle": "Mitjana sobre equips afectats", "status": _score_status(avg_impact_score)},
        {"key": "avg_severity_per_incident", "label": "Severitat mitjana/inc.", "value": _fmt_decimal(avg_severity_per_incident), "subtitle": "Mitjana sobre incidencies", "status": _score_status(avg_impact_score)},
        {"key": "avg_impact_score", "label": "Impacte mitja 0-10", "value": _fmt_decimal(avg_impact_score), "subtitle": f"Maxim {_fmt_decimal(max_impact_score)}/10", "status": _score_status(avg_impact_score)},
        {"key": "affected_incidents", "label": "Incidencies", "value": incident_count, "subtitle": f"{_fmt_decimal(avg_severity_per_incident)} severitat/inc.", "status": "warning" if incidents else "success"},
        {"key": "affected_rounds", "label": "Jornades afectades", "value": len(affected_rounds), "status": "neutral"},
        {"key": "affected_entities", "label": "Entitats afectades", "value": len(affected_entities), "status": "neutral"},
        {"key": "affected_modalities", "label": "Modalitats", "value": len(affected_modalities), "status": "neutral"},
        {"key": "excess_per_team", "label": "Exces material/equip", "value": _fmt_decimal(_safe_div(material_excess_total, affected_team_count)), "subtitle": f"Total {material_excess_total}", "status": "danger" if material_excess_total else "success"},
        {"key": "severity_total", "label": "Severitat bruta", "value": raw_severity_total, "subtitle": "Pes intern acumulat", "status": "warning" if incidents else "success"},
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


def _aggregate_rows(
    rows: list[dict[str, Any]],
    label_key: str,
    token_key: str,
    *,
    total_teams: int = 0,
    include: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
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
                "impact_score_total": 0.0,
                "impact_score_max": 0.0,
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
        impact_score = float(row.get("impact_score") or 0)
        bucket["impact_score_total"] += impact_score
        bucket["impact_score_max"] = max(bucket["impact_score_max"], impact_score)

    output = []
    for bucket in buckets.values():
        team_count = len(bucket["team_ids"])
        incident_count = len(bucket["incident_ids"])
        item = {
            "label": bucket["label"],
            "token": bucket["token"],
            "team_count": team_count,
            "incident_count": incident_count,
            "entity_count": len(bucket["entities"]),
            "modality_count": len(bucket["modalities"]),
            "excess_total": bucket["excess_total"],
            "severity_total": bucket["severity_total"],
            "affected_ratio": _safe_div(team_count * 100, total_teams),
            "severity_per_team": _safe_div(bucket["severity_total"], team_count),
            "severity_per_incident": _safe_div(bucket["severity_total"], incident_count),
            "impact_score_per_team": min(10.0, _safe_div(bucket["impact_score_total"], team_count)),
            "impact_score_avg": _safe_div(bucket["impact_score_total"], max(1, len(bucket["incident_ids"]) or team_count)),
            "impact_score_max": bucket["impact_score_max"],
        }
        for key in include:
            plural_key = {"entity": "entities", "modality": "modalities", "incident": "incident_ids", "team": "team_ids"}.get(key)
            if plural_key:
                item[f"{key}_count"] = len(bucket[plural_key])
        output.append(item)
    return sorted(output, key=lambda item: (item["impact_score_avg"], item["team_count"], item["incident_count"], item["label"]), reverse=True)


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


def _impact_label_from_scores(score: float, severity: int, excess: int) -> str:
    if score <= 0:
        return "-"
    details = []
    if excess:
        details.append(f"exces {excess}")
    if severity:
        details.append(f"sev. {severity}")
    suffix = f" ({', '.join(details)})" if details else ""
    return f"{_fmt_decimal(score)}/10{suffix}"


def _score_10(value: int | float, maximum: int | float) -> float:
    numeric = max(0.0, float(value or 0))
    max_value = max(0.0, float(maximum or 0))
    if numeric <= 0 or max_value <= 0:
        return 0.0
    return round(min(10.0, (numeric / max_value) * 10.0), 1)


def _semantic_excess_score(excess: int | float, incident_type: str) -> float:
    numeric = max(0.0, float(excess or 0))
    if numeric <= 0:
        return 0.0
    if incident_type in {
        WorkspaceResourceIncident.TYPE_RESOURCE_EXCESS,
        WorkspaceResourceIncident.TYPE_ASSIGNMENT_CONFLICT,
    }:
        return round(min(10.0, 2.5 + numeric * 2.5), 1)
    return round(min(10.0, 1.0 + math.log10(numeric + 1.0) * 2.5), 1)


def _semantic_severity_score(severity: int | float) -> float:
    numeric = max(0.0, float(severity or 0))
    if numeric <= 0:
        return 0.0
    if numeric <= 3:
        return round(numeric, 1)
    return round(min(10.0, 1.0 + math.log10(numeric + 1.0) * 2.5), 1)


def _impact_band(score: int | float) -> str:
    numeric = float(score or 0)
    if numeric <= 0:
        return "Net"
    if numeric < 4:
        return "Baix"
    if numeric < 7:
        return "Mitja"
    return "Alt"


def _score_status(score: int | float) -> str:
    numeric = float(score or 0)
    if numeric <= 0:
        return "success"
    if numeric < 4:
        return "neutral"
    if numeric < 7:
        return "warning"
    return "danger"


def _safe_div(numerator: int | float, denominator: int | float) -> float:
    try:
        denom = float(denominator)
        if denom == 0:
            return 0.0
        return float(numerator) / denom
    except (TypeError, ValueError):
        return 0.0


def _fmt_decimal(value: int | float) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "0"
    numeric = math.floor(numeric * 10 + 0.5) / 10
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.1f}"


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
