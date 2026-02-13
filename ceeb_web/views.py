import logging
import os, io, uuid, zipfile, requests, sys, json
from django.http import HttpResponse
from django.shortcuts import render
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.http import JsonResponse, StreamingHttpResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from celery.result import AsyncResult
from .tasks import process_certificats_task, process_calendaritzacions_task, process_designacions_task, process_llistats_provisionals_task
from .tasks import process_llistats_definitius_task, process_calendaritzacions_fase_dos_task
import redis
from django.views import View
from django.utils.dateparse import parse_datetime
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import CalendarEvent
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView
from django.contrib import messages
from django.views.generic.edit import FormView
from .forms import CertificatsUploadForm


REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
RAG_URL = os.getenv("RAG_URL", "http://rag:8000/chatbot/")

def home_view(request):

    return render(request, 'home.html')  # Renderitza la plantilla 'index.html'

def about_view(request):
    return render(request, 'about.html')  # Renderitza la plantilla 'about.html'

def formacio_view(request):
    return render(request, 'formacio.html')  # Renderitza la plantilla 'formacio.html'

def esports_equip_view(request):
    return render(request, 'esports_equip.html')  # Renderitza la plantilla 'esports_equip.html'

def marbella_view(request):
    return render(request, 'marbella.html')  # Renderitza la plantilla 'marbella.html'

def esports_individuals_view(request):
    return render(request, 'esports_individuals.html')  # Renderitza la plantilla 'esports_individuals.html'

# ---------------------------------------------------------------------------------------------------
# CALENDARIS
# ---------------------------------------------------------------------------------------------------
@csrf_exempt
def calendaritzacions_view(request):
    # Nova implementació: similar a `certificats` — guardem temporalment el fitxer, enfilem
    # una tasca Celery `process_calendaritzacions_task` i retornem el `task_id` al frontend
    # perquè aquest obri l'SSE i faci polling de l'estat.
    if request.method == 'POST':
        # Esperem un únic fitxer amb camp 'file'
        up = request.FILES.get('file')
        if not up:
            return JsonResponse({'error': 'Cap fitxer rebut.'}, status=400)

        # Desa temporalment al directori MEDIA_ROOT/temp
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, up.name)
        with open(temp_path, 'wb') as f:
            for chunk in up.chunks():
                f.write(chunk)

        # Enfilem la tasca Celery passant la ruta temporal del fitxer perquè la tasca
        # faci un POST multipart al servei de calendaritzacions (no codifiquem en base64).
        task = process_calendaritzacions_task.delay(temp_path)
        return JsonResponse({'task_id': task.id})

    # GET normal: renderitza la plantilla (el JS de la plantilla s'encarregarà d'enviar la crida)
    return render(request, 'calendaritzacions.html', {})


@csrf_exempt
def calendaritzacions_fase_dos_view(request):
    # Nova implementació: similar a `certificats` — guardem temporalment el fitxer, enfilem
    # una tasca Celery `process_calendaritzacions_task` i retornem el `task_id` al frontend
    # perquè aquest obri l'SSE i faci polling de l'estat.
    if request.method == 'POST':
        # Esperem un únic fitxer amb camp 'file'
        up = request.FILES.get('file')
        if not up:
            return JsonResponse({'error': 'Cap fitxer rebut.'}, status=400)

        # Desa temporalment al directori MEDIA_ROOT/temp
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, up.name)
        with open(temp_path, 'wb') as f:
            for chunk in up.chunks():
                f.write(chunk)

        # Enfilem la tasca Celery passant la ruta temporal del fitxer perquè la tasca
        # faci un POST multipart al servei de calendaritzacions (no codifiquem en base64).
        task = process_calendaritzacions_fase_dos_task.delay(temp_path)
        return JsonResponse({'task_id': task.id})

    # GET normal: renderitza la plantilla (el JS de la plantilla s'encarregarà d'enviar la crida)
    return render(request, 'calendaritzacions_fase_dos.html', {})


# ---------------------------------------------------------------------------------------------------
# LLISTATS PROVISIONALS
# ---------------------------------------------------------------------------------------------------
@csrf_exempt
def llistats_provisionals_view(request):
    
    if request.method == 'POST':
        # Esperem un únic fitxer amb camp 'file'
        up = request.FILES.get('file')
        if not up:
            return JsonResponse({'error': 'Cap fitxer rebut.'}, status=400)

        # Desa temporalment al directori MEDIA_ROOT/temp
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, up.name)
        with open(temp_path, 'wb') as f:
            for chunk in up.chunks():
                f.write(chunk)

        # Enfilem la tasca Celery passant la ruta temporal del fitxer perquè la tasca
        # faci un POST multipart al servei de calendaritzacions (no codifiquem en base64).
        task = process_llistats_provisionals_task.delay(temp_path)
        return JsonResponse({'task_id': task.id})

    return render(request, 'llistats_provisionals.html', {})

# ---------------------------------------------------------------------------------------------------
# LLISTATS DEFINITIUS
# ---------------------------------------------------------------------------------------------------
@csrf_exempt
def llistats_definitius_view(request):
    
    if request.method == 'POST':
        # Esperem un únic fitxer amb camp 'file'
        up = request.FILES.get('file')
        if not up:
            return JsonResponse({'error': 'Cap fitxer rebut.'}, status=400)

        # Desa temporalment al directori MEDIA_ROOT/temp
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, up.name)
        with open(temp_path, 'wb') as f:
            for chunk in up.chunks():
                f.write(chunk)

        # Enfilem la tasca Celery passant la ruta temporal del fitxer perquè la tasca
        # faci un POST multipart al servei de calendaritzacions (no codifiquem en base64).
        task = process_llistats_definitius_task.delay(temp_path)
        return JsonResponse({'task_id': task.id})

    return render(request, 'llistats_definitius.html', {})

# ---------------------------------------------------------------------------------------------------
# DESIGNACIONS
# ---------------------------------------------------------------------------------------------------
@csrf_exempt
def designacions_view(request):
    # Nova implementació: similar a `certificats` — guardem temporalment el fitxer, enfilem
    # una tasca Celery `process_designacions_task` i retornem el `task_id` al frontend
    # perquè aquest obri l'SSE i faci polling de l'estat.
    if request.method == 'POST':
        # Esperem un únic fitxer amb camp 'file'
        files = request.FILES.getlist('files')
        if not files:
            print("No s'han seleccionat fitxers.")
            return render(request, 'certificats.html', {
                'error': 'Cap arxiu seleccionat!',
            }, status=400)

        # Desa els fitxers en una ubicació temporal
        temp_file_paths = []
        for file in files:
            temp_path = os.path.join(settings.MEDIA_ROOT, 'temp', file.name)
            os.makedirs(os.path.dirname(temp_path), exist_ok=True)
            with open(temp_path, 'wb') as temp_file:
                for chunk in file.chunks():
                    temp_file.write(chunk)
            temp_file_paths.append(temp_path)
        task = process_designacions_task.delay(temp_file_paths)
        return JsonResponse({'task_id': task.id})

    # GET normal: renderitza la plantilla (el JS de la plantilla s'encarregarà d'enviar la crida)
    return render(request, 'designacions.html', {})

# ---------------------------------------------------------------------------------------------------
# CERTIFICATS
# ---------------------------------------------------------------------------------------------------



class CertificatsUploadView(FormView):
    template_name = "certificats.html"
    form_class = CertificatsUploadForm
    success_url = "/formacio/certificats/"  # o reverse_lazy si vols

    def form_valid(self, form):
        import zipfile
        files = self.request.FILES.getlist('files')
        temp_file_paths = []
        for file in files:
            if file.name.lower().endswith('.zip'):
                temp_zip_path = os.path.join(settings.MEDIA_ROOT, 'temp', file.name)
                os.makedirs(os.path.dirname(temp_zip_path), exist_ok=True)
                with open(temp_zip_path, 'wb') as temp_zip_file:
                    for chunk in file.chunks():
                        temp_zip_file.write(chunk)
                with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                    for member in zip_ref.namelist():
                        if member.lower().endswith('.pdf'):
                            extracted_path = os.path.join(settings.MEDIA_ROOT, 'temp', member)
                            os.makedirs(os.path.dirname(extracted_path), exist_ok=True)
                            with open(extracted_path, 'wb') as out_f:
                                out_f.write(zip_ref.read(member))
                            temp_file_paths.append(extracted_path)
            else:
                temp_path = os.path.join(settings.MEDIA_ROOT, 'temp', file.name)
                os.makedirs(os.path.dirname(temp_path), exist_ok=True)
                with open(temp_path, 'wb') as temp_file:
                    for chunk in file.chunks():
                        temp_file.write(chunk)
                temp_file_paths.append(temp_path)

        task = process_certificats_task.delay(temp_file_paths)
        self.request.session['certificats_task_id'] = task.id
        messages.success(self.request, "Fitxers pujats correctament. S'estan processant.")

        # Si no, comportament normal de FormView
        return JsonResponse({'task_id': task.id})


# ---------------------------------------------------------------------------------------------------
# RAG
# ---------------------------------------------------------------------------------------------------
@csrf_exempt
def chatbot_view(request):
    if request.method == "POST":
        logging.info("S'ha rebut una crida a /chatbot/")
        try:
            # Llegeix el missatge enviat pel frontend
            data = json.loads(request.body)
            query = data.get("message")
            session_id = data.get("session_id")
            logging.info(f"Missatge de l'usuari: {query}, Session ID: {session_id}")
            logging.info(f"RAG URL: {RAG_URL}")
            # Envia el missatge al servei RAG
            logging.info(f"JSON enviat: {json.dumps({'message': query, 'session_id': session_id})}")
            payload = {"query": query, "session_id": session_id, "collection": "enhanced_documents", "model": "llama3.1"}
            response = requests.post(
                RAG_URL,
                json=payload,
                timeout=600,
            )
            response.raise_for_status()

            # Retorna la resposta del servei RAG al frontend
            rag_reply = response.json().get("response", "No s'ha rebut cap resposta.")
            return JsonResponse({"reply": rag_reply})

        except requests.exceptions.RequestException as e:
            return JsonResponse({"error": f"Error de connexió amb el servei RAG: {e}"}, status=500)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Dades JSON no vàlides."}, status=400)

    return JsonResponse({"error": "Mètode no permès."}, status=405)




# ---------------------------------------------------------------------------------------------------
# HOME
# ---------------------------------------------------------------------------------------------------

class HomeCalendarView(LoginRequiredMixin, TemplateView):
    template_name = "home.html"


class CalendarEventsJsonView(LoginRequiredMixin, View):
    def get(self, request):
        # Només mostra els esdeveniments creats per l'usuari autenticat
        events = CalendarEvent.objects.filter(created_by=request.user).order_by("start")
        data = []
        for e in events:
            data.append({
                "id": e.id,
                "title": e.title,
                "start": e.start.isoformat(),
                "end": e.end.isoformat() if e.end else None,
                "description": e.description,
            })
        return JsonResponse(data, safe=False)


@method_decorator(csrf_exempt, name="dispatch")  # opcional si ja envies CSRF bé
class CalendarEventCreateView(LoginRequiredMixin, View):
    def post(self, request):
        payload = json.loads(request.body.decode("utf-8"))
        title = payload.get("title", "").strip()
        start = parse_datetime(payload.get("start"))
        end = parse_datetime(payload.get("end")) if payload.get("end") else None
        description = (payload.get("description") or "").strip()

        if not title or not start:
            return JsonResponse({"ok": False, "error": "Títol i inici són obligatoris."}, status=400)

        e = CalendarEvent.objects.create(
            title=title, start=start, end=end, description=description, created_by=request.user
        )
        return JsonResponse({"ok": True, "id": e.id})



@method_decorator(csrf_exempt, name="dispatch")
class CalendarEventUpdateView(LoginRequiredMixin, View):
    def post(self, request, event_id):
        payload = json.loads(request.body.decode("utf-8"))

        e = get_object_or_404(CalendarEvent, pk=event_id, created_by=request.user)

        title = (payload.get("title") or "").strip()
        start = parse_datetime(payload.get("start"))
        end = parse_datetime(payload.get("end")) if payload.get("end") else None
        description = (payload.get("description") or "").strip()

        if not title or not start:
            return JsonResponse({"ok": False, "error": "Títol i inici són obligatoris."}, status=400)

        # Si USE_TZ=True, fem aware quan arribi naive
        if start and timezone.is_naive(start):
            start = timezone.make_aware(start, timezone.get_current_timezone())
        if end and timezone.is_naive(end):
            end = timezone.make_aware(end, timezone.get_current_timezone())

        e.title = title
        e.start = start
        e.end = end
        e.description = description
        e.save(update_fields=["title", "start", "end", "description"])

        return JsonResponse({"ok": True})


@method_decorator(csrf_exempt, name="dispatch")
class CalendarEventDeleteView(LoginRequiredMixin, View):
    def post(self, request, event_id):
        e = get_object_or_404(CalendarEvent, pk=event_id, created_by=request.user)
        e.delete()
        return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------------------------------
# LOGS I ESTAT TASQUES CELERY
# ---------------------------------------------------------------------------------------------------
def sse_logs(request, task_id):
    r = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    pubsub = r.pubsub()
    pubsub.subscribe(f"logs:{task_id}")

    def event_stream():
        # 1) Primer, envia qualsevol log ja guardat al result-backend (fallback)
        try:
            task = AsyncResult(task_id)
            info = task.info
            if info:
                # Si hi ha logs en el meta, els reenviem en ordre
                if isinstance(info, dict):
                    logs = info.get('logs') or []
                    progress = info.get('progress') if isinstance(info.get('progress'), (int, float)) else None
                    for entry in logs:
                        payload = json.dumps({'message': entry, 'progress': progress})
                        yield f"data: {payload}\n\n"
                else:
                    # Informació no-dict: envia-la tal qual
                    payload = json.dumps({'message': str(info)})
                    yield f"data: {payload}\n\n"

            # 2) Ara subscriu al canal pub/sub i transmet missatges nous en temps real
            for message in pubsub.listen():
                print(f"Missatge rebut de Redis: {message}")  # Depuració
                if message.get("type") == "message":
                    data = message.get("data")  # esperem JSON: {"message":"...", "progress": 15}
                    # Si el payload és ja una cadena JSON, l'enviem tal qual
                    try:
                        # Assegurem que és una cadena
                        if isinstance(data, str):
                            yield f"data: {data}\n\n"
                        else:
                            yield f"data: {json.dumps(data)}\n\n"
                    except Exception:
                        yield f"data: {json.dumps({'message': str(data)})}\n\n"
        finally:
            try:
                pubsub.unsubscribe(f"logs:{task_id}")
            finally:
                pubsub.close()

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    return response

@csrf_exempt
def task_status_view(request, task_id):
    task = AsyncResult(task_id)
    print(f"Task info: {task.info}")  # Depura el contingut de task.info
    response_data = {
        'task_id': task_id,
        'status': task.status,
    }

    if task.info:  # Inclou els logs si estan disponibles
        if isinstance(task.info, dict):  # Comprova si task.info és un diccionari
            response_data['logs'] = task.info.get('logs', [])
        else:
            response_data['logs'] = [f"Error: {str(task.info)}"]

    if task.status == 'FAILURE':
        response_data['error'] = str(task.result)
    elif task.status == 'SUCCESS':
        # By default include the Celery result, but if the result is a
        # remote job id we should NOT consider the whole work finished
        # until the remote service reports "done" in Redis. In that
        # case we consult Redis job:{remote_id} and only return
        # 'SUCCESS' when remote status == 'done'. Otherwise return
        # 'PENDING' so the frontend keeps polling.
        response_data['result'] = task.result
        try:
            if isinstance(task.result, str):
                remote_id = task.result
                try:
                    r = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
                    raw = r.get(f"job:{remote_id}")
                    if raw:
                        try:
                            remote_data = json.loads(raw)
                        except Exception:
                            remote_data = None
                        if isinstance(remote_data, dict):
                            remote_status = remote_data.get('status')
                            # If remote finished, expose result/result_url and
                            # report SUCCESS to the frontend so it can show the link.
                            if remote_status == 'done':
                                response_data['status'] = 'SUCCESS'
                                response_data['result_url'] = remote_data.get('result_url') or remote_data.get('result')
                                response_data['logs'] = remote_data.get('logs', [])
                            else:
                                # Not finished remotely yet: instruct frontend to keep polling
                                response_data['status'] = remote_status or 'PENDING'
                                response_data['logs'] = remote_data.get('logs', [])
                    else:
                        # No remote job metadata yet: still pending
                        response_data['status'] = 'PENDING'
                except Exception:
                    # If Redis is unreachable or any error happens, fall back
                    # to returning the Celery SUCCESS so the frontend can
                    # attempt other fallbacks.
                    pass
        except Exception:
            pass

    return JsonResponse(response_data)


