import io
from celery import shared_task
import requests
import os
import uuid
import httpx
import aiofiles
import asyncio
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from django.conf import settings
import redis
import json

CALENDARITZACIONS_API = os.getenv("CALENDARITZACIONS_API", "http://calendaritzacions:8000/process_async")
CALENDARITZACIONS_API_SEGONA_FASE = os.getenv("CALENDARITZACIONS_API_SEGONA_FASE", "http://calendaritzacions:8000/process_async_segona_fase/")
LLISTATS_PROVISIONALS_API = os.getenv("LLISTATS_PROVISIONALS_API", "http://natacio:8000/provisionals/")
LLISTATS_DEFINITIUS_API = os.getenv("LLISTATS_DEFINITIUS_API", "http://natacio:8000/definitius/")
DESIGNACIONS_API = os.getenv("DESIGNACIONS_API", "http://designacions:8000/process_designacions/")
MEDIA_URL = os.getenv("MEDIA_URL", "/media/")  # e.g., "/media/"
RESULTS_DIR = os.getenv("MEDIA_ROOT", "/data/media")  # e.g., "/data/media"


def _path_to_media_url(path: str) -> str | None:
    """If `path` is under RESULTS_DIR (or MEDIA_ROOT), return a media URL.
    Otherwise return None.
    """
    try:
        if not path:
            return None
        normalized = os.path.normpath(path)
        root = os.path.normpath(RESULTS_DIR)
        if normalized.startswith(root):
            rel = os.path.relpath(normalized, root).replace(os.sep, '/')
            return MEDIA_URL.rstrip('/') + '/' + rel
    except Exception:
        pass
    return None


def _path_to_settings_media_url(path: str | Path) -> str | None:
    try:
        media_root = Path(settings.MEDIA_ROOT).resolve()
        resolved_path = Path(path).resolve()
        rel = resolved_path.relative_to(media_root).as_posix()
        return settings.MEDIA_URL.rstrip('/') + '/' + rel
    except Exception:
        return None


def _load_certificats_services():
    try:
        from certificats.services.archive import create_certificats_zip
        from certificats.services.processor import processar_certificats
    except ModuleNotFoundError as exc:
        raise RuntimeError("No s'ha pogut carregar l'app local de certificats.") from exc

    return processar_certificats, create_certificats_zip


def _normalise_file_paths(file_paths) -> list[Path]:
    if isinstance(file_paths, (str, bytes, os.PathLike)):
        raw_paths = [file_paths]
    elif file_paths is None:
        raw_paths = []
    else:
        raw_paths = list(file_paths)

    paths = [Path(path) for path in raw_paths if path]
    if not paths:
        raise RuntimeError("No hi ha cap fitxer per processar a certificats.")

    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"No s'ha trobat el fitxer temporal: {missing[0]}")

    unsupported = [path.name for path in paths if path.suffix.lower() != ".pdf"]
    if unsupported:
        raise RuntimeError(f"Tipus de fitxer no suportat a certificats: {unsupported[0]}. Ha de ser .pdf")

    return paths


def _copy_certificats_inputs(file_paths, destination: Path) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    copied = 0
    for index, source in enumerate(_normalise_file_paths(file_paths), start=1):
        target = destination / source.name
        if target.exists():
            target = destination / f"{source.stem}_{index}{source.suffix}"
        shutil.copy2(source, target)
        copied += 1
    return copied


def _store_certificats_result(task_id: str, result: str, zip_path: str | Path) -> None:
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    try:
        r = redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        result_url = _path_to_settings_media_url(zip_path) or result
        job_meta = json.dumps(
            {
                'status': 'done',
                'result': str(zip_path),
                'result_url': result_url,
                'logs': ['Proces complet.'],
            }
        )
        for key in {task_id, result, result_url}:
            if key:
                r.set(f"job:{key}", job_meta)
                r.expire(f"job:{key}", 60 * 60 * 24 * 7)
        r.publish(
            f"logs:{task_id}",
            json.dumps({'message': 'Proces complet. Preparant enllac de descarrega...', 'progress': 100}),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------------------------------
# CERTIFICATS
# ---------------------------------------------------------------------------------------------------


@shared_task(bind=True, queue='heavy_queue')
def process_certificats_task(self, file_paths):
    """
    Tasca SÍNCRONA per a Celery (retorna un valor serialitzable),
    però que executa codi ASÍNCRON intern amb asyncio.run(...).
    """
    task_id = str(self.request.id)
    push = _push(self)
    self.update_state(state='STARTED', meta={'logs': ['Iniciant el proces...']})

    try:
        processar_certificats, create_certificats_zip = _load_certificats_services()
        with TemporaryDirectory(prefix=f"certificats_{task_id}_") as temp_dir:
            work_dir = Path(temp_dir)
            input_dir = work_dir / "input"
            copied = _copy_certificats_inputs(file_paths, input_dir)
            push(f"Preparats {copied} fitxers per processar localment.", 10)

            result_dir = processar_certificats(input_dir, work_dir, on_progress=push)
            if result_dir is None:
                raise RuntimeError("No s'ha pogut processar cap certificat.")

            push("Comprimint certificats generats...", 95)
            zip_path = create_certificats_zip(
                result_dir,
                Path(settings.MEDIA_ROOT) / "certificats",
            )
        result_url = _path_to_settings_media_url(zip_path) or _path_to_media_url(str(zip_path)) or str(zip_path)
        _store_certificats_result(task_id, result_url, zip_path)

        self.update_state(
            state='SUCCESS',
            meta={'logs': ['Proces complet.'], 'progress': 100, 'result': result_url, 'result_url': result_url},
        )
        push("Proces complet. Preparant enllac de descarrega...", 100)
        return result_url
    except Exception as e:
        try:
            self.update_state(state='FAILURE', meta={'logs': [str(e)]})
        finally:
            raise

def _push(self_task):
    """Callback per reportar logs a Celery meta, sempre serialitzable."""
    def _inner(msg: str, progress: int | None = None):
        try:
            print(f"Enviant log: {msg}")
            meta = {'logs': [str(msg)]}
            if progress is not None:
                meta['progress'] = progress
            self_task.update_state(state='PROGRESS', meta=meta)
            # També publiquem el missatge al canal Redis perquè l'SSE pugui llegir-lo
            try:
                task_id_local = str(self_task.request.id)
                redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
                r = redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
                payload = {'message': str(msg)}
                if progress is not None:
                    payload['progress'] = progress
                payload = json.dumps(payload)
                r.publish(f"logs:{task_id_local}", payload)
            except Exception:
                # No brownzeu la tasca per fallades en pub/sub
                pass
        except Exception:
            # Evita que cap problema de backend de resultats mati la tasca
            pass
    return _inner



# ---------------------------------------------------------------------------------------------------
# CALENDARITZACIONS
# ---------------------------------------------------------------------------------------------------

@shared_task(bind=True, queue='heavy_queue')
def process_calendaritzacions_task(self, file_path: str):
    """
    Tasca SÍNCRONA per a Celery (retorna un valor serialitzable),
    però que executa codi ASÍNCRON intern amb asyncio.run(...).
    """
    task_id = str(self.request.id)
    # Estat inicial (meta 100% JSON-serialitzable)
    self.update_state(state='STARTED', meta={'logs': ['Iniciant el procés de calendaritzacions...']})

    try:
        result_url = asyncio.run(_process_calendaritzacions_async(task_id, file_path, _push(self)))
        return result_url  # <- str serialitzable
    except Exception as e:
        # Marca PROGRESS/FAILURE amb meta serialitzable
        try:
            self.update_state(state='FAILURE', meta={'logs': [str(e)]})
        finally:
            raise

async def _process_calendaritzacions_async(task_id: str, file_path: str, push):
    """
    Nucli ASÍNCRON: fa la crida HTTP al servei, escriu el ZIP i neteja temporals.
    Manté tots els avantatges d'async (httpx, aiofiles).
    """
    headers = {"X-Task-ID": task_id}

    # Llegim el fitxer local i fem un POST multipart/form-data al servei FastAPI
    filename = os.path.basename(file_path)
    # Intenta inferir el content-type a partir de l'extensió per ajudar el servei remot
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.xlsx':
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        raise RuntimeError(f"Tipus de fitxer no suportat a calendaritzacions: {filename}. Ha de ser .xlsx")
    try:
        with open(file_path, 'rb') as f:
            file_bytes = f.read()
    except Exception as e:
        raise RuntimeError(f"No s'ha pogut llegir el fitxer temporal: {e}")

    push(f'Enviant ruta al servei extern de calendaritzacions... (filename={filename}, content_type={content_type})')
    async with httpx.AsyncClient(timeout=None) as client:
        # Send only the path string as JSON so the remote service can open the
        # file from the shared MEDIA directory. We also forward the X-Task-ID
        # header so the remote service can associate logs/results.
        resp = await client.post(
            CALENDARITZACIONS_API,
            json={"file_path": file_path},
            headers=headers,
            follow_redirects=True,
        )

    # Debug: publish status and body when unexpected to help troubleshooting
    push(f"Resposta remota: status={resp.status_code}")
    if resp.status_code not in (200, 202):
        try:
            push(f"Resposta remota cos: {resp.text[:1000]}")
        except Exception:
            pass

    # Expect the external service to accept the job and return a JSON with job_id
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Error del servei de calendaritzacions ({resp.status_code}).")

    try:
        data = resp.json()
    except Exception:
        data = None

    remote_job_id = None
    if isinstance(data, dict):
        remote_job_id = data.get('job_id')

    # We don't poll or download here: the frontend will poll and read the file from MEDIA
    # Ensure the external service received the client task id (we sent X-Task-ID)
    if not remote_job_id:
        # If service didn't return job_id, still consider POST successful when 202/200
        remote_job_id = task_id

    push(f"Servei acceptat la tasca remota: {remote_job_id}. Worker finalitzat, el frontend farà polling de l'estat.")

    # Do NOT remove the local temp file here: the remote service will open
    # the shared path and must be able to read it. Removing it immediately
    # caused `FileNotFoundError` in the remote worker when it tried to process.
    push(f"Left local temp file in place for remote processing: {file_path}")

    # Return the remote job id so the frontend (or Django) can poll the external service.
    return remote_job_id


@shared_task(bind=True, queue='heavy_queue')
def process_calendaritzacions_fase_dos_task(self, file_path: str):
    """
    Tasca SÍNCRONA per a Celery (retorna un valor serialitzable),
    però que executa codi ASÍNCRON intern amb asyncio.run(...).
    """
    task_id = str(self.request.id)
    # Estat inicial (meta 100% JSON-serialitzable)
    self.update_state(state='STARTED', meta={'logs': ['Iniciant el procés de calendaritzacions...']})

    try:
        result_url = asyncio.run(_process_calendaritzacions_fase_dos_async(task_id, file_path, _push(self)))
        return result_url  # <- str serialitzable
    except Exception as e:
        # Marca PROGRESS/FAILURE amb meta serialitzable
        try:
            self.update_state(state='FAILURE', meta={'logs': [str(e)]})
        finally:
            raise

async def _process_calendaritzacions_fase_dos_async(task_id: str, file_path: str, push):
    """
    Nucli ASÍNCRON: fa la crida HTTP al servei, escriu el ZIP i neteja temporals.
    Manté tots els avantatges d'async (httpx, aiofiles).
    """
    headers = {"X-Task-ID": task_id}

    # Llegim el fitxer local i fem un POST multipart/form-data al servei FastAPI
    filename = os.path.basename(file_path)
    # Intenta inferir el content-type a partir de l'extensió per ajudar el servei remot
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.xlsx':
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        raise RuntimeError(f"Tipus de fitxer no suportat a calendaritzacions: {filename}. Ha de ser .xlsx")
    try:
        with open(file_path, 'rb') as f:
            file_bytes = f.read()
    except Exception as e:
        raise RuntimeError(f"No s'ha pogut llegir el fitxer temporal: {e}")

    push(f'Enviant ruta al servei extern de calendaritzacions... (filename={filename}, content_type={content_type})')
    async with httpx.AsyncClient(timeout=None) as client:
        # Send only the path string as JSON so the remote service can open the
        # file from the shared MEDIA directory. We also forward the X-Task-ID
        # header so the remote service can associate logs/results.
        resp = await client.post(
            CALENDARITZACIONS_API_SEGONA_FASE,
            json={"file_path": file_path},
            headers=headers,
            follow_redirects=True,
        )

    # Debug: publish status and body when unexpected to help troubleshooting
    push(f"Resposta remota: status={resp.status_code}")
    if resp.status_code not in (200, 202):
        try:
            push(f"Resposta remota cos: {resp.text[:1000]}")
        except Exception:
            pass

    # Expect the external service to accept the job and return a JSON with job_id
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Error del servei de calendaritzacions ({resp.status_code}).")

    try:
        data = resp.json()
    except Exception:
        data = None

    remote_job_id = None
    if isinstance(data, dict):
        remote_job_id = data.get('job_id')

    # We don't poll or download here: the frontend will poll and read the file from MEDIA
    # Ensure the external service received the client task id (we sent X-Task-ID)
    if not remote_job_id:
        # If service didn't return job_id, still consider POST successful when 202/200
        remote_job_id = task_id

    push(f"Servei acceptat la tasca remota: {remote_job_id}. Worker finalitzat, el frontend farà polling de l'estat.")

    # Do NOT remove the local temp file here: the remote service will open
    # the shared path and must be able to read it. Removing it immediately
    # caused `FileNotFoundError` in the remote worker when it tried to process.
    push(f"Left local temp file in place for remote processing: {file_path}")

    # Return the remote job id so the frontend (or Django) can poll the external service.
    return remote_job_id


# ---------------------------------------------------------------------------------------------------
# DESIGNACIONS
# ---------------------------------------------------------------------------------------------------

@shared_task(bind=True, queue='heavy_queue')
def process_designacions_task(self, file_paths):
    """
    Tasca SÍNCRONA per a Celery que accepta una ruta o una llista de rutes.
    Executa codi ASÍNCRON intern amb asyncio.run(...).
    """
    task_id = str(self.request.id)
    print(f"process_designacions_task: file_paths={file_paths}")
    # Estat inicial (meta 100% JSON-serialitzable)
    self.update_state(state='STARTED', meta={'logs': [f'Iniciant el procés de designacions...{file_paths}']})

    try:
        result = asyncio.run(_process_designacions_async(task_id, file_paths, _push(self)))
        return result  # <- str serialitzable (remote job id or url)
    except Exception as e:
        # Marca PROGRESS/FAILURE amb meta serialitzable
        try:
            self.update_state(state='FAILURE', meta={'logs': [str(e)]})
        finally:
            raise


async def _process_designacions_async(task_id: str, file_paths, push):
    """
    Nucli ASÍNCRON: accepta una ruta o una llista de rutes, fa la crida HTTP
    al servei de designacions i retorna el `job_id` remot (o el task_id si
    el servei no en retorna).
    """
    headers = {"X-Task-ID": task_id}

    # Normalize to list
    if isinstance(file_paths, (str, bytes)):
        paths = [file_paths]
    elif file_paths is None:
        paths = []
    else:
        paths = list(file_paths)

    if not paths:
        raise RuntimeError("No hi ha cap fitxer per processar a designacions.")

    # Build multipart payload with multiple files
    multipart = []
    for path in paths:
        filename = os.path.basename(path)
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.xlsx':
            content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        else:
            
            raise RuntimeError(f"Tipus de fitxer no suportat a designacions: {filename}. Ha de ser .xlsx")

        try:
            with open(path, 'rb') as f:
                file_bytes = f.read()
        except Exception as e:
            raise RuntimeError(f"No s'ha pogut llegir el fitxer temporal: {e}")

        # Use the same 'files' field name as other endpoints that accept multiple files
        multipart.append(('files', (filename, file_bytes, content_type)))

    push('Enviant fitxers al servei de designacions...')
    print(f"Sending to DESIGNACIONS_API={DESIGNACIONS_API} with headers={headers} and {len(multipart)} files.")
    async with httpx.AsyncClient(timeout=None) as client:
        # Follow redirects (307/308) so POST-preserving redirects are handled
        resp = await client.post(DESIGNACIONS_API, files=multipart, headers=headers, follow_redirects=True)

    # Log redirect history for debugging
    try:
        history = getattr(resp, 'history', None)
        if history:
            push(f"Redirect history: {[{'status': r.status_code, 'url': str(r.url)} for r in history]}")
    except Exception:
        pass

    push(f"Resposta remota: status={resp.status_code}")
    if resp.status_code not in (200, 202):
        try:
            push(f"Resposta remota cos: {resp.text[:1000]}")
        except Exception:
            pass
        raise RuntimeError(f"Error del servei de designacions ({resp.status_code}).")

    try:
        data = resp.json()
    except Exception:
        data = None

    remote_job_id = None
    if isinstance(data, dict):
        remote_job_id = data.get('job_id')

    if not remote_job_id:
        remote_job_id = task_id

    push(f"Servei acceptat a la tasca remota: {remote_job_id}. Worker finalitzat, el frontend farà polling de l'estat.")

    # Do NOT remove local temp files: remote worker may need them (shared MEDIA dir)
    for p in paths:
        push(f"Left local temp file in place for remote processing: {p}")

    return remote_job_id


# ---------------------------------------------------------------------------------------------------
# LLISTATS PROVISIONALS
# ---------------------------------------------------------------------------------------------------
@shared_task(bind=True, queue='heavy_queue')
def process_llistats_provisionals_task(self, file_path):
    """
    Tasca SÍNCRONA per a Celery que accepta una ruta o una llista de rutes.
    Executa codi ASÍNCRON intern amb asyncio.run(...).
    """
    task_id = str(self.request.id)
    print(f"process_llistats_provisionals_task: file_path={file_path}")
    # Estat inicial (meta 100% JSON-serialitzable)
    self.update_state(state='STARTED', meta={'logs': [f'Iniciant el procés de llistats provisionals...{file_path}']})

    try:
        result = asyncio.run(_process_llistats_provisionals_async(task_id, file_path, _push(self)))
        return result  # <- str serialitzable (remote job id or url)
    except Exception as e:
        # Marca PROGRESS/FAILURE amb meta serialitzable
        try:
            self.update_state(state='FAILURE', meta={'logs': [str(e)]})
        finally:
            raise


async def _process_llistats_provisionals_async(task_id: str, file_path: str, push):
    """
    Nucli ASÍNCRON: fa la crida HTTP al servei, escriu el ZIP i neteja temporals.
    Manté tots els avantatges d'async (httpx, aiofiles).
    """
    headers = {"X-Task-ID": task_id}

    # Llegim el fitxer local i fem un POST multipart/form-data al servei FastAPI
    filename = os.path.basename(file_path)
    # Intenta inferir el content-type a partir de l'extensió per ajudar el servei remot
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.xlsx':
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        raise RuntimeError(f"Tipus de fitxer no suportat: {filename}. Ha de ser .xlsx")
    try:
        with open(file_path, 'rb') as f:
            file_bytes = f.read()
    except Exception as e:
        raise RuntimeError(f"No s'ha pogut llegir el fitxer temporal: {e}")

    push(f'Enviant ruta al servei extern... (filename={filename}, content_type={content_type})')
    async with httpx.AsyncClient(timeout=None) as client:
        # Send only the path string as JSON so the remote service can open the
        # file from the shared MEDIA directory. We also forward the X-Task-ID
        # header so the remote service can associate logs/results.
        resp = await client.post(
            LLISTATS_PROVISIONALS_API,
            json={"file_path": file_path},
            headers=headers, follow_redirects=True
        )

    # Debug: publish status and body when unexpected to help troubleshooting
    push(f"Resposta remota: status={resp.status_code}")
    if resp.status_code not in (200, 202):
        try:
            push(f"Resposta remota cos: {resp.text[:1000]}")
        except Exception:
            pass

    # Expect the external service to accept the job and return a JSON with job_id
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Error del servei de llistats ({resp.status_code}).")

    try:
        data = resp.json()
    except Exception:
        data = None

    remote_job_id = None
    if isinstance(data, dict):
        remote_job_id = data.get('job_id')

    # We don't poll or download here: the frontend will poll and read the file from MEDIA
    # Ensure the external service received the client task id (we sent X-Task-ID)
    if not remote_job_id:
        # If service didn't return job_id, still consider POST successful when 202/200
        remote_job_id = task_id

    push(f"Servei acceptat la tasca remota: {remote_job_id}. Worker finalitzat, el frontend farà polling de l'estat.")

    # Do NOT remove the local temp file here: the remote service will open
    # the shared path and must be able to read it. Removing it immediately
    # caused `FileNotFoundError` in the remote worker when it tried to process.
    push(f"Left local temp file in place for remote processing: {file_path}")

    # Return the remote job id so the frontend (or Django) can poll the external service.
    return remote_job_id


# ---------------------------------------------------------------------------------------------------
# LLISTATS DEFINITIUS
# ---------------------------------------------------------------------------------------------------
@shared_task(bind=True, queue='heavy_queue')
def process_llistats_definitius_task(self, file_path):
    """
    Tasca SÍNCRONA per a Celery que accepta una ruta o una llista de rutes.
    Executa codi ASÍNCRON intern amb asyncio.run(...).
    """
    task_id = str(self.request.id)
    print(f"process_llistats_provisionals_task: file_path={file_path}")
    # Estat inicial (meta 100% JSON-serialitzable)
    self.update_state(state='STARTED', meta={'logs': [f'Iniciant el procés de llistats provisionals...{file_path}']})

    try:
        result = asyncio.run(_process_llistats_definitius_async(task_id, file_path, _push(self)))
        return result  # <- str serialitzable (remote job id or url)
    except Exception as e:
        # Marca PROGRESS/FAILURE amb meta serialitzable
        try:
            self.update_state(state='FAILURE', meta={'logs': [str(e)]})
        finally:
            raise


async def _process_llistats_definitius_async(task_id: str, file_path: str, push):
    """
    Nucli ASÍNCRON: fa la crida HTTP al servei, escriu el ZIP i neteja temporals.
    Manté tots els avantatges d'async (httpx, aiofiles).
    """
    headers = {"X-Task-ID": task_id}

    # Llegim el fitxer local i fem un POST multipart/form-data al servei FastAPI
    filename = os.path.basename(file_path)
    # Intenta inferir el content-type a partir de l'extensió per ajudar el servei remot
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.xlsx':
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        raise RuntimeError(f"Tipus de fitxer no suportat: {filename}. Ha de ser .xlsx")
    try:
        with open(file_path, 'rb') as f:
            file_bytes = f.read()
    except Exception as e:
        raise RuntimeError(f"No s'ha pogut llegir el fitxer temporal: {e}")

    push(f'Enviant ruta al servei extern... (filename={filename}, content_type={content_type})')
    async with httpx.AsyncClient(timeout=None) as client:
        # Send only the path string as JSON so the remote service can open the
        # file from the shared MEDIA directory. We also forward the X-Task-ID
        # header so the remote service can associate logs/results.
        resp = await client.post(
            LLISTATS_DEFINITIUS_API,
            json={"file_path": file_path},
            headers=headers, follow_redirects=True
        )

    # Debug: publish status and body when unexpected to help troubleshooting
    push(f"Resposta remota: status={resp.status_code}")
    if resp.status_code not in (200, 202):
        try:
            push(f"Resposta remota cos: {resp.text[:1000]}")
        except Exception:
            pass

    # Expect the external service to accept the job and return a JSON with job_id
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Error del servei de llistats ({resp.status_code}).")

    try:
        data = resp.json()
    except Exception:
        data = None

    remote_job_id = None
    if isinstance(data, dict):
        remote_job_id = data.get('job_id')

    # We don't poll or download here: the frontend will poll and read the file from MEDIA
    # Ensure the external service received the client task id (we sent X-Task-ID)
    if not remote_job_id:
        # If service didn't return job_id, still consider POST successful when 202/200
        remote_job_id = task_id

    push(f"Servei acceptat la tasca remota: {remote_job_id}. Worker finalitzat, el frontend farà polling de l'estat.")

    # Do NOT remove the local temp file here: the remote service will open
    # the shared path and must be able to read it. Removing it immediately
    # caused `FileNotFoundError` in the remote worker when it tried to process.
    push(f"Left local temp file in place for remote processing: {file_path}")

    # Return the remote job id so the frontend (or Django) can poll the external service.
    return remote_job_id
