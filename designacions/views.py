# designacions_app/views.py
import os, uuid, json
from pathlib import Path
from redis import Redis
from django.contrib import messages
from .models import Address
from django.conf import settings
from django.core.files.base import ContentFile
from django.http import JsonResponse, StreamingHttpResponse, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_GET, require_POST

from .models import DesignationRun, Assignment, Referee
from .tasks import process_designacions_run
from .services.jobstore import write_job_sync, read_job_sync
from .services.excel_export import export_run_to_excel

REDIS_URL = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")

def _temp_dir():
    d = os.path.join(settings.MEDIA_ROOT, "temp")
    os.makedirs(d, exist_ok=True)
    return d

def _save_uploaded(f, prefix: str) -> str:
    out_path = os.path.join(_temp_dir(), f"{prefix}__{f.name}")
    with open(out_path, "wb") as dest:
        for chunk in f.chunks():
            dest.write(chunk)
    return out_path

@require_http_methods(["GET", "POST"])
def upload_view(request):
    if request.method == "GET":
        return render(request, "upload.html")

    files = request.FILES.getlist("files")
    if len(files) != 2:
        return HttpResponseBadRequest("Cal pujar exactament 2 fitxers .xlsx (partits i disponibilitats).")

    task_id = uuid.uuid4().hex

    # Guardem a disc (temp)
    path1 = _save_uploaded(files[0], task_id)
    path2 = _save_uploaded(files[1], task_id)

    # Guardem també els originals a MEDIA per auditoria (opcional, però recomanat)
    run = DesignationRun.objects.create(
        task_id=task_id,
        status="queued",
        input_partits=files[0],
        input_disponibilitats=files[1],
    )

    write_job_sync(task_id, {"status": "queued", "task_id": task_id})

    # Arrenca celery (si l’ordre ve invertit, el teu motor ja ho tracta com a l’API)
    process_designacions_run.delay(run.id, task_id, path1, path2)

    return redirect("designacions_run_detail", run_id=run.id)

@require_GET
def run_detail_view(request, run_id: int):
    run = get_object_or_404(DesignationRun, id=run_id)
    return render(request, "run_detail.html", {"run": run})

@require_GET
def task_status_view(request, task_id: str):
    job = read_job_sync(task_id) or {}
    st = job.get("status") or "PENDING"

    if st in ("done", "SUCCESS"):
        return JsonResponse({"status": "SUCCESS"})
    if st in ("failed", "FAILURE"):
        return JsonResponse({"status": "FAILURE", "error": job.get("error")})

    return JsonResponse({"status": st})

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

# designacions_app/views.py
from django.db.models import Count, Q
from .services.colors import color_per_tutor

@require_GET
def assignments_view(request, run_id: int):
    run = get_object_or_404(DesignationRun, id=run_id)

    # Assignacions del run
    qs = (
        run.assignments
           .select_related("match", "referee")
           .all()
    )

    assigned_qs = qs.filter(referee__isnull=False).order_by("referee__code", "match__date", "match__hour_raw", "match__code")
    unassigned_matches = qs.filter(referee__isnull=True).select_related("match").order_by("match__date", "match__hour_raw", "match__code")

    # Llista de tutors actius (per desplegable d’edició)
    referees = Referee.objects.filter(active=True).order_by("name")

    # Tutors sense cap partit assignat en aquest run
    # (tutors actius amb 0 assignacions)
    referees_with_counts = (
        Referee.objects.filter(active=True)
        .annotate(n=Count("assignments", filter=Q(assignments__run=run)))
        .order_by("name")
    )
    unassigned_referees = [r for r in referees_with_counts if (r.n or 0) == 0]

    # Tutors “sense nivell” (si Referee.level buit)
    needs_review_referees = (
        Referee.objects.filter(active=True)
        .filter(Q(level__isnull=True) | Q(level__exact=""))
        .annotate(n=Count("assignments", filter=Q(assignments__run=run)))
        .filter(n__gt=0)
        .order_by("name")
    )

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
            current = {
                "referee": r,
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

    # Comptadors per pestanyes
    counts = {
        "assigned": assigned_qs.count(),
        "unassigned_matches": unassigned_matches.count(),
        "unassigned_referees": len(unassigned_referees),
        "needs_review_referees": needs_review_referees.count(),
        "has_map": bool(run.map_path),
    }

    return render(request, "assignments.html", {
        "run": run,
        "groups": groups,
        "unassigned_matches": unassigned_matches,
        "unassigned_referees": unassigned_referees,
        "needs_review_referees": needs_review_referees,
        "referees": referees,
        "counts": counts,
    })

@require_POST
def update_assignment_view(request, run_id: int, assignment_id: int):
    run = get_object_or_404(DesignationRun, id=run_id)
    a = get_object_or_404(Assignment, id=assignment_id, run=run)

    ref_id = request.POST.get("referee_id", "").strip()
    locked = request.POST.get("locked") == "on"
    note = request.POST.get("note", "").strip()

    if ref_id:
        a.referee = get_object_or_404(Referee, id=int(ref_id))
    else:
        a.referee = None

    a.locked = locked
    a.note = note
    a.save()

    return redirect("designacions_assignments", run_id=run.id)

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


# designacions_app/views.py
from django.http import Http404, HttpResponse

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
    return HttpResponse(data, content_type="text/html; charset=utf-8")
