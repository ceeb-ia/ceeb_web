import io
from celery import shared_task
import requests
import os
import uuid
import httpx
import aiofiles
import asyncio
from django.conf import settings

CERTIFICATS_API = os.getenv("CERTIFICATS_API", "http://certificats:8000/process-pdfs/")

@shared_task(bind=True, queue='heavy_queue')
def process_certificats_task(self, file_paths):
    """
    Tasca SÍNCRONA per a Celery (retorna un valor serialitzable),
    però que executa codi ASÍNCRON intern amb asyncio.run(...).
    """
    task_id = str(self.request.id)
    # Estat inicial (meta 100% JSON-serialitzable)
    self.update_state(state='STARTED', meta={'logs': ['Iniciant el procés...']})

    try:
        result_url = asyncio.run(_process_certificats_async(task_id, file_paths, _push(self)))
        return result_url  # <- str serialitzable
    except Exception as e:
        # Marca PROGRESS/FAILURE amb meta serialitzable
        try:
            self.update_state(state='FAILURE', meta={'logs': [str(e)]})
        finally:
            raise


def _push(self_task):
    """Callback per reportar logs a Celery meta, sempre serialitzable."""
    def _inner(msg: str):
        try:
            print(f"Enviant log: {msg}")
            self_task.update_state(state='PROGRESS', meta={'logs': [str(msg)]})
        except Exception:
            # Evita que cap problema de backend de resultats mati la tasca
            pass
    return _inner


async def _process_certificats_async(task_id: str, file_paths: list[str], push):
    """
    Nucli ASÍNCRON: fa la crida HTTP al servei, escriu el ZIP i neteja temporals.
    Manté tots els avantatges d'async (httpx, aiofiles).
    """
    # 1) Prepara el multipart amb BYTES (evitem deixar handlers oberts)
    multipart = []
    for path in file_paths:
        filename = os.path.basename(path)
        with open(path, 'rb') as f:
            data = f.read()
        # httpx accepta bytes en el camp del fitxer
        multipart.append(('files', (filename, data, 'application/pdf')))

    headers = {"X-Task-ID": task_id}

    push('Enviant fitxers al servei extern...')
    async with httpx.AsyncClient(timeout=None) as client:
        resp = await client.post(CERTIFICATS_API, files=multipart, headers=headers)

    if resp.status_code != 200:
        raise RuntimeError(f"Error del servei de certificats ({resp.status_code}).")

    push('Processant resposta del servei...')
    buffer = io.BytesIO(resp.content)

    # 2) Escriu el ZIP a MEDIA_ROOT
    zip_filename = f"certificats_{uuid.uuid4()}.zip"
    dest_dir = os.path.join(settings.MEDIA_ROOT, 'certificats')
    os.makedirs(dest_dir, exist_ok=True)
    zip_path = os.path.join(dest_dir, zip_filename)

    async with aiofiles.open(zip_path, 'wb') as zip_file:
        await zip_file.write(buffer.getvalue())

    # 3) Neteja fitxers temporals (no interromp si algun ja no hi és)
    for path in file_paths:
        try:
            await asyncio.to_thread(os.remove, path)
        except FileNotFoundError:
            print(f"Fitxer temporal ja no existeix: {path}")
        except Exception as e:
            # No fallis per neteja; només informa
            push(f"No s'ha pogut esborrar {path}: {e}")

    

    result_url = f"{settings.MEDIA_URL}certificats/{zip_filename}" 
    push('Procés complet. Preparant enllaç de descàrrega...')
    return result_url
