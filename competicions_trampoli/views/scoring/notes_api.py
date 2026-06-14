import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from ...models import Competicio
from ...models.scoring import (
    ScoreEntry,
    ScoreEntryVideo,
    ScoreWarningAcknowledgement,
    TeamScoreEntry,
    TeamScoreEntryVideo,
)
from ...services.scoring.schema_resolution import resolve_scoring_schema_for_comp_aparell
from ...services.scoring.notes_units import (
    build_notes_units_context,
    clamp_exercici,
    effective_exercise_count,
    media_counts_for_inscripcions,
    order_subjects_for_unit,
    resolve_notes_unit,
    serialize_comp_aparell,
    serialize_franja,
    serialize_phase,
    serialize_individual_subject,
    subjects_for_unit,
)
from ...services.scoring.score_warnings import generate_score_warnings
from ...services.scoring.judge_presence import is_judge_shaped_field, presence_key
from ...services.scoring.scoring_subjects import score_store_key
from ...services.inscripcions.admission import filter_score_entries_admeses
from ...services.scoring.team_scoring import is_team_context_app, runtime_schema_for_comp_aparell
from ...services.scoring.team_subject_contract import build_team_subject_registry, runtime_schema_for_team_subjects
from .helpers import (
    _allowed_input_codes_for_schema,
    _logical_schema_for_notes_ui,
    _logical_team_input_codes,
    _sanitize_inputs_for_client,
)


def _schema_payload(comp_aparell, competicio):
    _schema_obj, base_schema = resolve_scoring_schema_for_comp_aparell(comp_aparell)
    base_schema = base_schema or {}
    logical_schema = _logical_schema_for_notes_ui(base_schema, comp_aparell)
    if is_team_context_app(comp_aparell):
        registry = build_team_subject_registry(competicio, comp_aparell)
        schema = runtime_schema_for_team_subjects(base_schema, comp_aparell, registry["subjects"])
    else:
        schema = runtime_schema_for_comp_aparell(base_schema, comp_aparell)
    return schema, logical_schema


def _schema_summary(schema):
    fields = schema.get("fields") if isinstance(schema, dict) else []
    computed = schema.get("computed") if isinstance(schema, dict) else []
    return {
        "fields_count": len(fields) if isinstance(fields, list) else 0,
        "computed_count": len(computed) if isinstance(computed, list) else 0,
        "meta": schema.get("meta", {}) if isinstance(schema, dict) and isinstance(schema.get("meta"), dict) else {},
    }


def _initial_context(units, out_of_program_units, apps):
    first_unit = next((unit for unit in units if unit.get("count", 0) > 0), None)
    if first_unit is None:
        first_unit = next(iter(units), None) or next(iter(out_of_program_units), None)
    if first_unit is None and apps:
        return {
            "franja_id": None,
            "comp_aparell_id": apps[0].id,
            "exercici": 1,
            "unit_key": "",
        }
    if first_unit is None:
        return None
    return {
        "franja_id": first_unit.get("franja_id"),
        "fase_id": first_unit.get("phase_id"),
        "comp_aparell_id": first_unit.get("comp_aparell_id"),
        "exercici": 1,
        "unit_key": str(first_unit.get("key")),
    }


@require_GET
def notes_manifest(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    context = build_notes_units_context(competicio)

    schema_summaries = {}
    for comp_aparell in context["apps"]:
        _schema, logical_schema = _schema_payload(comp_aparell, competicio)
        schema_summaries[str(comp_aparell.id)] = _schema_summary(logical_schema)

    return JsonResponse(
        {
            "ok": True,
            "competition": {"id": competicio.id, "name": competicio.nom},
            "franges": [serialize_franja(franja) for franja in context["franges"]],
            "apps": [serialize_comp_aparell(comp_aparell) for comp_aparell in context["apps"]],
            "phases_by_app": {
                str(comp_aparell.id): [
                    {"id": "", "label": "Preliminar", "code": "DEFAULT", "ordre": 0, "estat": "implicit", "comp_aparell_id": comp_aparell.id},
                    *[serialize_phase(phase) for phase in context["phases_by_app"].get(int(comp_aparell.id), [])],
                ]
                for comp_aparell in context["apps"]
            },
            "units": context["units"],
            "out_of_program_units": context["out_of_program_units"],
            "schema_summaries": schema_summaries,
            "initial_context": _initial_context(context["units"], context["out_of_program_units"], context["apps"]),
            "team_issues_by_app": context["team_issues_by_app"],
        }
    )


def _parse_positive_int(raw_value):
    try:
        value = int(raw_value)
    except Exception:
        return None
    return value if value > 0 else None


def _normalize_search_text(value):
    return " ".join(str(value or "").strip().lower().split())


def _search_matches(query, *values):
    query = _normalize_search_text(query)
    if not query:
        return False
    return any(query in _normalize_search_text(value) for value in values)


def _app_for_unit(context, unit):
    return context["apps_by_id"].get(int(unit.get("comp_aparell_id") or 0))


def _unit_identity(unit):
    return "|".join(
        [
            f"franja:{unit.get('franja_id')}" if unit.get("franja_id") else "off",
            str(unit.get("comp_aparell_id") or ""),
            str(unit.get("key") or ""),
        ]
    )


def _unit_context_payload(context, unit):
    comp_aparell = _app_for_unit(context, unit)
    if isinstance(unit.get("exercicis"), list) and unit.get("exercicis"):
        exercicis = unit.get("exercicis")
    else:
        exercicis = list(range(1, effective_exercise_count(comp_aparell) + 1)) if comp_aparell else [1]
    label_parts = [
        unit.get("franja_label") or ("Fora de programa" if unit.get("is_out_of_program") else ""),
        unit.get("app_label") or "",
        unit.get("label") or unit.get("key") or "",
    ]
    return {
        "franja_id": unit.get("franja_id"),
        "franja_label": unit.get("franja_label") or "",
        "comp_aparell_id": unit.get("comp_aparell_id"),
        "app_label": unit.get("app_label") or "",
        "unit_key": str(unit.get("key") or ""),
        "unit_identity": _unit_identity(unit),
        "unit_label": unit.get("label") or str(unit.get("key") or ""),
        "fase_id": unit.get("phase_id"),
        "phase_id": unit.get("phase_id"),
        "is_out_of_program": bool(unit.get("is_out_of_program")),
        "exercicis": exercicis,
        "label": " - ".join(str(part) for part in label_parts if part),
    }


def _contexts_for_subject(context, subject, *, max_contexts=8):
    subject_kind = str(subject.get("subject_kind") or "inscripcio")
    subject_group = str(subject.get("group") if subject.get("group") is not None else "")
    allowed_app_ids = [str(app_id) for app_id in (subject.get("allowed_app_ids") or [])]
    contexts = []
    for unit in list(context["units"]) + list(context["out_of_program_units"]):
        if subject_kind == "team_unit" and unit.get("subject_kind") != "team_unit":
            continue
        if subject_kind != "team_unit" and unit.get("subject_kind") == "team_unit":
            continue
        if allowed_app_ids and str(unit.get("comp_aparell_id") or "") not in allowed_app_ids:
            continue
        members = [str(member) for member in (unit.get("member_keys") or [])]
        if subject_group not in members:
            continue
        contexts.append(_unit_context_payload(context, unit))
        if len(contexts) >= max_contexts:
            break
    return contexts


def _search_subject_payload(subject, contexts):
    subject_kind = str(subject.get("subject_kind") or "inscripcio")
    subject_id = subject.get("subject_id") or subject.get("id")
    return {
        "id": f"{subject_kind}:{subject_id}",
        "kind": "subject",
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "name": subject.get("name") or subject.get("label") or "",
        "meta": subject.get("meta") or subject.get("context_name") or "",
        "subject": subject,
        "contexts": contexts,
    }


def _unit_search_payload(context, unit):
    return {
        "id": f"unit:{_unit_identity(unit)}",
        "kind": "unit",
        "name": unit.get("label") or str(unit.get("key") or ""),
        "meta": " - ".join(
            str(part)
            for part in [
                unit.get("franja_label") or ("Fora de programa" if unit.get("is_out_of_program") else ""),
                unit.get("app_label") or "",
                f"{unit.get('count') or 0} subjectes",
            ]
            if part
        ),
        "subject": None,
        "contexts": [_unit_context_payload(context, unit)],
    }


@require_GET
def notes_search(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    query = str(request.GET.get("q") or "").strip()
    limit = _parse_positive_int(request.GET.get("limit")) or 20
    limit = max(1, min(50, limit))
    if len(query) < 2:
        return JsonResponse({"ok": True, "query": query, "results": [], "count": 0})

    context = build_notes_units_context(competicio)
    active_individual_app_ids = [
        int(app.id)
        for app in context["apps"]
        if not is_team_context_app(app)
    ]

    results = []
    seen = set()

    def add_result(payload):
        key = str(payload.get("id") or "")
        if not key or key in seen or not payload.get("contexts"):
            return
        seen.add(key)
        results.append(payload)

    for rows in context["grouped_inscripcions"].values():
        for inscripcio in rows:
            group_label_text = ""
            if getattr(inscripcio, "grup_competicio", None):
                group_label_text = getattr(inscripcio.grup_competicio, "label", "") or getattr(
                    inscripcio.grup_competicio,
                    "nom",
                    "",
                )
            subject = serialize_individual_subject(
                inscripcio,
                active_individual_app_ids,
                context["excluded_by_inscripcio"],
            )
            if not _search_matches(
                query,
                subject.get("name"),
                subject.get("meta"),
                subject.get("group_display_num"),
                subject.get("order"),
                group_label_text,
                f"grup {subject.get('group_display_num') or subject.get('group') or ''}",
            ):
                continue
            add_result(_search_subject_payload(subject, _contexts_for_subject(context, subject)))
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break

    if len(results) < limit:
        for subjects in context["team_subjects_by_bucket"].values():
            for subject in subjects:
                if not _search_matches(
                    query,
                    subject.get("name"),
                    subject.get("label"),
                    subject.get("meta"),
                    subject.get("context_name"),
                    subject.get("members_text"),
                    subject.get("group_label"),
                ):
                    continue
                add_result(_search_subject_payload(subject, _contexts_for_subject(context, subject)))
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break

    if len(results) < limit:
        for unit in list(context["units"]) + list(context["out_of_program_units"]):
            if not _search_matches(
                query,
                unit.get("label"),
                unit.get("app_label"),
                unit.get("franja_label"),
                unit.get("key"),
                f"grup {unit.get('label') or ''}",
            ):
                continue
            add_result(_unit_search_payload(context, unit))
            if len(results) >= limit:
                break

    return JsonResponse(
        {
            "ok": True,
            "query": query,
            "results": results,
            "count": len(results),
        }
    )


def _score_phase_filter(qs, phase_id):
    if phase_id:
        return qs.filter(fase_id=phase_id)
    return qs.filter(fase__isnull=True)


def _serialize_scores(competicio, comp_aparell, exercici, subjects, logical_schema, phase_id=None):
    scores = {}
    if is_team_context_app(comp_aparell):
        subject_ids = [int(subject["subject_id"]) for subject in subjects]
        if not subject_ids:
            return scores
        allowed_inputs = _logical_team_input_codes(logical_schema)
        qs = TeamScoreEntry.objects.filter(
            competicio=competicio,
            comp_aparell=comp_aparell,
            exercici=exercici,
            team_subject_id__in=subject_ids,
        )
        qs = _score_phase_filter(qs, phase_id)
        for score in qs:
            key = score_store_key("team_unit", score.team_subject_id, score.exercici, score.comp_aparell_id, score.fase_id)
            scores[key] = {
                "inputs": _sanitize_inputs_for_client(score.inputs or {}, allowed_inputs),
                "outputs": score.outputs or {},
                "total": float(score.total),
            }
        return scores

    subject_ids = [int(subject.id) for subject in subjects]
    if not subject_ids:
        return scores
    allowed_inputs = _allowed_input_codes_for_schema(logical_schema, comp_aparell)
    qs = ScoreEntry.objects.filter(
        competicio=competicio,
        comp_aparell=comp_aparell,
        exercici=exercici,
        inscripcio_id__in=subject_ids,
    )
    qs = filter_score_entries_admeses(qs)
    qs = _score_phase_filter(qs, phase_id)
    for score in qs:
        key = score_store_key("inscripcio", score.inscripcio_id, score.exercici, score.comp_aparell_id, score.fase_id)
        scores[key] = {
            "inputs": _sanitize_inputs_for_client(score.inputs or {}, allowed_inputs),
            "outputs": score.outputs or {},
            "total": float(score.total),
        }
    return scores


def _judge_video_presence(competicio, comp_aparell, exercici, subjects, phase_id=None):
    presence = {}
    if is_team_context_app(comp_aparell):
        subject_ids = [int(subject["subject_id"]) for subject in subjects]
        rows = (
            TeamScoreEntryVideo.objects
            .filter(
                team_score_entry__competicio=competicio,
                team_score_entry__team_subject_id__in=subject_ids,
                team_score_entry__comp_aparell=comp_aparell,
                team_score_entry__exercici=exercici,
            )
            .exclude(video_file="")
            .values_list("team_score_entry__team_subject_id", "team_score_entry__exercici", "team_score_entry__comp_aparell_id")
        )
        rows = rows.filter(team_score_entry__fase_id=phase_id) if phase_id else rows.filter(team_score_entry__fase__isnull=True)
        for subject_id, ex, app_id in rows:
            presence[score_store_key("team_unit", subject_id, ex, app_id, phase_id)] = 1
        return presence

    subject_ids = [int(subject.id) for subject in subjects]
    rows = (
        ScoreEntryVideo.objects
        .filter(
            score_entry__competicio=competicio,
            score_entry__inscripcio_id__in=subject_ids,
            score_entry__comp_aparell=comp_aparell,
            score_entry__exercici=exercici,
        )
        .exclude(video_file="")
        .values_list("score_entry__inscripcio_id", "score_entry__exercici", "score_entry__comp_aparell_id")
    )
    rows = rows.filter(score_entry__fase_id=phase_id) if phase_id else rows.filter(score_entry__fase__isnull=True)
    for inscripcio_id, ex, app_id in rows:
        presence[score_store_key("inscripcio", inscripcio_id, ex, app_id, phase_id)] = 1
    return presence


def _warnings_payload(logical_schema, scores, subjects, comp_aparell, exercici, phase_id=None):
    warnings = []
    context = {"comp_aparell_id": comp_aparell.id, "exercici": exercici, "fase_id": phase_id}
    for subject in subjects:
        subject_kind = str(subject.get("subject_kind") or "inscripcio")
        subject_id = subject.get("subject_id", subject.get("id"))
        if not subject_id:
            continue
        score_key = score_store_key(subject_kind, subject_id, exercici, comp_aparell.id, phase_id)
        generated = generate_score_warnings(
            logical_schema,
            scores.get(score_key) or {},
            subject,
            context,
        )
        for warning in generated:
            if phase_id:
                warning["fase_id"] = phase_id
        warnings.extend(generated)
    return warnings


def _warning_subject_map(subjects):
    out = {}
    for subject in subjects or []:
        if not isinstance(subject, dict):
            continue
        subject_kind = str(subject.get("subject_kind") or "inscripcio")
        subject_id = subject.get("subject_id", subject.get("id"))
        if subject_id:
            out[(subject_kind, str(subject_id))] = subject
    return out


def _warning_unit_identity(unit):
    return "|".join(
        [
            f"franja:{unit.get('franja_id')}" if unit.get("franja_id") else "off",
            str(unit.get("comp_aparell_id") or ""),
            str(unit.get("key") or ""),
        ]
    )


def _warning_navigation_payload(unit, comp_aparell, exercici):
    payload = {
        "franja_id": unit.get("franja_id"),
        "comp_aparell_id": comp_aparell.id,
        "exercici": exercici,
        "unit_key": str(unit.get("key") or ""),
        "unit_identity": _warning_unit_identity(unit),
    }
    if unit.get("phase_id"):
        payload["fase_id"] = unit.get("phase_id")
    return payload


def _enrich_warnings(warnings, *, unit, comp_aparell, exercici, subjects_by_warning_key):
    enriched = []
    unit_payload = {
        "key": str(unit.get("key") or ""),
        "identity": _warning_unit_identity(unit),
        "label": unit.get("label") or str(unit.get("key") or ""),
        "franja_id": unit.get("franja_id"),
        "franja_label": unit.get("franja_label") or "",
        "phase_id": unit.get("phase_id"),
        "phase_label": unit.get("phase_label") or "",
        "is_out_of_program": bool(unit.get("is_out_of_program")),
    }
    app_payload = {
        "id": comp_aparell.id,
        "label": str(getattr(comp_aparell, "display_nom", "") or getattr(comp_aparell.aparell, "nom", "") or "Aparell"),
    }
    navigation = _warning_navigation_payload(unit, comp_aparell, exercici)
    for warning in warnings:
        subject = subjects_by_warning_key.get(
            (str(warning.get("subject_kind") or "inscripcio"), str(warning.get("subject_id") or ""))
        ) or {}
        row_id = subject.get("id")
        if row_id is None:
            row_id = f"{warning.get('subject_kind')}:{warning.get('subject_id')}"
        enriched_warning = dict(warning)
        enriched_warning["ack_key"] = _warning_ack_key(enriched_warning)
        enriched_warning.update(
            {
                "unit": unit_payload,
                "app": app_payload,
                "navigation": navigation,
                "subject": {
                    "id": row_id,
                    "subject_kind": warning.get("subject_kind"),
                    "subject_id": warning.get("subject_id"),
                    "name": subject.get("name") or subject.get("label") or "",
                    "meta": subject.get("meta") or subject.get("context_name") or "",
                },
            }
        )
        enriched.append(enriched_warning)
    return enriched


def _warning_ack_key(warning):
    parts = [
        warning.get("code"),
        warning.get("subject_kind"),
        warning.get("subject_id"),
        warning.get("comp_aparell_id"),
    ]
    if warning.get("fase_id") is not None:
        parts.append(f"fase:{warning.get('fase_id')}")
    parts.extend(
        [
            warning.get("exercici"),
            warning.get("field_code"),
            warning.get("judge") if warning.get("judge") is not None else "-",
            warning.get("item") if warning.get("item") is not None else "-",
        ]
    )
    return ":".join(str(part) for part in parts)[:255]


def _acknowledged_warning_keys(competicio):
    return set(
        ScoreWarningAcknowledgement.objects
        .filter(competicio=competicio)
        .values_list("warning_key", flat=True)
    )


def _filter_acknowledged_warnings(warnings, acknowledged_keys):
    if not acknowledged_keys:
        return warnings
    return [warning for warning in warnings if warning.get("ack_key") not in acknowledged_keys]


def _unique_texts(values):
    seen = set()
    out = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _aggregate_warnings_by_subject(warnings):
    grouped = {}
    order = []
    for warning in warnings:
        subject = warning.get("subject") if isinstance(warning.get("subject"), dict) else {}
        key = (
            str(subject.get("subject_kind") or warning.get("subject_kind") or "inscripcio"),
            str(subject.get("subject_id") or warning.get("subject_id") or ""),
        )
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(warning)

    aggregated = []
    for key in order:
        items = grouped[key]
        first = dict(items[0])
        count = len(items)
        first["details"] = items
        first["ack_keys"] = _unique_texts(item.get("ack_key") for item in items)
        first["warning_count"] = count
        first["summary"] = {
            "franges": _unique_texts(
                (item.get("unit") or {}).get("franja_label") or "Fora de programa"
                for item in items
            ),
            "units": _unique_texts((item.get("unit") or {}).get("label") for item in items),
            "apps": _unique_texts((item.get("app") or {}).get("label") for item in items),
            "exercicis": _unique_texts((item.get("navigation") or {}).get("exercici") for item in items),
            "fields": _unique_texts(item.get("field_code") for item in items),
            "codes": _unique_texts(item.get("code") for item in items),
        }
        if count > 1:
            first["id"] = "grouped:" + ":".join(key)
            first["code"] = "grouped"
            first["message"] = f"{count} avisos pendents"
        aggregated.append(first)
    return aggregated


def _subject_score_for_warnings(scores, subject, exercici, comp_aparell_id, phase_id=None):
    subject_kind = str(subject.get("subject_kind") or "inscripcio")
    subject_id = subject.get("subject_id", subject.get("id"))
    return scores.get(score_store_key(subject_kind, subject_id, exercici, comp_aparell_id, phase_id)) or {}


def _presence_count_for_field(field, score):
    code = str(field.get("code") or "")
    inputs = score.get("inputs") if isinstance(score, dict) and isinstance(score.get("inputs"), dict) else score
    if not isinstance(inputs, dict):
        return None, []
    presence = inputs.get(presence_key(code))
    if not isinstance(presence, list):
        return None, []
    present_judges = [idx + 1 for idx, value in enumerate(presence) if bool(value)]
    return len(present_judges), present_judges


def _judge_presence_outlier_warnings(logical_schema, scores, subjects, comp_aparell, exercici, phase_id=None):
    fields = [
        field for field in (logical_schema.get("fields") or [])
        if isinstance(field, dict) and field.get("code") and is_judge_shaped_field(field)
    ]
    warnings = []
    for field in fields:
        code = str(field.get("code") or "")
        rows = []
        for subject in subjects:
            score = _subject_score_for_warnings(scores, subject, exercici, comp_aparell.id, phase_id)
            count, present_judges = _presence_count_for_field(field, score)
            if count is None:
                continue
            rows.append((subject, count, present_judges))
        if len(rows) < 3:
            continue
        counts = {}
        for _subject, count, _present_judges in rows:
            counts[count] = counts.get(count, 0) + 1
        expected_count, expected_frequency = max(counts.items(), key=lambda item: (item[1], item[0]))
        if expected_count <= 0 or expected_frequency < 2:
            continue
        for subject, count, present_judges in rows:
            if count >= expected_count:
                continue
            subject_kind = str(subject.get("subject_kind") or "inscripcio")
            subject_id = subject.get("subject_id", subject.get("id"))
            missing_judges = [idx for idx in range(1, expected_count + 1) if idx not in present_judges]
            warning = {
                "id": "",
                "severity": "warning",
                "code": "judge_presence_outlier",
                "message": f"{code} te {count} jutges que compten; la unitat normalment en te {expected_count}",
                "subject_kind": subject_kind,
                "subject_id": subject_id,
                "comp_aparell_id": comp_aparell.id,
                "exercici": exercici,
                "field_code": code,
                "judge": None,
                "item": None,
                "value": {"presence_count": count, "present_judges": present_judges},
                "expected": {"presence_count": expected_count, "missing_judges": missing_judges},
            }
            warning["id"] = _warning_ack_key(warning)
            warnings.append(warning)
    return warnings


def _all_warnings_payload(logical_schema, scores, subjects, comp_aparell, exercici, phase_id=None):
    warnings = _warnings_payload(logical_schema, scores, subjects, comp_aparell, exercici, phase_id=phase_id)
    warnings.extend(_judge_presence_outlier_warnings(logical_schema, scores, subjects, comp_aparell, exercici, phase_id=phase_id))
    return warnings


@require_GET
def notes_table(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    context = build_notes_units_context(competicio)
    comp_aparell_id = _parse_positive_int(request.GET.get("comp_aparell_id"))
    comp_aparell = context["apps_by_id"].get(int(comp_aparell_id or 0))
    if comp_aparell is None:
        return JsonResponse({"ok": False, "error": "invalid_comp_aparell"}, status=400)

    franja_id = _parse_positive_int(request.GET.get("franja_id"))
    phase_id = _parse_positive_int(request.GET.get("fase_id"))
    if phase_id:
        valid_phase_ids = {int(phase.id) for phase in context["phases_by_app"].get(int(comp_aparell.id), [])}
        if phase_id not in valid_phase_ids:
            return JsonResponse({"ok": False, "error": "invalid_fase"}, status=400)
    unit = resolve_notes_unit(
        context,
        comp_aparell.id,
        unit_key=request.GET.get("unit_key"),
        group=request.GET.get("group"),
        franja_id=franja_id,
        phase_id=phase_id,
    )
    if unit is None:
        return JsonResponse({"ok": False, "error": "invalid_unit"}, status=404)
    if phase_id and int(unit.get("phase_id") or 0) != phase_id:
        return JsonResponse({"ok": False, "error": "invalid_phase_unit"}, status=400)
    if not phase_id and unit.get("phase_id"):
        return JsonResponse({"ok": False, "error": "invalid_phase_unit"}, status=400)

    exercici = clamp_exercici(request.GET.get("exercici"), comp_aparell, max_exercicis=unit.get("nombre_exercicis"))
    schema, logical_schema = _schema_payload(comp_aparell, competicio)
    raw_subjects = subjects_for_unit(context, unit, comp_aparell)
    ordered_subjects = order_subjects_for_unit(context, unit, raw_subjects, comp_aparell)

    active_individual_app_ids = [
        int(app.id)
        for app in context["apps"]
        if not is_team_context_app(app)
    ]
    if is_team_context_app(comp_aparell):
        subjects = ordered_subjects
        media_counts = {}
        rotation_rank = {
            f"{comp_aparell.id}|{int(subject['subject_id'])}": idx
            for idx, subject in enumerate(ordered_subjects, start=1)
        }
    else:
        subjects = [
            serialize_individual_subject(subject, active_individual_app_ids, context["excluded_by_inscripcio"])
            for subject in ordered_subjects
        ]
        media_counts = media_counts_for_inscripcions(competicio, [int(subject.id) for subject in ordered_subjects])
        rotation_rank = {
            f"{comp_aparell.id}|{int(subject.id)}": idx
            for idx, subject in enumerate(ordered_subjects, start=1)
        }

    scores = _serialize_scores(competicio, comp_aparell, exercici, ordered_subjects, logical_schema, phase_id=phase_id)
    warnings = _filter_acknowledged_warnings(
        _enrich_warnings(
            _all_warnings_payload(logical_schema, scores, subjects, comp_aparell, exercici, phase_id=phase_id),
            unit=unit,
            comp_aparell=comp_aparell,
            exercici=exercici,
            subjects_by_warning_key=_warning_subject_map(subjects),
        ),
        _acknowledged_warning_keys(competicio),
    )
    return JsonResponse(
        {
            "ok": True,
            "context": {
                "franja_id": unit.get("franja_id") if franja_id else None,
                "fase_id": phase_id,
                "comp_aparell_id": comp_aparell.id,
                "exercici": exercici,
                "unit_key": str(unit.get("key")),
                "group": request.GET.get("group") or "",
            },
            "unit": unit,
            "schema": schema,
            "logical_schema": logical_schema,
            "subjects": subjects,
            "scores": scores,
            "media_counts": media_counts,
            "judge_video_presence": _judge_video_presence(competicio, comp_aparell, exercici, ordered_subjects, phase_id=phase_id),
            "rotation_rank": rotation_rank,
            "warnings": warnings,
        }
    )


@require_GET
def notes_warnings(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    context = build_notes_units_context(competicio)
    comp_aparell_filter = _parse_positive_int(request.GET.get("comp_aparell_id"))
    franja_filter = _parse_positive_int(request.GET.get("franja_id"))
    phase_filter = _parse_positive_int(request.GET.get("fase_id"))
    unit_key_filter = str(request.GET.get("unit_key") or "").strip()
    exercici_filter = _parse_positive_int(request.GET.get("exercici"))
    limit = _parse_positive_int(request.GET.get("limit")) or 500
    limit = max(1, min(1000, limit))

    units = list(context["units"]) + list(context["out_of_program_units"])
    if comp_aparell_filter:
        units = [unit for unit in units if int(unit.get("comp_aparell_id") or 0) == comp_aparell_filter]
    if franja_filter:
        units = [unit for unit in units if int(unit.get("franja_id") or 0) == franja_filter]
    if phase_filter:
        units = [unit for unit in units if int(unit.get("phase_id") or 0) == phase_filter]
    if unit_key_filter:
        units = [unit for unit in units if str(unit.get("key") or "") == unit_key_filter]

    active_individual_app_ids = [
        int(app.id)
        for app in context["apps"]
        if not is_team_context_app(app)
    ]
    schema_cache = {}
    raw_warnings = []
    acknowledged_keys = _acknowledged_warning_keys(competicio)
    scanned = {"units": 0, "score_contexts": 0}
    truncated = False

    for unit in units:
        comp_aparell = context["apps_by_id"].get(int(unit.get("comp_aparell_id") or 0))
        if comp_aparell is None:
            continue
        if comp_aparell.id not in schema_cache:
            schema_cache[comp_aparell.id] = _schema_payload(comp_aparell, competicio)
        _schema, logical_schema = schema_cache[comp_aparell.id]
        raw_subjects = subjects_for_unit(context, unit, comp_aparell)
        ordered_subjects = order_subjects_for_unit(context, unit, raw_subjects, comp_aparell)
        if is_team_context_app(comp_aparell):
            subjects = ordered_subjects
        else:
            subjects = [
                serialize_individual_subject(subject, active_individual_app_ids, context["excluded_by_inscripcio"])
                for subject in ordered_subjects
            ]
        subjects_by_warning_key = _warning_subject_map(subjects)
        unit_exercise_count = effective_exercise_count(comp_aparell, max_exercicis=unit.get("nombre_exercicis"))
        exercises = [exercici_filter] if exercici_filter else list(range(1, unit_exercise_count + 1))
        scanned["units"] += 1
        for exercici in exercises:
            exercici = clamp_exercici(exercici, comp_aparell, max_exercicis=unit_exercise_count)
            unit_phase_id = _parse_positive_int(unit.get("phase_id"))
            scores = _serialize_scores(competicio, comp_aparell, exercici, ordered_subjects, logical_schema, phase_id=unit_phase_id)
            unit_warnings = _all_warnings_payload(logical_schema, scores, subjects, comp_aparell, exercici, phase_id=unit_phase_id)
            scanned["score_contexts"] += 1
            if not unit_warnings:
                continue
            raw_warnings.extend(
                _filter_acknowledged_warnings(
                    _enrich_warnings(
                        unit_warnings,
                        unit=unit,
                        comp_aparell=comp_aparell,
                        exercici=exercici,
                        subjects_by_warning_key=subjects_by_warning_key,
                    ),
                    acknowledged_keys,
                )
            )
            if len(raw_warnings) >= limit:
                raw_warnings = raw_warnings[:limit]
                truncated = True
                break
        if truncated:
            break

    warnings = _aggregate_warnings_by_subject(raw_warnings)
    return JsonResponse(
        {
            "ok": True,
            "warnings": warnings,
            "count": len(warnings),
            "raw_count": len(raw_warnings),
            "limit": limit,
            "truncated": truncated,
            "scanned": scanned,
        }
    )


@require_POST
def notes_warning_validate(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)
    try:
        payload = json.loads((request.body or b"{}").decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON invalid"}, status=400)
    ack_keys = payload.get("ack_keys")
    if not isinstance(ack_keys, list):
        ack_keys = [payload.get("ack_key")]
    clean_keys = _unique_texts(str(key or "")[:255] for key in ack_keys)
    if not clean_keys:
        return JsonResponse({"ok": False, "error": "Falten ack_keys."}, status=400)
    user = request.user if getattr(request, "user", None) is not None and request.user.is_authenticated else None
    created = []
    for key in clean_keys:
        obj, was_created = ScoreWarningAcknowledgement.objects.get_or_create(
            competicio=competicio,
            warning_key=key,
            defaults={"created_by": user},
        )
        if was_created:
            created.append(obj.warning_key)
    return JsonResponse({"ok": True, "validated": clean_keys, "created": created})
