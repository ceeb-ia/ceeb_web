import logging
import os, io, uuid, zipfile, requests, sys, json
from django.http import HttpResponse
from django.shortcuts import render
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.http import JsonResponse, StreamingHttpResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from celery.result import AsyncResult
from .tasks import process_certificats_task
import redis


REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CALENDARITZACIONS_BASE = "http://calendaritzacions:8000"
CERTIFICATS_API = os.getenv("CERTIFICATS_API", "http://certificats:8000/process-pdfs/")  # ajusta-ho al teu docker/network
RAG_URL = os.getenv("RAG_URL", "http://rag:8000/chatbot/")

def home_view(request):

    return render(request, 'home.html')  # Renderitza la plantilla 'index.html'

def about_view(request):
    return render(request, 'about.html')  # Renderitza la plantilla 'about.html'


def esports_equip_view(request):
    return render(request, 'esports_equip.html')  # Renderitza la plantilla 'esports_equip.html'

# ---------------------------------------------------------------------------------------------------
# CALENDARIS
# ---------------------------------------------------------------------------------------------------

def calendaritzacions_view(request):
    if request.method == 'POST' and request.FILES.get('file'):
        up = request.FILES['file']
        files = {'file': (up.name, up.read(), up.content_type)}
        try:
            # 1) crea feina
            r = requests.post('http://calendaritzacions:8000/process_async', files=files, timeout=60)
            r.raise_for_status()
            job_id = r.json().get("job_id")
            # Passem el job_id a la plantilla i que el frontend faci polling
            return render(request, 'calendaritzacions.html', {'job_id': job_id, 'messages': ['Procés en marxa...']})
        except requests.exceptions.RequestException as e:
            return render(request, 'calendaritzacions.html', {'messages': [f"Error: {e}"]})
    # GET normal
    return render(request, 'calendaritzacions.html', {})

@csrf_exempt
def calendaritzacions_status(request, job_id):
    """
    Proxy: consulta l'estat d'una tasca al servei calendaritzacions.
    Retorna un JSON amb {'status': '...', 'logs': [...]}.
    """
    try:
        r = requests.get(f"{CALENDARITZACIONS_BASE}/status/{job_id}", timeout=10)
        r.raise_for_status()
        data = r.json()
        return JsonResponse(data)
    except requests.exceptions.RequestException as e:
        return JsonResponse({"status": "error", "logs": [f"Error de connexió: {e}"]}, status=500)


@csrf_exempt
def calendaritzacions_download(request, job_id):
    """
    Proxy: descarrega el fitxer processat des del servei calendaritzacions.
    Retorna un FileResponse perquè l'usuari el descarregui.
    """
    try:
        r = requests.get(f"{CALENDARITZACIONS_BASE}/download/{job_id}", stream=True, timeout=60)
        if r.status_code != 200:
            return HttpResponse(f"Error: {r.text}", status=r.status_code)

        # Nom del fitxer (si està al header)
        filename = r.headers.get(
            "content-disposition", ""
        ).replace("attachment; filename=", "").strip('"') or "resultat.xlsx"

        response = HttpResponse(r.content, content_type=r.headers.get("content-type", "application/octet-stream"))
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    except requests.exceptions.RequestException as e:
        return HttpResponse(f"Error de connexió amb calendaritzacions: {e}", status=500)
    

# ---------------------------------------------------------------------------------------------------
# CERTIFICATS
# ---------------------------------------------------------------------------------------------------


@csrf_exempt
def procesar_certificats_view(request):
    if request.method == 'POST':
        print("Iniciant procés de certificats...")
        files = request.FILES.getlist('files')
        print(f"Nombre de fitxers rebuts: {len(files)}")
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

        # Envia la tasca Celery amb els camins dels fitxers
        task = process_certificats_task.delay(temp_file_paths)
        print(f"Tasca Celery en marxa amb ID: {task.id}")

        return JsonResponse({'task_id': task.id})

    return render(request, 'certificats.html')


def sse_logs(request, task_id):
    r = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    pubsub = r.pubsub()
    pubsub.subscribe(f"logs:{task_id}")

    def event_stream():
        try:
            for message in pubsub.listen():
                print(f"Missatge rebut de Redis: {message}")  # Depuració
                if message.get("type") == "message":
                    data = message.get("data")  # esperem JSON: {"message":"...", "progress": 15}
                    yield f"data: {data}\n\n"
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
        response_data['result'] = task.result

    return JsonResponse(response_data)

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