# views.py
from django.core.paginator import Paginator
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
from django.db.models import Count, Q
from .services.colors import color_per_tutor
from django.http import Http404, HttpResponse
from .models import DesignationRun, Assignment, Referee
from .tasks import process_designacions_run
from .services.jobstore import write_job_sync, read_job_sync
from .services.excel_export import export_run_to_excel
from django.views.decorators.http import require_POST
from .services.map_rebuild import rebuild_run_map
from .models import Availability
import pandas as pd



REDIS_URL = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")

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
        return render(request, "upload.html", {
            "defaults": {
                "cluster_eps_m": 500,
                "cluster_min_samples": 2,
                "max_partits_subgrup": 3,
                "gap_same_pitch_min": 60,
                "gap_diff_pitch_min": 75,
                "modalitats_csv": "",
                "date_from": "",
                "date_to": "",
            }
        })

    files = request.FILES.getlist("files")
    if len(files) != 2:
        return HttpResponseBadRequest("Cal pujar exactament 2 fitxers .xlsx (partits i disponibilitats).")

    task_id = uuid.uuid4().hex

    path1 = _save_uploaded(files[0], task_id)
    path2 = _save_uploaded(files[1], task_id)

    # --- PARAMS del run (venen del formulari) ---
    params = {
        "cluster_eps_m": _to_float(request.POST.get("cluster_eps_m"), 500),
        "cluster_min_samples": _to_int(request.POST.get("cluster_min_samples"), 2),
        "max_partits_subgrup": _to_int(request.POST.get("max_partits_subgrup"), 3),
        "gap_same_pitch_min": _to_int(request.POST.get("gap_same_pitch_min"), 60),
        "gap_diff_pitch_min": _to_int(request.POST.get("gap_diff_pitch_min"), 75),
        "modalitats": _to_str_list_csv(request.POST.get("modalitats_csv")),
        "date_from": (request.POST.get("date_from") or "").strip(),
        "date_to": (request.POST.get("date_to") or "").strip(),
    }

    run = DesignationRun.objects.create(
        task_id=task_id,
        status="queued",
        input_partits=files[0],
        input_disponibilitats=files[1],
        params=params,
    )

    write_job_sync(task_id, {"status": "queued", "task_id": task_id})

    # passa params a celery
    process_designacions_run.delay(run.id, task_id, path1, path2, params)

    return redirect("designacions_run_detail", run_id=run.id)

@require_GET
def run_detail_view(request, run_id: int):
    run = get_object_or_404(DesignationRun, id=run_id)
    return render(request, "run_detail.html", {"run": run})

@require_GET
@require_GET
def task_status_view(request, task_id: str):
    job = read_job_sync(task_id) or {}

    status = job.get("status") or "PENDING"

    if status in ("done", "SUCCESS"):
        return JsonResponse({
            "status": "SUCCESS",
            "progress": 100,
            "message": job.get("message"),
        })

    if status in ("failed", "FAILURE"):
        return JsonResponse({
            "status": "FAILURE",
            "progress": job.get("progress"),
            "message": job.get("message"),
            "error": job.get("error"),
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


    avail_qs = (run.availabilities
                .select_related("referee")
                .all())

    availability_by_ref = {a.referee_id: a.raw for a in avail_qs}



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
        "availability_by_ref": availability_by_ref,
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


@require_POST
def unassign_assignment_view(request, run_id: int, assignment_id: int):
    run = get_object_or_404(DesignationRun, id=run_id)
    a = get_object_or_404(Assignment, id=assignment_id, run=run)

    # Desassignar
    a.referee = None
    a.locked = False  # recomanat: si el deixes locked=True, després no té sentit
    a.save(update_fields=["referee", "locked", "updated_at"])

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
