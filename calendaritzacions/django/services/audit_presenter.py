"""Human-oriented presentation models for audit JSON payloads."""

from __future__ import annotations

from collections import Counter
from typing import Any


VARIABLE_HELP = {
    "resource_id": "Identificador intern d'una pista, dia i franja horaria.",
    "base_resource_id": "Recurs base sense jornada concreta: pista, dia i hora.",
    "venue": "Pista o instal.lacio on juga com a local l'equip.",
    "day": "Dia de joc demanat per l'equip.",
    "hour_slot": "Franja horaria normalitzada.",
    "round_index": "Numero de jornada dins la fase.",
    "demand_count": "Equips que demanen el mateix recurs base.",
    "estimated_capacity": "Capacitat estimada per aquell recurs.",
    "capacity": "Maxim de locals assumit per recurs i jornada.",
    "pressure": "Demanda dividida per capacitat. Valors alts indiquen saturacio.",
    "is_critical": "Marca que el recurs esta per sobre de la capacitat estimada.",
    "team_id": "Nom de l'equip; si el run antic no porta cataleg, pot aparèixer un identificador intern.",
    "group_id": "Grup assignat.",
    "number": "Numero de sorteig assignat dins del grup.",
    "seed_request_original": "Valor demanat al fitxer d'entrada.",
    "potential_home_rounds": "Jornades on aquell numero jugaria com a local.",
    "opponent_number_by_round": "Numero rival que tocaria a cada jornada.",
    "potential_resources": "Recursos que consumiria l'equip si agafes aquest numero.",
    "status": "Estat retornat pel solver.",
    "objective_value": "Valor final de la funcio objectiu. Mes baix acostuma a ser millor.",
    "best_bound": "Millor cota provada pel solver per comparar qualitat de solucio.",
    "wall_time": "Temps de resolucio en segons.",
    "assignments": "Assignacions finals equip, grup i numero.",
    "real_matches": "Partits reals generats, excloent descansos.",
    "resource_usage": "Us de pistes/franges per jornada.",
    "group_summary": "Resum de numeros ocupats i descansos per grup.",
    "entity_excess": "Conflictes on una entitat te mes d'un equip al mateix grup.",
    "locals_count": "Partits locals acumulats en aquell recurs i jornada.",
    "excess": "Quantitat que supera la capacitat configurada.",
}


ARTIFACT_EXPLANATIONS = {
    "resource_pressure": (
        "Pressio de pistes i franges",
        "Mostra quines pistes, dies i hores concentren mes demanda abans de resoldre.",
    ),
    "candidate_catalog": (
        "Cataleg de candidates",
        "Llista totes les combinacions possibles equip, grup i numero que el solver pot escollir.",
    ),
    "solver_model_summary": (
        "Resum del model",
        "Explica la mida del model, pesos de penalitzacio i estat de la resolucio.",
    ),
    "resource_solution": (
        "Solucio del solver",
        "Resumeix les assignacions finals i els impactes sobre recursos, grups i entitats.",
    ),
    "solver_explanations": (
        "Explicacions de la solucio",
        "Tradueix el resultat a incidencies: saturacio, excessos, descansos i desviacions.",
    ),
    "local_combinations": (
        "Combinacions locals",
        "Mostra alternatives locals analitzades quan el volum permet calcular-les.",
    ),
    "team_catalog": (
        "Equips del run",
        "Cataleg d'equips utilitzat per traduir identificadors interns a noms llegibles.",
    ),
    "resource_solver_result": (
        "Resultat complet del solver",
        "Resultat tecnic complet que alimenta l'Excel i les auditories.",
    ),
    "resource_solver_conflict_repair_result": (
        "Resultat complet conflict-repair",
        "Resultat tecnic complet del motor per components inicials i reparacio de hubs.",
    ),
    "conflict_repair_initial_components": (
        "Components inicials conflict-repair",
        "Components generats amb competicions i vinculacions, abans de mirar recursos.",
    ),
    "conflict_repair_component_solves": (
        "Resolucions parcials conflict-repair",
        "Detall de les resolucions dels components inicials i dels blocs reparats.",
    ),
    "conflict_repair_hubs": (
        "Hubs de conflicte",
        "Recursos i jornades on la solucio inicial supera capacitat.",
    ),
    "conflict_repair_blocks": (
        "Blocs de reparacio",
        "Subgrafs reconnectats per reparar xocs de recursos, expandits per vinculacions.",
    ),
    "conflict_repair_iteration_summary": (
        "Resum conflict-repair",
        "Comparativa entre solucio inicial i solucio final despres de la reparacio.",
    ),
    "conflict_repair_iteration_summary_partial": (
        "Resum parcial conflict-repair",
        "Estat abans de reoptimitzar blocs: exces inicial, hubs detectats i blocs pendents.",
    ),
}


def build_audit_presentation(
    artifact: str,
    payload: Any,
    *,
    related_payloads: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title, description = ARTIFACT_EXPLANATIONS.get(
        artifact,
        (_humanize(artifact), "Vista explicativa generada a partir de l'artifact d'auditoria."),
    )
    presentation = {
        "title": title,
        "description": description,
        "team_lookup": _team_lookup(payload, related_payloads or {}),
        "cards": [],
        "charts": [],
        "tables": [],
        "definitions": [],
        "notes": [],
    }

    if artifact == "team_catalog" and isinstance(payload, list):
        _present_team_catalog(presentation, payload)
    elif artifact == "resource_pressure" and isinstance(payload, list):
        _present_resource_pressure(presentation, payload)
    elif artifact == "candidate_catalog" and isinstance(payload, list):
        _present_candidate_catalog(presentation, payload)
    elif artifact == "solver_model_summary" and isinstance(payload, dict):
        _present_solver_model_summary(presentation, payload)
    elif artifact in {"resource_solution", "resource_solver_result", "resource_solver_conflict_repair_result"} and isinstance(payload, dict):
        _present_resource_solution(presentation, payload)
    elif artifact == "solver_explanations" and isinstance(payload, dict):
        _present_solver_explanations(presentation, payload)
    else:
        _present_generic(presentation, payload)

    _attach_definitions(presentation)
    presentation.pop("team_lookup", None)
    return presentation


def _present_team_catalog(presentation: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    entities = {row.get("entity") for row in rows if row.get("entity")}
    venues = {row.get("venue") for row in rows if row.get("venue")}
    presentation["cards"].extend(
        [
            _card("Equips", len(rows), "Equips llegits del fitxer d'entrada."),
            _card("Entitats", len(entities), "Clubs o entitats diferents."),
            _card("Pistes", len(venues), "Pistes locals declarades."),
        ]
    )
    _add_table(
        presentation,
        "Equips",
        rows,
        ["name", "entity", "league_name", "modality", "category", "venue", "day", "time", "seed_request_original"],
    )


def _present_resource_pressure(presentation: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    critical = [row for row in rows if row.get("is_critical")]
    max_pressure = max((_number(row.get("pressure")) for row in rows), default=0.0)
    presentation["cards"].extend(
        [
            _card("Recursos analitzats", len(rows), "Pistes/franges detectades a l'entrada."),
            _card("Recursos critics", len(critical), "Recursos amb demanda superior a la capacitat estimada."),
            _card("Pressio maxima", _fmt(max_pressure), "Demanda/capacitat mes alta detectada."),
        ]
    )
    bars = [
        _bar(
            _resource_label(row),
            _number(row.get("pressure")),
            max_pressure or 1,
            value_text=_fmt(row.get("pressure")),
            kind="danger" if row.get("is_critical") else "normal",
        )
        for row in sorted(rows, key=lambda item: _number(item.get("pressure")), reverse=True)[:12]
    ]
    presentation["charts"].append(
        {
            "title": "Pressio per pista/franja",
            "description": "Valors per sobre d'1 indiquen que la demanda supera la capacitat estimada.",
            "bars": bars,
        }
    )
    _add_table(
        presentation,
        "Detall de recursos",
        rows,
        ["venue", "day", "hour_slot", "teams", "demand_count", "estimated_capacity", "pressure", "is_critical"],
    )


def _present_candidate_catalog(presentation: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    teams = {row.get("team_id") for row in rows}
    groups = {row.get("group_id") for row in rows}
    numbers = {row.get("number") for row in rows}
    by_group = Counter(str(row.get("group_id", "")) for row in rows)
    max_count = max(by_group.values(), default=1)
    presentation["cards"].extend(
        [
            _card("Candidates", len(rows), "Combinacions equip, grup i numero possibles."),
            _card("Equips", len(teams), "Equips amb candidates generades."),
            _card("Grups", len(groups), "Grups disponibles per al solver."),
            _card("Numeros", len(numbers), "Numeros de sorteig considerats."),
        ]
    )
    presentation["charts"].append(
        {
            "title": "Candidates per grup",
            "description": "Serveix per detectar si algun grup concentra massa opcions o si el cataleg esta desequilibrat.",
            "bars": [_bar(group, count, max_count, value_text=str(count)) for group, count in sorted(by_group.items())],
        }
    )
    _add_table(
        presentation,
        "Primeres candidates",
        rows,
        ["team_id", "group_id", "number", "seed_request_original", "potential_home_rounds", "potential_resources"],
    )


def _present_solver_model_summary(presentation: dict[str, Any], payload: dict[str, Any]) -> None:
    objective_terms = payload.get("objective_terms") if isinstance(payload.get("objective_terms"), dict) else {}
    weights = payload.get("weights") if isinstance(payload.get("weights"), dict) else {}
    max_terms = max([_number(value) for value in objective_terms.values()] or [1])
    presentation["cards"].extend(
        [
            _card("Estat", payload.get("status", "-"), "Resultat global del solver."),
            _card("Equips", payload.get("num_teams", 0), "Equips inclosos al model."),
            _card("Grups", payload.get("num_groups", 0), "Grups generats."),
            _card("Variables", payload.get("num_variables", 0), "Decisions internes del model."),
            _card("Restriccions", payload.get("num_constraints", 0), "Condicions imposades al solver."),
            _card("Temps", _fmt(payload.get("wall_time")), "Segons de resolucio."),
        ]
    )
    presentation["charts"].append(
        {
            "title": "Termes de la funcio objectiu",
            "description": "Indica quins tipus de penalitzacio intervenen en la solucio.",
            "bars": [_bar(_humanize(key), value, max_terms, value_text=str(value)) for key, value in objective_terms.items()],
        }
    )
    _add_key_value_table(presentation, "Pesos configurats", weights)
    _add_key_value_table(presentation, "Valors principals", payload)


def _present_resource_solution(presentation: dict[str, Any], payload: dict[str, Any]) -> None:
    assignments = _list(payload.get("assignments"))
    real_matches = _list(payload.get("real_matches"))
    usage = _list(payload.get("resource_usage"))
    groups = _list(payload.get("group_summary"))
    entity_excess = payload.get("entity_excess") if isinstance(payload.get("entity_excess"), dict) else {}
    total_excess = sum(_number(row.get("excess")) for row in usage if isinstance(row, dict))
    presentation["cards"].extend(
        [
            _card("Estat", payload.get("status", "-"), "Estat retornat pel solver."),
            _card("Assignacions", len(assignments), "Equips assignats a grup i numero."),
            _card("Partits reals", len(real_matches), "Partits generats sense comptar descansos."),
            _card("Exces recursos", int(total_excess), "Capacitat superada en pistes/franges."),
            _card("Conflictes entitat", len(entity_excess), "Entitat repetida dins d'un grup."),
        ]
    )
    _add_usage_chart(presentation, usage)
    _add_table(presentation, "Assignacions", assignments, ["team_id", "group_id", "number"])
    _add_table(presentation, "Us de recursos", usage, ["resource_id", "locals_count", "capacity", "excess", "team_ids"])
    _add_table(presentation, "Resum de grups", groups, ["group_id", "assigned_numbers", "empty_numbers", "rests_by_team", "entity_excess"])


def _present_solver_explanations(presentation: dict[str, Any], payload: dict[str, Any]) -> None:
    saturation = _list(payload.get("resource_saturation"))
    excess_resources = _list(payload.get("resource_excess"))
    seed_deviations = _list(payload.get("seed_request_deviations_informative_only"))
    entity_excess = payload.get("entity_excess") if isinstance(payload.get("entity_excess"), dict) else {}
    notes = _list(payload.get("notes"))
    presentation["cards"].extend(
        [
            _card("Estat", payload.get("status", "-"), "Estat explicat de la solucio."),
            _card("Recursos saturats", len(saturation), "Pistes/franges al limit o per sobre."),
            _card("Recursos amb exces", len(excess_resources), "Pistes/franges que superen capacitat."),
            _card("Conflictes entitat", len(entity_excess), "Entitats repetides dins un mateix grup."),
            _card("Desviacions sorteig", len(seed_deviations), "Peticions numeriques no assignades exactament."),
        ]
    )
    _add_usage_chart(presentation, saturation)
    _add_table(presentation, "Recursos amb exces", excess_resources, ["resource_id", "locals_count", "capacity", "excess", "teams"])
    _add_key_value_table(presentation, "Conflictes d'entitat", entity_excess)
    _add_table(presentation, "Desviacions de sorteig", seed_deviations, ["team_id", "requested", "assigned_number"])
    presentation["notes"].extend(str(note) for note in notes)


def _present_generic(presentation: dict[str, Any], payload: Any) -> None:
    if isinstance(payload, dict):
        presentation["cards"].append(_card("Camps", len(payload), "Nombre de claus principals de l'artifact."))
        arrays = {key: value for key, value in payload.items() if isinstance(value, list)}
        for key, value in arrays.items():
            if value and isinstance(value[0], dict):
                _add_table(presentation, _humanize(key), value, list(value[0].keys())[:8])
        scalar_values = {key: value for key, value in payload.items() if not isinstance(value, (list, dict))}
        if scalar_values:
            _add_key_value_table(presentation, "Valors principals", scalar_values)
        return
    if isinstance(payload, list):
        presentation["cards"].append(_card("Registres", len(payload), "Nombre de files a l'artifact."))
        if payload and isinstance(payload[0], dict):
            _add_table(presentation, "Registres", payload, list(payload[0].keys())[:8])
        return
    presentation["cards"].append(_card("Valor", payload, "Contingut de l'artifact."))


def _attach_definitions(presentation: dict[str, Any]) -> None:
    seen = []
    labels_by_source = {}
    for table in presentation["tables"]:
        for column in table.get("columns", []):
            source = column.get("source") if isinstance(column, dict) else column
            if isinstance(column, dict):
                labels_by_source[source] = column.get("label", source)
            if source in VARIABLE_HELP and source not in seen:
                seen.append(source)
    for chart in presentation["charts"]:
        for key in ("pressure", "capacity", "locals_count", "excess"):
            if key in VARIABLE_HELP and key not in seen:
                seen.append(key)
    presentation["definitions"] = [{"name": labels_by_source.get(key, key), "description": VARIABLE_HELP[key]} for key in seen]


def _add_usage_chart(presentation: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    max_locals = max((_number(row.get("locals_count")) for row in rows), default=1)
    presentation["charts"].append(
        {
            "title": "Us de recursos",
            "description": "Compara partits locals acumulats amb la capacitat configurada.",
            "bars": [
                _bar(
                    _pretty_resource_id(row.get("resource_id", "-")),
                    _number(row.get("locals_count")),
                    max_locals or 1,
                    value_text=f"{row.get('locals_count', 0)} / {row.get('capacity', '-')}",
                    kind="danger" if _number(row.get("excess")) > 0 else "normal",
                )
                for row in rows[:12]
            ],
        }
    )


def _add_table(
    presentation: dict[str, Any],
    title: str,
    rows: list[Any],
    columns: list[str],
    *,
    limit: int = 50,
) -> None:
    clean_rows = [row for row in rows if isinstance(row, dict)]
    if not clean_rows:
        return
    display_columns = [_display_column(column) for column in columns]
    presentation["tables"].append(
        {
            "title": title,
            "columns": display_columns,
            "rows": [_display_row(row, columns, presentation) for row in clean_rows[:limit]],
            "total": len(clean_rows),
            "limit": limit,
        }
    )


def _add_key_value_table(presentation: dict[str, Any], title: str, mapping: dict[str, Any]) -> None:
    if not mapping:
        return
    rows = [{"variable": key, "valor": value} for key, value in mapping.items()]
    _add_table(presentation, title, rows, ["variable", "valor"], limit=80)


def _card(label: str, value: Any, help_text: str = "") -> dict[str, Any]:
    display_value = _display_scalar(value)
    return {"label": label, "value": display_value, "help": help_text, "tone": _card_tone(label, display_value)}


def _bar(label: str, value: Any, maximum: Any, *, value_text: str = "", kind: str = "normal") -> dict[str, Any]:
    numeric_value = _number(value)
    numeric_max = _number(maximum) or 1.0
    pct = max(0, min(100, int(round((numeric_value / numeric_max) * 100))))
    return {
        "label": label,
        "value": numeric_value,
        "value_text": value_text or _fmt(numeric_value),
        "percent": pct,
        "kind": kind,
    }


def _card_tone(label: str, value: Any) -> str:
    text_value = str(value).strip().upper()
    if text_value in {"OPTIMAL", "OK", "0"} and any(key in label.lower() for key in ("estat", "exces", "conflictes", "desviacions")):
        return "success"
    if text_value in {"FEASIBLE", "UNKNOWN"}:
        return "warning"
    if text_value in {"INFEASIBLE", "ERROR"}:
        return "danger"
    numeric = _number(value)
    lowered = label.lower()
    if any(key in lowered for key in ("exces", "saturats", "desviacions", "conflictes", "critics")):
        return "danger" if numeric > 0 else "success"
    return "neutral"


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fmt(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.2f}"


def _resource_label(row: dict[str, Any]) -> str:
    return " · ".join(str(row.get(key, "")) for key in ("venue", "day", "hour_slot") if row.get(key)) or str(row.get("resource_id", "-"))


def _humanize(value: Any) -> str:
    labels = {
        "resource_excess": "Exces de recursos",
        "entity_excess": "Conflictes d'entitat",
        "empty_number_imbalance": "Desequilibri de descansos",
        "resource_excess_weight": "Pes exces recursos",
        "entity_excess_weight": "Pes conflictes entitat",
        "empty_number_imbalance_weight": "Pes descansos",
    }
    text = str(value)
    return labels.get(text, text.replace("_", " ").strip().capitalize())


def _display_column(column: str) -> dict[str, str]:
    labels = {
        "team_id": "Equip",
        "team_ids": "Equips",
        "teams": "Equips",
        "resource_id": "Recurs",
        "base_resource_id": "Recurs",
        "group_id": "Grup",
        "number": "Numero",
        "assigned_number": "Numero assignat",
        "requested": "Demanat",
        "seed_request_original": "Peticio",
        "potential_home_rounds": "Jornades local",
        "potential_resources": "Recursos possibles",
        "assigned_numbers": "Numeros assignats",
        "empty_numbers": "Descansos",
        "rests_by_team": "Descansos per equip",
        "entity_excess": "Conflictes entitat",
        "locals_count": "Locals",
        "capacity": "Capacitat",
        "excess": "Exces",
        "is_critical": "Critic",
        "demand_count": "Demanda",
        "estimated_capacity": "Capacitat estimada",
        "pressure": "Pressio",
        "venue": "Pista",
        "day": "Dia",
        "hour_slot": "Hora",
        "time": "Hora",
        "name": "Equip",
        "entity": "Entitat",
        "league_name": "Lliga",
        "modality": "Modalitat",
        "category": "Categoria",
        "subcategory": "Subcategoria",
        "level": "Nivell",
        "variable": "Variable",
        "valor": "Valor",
    }
    return {"source": column, "key": _display_key(column), "label": labels.get(column, _humanize(column))}


def _display_key(column: str) -> str:
    return {
        "team_id": "team",
        "team_ids": "teams_display",
        "teams": "teams_display",
        "resource_id": "resource",
        "base_resource_id": "resource",
        "potential_resources": "resources_display",
    }.get(column, column)


def _display_row(row: dict[str, Any], columns: list[str], presentation: dict[str, Any]) -> dict[str, Any]:
    return {_display_key(column): _display_value(column, row.get(column), presentation) for column in columns}


def _display_value(column: str, value: Any, presentation: dict[str, Any]) -> Any:
    if column == "team_id":
        return _team_label(value, presentation)
    if column in {"team_ids", "teams"}:
        return [_team_label(item, presentation) for item in _as_list(value)]
    if column in {"resource_id", "base_resource_id"}:
        return _pretty_resource_id(value)
    if column == "potential_resources":
        return [_pretty_resource_id(item) for item in _as_list(value)]
    if column == "potential_home_rounds":
        return [f"Jornada {item}" for item in _as_list(value)]
    if column == "rests_by_team" and isinstance(value, dict):
        return {
            _team_label(team_id, presentation): [f"Jornada {round_index}" for round_index in _as_list(rounds)]
            for team_id, rounds in value.items()
        }
    if column == "assigned_numbers" and isinstance(value, dict):
        return {f"Numero {number}": _team_label(team_id, presentation) for number, team_id in value.items()}
    if column == "entity_excess" and isinstance(value, dict):
        return {str(key).replace("|", " · "): item for key, item in value.items()}
    if column == "is_critical":
        return "Si" if value else "No"
    return _display_scalar(value)


def _display_scalar(value: Any) -> Any:
    if isinstance(value, str) and "|" in value:
        return _pretty_resource_id(value)
    return value


def _team_lookup(payload: Any, related_payloads: dict[str, Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for candidate in [payload, *related_payloads.values()]:
        if not isinstance(candidate, list):
            continue
        for row in candidate:
            if isinstance(row, dict) and row.get("team_id") and row.get("name"):
                lookup[str(row["team_id"])] = str(row["name"])
    return lookup


def _team_label(value: Any, presentation: dict[str, Any]) -> str:
    team_id = "" if value is None else str(value)
    if not team_id:
        return "-"
    lookup = presentation.get("team_lookup", {})
    if isinstance(lookup, dict) and team_id in lookup:
        return str(lookup[team_id])
    if team_id.startswith("row-"):
        return f"Equip sense nom ({team_id})"
    return team_id


def _pretty_resource_id(value: Any) -> str:
    text = "" if value is None else str(value)
    if not text:
        return "-"
    parts = text.split("|")
    if len(parts) < 3:
        return text.replace("_", " ").replace("-", " ").strip().capitalize()
    label = f"{_pretty_token(parts[0])} · {_pretty_token(parts[1])} · {_pretty_hour(parts[2])}"
    if len(parts) >= 4 and parts[3]:
        label = f"{label} · {_pretty_round(parts[3])}"
    return label


def _pretty_token(value: str) -> str:
    text = value.replace("_", " ").replace("-", " ").strip()
    lowered = text.lower()
    if lowered in {"sense pista", "sensepista"}:
        return "Sense pista"
    if lowered in {"sense dia", "sensedia"}:
        return "Sense dia"
    return text.capitalize() if text else "-"


def _pretty_hour(value: str) -> str:
    text = value.strip()
    if "-" in text and len(text) >= 5:
        hour, minute = text.split("-", 1)
        if hour.isdigit() and minute[:2].isdigit():
            return f"{hour.zfill(2)}:{minute[:2]}"
    return text


def _pretty_round(value: str) -> str:
    text = value.strip()
    if text.upper().startswith("J") and text[1:].isdigit():
        return f"Jornada {int(text[1:])}"
    return text


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in (None, ""):
        return []
    return [value]
