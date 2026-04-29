from __future__ import annotations

from .manual_assignment import (
    LOAD_BALANCING_PENALTY_PER_ASSIGNMENT,
    build_manual_assignment_context,
    classify_level_fit,
    compute_cost_breakdown,
    diagnose_assignment_for_referee,
    serialize_proposal,
)


SIGNIFICANT_EFFECTIVE_COST_GAP = 100

LEVEL_FIT_PRIORITY = {
    "ideal": 0,
    "slightly_underleveled": 1,
    "slightly_overleveled": 1,
    "clearly_underleveled": 2,
    "clearly_overleveled": 2,
    "unscorable": 3,
}

ORIGIN_LABELS = {
    "high": ("Assignacio prioritaria", "El partit es va cobrir en la primera passada prioritaria."),
    "medium": ("Assignacio de nivell mitja/alt", "El partit es va cobrir quan el motor va ampliar tutors i partits compatibles."),
    "general": ("Assignacio general", "El partit es va cobrir en la passada general."),
    "partial_rescue": ("Recuperacio parcial", "El partit es va recuperar despres d'una passada parcial."),
    "final_rescue": ("Recuperacio final", "El partit es va assignar en una passada final de recuperacio."),
    "new_route_rescue": ("Nova sequencia recuperada", "El motor va formar una nova sequencia amb partits pendents."),
    "individual_rescue": ("Recuperacio individual", "El partit es va assignar individualment en una passada de recuperacio."),
    "package_solver": ("Assignacio per paquet", "El partit es va assignar amb el motor de paquets."),
    "initial": ("Assignacio inicial", "El partit es va cobrir en la passada inicial del motor."),
    "rescue_idle": ("Recuperacio amb tutor lliure", "El partit es va recuperar amb un tutor que encara no tenia assignacions."),
    "rescue_reused": ("Recuperacio afegida", "El partit es va recuperar reutilitzant un tutor compatible."),
    "manual_override": ("Assignacio manual", "La designacio ha estat modificada manualment per un usuari."),
    "manual_unassigned": ("Desassignacio manual", "La designacio ha estat retirada manualment per un usuari."),
}


def _ensure_context(run, context=None):
    return context or build_manual_assignment_context(run)


def _build_candidate_diagnoses_for_assignment(run, assignment, context):
    cache = context.setdefault("_candidate_diagnoses_by_assignment", {})
    if assignment.id in cache:
        return cache[assignment.id]

    diagnoses = {}
    for referee in context["referees_by_assignment"].get(assignment.id, []):
        diagnoses[referee.id] = diagnose_assignment_for_referee(
            run,
            assignment,
            referee,
            availability_lookup=context["availability_lookup"],
            assignments_by_referee=context["assignments_by_referee"],
            cluster_by_match_id=context["cluster_by_match_id"],
        )
    cache[assignment.id] = diagnoses
    return diagnoses


def _feasibility_status(diagnosis: dict) -> str:
    blocking_reasons = diagnosis.get("blocking_reasons")
    if blocking_reasons is None:
        blocking_reasons = diagnosis.get("warning_reasons") or []
    if not blocking_reasons:
        return "valid"
    if set(blocking_reasons).issubset({"missing_match_datetime"}):
        return "unknown"
    return "invalid"


def _better_candidate_exists(run, assignment, candidate_diagnosis: dict, context) -> bool:
    compatible_diagnoses = _build_candidate_diagnoses_for_assignment(run, assignment, context)
    for other_referee_id, other_diagnosis in compatible_diagnoses.items():
        if other_referee_id == candidate_diagnosis["referee"].id:
            continue
        if _is_better_candidate(run, assignment, other_diagnosis, candidate_diagnosis, context):
            return True
    return False


def _is_better_candidate(run, assignment, other_diagnosis: dict, current_diagnosis: dict, context) -> bool:
    if not other_diagnosis.get("is_valid") or other_diagnosis.get("cost") is None:
        return False

    other_level_fit = classify_level_fit(assignment.match, other_diagnosis["referee"])["label"]
    current_level_fit = classify_level_fit(assignment.match, current_diagnosis["referee"])["label"]

    other_priority = LEVEL_FIT_PRIORITY.get(other_level_fit, 999)
    current_priority = LEVEL_FIT_PRIORITY.get(current_level_fit, 999)
    if other_priority < current_priority:
        return True

    if other_priority == current_priority:
        other_effective_cost = other_diagnosis.get("effective_cost")
        current_effective_cost = current_diagnosis.get("effective_cost")
        if other_effective_cost is not None and current_effective_cost is not None:
            return (current_effective_cost - other_effective_cost) >= SIGNIFICANT_EFFECTIVE_COST_GAP
    return False


def _quality_label(is_manual_override: bool, diagnosis: dict, level_fit_label: str, better_alternative_exists: bool) -> str:
    if is_manual_override:
        return "manual_override"
    if not diagnosis.get("is_valid"):
        return "forced_by_constraints"
    if level_fit_label == "ideal":
        return "recommended"
    if level_fit_label in {"slightly_underleveled", "slightly_overleveled", "unscorable"}:
        return "acceptable"
    if better_alternative_exists:
        return "suspicious"
    return "forced_by_constraints"


def _selection_reason_summary(feasibility_status: str, level_fit_label: str, quality_label: str) -> str:
    parts = []

    if feasibility_status == "valid":
        parts.append("Vàlida horàriament")
    elif feasibility_status == "unknown":
        parts.append("Validació horària incompleta")
    else:
        parts.append("Amb restriccions operatives")

    level_messages = {
        "ideal": "encaix de nivell ideal",
        "slightly_underleveled": "tutor lleugerament per sota del nivell recomanat",
        "slightly_overleveled": "tutor lleugerament per sobre del nivell recomanat",
        "clearly_underleveled": "tutor clarament per sota del nivell recomanat",
        "clearly_overleveled": "tutor clarament per sobre del nivell recomanat",
        "unscorable": "encaix de nivell no puntuable",
    }
    parts.append(level_messages.get(level_fit_label, "encaix de nivell no classificat"))

    quality_messages = {
        "recommended": "és una de les opcions recomanades",
        "acceptable": "selecció operativament raonable",
        "forced_by_constraints": "triat per manca d'alternatives compatibles clarament millors",
        "suspicious": "hi ha alternatives compatibles millors",
        "manual_override": "designació manual amb warning",
    }
    parts.append(quality_messages.get(quality_label, "explicació no disponible"))
    return "; ".join(parts)


def _trace_stage_key(trace) -> str:
    stage = str(getattr(trace, "stage", "") or "")
    phase_name = str(getattr(trace, "phase_name", "") or "")
    rescue_kind = str(getattr(trace, "rescue_kind", "") or "")
    if rescue_kind:
        return rescue_kind
    if phase_name in ORIGIN_LABELS:
        return phase_name
    if stage.startswith("phase:"):
        return stage.split(":", 1)[1]
    if stage.startswith("partial_rescue"):
        return "partial_rescue"
    if stage.startswith("individual_rescue"):
        return "individual_rescue"
    return stage


def _assignment_origin_payload(assignment) -> dict:
    trace = getattr(assignment, "trace", None)
    if trace is None:
        return {
            "available": False,
            "label": "Origen no disponible",
            "summary": "Origen no disponible perque aquesta designacio es anterior al tracking.",
            "stage": "",
            "route_size": 1,
            "inserted_into_existing_route": False,
            "route_match_codes": [],
        }
    key = _trace_stage_key(trace)
    label, summary = ORIGIN_LABELS.get(
        key,
        ("Assignacio automatica", "El partit es va assignar automaticament amb el motor de designacions."),
    )
    route_size = int(getattr(trace, "route_size", 1) or 1)
    details = []
    if route_size > 1:
        details.append(f"Forma part d'una sequencia de {route_size} partits.")
    if getattr(trace, "inserted_into_existing_route", False):
        details.append("El partit es va afegir a una jornada que aquest tutor ja tenia assignada.")
    warning_codes = list(getattr(trace, "warning_codes", None) or [])
    if warning_codes:
        details.append("La designacio queda marcada per revisio operativa.")
    return {
        "available": True,
        "label": label,
        "summary": " ".join([summary, *details]).strip(),
        "stage": getattr(trace, "stage", "") or "",
        "phase_name": getattr(trace, "phase_name", "") or "",
        "route_size": route_size,
        "inserted_into_existing_route": bool(getattr(trace, "inserted_into_existing_route", False)),
        "route_match_codes": list(getattr(trace, "route_match_codes", None) or []),
        "warning_codes": warning_codes,
    }


def _route_context_payload(trace) -> list[dict]:
    if trace is None:
        return []
    ids = [str(value) for value in (getattr(trace, "route_match_ids", None) or [])]
    codes = [str(value) for value in (getattr(trace, "route_match_codes", None) or [])]
    if not (ids or codes):
        return []
    qs = trace.run.matches.all()
    if ids:
        qs = qs.filter(engine_id__in=ids)
    else:
        qs = qs.filter(code__in=codes)
    matches = list(qs)
    order = {value: index for index, value in enumerate(ids or codes)}
    matches.sort(key=lambda match: (match.date or "", match.hour_raw or "", order.get(str(match.engine_id or match.code), 999)))
    return [
        {
            "code": match.code or "",
            "hour": match.hour_raw or "",
            "venue": match.venue or "",
            "category": match.category or "",
        }
        for match in matches
    ]


def _build_explanation_payload(run, assignment, diagnosis: dict, context, *, manual_override: bool = False) -> dict:
    referee = diagnosis["referee"]
    level_fit = classify_level_fit(assignment.match, referee)
    feasibility_status = _feasibility_status(diagnosis)
    better_alternative_exists = _better_candidate_exists(run, assignment, diagnosis, context)
    quality_label = _quality_label(manual_override, diagnosis, level_fit["label"], better_alternative_exists)

    score_breakdown = compute_cost_breakdown(
        assignment.match,
        referee,
        context["cluster_by_match_id"].get(assignment.match.id),
    )
    score_breakdown.update(
        {
            "load_balancing_penalty": (
                diagnosis["n_assignments_in_run"] * LOAD_BALANCING_PENALTY_PER_ASSIGNMENT
                if diagnosis.get("cost") is not None
                else None
            ),
            "effective_cost": diagnosis.get("effective_cost"),
            "n_assignments_in_run": diagnosis.get("n_assignments_in_run"),
        }
    )

    trace = getattr(assignment, "trace", None)
    explanation = {
        "assignment_origin": _assignment_origin_payload(assignment),
        "route_context": _route_context_payload(trace),
        "feasibility": {
            "status": feasibility_status,
            "blocking_reasons": diagnosis.get("blocking_reasons", diagnosis.get("warning_reasons")) if feasibility_status == "invalid" else [],
            "advisory_reasons": diagnosis.get("advisory_reasons", []),
            "warning_reasons": diagnosis.get("warning_reasons", []),
            "warning_messages": diagnosis.get("warning_messages", []),
        },
        "level_fit": level_fit["label"],
        "level_fit_detail": {
            "tutor_level": level_fit["tutor_level"],
            "match_category": level_fit["match_category"],
            "band_delta": level_fit["band_delta"],
        },
        "score_breakdown": score_breakdown,
        "quality_label": quality_label,
        "selection_reason_summary": _selection_reason_summary(
            feasibility_status,
            level_fit["label"],
            quality_label,
        ),
    }
    return explanation


def explain_candidate_for_assignment(run, assignment, referee, context=None):
    context = _ensure_context(run, context)
    compatible_diagnoses = _build_candidate_diagnoses_for_assignment(run, assignment, context)
    diagnosis = compatible_diagnoses.get(referee.id)
    if diagnosis is None:
        diagnosis = diagnose_assignment_for_referee(
            run,
            assignment,
            referee,
            availability_lookup=context["availability_lookup"],
            assignments_by_referee=context["assignments_by_referee"],
            cluster_by_match_id=context["cluster_by_match_id"],
        )

    return _build_explanation_payload(run, assignment, diagnosis, context)


def _serialize_explained_candidate(run, assignment, diagnosis: dict, context, *, comparison_reason: str = "") -> dict:
    explanation = _build_explanation_payload(run, assignment, diagnosis, context)
    serialized = serialize_proposal(
        {
            **diagnosis,
            "level_fit": explanation["level_fit"],
            "quality_label": explanation["quality_label"],
            "selection_reason_summary": explanation["selection_reason_summary"],
        }
    )
    if comparison_reason:
        serialized["comparison_reason"] = comparison_reason
    return serialized


def find_better_alternatives(run, assignment, assigned_referee, limit: int = 3, context=None):
    context = _ensure_context(run, context)
    compatible_diagnoses = _build_candidate_diagnoses_for_assignment(run, assignment, context)
    assigned_diagnosis = compatible_diagnoses.get(assigned_referee.id)
    if assigned_diagnosis is None:
        assigned_diagnosis = diagnose_assignment_for_referee(
            run,
            assignment,
            assigned_referee,
            availability_lookup=context["availability_lookup"],
            assignments_by_referee=context["assignments_by_referee"],
            cluster_by_match_id=context["cluster_by_match_id"],
        )

    better_alternatives = []
    for referee_id, diagnosis in compatible_diagnoses.items():
        if referee_id == assigned_referee.id:
            continue
        if not _is_better_candidate(run, assignment, diagnosis, assigned_diagnosis, context):
            continue

        better_alternatives.append(
            _serialize_explained_candidate(
                run,
                assignment,
                diagnosis,
                context,
                comparison_reason="Alternativa compatible millor que la designació actual.",
            )
        )

    better_alternatives.sort(
        key=lambda item: (
            LEVEL_FIT_PRIORITY.get(item.get("level_fit"), 999),
            item.get("effective_cost") if item.get("effective_cost") is not None else float("inf"),
            item.get("code") or "",
        )
    )
    return better_alternatives[:limit]


def explain_current_assignment(run, assignment, context=None):
    if not assignment.referee_id:
        raise ValueError("L'assignacio no te tutor assignat.")

    context = _ensure_context(run, context)
    diagnosis = diagnose_assignment_for_referee(
        run,
        assignment,
        context["referee_summaries_by_id"].get(assignment.referee_id, assignment.referee),
        availability_lookup=context["availability_lookup"],
        assignments_by_referee=context["assignments_by_referee"],
        cluster_by_match_id=context["cluster_by_match_id"],
    )
    explanation = _build_explanation_payload(
        run,
        assignment,
        diagnosis,
        context,
        manual_override=assignment.manual_override_warning,
    )

    return {
        "assignment_id": assignment.id,
        "assigned_referee": {
            "id": assignment.referee.id,
            "code": assignment.referee.code,
            "name": assignment.referee.name,
            "level": context["referee_summaries_by_id"].get(assignment.referee_id, assignment.referee).level
            if assignment.referee_id
            else (assignment.referee.level or ""),
        },
        "explanation": explanation,
        "better_alternatives": find_better_alternatives(
            run,
            assignment,
            context["referee_summaries_by_id"].get(assignment.referee_id, assignment.referee),
            context=context,
        ),
    }
