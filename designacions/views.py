# views.py
from django.core.paginator import Paginator
import os, uuid, json
from redis import Redis
from django.contrib import messages
from .models import Address
from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from django.db.models import Count, Q
from .services.colors import color_per_tutor
from django.http import Http404
from .models import DesignationRun, Assignment, Referee
from .tasks import process_designacions_run, rebuild_run_map_task
from .services.jobstore import write_job_sync, read_job_sync
from .services.excel_export import export_run_to_excel
from .services.assignment_explainer import (
    explain_candidate_for_assignment,
    explain_current_assignment,
)
import pandas as pd
from .services.manual_assignment import (
    build_assignment_availability_by_assignment,
    build_availability_display_by_ref,
    build_availability_lookup_by_ref_and_date,
    build_run_mobility_summary,
    build_manual_assignment_context,
    build_run_scoped_referee_summaries,
    build_run_scoped_referee_summary_by_id,
    build_top_proposals_for_assignments,
    diagnose_assignment_for_referee,
    get_run_referees_with_counts,
    serialize_proposal,
    serialize_referee_option,
    update_run_mobility_summary,
)



REDIS_URL = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")

MATCH_FILE_COLUMNS = {
    "codi",
    "codi extern local",
    "lliga",
    "local",
    "visitant",
    "pista joc",
}
AVAILABILITY_FILE_COLUMNS = {
    "codi tutor de joc",
    "nivell",
    "hora inici",
    "hora fi",
    "mitja de transport",
    "mitjà de transport",
}
UPLOAD_KIND_MATCHES = "partits"
UPLOAD_KIND_AVAILABILITY = "disponibilitats"
UPLOAD_KIND_UNKNOWN = "desconegut"

def _to_int(v, default):
    try:
        return int(str(v).strip())
    except Exception:
        return default

def _to_float(v, default):
    try:
        return float(str(v).strip().replace(",", "."))
    except Exception:
        return default

def _to_str_list_csv(v):
    s = (v or "").strip()
    if not s:
        return []
    # separa per comes / salts de línia
    parts = []
    for x in s.replace("\n", ",").split(","):
        x = x.strip()
        if x:
            parts.append(x)
    return parts


def _to_fase(v, default="FS1"):
    value = (v or default).strip().upper()
    return value if value in {"FS1", "FS2"} else default


def _temp_dir():
    d = os.path.join(settings.MEDIA_ROOT, "temp")
    os.makedirs(d, exist_ok=True)
    return d

def _save_uploaded(f, prefix: str) -> str:
    out_path = os.path.join(_temp_dir(), f"{prefix}__{f.name}")
    if hasattr(f, "seek"):
        f.seek(0)
    with open(out_path, "wb") as dest:
        for chunk in f.chunks():
            dest.write(chunk)
    if hasattr(f, "seek"):
        f.seek(0)
    return out_path


def _normalized_excel_columns(df: pd.DataFrame) -> set[str]:
    return {str(column).strip().casefold() for column in df.columns if str(column).strip()}


def _detect_designacions_upload_kind(uploaded_file) -> str:
    try:
        df = pd.read_excel(uploaded_file, engine="openpyxl", nrows=50)
    except Exception:
        return UPLOAD_KIND_UNKNOWN
    finally:
        if hasattr(uploaded_file, "seek"):
            uploaded_file.seek(0)

    columns = _normalized_excel_columns(df)
    match_score = len(columns & MATCH_FILE_COLUMNS)
    availability_score = len(columns & AVAILABILITY_FILE_COLUMNS)

    if {"codi", "codi extern local", "lliga"}.issubset(columns):
        match_score += 3
    if "codi tutor de joc" in columns:
        availability_score += 3
    if "categoria" in columns:
        categories = (
            df["Categoria"]
            .dropna()
            .astype(str)
            .str.strip()
            .str.casefold()
        )
        if categories.eq("tutor/tutora de joc").any():
            availability_score += 3

    if match_score >= 4 and match_score > availability_score:
        return UPLOAD_KIND_MATCHES
    if availability_score >= 3 and availability_score > match_score:
        return UPLOAD_KIND_AVAILABILITY
    return UPLOAD_KIND_UNKNOWN


def _resolve_designacions_upload_files(files):
    detected = [(file, _detect_designacions_upload_kind(file)) for file in files]
    by_kind = {kind: [file for file, detected_kind in detected if detected_kind == kind] for kind in (
        UPLOAD_KIND_MATCHES,
        UPLOAD_KIND_AVAILABILITY,
        UPLOAD_KIND_UNKNOWN,
    )}

    if len(by_kind[UPLOAD_KIND_MATCHES]) == 1 and len(by_kind[UPLOAD_KIND_AVAILABILITY]) == 1:
        return by_kind[UPLOAD_KIND_MATCHES][0], by_kind[UPLOAD_KIND_AVAILABILITY][0], detected

    names_by_kind = {
        kind: [getattr(file, "name", "fitxer") for file in kind_files]
        for kind, kind_files in by_kind.items()
        if kind_files
    }
    if len(by_kind[UPLOAD_KIND_MATCHES]) == 2:
        detail = "Has pujat dos fitxers que semblen de partits. Falta el fitxer de disponibilitats."
    elif len(by_kind[UPLOAD_KIND_AVAILABILITY]) == 2:
        detail = "Has pujat dos fitxers que semblen de disponibilitats. Falta el fitxer de partits."
    else:
        detail = "No s'han pogut identificar els fitxers. Cal pujar un Excel de partits i un de disponibilitats."
    raise ValueError(f"{detail} Detectat: {names_by_kind}")


def _build_counts(run, referees_with_counts=None):
    referees_with_counts = list(referees_with_counts or build_run_scoped_referee_summaries(run))
    assigned = run.assignments.filter(referee__isnull=False).count()
    unassigned_matches = run.assignments.filter(referee__isnull=True).count()
    unassigned_referees = sum(1 for referee in referees_with_counts if (referee.n or 0) == 0)
    needs_review_referees = sum(1 for referee in referees_with_counts if not (referee.level or "").strip())
    result_summary = getattr(run, "result_summary", None) or {}
    return {
        "assigned": assigned,
        "unassigned_matches": unassigned_matches,
        "unassigned_referees": unassigned_referees,
        "needs_review_referees": needs_review_referees,
        "mobility_warnings": int(result_summary.get("mobility_warning_count", 0) or 0),
        "mobility_errors": int(result_summary.get("mobility_error_count", 0) or 0),
        "has_map": bool(run.map_path),
    }


def _queue_map_rebuild(run):
    run.map_status = "queued"
    run.save(update_fields=["map_status"])
    rebuild_run_map_task.delay(run.id)


def _assignment_json_payload(run, assignment, message, counts, map_queued, referee_summary_by_id=None, mobility_summary=None):
    referee_summary_by_id = referee_summary_by_id or build_run_scoped_referee_summary_by_id(run)
    referee_summary = referee_summary_by_id.get(assignment.referee_id) if assignment.referee_id else None
    return {
        "ok": True,
        "assignment_id": assignment.id,
        "row_state": "assigned" if assignment.referee_id else "unassigned",
        "referee": (
            {
                "id": assignment.referee.id,
                "code": assignment.referee.code,
                "name": assignment.referee.name,
                "level": referee_summary.level if referee_summary else (assignment.referee.level or ""),
            }
            if assignment.referee_id
            else None
        ),
        "warning": {
            "active": bool(assignment.manual_override_warning),
            "text": assignment.manual_override_reason or "",
        },
        "note": assignment.note or "",
        "locked": assignment.locked,
        "counts": counts,
        "message": message,
        "map_status": run.map_status,
        "map_queued": map_queued,
        "match_code": assignment.match.code,
        "assigned_referee_id": assignment.referee_id,
        "assigned_referee_code": assignment.referee.code if assignment.referee_id else "",
        "refresh_suggestions": True,
        "mobility_summary": mobility_summary or {},
    }


def _parse_assignment_ids(raw_assignment_ids):
    if not isinstance(raw_assignment_ids, list):
        raise ValueError("assignment_ids ha de ser una llista.")

    assignment_ids = []
    seen = set()
    for item in raw_assignment_ids:
        try:
            assignment_id = int(item)
        except (TypeError, ValueError) as exc:
            raise ValueError("assignment_ids ha de contenir nomes IDs numerics.") from exc
        if assignment_id in seen:
            continue
        seen.add(assignment_id)
        assignment_ids.append(assignment_id)
    return assignment_ids


def _build_manual_suggestions_bulk_items(run, assignment_ids, *, limit: int = 3):
    ordered_ids = sorted(assignment_ids)
    assignments = {
        assignment.id: assignment
        for assignment in run.assignments.select_related("match", "referee").filter(id__in=ordered_ids)
    }
    context = build_manual_assignment_context(run)
    proposals_by_assignment = build_top_proposals_for_assignments(
        run,
        assignments.values(),
        limit=limit,
        context=context,
    )

    items = []
    for assignment_id in ordered_ids:
        assignment = assignments.get(assignment_id)
        if assignment is None:
            items.append({
                "assignment_id": assignment_id,
                "top_proposals": [],
                "rank_1_referee_id": None,
                "status": "missing_assignment",
            })
            continue

        top_proposals = [
            _serialize_explained_proposal(run, assignment, item, context)
            for item in proposals_by_assignment.get(assignment_id, [])
        ]
        items.append({
            "assignment_id": assignment_id,
            "top_proposals": top_proposals,
            "rank_1_referee_id": top_proposals[0]["referee_id"] if top_proposals else None,
            "status": "ok",
        })
    return items


def _serialize_explained_proposal(run, assignment, diagnosis, context):
    serialized = serialize_proposal(diagnosis)
    explanation = explain_candidate_for_assignment(run, assignment, diagnosis["referee"], context=context)
    serialized.update(
        {
            "level_fit": explanation["level_fit"],
            "quality_label": explanation["quality_label"],
            "selection_reason_summary": explanation["selection_reason_summary"],
        }
    )
    return serialized


def _apply_assignment_update(run, assignment, referee_id_raw, note, locked):
    previous_referee_id = assignment.referee_id
    referee_lookup = {referee.id: referee for referee in get_run_referees_with_counts(run)}
    context = build_manual_assignment_context(run, referees_with_counts=referee_lookup.values())

    if referee_id_raw not in (None, ""):
        try:
            referee_pk = int(referee_id_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("Tutor no valid.") from exc

        referee = referee_lookup.get(referee_pk)
        if referee is None:
            raise ValueError("Aquest tutor no forma part del run actual.")

        compatible_referees = {
            item.id
            for item in context["referees_by_assignment"].get(assignment.id, [])
        }
        if referee.id not in compatible_referees:
            raise ValueError("Aquest tutor no és compatible amb la modalitat del partit.")

        referee_summary = context["referee_summaries_by_id"].get(referee.id, referee)
        diagnosis = diagnose_assignment_for_referee(
            run,
            assignment,
            referee_summary,
            availability_lookup=context["availability_lookup"],
            assignments_by_referee=context["assignments_by_referee"],
            cluster_by_match_id=context["cluster_by_match_id"],
        )
        assignment.referee = referee
        assignment.manual_override_warning = not diagnosis["is_valid"]
        assignment.manual_override_reason = diagnosis["warning_text"]
        if diagnosis["is_valid"]:
            message = f"Assignacio de {assignment.match.code} guardada."
        else:
            message = f"Assignacio de {assignment.match.code} guardada amb warning: {diagnosis['warning_text']}"
    else:
        assignment.referee = None
        assignment.locked = False
        assignment.manual_override_warning = False
        assignment.manual_override_reason = ""
        if previous_referee_id is not None:
            message = f"Partit {assignment.match.code} desassignat."
        else:
            message = f"Partit {assignment.match.code} continua sense assignar."

    if assignment.referee_id:
        assignment.locked = locked
    assignment.note = note
    assignment.save()

    map_queued = previous_referee_id != assignment.referee_id
    if map_queued:
        _queue_map_rebuild(run)
        run.refresh_from_db(fields=["map_status", "map_path"])

    updated_context = build_manual_assignment_context(run)
    update_run_mobility_summary(run, context=updated_context)
    referee_summaries = build_run_scoped_referee_summaries(run)
    counts = _build_counts(run, referees_with_counts=referee_summaries)
    return {
        "assignment": assignment,
        "message": message,
        "counts": counts,
        "map_queued": map_queued,
        "referee_summary_by_id": {summary.id: summary for summary in referee_summaries},
        "mobility_summary": build_run_mobility_summary(run, context=updated_context),
    }

@require_http_methods(["GET", "POST"])
def upload_view(request):
    if request.method == "GET":
        return render(request, "upload.html", {
            "defaults": {
                "cluster_eps_m": 500,
                "cluster_min_samples": 2,
                "max_partits_subgrup": 3,
                "gap_same_pitch_min": 60,
                "gap_diff_pitch_min": 75,
                "gap_diff_cluster_min": 100,
                "modalitats_csv": "",
                "date_from": "",
                "date_to": "",
                "fase": "FS1",
            }
        })

    files = request.FILES.getlist("files")
    if len(files) != 2:
        return HttpResponseBadRequest("Cal pujar exactament 2 fitxers .xlsx (partits i disponibilitats).")

    try:
        partits_file, disponibilitats_file, detected_files = _resolve_designacions_upload_files(files)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    task_id = uuid.uuid4().hex

    path_partits = _save_uploaded(partits_file, f"{task_id}__partits")
    path_disponibilitats = _save_uploaded(disponibilitats_file, f"{task_id}__disponibilitats")

    # --- PARAMS del run (venen del formulari) ---
    params = {
        "cluster_eps_m": _to_float(request.POST.get("cluster_eps_m"), 500),
        "cluster_min_samples": _to_int(request.POST.get("cluster_min_samples"), 2),
        "max_partits_subgrup": _to_int(request.POST.get("max_partits_subgrup"), 3),
        "gap_same_pitch_min": _to_int(request.POST.get("gap_same_pitch_min"), 60),
        "gap_diff_pitch_min": _to_int(request.POST.get("gap_diff_pitch_min"), 75),
        "gap_diff_cluster_min": _to_int(request.POST.get("gap_diff_cluster_min"), 100),
        "modalitats": _to_str_list_csv(request.POST.get("modalitats_csv")),
        "date_from": (request.POST.get("date_from") or "").strip(),
        "date_to": (request.POST.get("date_to") or "").strip(),
        "fase": _to_fase(request.POST.get("fase"), "FS1"),
    }

    run = DesignationRun.objects.create(
        task_id=task_id,
        status="queued",
        input_partits=partits_file,
        input_disponibilitats=disponibilitats_file,
        params=params,
    )

    detected_summary = {
        getattr(file, "name", "fitxer"): kind
        for file, kind in detected_files
    }
    write_job_sync(task_id, {"status": "queued", "task_id": task_id, "detected_files": detected_summary})

    # passa params a celery
    process_designacions_run.delay(run.id, task_id, path_disponibilitats, path_partits, params)

    return redirect("designacions_run_detail", run_id=run.id)

@require_GET
def run_detail_view(request, run_id: int):
    run = get_object_or_404(DesignationRun, id=run_id)
    mobility_summary = build_run_mobility_summary(run) if run.status == "done" else {
        "mobility_warning_count": 0,
        "mobility_error_count": 0,
        "mobility_warnings": [],
        "mobility_errors": [],
    }
    return render(request, "run_detail.html", {"run": run, "mobility_summary": mobility_summary})

def _serialize_terminal_run_status(run, job: dict | None = None):
    job = job or {}
    if run.status == "done":
        return {
            "status": "SUCCESS",
            "progress": 100,
            "message": job.get("message") or "Procés finalitzat.",
            "error": job.get("error"),
        }
    if run.status == "failed":
        return {
            "status": "FAILURE",
            "progress": job.get("progress"),
            "message": job.get("message"),
            "error": job.get("error") or run.error,
        }
    return None

@require_GET
@require_GET
def task_status_view(request, task_id: str):
    job = read_job_sync(task_id) or {}
    run = DesignationRun.objects.filter(task_id=task_id).only("status", "error").first()
    status = job.get("status")

    terminal_from_run = _serialize_terminal_run_status(run, job) if run else None
    if terminal_from_run and status not in ("done", "SUCCESS", "failed", "FAILURE"):
        return JsonResponse(terminal_from_run)

    status = status or (run.status if run else "PENDING")

    if status in ("done", "SUCCESS"):
        return JsonResponse({
            "status": "SUCCESS",
            "progress": 100,
            "message": job.get("message") or (terminal_from_run or {}).get("message"),
        })

    if status in ("failed", "FAILURE"):
        return JsonResponse({
            "status": "FAILURE",
            "progress": job.get("progress"),
            "message": job.get("message"),
            "error": job.get("error") or (run.error if run else None),
        })

    return JsonResponse({
        "status": status,
        "progress": job.get("progress"),
        "message": job.get("message"),
        "error": job.get("error"),
    })

@require_GET
def logs_stream_view(request, task_id: str):
    r = Redis.from_url(REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    channel = f"job:{task_id}:channel"
    pubsub.subscribe(channel)

    def event_stream():
        yield "data: " + json.dumps({"message": "Connectat al stream.", "progress": None}) + "\n\n"
        try:
            for msg in pubsub.listen():
                if msg and msg.get("type") == "message":
                    yield f"data: {msg.get('data')}\n\n"
        finally:
            try:
                pubsub.close()
            except Exception:
                pass

    resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


@require_GET
def assignments_view(request, run_id: int):
    run = get_object_or_404(DesignationRun, id=run_id)
    filter_level_options = ["NIVELLA1", "NIVELLB1", "NIVELLC1", "NIVELLD1", "D"]

    # Assignacions del run
    qs = list(
        run.assignments
        .select_related("match", "referee")
        .all()
    )

    assigned_qs = sorted(
        [assignment for assignment in qs if assignment.referee_id],
        key=lambda assignment: (
            assignment.referee.code if assignment.referee else "",
            assignment.match.date or "",
            assignment.match.hour_raw or "",
            assignment.match.code or "",
        ),
    )
    unassigned_matches = sorted(
        [assignment for assignment in qs if not assignment.referee_id],
        key=lambda assignment: (
            assignment.match.date or "",
            assignment.match.hour_raw or "",
            assignment.match.code or "",
        ),
    )

    # Llista de tutors actius (per desplegable d’edició)
    referees_with_counts = list(get_run_referees_with_counts(run))
    referee_summaries = build_run_scoped_referee_summaries(run, referees_with_counts=referees_with_counts)
    referee_summary_by_id = {summary.id: summary for summary in referee_summaries}
    referees = referee_summaries

    unassigned_referees = [r for r in referee_summaries if (r.n or 0) == 0]

    # Tutors “sense nivell” dins l'scope del run
    needs_review_referees = [
        referee
        for referee in referee_summaries
        if not (referee.level or "").strip()
    ]

    # Agrupació per tutor (accordion)
    groups = []
    current_key = None
    current = None

    for a in assigned_qs:
        r = a.referee
        key = r.id if r else None
        if key != current_key:
            if current:
                groups.append(current)
            current_key = key
            display_referee = referee_summary_by_id.get(r.id, r) if r else None
            current = {
                "referee": display_referee,
                "color": color_per_tutor(r.code if r else None),
                "items": [],
                "total": 0,
                "locked": 0,
            }
        current["items"].append(a)
        current["total"] += 1
        if a.locked:
            current["locked"] += 1

    if current:
        groups.append(current)


    availability_lookup = build_availability_lookup_by_ref_and_date(run)
    availability_by_assignment = build_assignment_availability_by_assignment(assigned_qs, availability_lookup)
    availability_display_by_ref = build_availability_display_by_ref(run)
    mobility_summary = build_run_mobility_summary(run)
    mobility_warning_assignment_ids = mobility_summary["warning_assignment_ids"]
    mobility_error_assignment_ids = mobility_summary["error_assignment_ids"]
    mobility_warning_counts_by_referee = mobility_summary["warning_counts_by_referee"]
    mobility_error_counts_by_referee = mobility_summary["error_counts_by_referee"]
    counts = _build_counts(run, referees_with_counts=referee_summaries)

    for group in groups:
        referee_id = group["referee"].id if group.get("referee") else None
        group["mobility_warning_count"] = int(mobility_warning_counts_by_referee.get(referee_id, 0))
        group["mobility_error_count"] = int(mobility_error_counts_by_referee.get(referee_id, 0))
        group["level"] = (group["referee"].level or "").strip() if group.get("referee") else ""
        group["modality"] = (group["referee"].modality or "").strip() if group.get("referee") else ""
        group["has_mobility_error"] = group["mobility_error_count"] > 0
        group["has_mobility_warning"] = group["mobility_warning_count"] > 0
        group["has_manual_override"] = any(item.manual_override_warning for item in group["items"])
        group["has_locked"] = group["locked"] > 0
        group["categories"] = sorted(
            {
                (item.match.category or "").strip()
                for item in group["items"]
                if (item.match.category or "").strip()
            }
        )
        group["venues"] = sorted(
            {
                (item.match.venue or "").strip()
                for item in group["items"]
                if (item.match.venue or "").strip()
            }
        )

    filter_category_options = sorted(
        {
            (assignment.match.category or "").strip()
            for assignment in assigned_qs
            if (assignment.match.category or "").strip()
        }
    )

    return render(request, "assignments.html", {
        "run": run,
        "groups": groups,
        "availability_by_assignment": availability_by_assignment,
        "availability_by_ref": {referee_id: raw for (referee_id, _), raw in availability_lookup.items()},
        "availability_display_by_ref": availability_display_by_ref,
        "unassigned_matches": unassigned_matches,
        "unassigned_referees": unassigned_referees,
        "needs_review_referees": needs_review_referees,
        "referees": referees,
        "counts": counts,
        "mobility_summary": mobility_summary,
        "mobility_warning_assignment_ids": mobility_warning_assignment_ids,
        "mobility_error_assignment_ids": mobility_error_assignment_ids,
        "filter_level_options": filter_level_options,
        "filter_category_options": filter_category_options,
    })

@require_GET
def manual_assignment_options_view(request, run_id: int, assignment_id: int):
    run = get_object_or_404(DesignationRun, id=run_id)
    assignment = get_object_or_404(
        Assignment.objects.select_related("match", "referee"),
        id=assignment_id,
        run=run,
    )
    query = (request.GET.get("q") or "").strip().lower()

    context = build_manual_assignment_context(run)
    compatible_referees = context["referees_by_assignment"].get(assignment.id, [])
    if query:
        compatible_referees = [
            referee
            for referee in compatible_referees
            if query in (referee.code or "").lower()
        ]

    proposals = build_top_proposals_for_assignments(run, [assignment], context=context).get(assignment.id, [])
    compatible_referee_payload = []
    for referee in compatible_referees:
        diagnosis = diagnose_assignment_for_referee(
            run,
            assignment,
            referee,
            availability_lookup=context["availability_lookup"],
            assignments_by_referee=context["assignments_by_referee"],
            cluster_by_match_id=context["cluster_by_match_id"],
        )
        item = serialize_referee_option(referee)
        item.update(
            {
                "is_valid": bool(diagnosis["is_valid"]),
                "warning_text": diagnosis["warning_text"],
            }
        )
        compatible_referee_payload.append(item)
    return JsonResponse({
        "ok": True,
        "assignment_id": assignment.id,
        "top_proposals": [_serialize_explained_proposal(run, assignment, item, context) for item in proposals],
        "compatible_referees": compatible_referee_payload,
    })


@require_POST
def manual_assignment_suggestions_bulk_view(request, run_id: int):
    run = get_object_or_404(DesignationRun, id=run_id)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "message": "Payload JSON no valid."}, status=400)

    try:
        assignment_ids = _parse_assignment_ids(payload.get("assignment_ids", []))
        limit = max(1, min(int(payload.get("limit", 3)), 3))
    except (TypeError, ValueError) as exc:
        return JsonResponse({"ok": False, "message": str(exc)}, status=400)

    return JsonResponse({
        "ok": True,
        "items": _build_manual_suggestions_bulk_items(run, assignment_ids, limit=limit),
    })


@require_GET
def assignment_explanation_view(request, run_id: int, assignment_id: int):
    run = get_object_or_404(DesignationRun, id=run_id)
    assignment = get_object_or_404(
        Assignment.objects.select_related("match", "referee"),
        id=assignment_id,
        run=run,
    )
    if not assignment.referee_id:
        return JsonResponse({"ok": False, "message": "L'assignacio no te tutor assignat."}, status=400)

    explanation = explain_current_assignment(run, assignment, context=build_manual_assignment_context(run))
    return JsonResponse({"ok": True, **explanation})


@require_POST
def update_assignment_async_view(request, run_id: int, assignment_id: int):
    run = get_object_or_404(DesignationRun, id=run_id)
    assignment = get_object_or_404(
        Assignment.objects.select_related("match", "referee"),
        id=assignment_id,
        run=run,
    )

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "message": "Payload JSON no valid."}, status=400)

    referee_id = payload.get("referee_id")
    note = str(payload.get("note") or "").strip()
    locked = bool(payload.get("locked", assignment.locked))

    try:
        result = _apply_assignment_update(run, assignment, referee_id, note, locked)
    except ValueError as exc:
        return JsonResponse({"ok": False, "message": str(exc)}, status=400)

    return JsonResponse(
        _assignment_json_payload(
            run,
            result["assignment"],
            result["message"],
            result["counts"],
            result["map_queued"],
            result["referee_summary_by_id"],
            result["mobility_summary"],
        )
    )


@require_POST
def update_assignment_view(request, run_id: int, assignment_id: int):
    run = get_object_or_404(DesignationRun, id=run_id)
    assignment = get_object_or_404(
        Assignment.objects.select_related("match", "referee"),
        id=assignment_id,
        run=run,
    )

    ref_id = request.POST.get("referee_id", "").strip()
    locked = assignment.locked if "locked" not in request.POST else request.POST.get("locked") == "on"
    note = request.POST.get("note", "").strip()

    try:
        result = _apply_assignment_update(run, assignment, ref_id, note, locked)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("designacions_assignments", run_id=run.id)

    if result["assignment"].manual_override_warning:
        messages.warning(request, result["message"])
    else:
        messages.success(request, result["message"])
    if result["map_queued"]:
        messages.info(request, "El mapa s'actualitzara en segon pla.")

    return redirect("designacions_assignments", run_id=run.id)

    """
        compatible_referees = {
            item.id
            for item in build_referee_options_by_assignment(run, [a], referees_with_counts=referee_lookup.values()).get(a.id, [])
        }
        if referee.id not in compatible_referees:
            messages.error(request, "Aquest tutor no és compatible amb la modalitat del partit.")
            return redirect("designacions_assignments", run_id=run.id)

        diagnosis = diagnose_assignment_for_referee(run, a, referee)
        a.referee = referee
        a.manual_override_warning = not diagnosis["is_valid"]
        a.manual_override_reason = diagnosis["warning_text"]
        if diagnosis["is_valid"]:
            messages.success(request, f"Assignacio de {a.match.code} guardada.")
        else:
            messages.warning(
                request,
                f"Assignacio de {a.match.code} guardada amb warning: {diagnosis['warning_text']}",
            )
    else:
        a.referee = None
        a.manual_override_warning = False
        a.manual_override_reason = ""
        if previous_referee_id is not None:
            messages.success(request, f"Partit {a.match.code} desassignat.")

    a.locked = locked
    a.note = note
    a.save()

    if previous_referee_id != a.referee_id:
        rebuild_run_map(run)

    return redirect("designacions_assignments", run_id=run.id)

    """

@require_POST
def export_excel_view(request, run_id: int):
    run = get_object_or_404(DesignationRun, id=run_id)

    out_dir = os.path.join(settings.MEDIA_ROOT, "designacions", "exports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"designacions_run_{run.id}.xlsx")

    export_run_to_excel(run, out_path)

    # Servim el fitxer
    with open(out_path, "rb") as f:
        data = f.read()

    resp = HttpResponse(data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="designacions_run_{run.id}.xlsx"'
    return resp



@require_GET
def geocoding_pending_view(request):
    qs = Address.objects.filter(geocode_status__in=["pending","not_found"]).order_by("text")
    return render(request, "geocoding_pending.html", {"addresses": qs})

@require_POST
def geocoding_update_view(request, address_id: int):
    a = get_object_or_404(Address, id=address_id)

    lat = request.POST.get("lat", "").strip()
    lon = request.POST.get("lon", "").strip()

    try:
        a.lat = float(lat)
        a.lon = float(lon)
        a.geocode_status = "manual"
        a.last_error = None
        a.save(update_fields=["lat","lon","geocode_status","last_error","updated_at"])
        messages.success(request, "Coordenades guardades.")
    except Exception:
        messages.error(request, "Lat/Lon no vàlids.")

    return redirect("designacions_geocoding_pending")



@require_GET
def run_map_view(request, run_id: int):
    run = get_object_or_404(DesignationRun, id=run_id)
    if not run.map_path:
        raise Http404("Aquest run no té mapa.")

    abs_path = os.path.join(settings.MEDIA_ROOT, run.map_path)
    if not os.path.exists(abs_path):
        raise Http404("No es troba el fitxer de mapa al disc.")

    with open(abs_path, "rb") as f:
        data = f.read()

    # IMPORTANT: és HTML generat per folium. El servim tal qual.
    response = HttpResponse(data, content_type="text/html; charset=utf-8")
    response["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@require_POST
def unassign_assignment_view(request, run_id: int, assignment_id: int):
    run = get_object_or_404(DesignationRun, id=run_id)
    assignment = get_object_or_404(
        Assignment.objects.select_related("match", "referee"),
        id=assignment_id,
        run=run,
    )

    # Desassignar
    result = _apply_assignment_update(run, assignment, "", assignment.note or "", False)
    messages.success(request, result["message"])
    if result["map_queued"]:
        messages.info(request, "El mapa s'actualitzara en segon pla.")
    return redirect("designacions_assignments", run_id=run.id)
    a.locked = False  # recomanat: si el deixes locked=True, després no té sentit
    a.manual_override_warning = False
    a.manual_override_reason = ""
    a.save(update_fields=["referee", "locked", "manual_override_warning", "manual_override_reason", "updated_at"])

    # Refés mapa
    rebuild_run_map(run)

    messages.success(request, f"Partit {a.match.code} desassignat i mapa actualitzat.")
    return redirect("designacions_assignments", run_id=run.id)


@require_POST
def modalitats_preview_view(request):
    """
    Rep el fitxer de PARTITS i retorna modalitats úniques.
    Espera un input file amb nom: 'partits_file'
    """
    f = request.FILES.get("partits_file")
    if not f:
        return JsonResponse({"ok": False, "error": "Falta el fitxer de partits."}, status=400)

    try:
        # pandas pot llegir directament l'UploadedFile
        df = pd.read_excel(f, engine="openpyxl")
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"No s'ha pogut llegir l'Excel: {e}"}, status=400)

    if "Modalitat" not in df.columns:
        return JsonResponse({"ok": False, "error": "La columna 'Modalitat' no existeix al fitxer de partits."}, status=400)

    modalitats = (
        df["Modalitat"]
        .dropna()
        .astype(str)
        .map(lambda s: s.strip())
        .loc[lambda s: s != ""]
        .unique()
        .tolist()
    )
    modalitats.sort()

    return JsonResponse({"ok": True, "modalitats": modalitats})



@require_GET
def runs_list_view(request):
    """
    Llista d'històric de runs (designacions) amb cerca i filtre per estat.
    """
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()

    qs = (
        DesignationRun.objects
        .annotate(
            n_matches=Count("matches", distinct=True),
            n_assignments=Count("assignments", distinct=True),
            n_assigned=Count("assignments", filter=Q(assignments__referee__isnull=False), distinct=True),
        )
        .order_by("-created_at")
    )

    if status:
        qs = qs.filter(status=status)

    if q:
        # Cerca flexible: id, task_id i text dins params
        qs = qs.filter(
            Q(task_id__icontains=q) |
            Q(id__icontains=q) |
            Q(params__icontains=q)
        )

    paginator = Paginator(qs, 20)  # 20 per pàgina
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    return render(request, "run_list.html", {
        "page_obj": page_obj,
        "q": q,
        "status": status,
        "status_choices": DesignationRun.STATUS_CHOICES,
    })


@require_POST
def run_delete_view(request, run_id: int):
    """
    (Opcional) Esborra un run i totes les dades relacionades (matches, assignments... via CASCADE).
    """
    run = get_object_or_404(DesignationRun, id=run_id)

    # Esborrem també fitxers associats si existeixen
    try:
        if run.input_partits:
            run.input_partits.delete(save=False)
        if run.input_disponibilitats:
            run.input_disponibilitats.delete(save=False)
    except Exception:
        pass

    run.delete()
    messages.success(request, f"Run #{run_id} eliminat.")
    return redirect("designacions_runs_list")
